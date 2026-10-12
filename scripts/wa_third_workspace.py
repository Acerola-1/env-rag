#!/usr/bin/env python
"""Third-workspace extension proof.

Adds a new knowledge library using **only** registry configuration, instance
startup and the ingestion commands — then proves a granted reader can query it
and an ungranted reader is refused.  Records the hash of the core retrieval
modules before and after to show no retrieval code changed.

    .venv/bin/python scripts/wa_third_workspace.py --cleanup
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from env_rag_final.access.registry import hash_password, hash_token, load_registry  # noqa: E402

LOCAL = ROOT / ".local/workspace-access"
CORE_MODULES = [
    "src/env_rag_final/search/query.py",
    "src/env_rag_final/search/expand.py",
    "src/env_rag_final/search/index.py",
    "src/env_rag_final/enumerate_/doc_enum.py",
    "src/env_rag_final/enumerate_/prose_enum.py",
    "src/env_rag_final/enumerate_/table_enum.py",
    "src/env_rag_final/ask.py",
]


def core_fingerprint() -> dict:
    out = {}
    for rel in CORE_MODULES:
        path = ROOT / rel
        out[rel] = (
            hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.exists() else "missing"
        )
    return out


NEW_WORKSPACE = "coastal"
NEW_ROLE = "coastal-reader"
NEW_USER = "coastal-reader"
REAL_DOC = "water-01_国家法律法规数据库_中华人民共和国长江保护法_2021.pdf"


def registry_path() -> Path:
    return LOCAL / "registry.json"


def add_to_registry() -> dict:
    payload = json.loads(registry_path().read_text(encoding="utf-8"))
    payload["workspaces"][NEW_WORKSPACE] = {
        "name": "沿海资料（第三库扩展验证）",
        "pg_workspace": NEW_WORKSPACE,
        "vector_workspace": NEW_WORKSPACE,
        "graph_workspace": NEW_WORKSPACE,
        "status": "active",
        "instance_url": "http://127.0.0.1:9624",
        "instance_key_ref": NEW_WORKSPACE,
        "parsed_root": "datasets/corpus/parsed",
        "embedding_model": "Qwen/Qwen3-Embedding-4B",
        "embedding_dim": 2560,
        "code_identity": "lightrag-hku==1.5.7 / ghcr.io/hkuds/lightrag:latest",
        "notes": "配置扩展验证：仅注册表＋启动＋入库",
    }
    creds = json.loads((LOCAL / "credentials.json").read_text(encoding="utf-8"))
    entry = creds.setdefault(NEW_USER, {})
    password = entry.get("password") or "coastal-demo-pw"
    token = entry.get("bearer") or "coastal-demo-token"
    entry.update({"password": password, "bearer": token, "enterprise": "gamma-env"})
    (LOCAL / "credentials.json").write_text(json.dumps(creds, indent=1), encoding="utf-8")
    payload["grants"][f"gamma-env:{NEW_ROLE}"] = [NEW_WORKSPACE]
    payload["principals"][NEW_USER] = {
        "enterprise": "gamma-env",
        "display": "沿海资料读者",
        "roles": [NEW_ROLE],
        "password_hash": hash_password(password, f"wa-{NEW_USER}"),
        "bearer_sha256": [hash_token(token)],
    }
    stamp = time.strftime("%Y%m%d%H%M%S")
    payload["revision"] = f"wa-20261012-r1+{NEW_WORKSPACE}-{stamp}"
    registry_path().write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    load_registry(registry_path())  # validate
    return payload


def remove_from_registry() -> None:
    payload = json.loads(registry_path().read_text(encoding="utf-8"))
    payload["workspaces"].pop(NEW_WORKSPACE, None)
    payload["grants"].pop(f"gamma-env:{NEW_ROLE}", None)
    payload["principals"].pop(NEW_USER, None)
    payload["revision"] = "wa-20261012-r1"
    registry_path().write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def sh(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, **kwargs)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cleanup", action="store_true", help="remove the trial library afterwards"
    )
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument(
        "--out", default=str(ROOT / "reports/workspace-access/wa-20261012-r1/third-workspace.json")
    )
    args = parser.parse_args()

    report: dict = {"workspace": NEW_WORKSPACE, "document": REAL_DOC, "steps": []}

    def step(name: str, detail) -> None:
        report["steps"].append({"step": name, "detail": detail, "at": round(time.time(), 3)})

    before = core_fingerprint()
    report["core_modules_before"] = before

    add_to_registry()
    step("registry.add", {"revision": json.loads(registry_path().read_text())["revision"]})

    env_result = sh(
        [
            sys.executable,
            "scripts/wa_instance_env.py",
            "--workspace",
            NEW_WORKSPACE,
            "--allow-new-key",
        ]
    )
    step("instance.env", env_result.stdout.strip() or env_result.stderr.strip()[-200:])
    start = subprocess.run(
        ["bash", "scripts/wa_instances.sh", "start"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "WA_WORKSPACES": NEW_WORKSPACE},
    )
    step("instance.start", (start.stdout + start.stderr).strip()[-400:])
    health = subprocess.run(
        ["bash", "scripts/wa_instances.sh", "health"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "WA_WORKSPACES": NEW_WORKSPACE},
    )
    step("instance.health", health.stdout.strip()[-300:])

    if not args.skip_ingest:
        ingest = sh(
            [
                ".venv/bin/env-rag-final",
                "workspace-ingest",
                "--workspace",
                NEW_WORKSPACE,
                "--extra-doc",
                REAL_DOC,
                "--doc-name",
                REAL_DOC,
                "--process-rounds",
                "3",
                "--set",
                "EMBEDDING_TIMEOUT=300",
                "--out",
                str(ROOT / "reports/workspace-access/wa-20261012-r1/ingestion-coastal.json"),
            ]
        )
        step("ingest", (ingest.stdout or ingest.stderr)[-600:])
        for command in ("workspace-catalog", "workspace-index"):
            res = sh([".venv/bin/env-rag-final", command, "--workspace", NEW_WORKSPACE])
            step(command, (res.stdout or res.stderr)[-400:])

    # granted reader queries the new library through the gateway
    creds = json.loads((LOCAL / "credentials.json").read_text(encoding="utf-8"))
    client = httpx.Client(timeout=300)
    login = client.post(
        "http://127.0.0.1:8099/api/login",
        json={"user_id": NEW_USER, "password": creds[NEW_USER]["password"]},
    ).json()
    csrf = login["csrf"]
    q = client.post(
        "http://127.0.0.1:8099/api/query",
        json={
            "workspace": NEW_WORKSPACE,
            "question": "长江保护法 水生态保护",
            "route": "pg",
            "no_record": True,
        },
        headers={"X-RAG-Token": csrf},
    )
    step("granted-query", {"status": q.status_code, "result": _slim(q)})

    air = httpx.Client(timeout=300)
    air_login = air.post(
        "http://127.0.0.1:8099/api/login",
        json={"user_id": "air-reader", "password": creds["air-reader"]["password"]},
    ).json()
    refused = air.post(
        "http://127.0.0.1:8099/api/query",
        json={"workspace": NEW_WORKSPACE, "question": "长江保护法", "no_record": True},
        headers={"X-RAG-Token": air_login["csrf"]},
    )
    step("ungranted-query", {"status": refused.status_code, "body": _safe(refused)})
    report["granted_ok"] = q.status_code == 200
    report["ungranted_refused"] = refused.status_code == 403

    after = core_fingerprint()
    report["core_modules_after"] = after
    report["core_modules_unchanged"] = before == after

    if args.cleanup:
        cleanup = sh(
            [
                ".venv/bin/env-rag-final",
                "workspace-ingest",
                "--workspace",
                NEW_WORKSPACE,
                "--dry-run",
            ]
        )
        step("cleanup.dry-run", (cleanup.stdout or cleanup.stderr)[-200:])
        sh(["container", "stop", f"lightrag-{NEW_WORKSPACE}"])
        sh(["container", "delete", f"lightrag-{NEW_WORKSPACE}"])
        purge = subprocess.run(
            [
                "container",
                "exec",
                "lightrag-postgres",
                "psql",
                "-U",
                "rag",
                "-d",
                "rag",
                "-tAc",
                f"delete from public.lightrag_doc_chunks where workspace='{NEW_WORKSPACE}';"
                f"delete from public.lightrag_doc_full where workspace='{NEW_WORKSPACE}';"
                f"delete from public.lightrag_doc_status where workspace='{NEW_WORKSPACE}';"
                f"delete from public.lightrag_llm_cache where workspace='{NEW_WORKSPACE}';"
                f"delete from public.lightrag_entity_chunks where workspace='{NEW_WORKSPACE}';"
                f"delete from public.lightrag_relation_chunks where workspace='{NEW_WORKSPACE}';"
                f"delete from env_rag.documents where workspace='{NEW_WORKSPACE}';"
                f"delete from env_rag.source_units where workspace='{NEW_WORKSPACE}';"
                f"delete from env_rag.unit_chunk_links where workspace='{NEW_WORKSPACE}';"
                f"delete from env_rag.scopes where workspace='{NEW_WORKSPACE}';"
                f"delete from env_rag.scope_units where workspace='{NEW_WORKSPACE}';"
                f"delete from env_rag.search_documents where workspace='{NEW_WORKSPACE}';"
                f"delete from env_rag.search_chunks where workspace='{NEW_WORKSPACE}';"
                f"delete from env_rag.search_builds where workspace='{NEW_WORKSPACE}';"
                f"delete from env_rag.corpus_runs where workspace='{NEW_WORKSPACE}';",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        step("cleanup.pg", purge.stdout.strip()[-200:])
        qdrant = httpx.post(
            "http://localhost:6333/collections/lightrag_vdb_chunks_qwen_qwen3_embedding_4b_2560d/points/delete",
            json={"filter": {"must": [{"key": "workspace_id", "match": {"value": NEW_WORKSPACE}}]}},
            timeout=60,
        )
        for name in ("chunks", "entities", "relationships"):
            httpx.post(
                f"http://localhost:6333/collections/lightrag_vdb_{name}_qwen_qwen3_embedding_4b_2560d/points/delete",
                json={
                    "filter": {"must": [{"key": "workspace_id", "match": {"value": NEW_WORKSPACE}}]}
                },
                timeout=60,
            )
        step("cleanup.qdrant", qdrant.status_code)
        neo = subprocess.run(
            [
                "container",
                "exec",
                "lightrag-neo4j",
                "cypher-shell",
                "-u",
                "neo4j",
                "-p",
                _neo4j_password(),
                f"MATCH (n:`{NEW_WORKSPACE}`) DETACH DELETE n;",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        step("cleanup.neo4j", (neo.stdout + neo.stderr).strip()[-200:])
        remove_from_registry()
        step("registry.remove", True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        json.dumps({k: v for k, v in report.items() if k != "steps"}, ensure_ascii=False, indent=1)
    )
    return 0


def _neo4j_password() -> str:
    from dotenv import dotenv_values

    return dotenv_values(ROOT / ".env")["NEO4J_PASSWORD"]


def _safe(res: httpx.Response) -> dict:
    try:
        return res.json()
    except Exception:
        return {"text_len": len(res.text)}


def _slim(res: httpx.Response) -> dict:
    payload = _safe(res)
    result = payload.get("result") or {}
    return {
        "status": result.get("status"),
        "workspaces": result.get("workspaces"),
        "evidence": len(result.get("evidence") or []),
        "failures": result.get("failures"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
