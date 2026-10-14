"""Registry-driven Apple Container plans; credentials never enter command arguments."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from env_rag_final.access.registry import Registry, default_registry_path, load_registry
from env_rag_final.paths import PROJECT_ROOT

PINNED_IMAGE = (
    "ghcr.io/hkuds/lightrag@sha256:5bdbd524931b011df246fe20888d110cef691e6804c12cde636a2b746d7de27e"
)


def instance_plan(
    registry: Registry,
    workspace: str,
    *,
    image: str = PINNED_IMAGE,
    network: str = "lightrag-net",
    env_dir: Path | None = None,
) -> dict:
    ws = registry.workspace(workspace)
    if ws is None or ws.status not in ("active", "building", "draft"):
        raise ValueError("workspace must be registered and not retired")
    url = urlsplit(ws.instance_url or "")
    if (
        url.scheme != "http"
        or url.hostname != "127.0.0.1"
        or not url.port
        or url.path not in ("", "/")
        or url.username
    ):
        raise ValueError("instance_url must be a loopback HTTP URL with an explicit port")
    ports = [urlsplit(w.instance_url).port for w in registry.workspaces.values() if w.instance_url]
    if ports.count(url.port) != 1:
        raise ValueError("instance port conflicts with another workspace")
    if "@sha256:" not in image or len(image.rsplit("@sha256:", 1)[1]) != 64:
        raise ValueError("LightRAG image must be pinned to a SHA256 digest")
    env_file = (env_dir or PROJECT_ROOT / ".local/workspace-access/env") / f"lightrag-{ws.id}.env"
    return {
        "workspace": ws.id,
        "name": f"lightrag-{ws.id}",
        "port": url.port,
        "url": ws.instance_url.rstrip("/"),
        "pg_workspace": ws.pg_workspace,
        "vector_workspace": ws.vector_workspace,
        "graph_workspace": ws.graph_workspace,
        "image": image,
        "network": network,
        "env_file": str(env_file),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("plan", "start", "stop", "status", "health", "logs"))
    parser.add_argument("workspace", nargs="?", default="all")
    parser.add_argument("--registry", type=Path, default=default_registry_path())
    parser.add_argument(
        "--instance-keys",
        type=Path,
        default=PROJECT_ROOT / ".local/workspace-access/instance-keys.json",
    )
    args = parser.parse_args()
    registry = load_registry(args.registry)
    selected = (
        os.environ.get("WA_WORKSPACES", "").split()
        if args.workspace == "all"
        else [args.workspace.removeprefix("lightrag-")]
    )
    selected = selected or list(registry.active_workspaces())
    runtime = json.loads(args.registry.read_text()).get("deployment", {})
    plans = [
        instance_plan(
            registry,
            ws,
            image=os.environ.get("LIGHTRAG_IMAGE") or runtime.get("image") or PINNED_IMAGE,
            network=os.environ.get("LIGHTRAG_NETWORK") or runtime.get("network") or "lightrag-net",
        )
        for ws in selected
    ]
    if args.action == "plan":
        print(json.dumps(plans, ensure_ascii=False, indent=2))
        return 0
    for plan in plans:
        name = plan["name"]
        if args.action in ("stop", "logs"):
            subprocess.run(["container", args.action, name], check=True)
            continue
        if args.action == "start":
            existing = subprocess.run(
                ["container", "inspect", name], capture_output=True, text=True
            )
            if existing.returncode == 0:
                inspected = json.loads(existing.stdout)[0]
                detail = inspected["configuration"]
                expected_digest = plan["image"].rsplit("@", 1)[1]
                if detail["image"]["descriptor"]["digest"] != expected_digest:
                    raise ValueError(
                        "existing instance has a different image; refusing automatic replacement"
                    )
                env = dict(
                    x.split("=", 1) for x in detail["initProcess"]["environment"] if "=" in x
                )
                for key, wanted in (
                    ("WORKSPACE", plan["workspace"]),
                    ("POSTGRES_WORKSPACE", plan["pg_workspace"]),
                    ("QDRANT_WORKSPACE", plan["vector_workspace"]),
                    ("NEO4J_WORKSPACE", plan["graph_workspace"]),
                ):
                    if env.get(key) != wanted:
                        raise ValueError("existing instance namespace differs from registry")
                if inspected["status"]["state"] != "running":
                    subprocess.run(["container", "start", name], check=True, capture_output=True)
            else:
                if not Path(plan["env_file"]).is_file():
                    raise ValueError("generate the workspace environment file first")
                env = dict(
                    line.split("=", 1)
                    for line in Path(plan["env_file"]).read_text().splitlines()
                    if "=" in line and not line.lstrip().startswith("#")
                )
                for key_name, wanted in (
                    ("WORKSPACE", plan["workspace"]),
                    ("POSTGRES_WORKSPACE", plan["pg_workspace"]),
                    ("QDRANT_WORKSPACE", plan["vector_workspace"]),
                    ("NEO4J_WORKSPACE", plan["graph_workspace"]),
                ):
                    if env.get(key_name) != wanted:
                        raise ValueError("environment file namespace differs from registry")
                subprocess.run(
                    [
                        "container",
                        "run",
                        "-d",
                        "--name",
                        name,
                        "--network",
                        plan["network"],
                        "-p",
                        f"127.0.0.1:{plan['port']}:9621",
                        "--env-file",
                        plan["env_file"],
                        plan["image"],
                    ],
                    check=True,
                    capture_output=True,
                )
        if args.action == "status":
            detail = subprocess.run(
                ["container", "inspect", name], capture_output=True, text=True, check=True
            )
            print(name, json.loads(detail.stdout)[0]["status"], plan["url"])
        else:
            keys = json.loads(args.instance_keys.read_text())
            ws = registry.workspace(plan["workspace"])
            key = keys[ws.instance_key_ref or ws.id]
            attempts = 90 if args.action == "start" else 1
            for attempt in range(attempts):
                try:
                    res = httpx.get(plan["url"] + "/health", headers={"X-API-Key": key}, timeout=3)
                    res.raise_for_status()
                    config = res.json().get("configuration") or {}
                    expected = {
                        "kv_storage": plan["pg_workspace"],
                        "doc_status_storage": plan["pg_workspace"],
                        "vector_storage": plan["vector_workspace"],
                        "graph_storage": plan["graph_workspace"],
                    }
                    if (
                        config.get("workspace") != plan["workspace"]
                        or config.get("storage_workspaces") != expected
                    ):
                        raise ValueError("running instance namespace differs from registry")
                    private = httpx.get(
                        plan["url"] + "/documents/pipeline_status",
                        headers={"X-API-Key": key},
                        timeout=3,
                    )
                    private.raise_for_status()
                    print(name, "healthy", plan["url"])
                    break
                except httpx.HTTPError:
                    if attempt + 1 == attempts:
                        raise RuntimeError(f"{name}: not ready") from None
                    time.sleep(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
