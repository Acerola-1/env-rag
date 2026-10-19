"""Run the Knowledge API gateway: ``python -m env_rag_final.access``.

``ENV_RAG_AUTH_MODE=local|remote`` is fixed at process start:

* ``local`` (explicit isolated tests only) — the original registry-backed behaviour; no IAM request
  is ever issued, so an IAM outage cannot affect a local deployment.
* ``remote`` — IAM-backed authorization; the process refuses to start without
  the IAM URL, issuer, consumer client credential, explicit tenant mapping and
  the safety prerequisites, and it never falls back to local on a failure.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from aiohttp import web

from env_rag_final.access.registry import load_registry
from env_rag_final.access.server import create_app
from env_rag_final.paths import PARSED_ROOT, PROJECT_ROOT

DEFAULT_REGISTRY = PROJECT_ROOT / ".local/workspace-access/registry.json"
DEFAULT_KEYS = PROJECT_ROOT / ".local/workspace-access/instance-keys.json"
DEFAULT_RECORDS = PROJECT_ROOT / ".local/workspace-access/records"

VALID_MODES = ("local", "remote")


def ensure_isolated_record_root(mode: str, record_root: Path) -> None:
    """Remote mode must never write into the local deployment's record store.

    Remote records carry a different identity model (principal type, IAM tenant
    UUID, permission summary), so mixing roots would expose local history to a
    remote query path and vice versa.  The default root belongs to the local
    8099 deployment; a remote start has to name its own directory.
    """
    if mode != "remote":
        return
    resolved = Path(record_root).resolve()
    if resolved == DEFAULT_RECORDS.resolve() or DEFAULT_RECORDS.resolve() in resolved.parents:
        raise SystemExit(
            "remote mode requires an explicit --record-root outside the local "
            f"deployment store ({DEFAULT_RECORDS})"
        )


def resolve_mode(argv_mode: str | None = None) -> str:
    mode = (argv_mode or os.environ.get("ENV_RAG_AUTH_MODE") or "remote").strip().lower()
    if mode not in VALID_MODES:
        raise SystemExit(
            f"invalid ENV_RAG_AUTH_MODE {mode!r}; expected one of {', '.join(VALID_MODES)}"
        )
    return mode


def _collect_values(env_file: Path) -> dict:
    from dotenv import dotenv_values

    file_values = dotenv_values(env_file)
    values = {k: v for k, v in file_values.items() if v is not None}
    allowed_prefixes = (
        "POSTGRES_",
        "QDRANT_",
        "NEO4J_",
        "LLM_",
        "EMBEDDING_",
        "QUERY_LLM_",
        "MAX_TOTAL_TOKENS",
        "ENV_RAG_",
    )
    # SSO consumer settings come from the process environment (server-side).
    values.update({k: v for k, v in os.environ.items() if k.startswith(allowed_prefixes)})
    return values


def build_service(
    registry_path: Path,
    env_file: Path,
    keys_path: Path,
    record_root: Path,
    *,
    mode: str = "local",
    mapping_path: Path | None = None,
    iam_url: str | None = None,
    issuer: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
    deadline: float | None = None,
):
    from env_rag_final.access.gateway import KnowledgeService

    registry = load_registry(registry_path)
    values = _collect_values(env_file)
    if mapping_path is not None:
        values["ENV_RAG_IAM_MAPPING"] = str(mapping_path)
    if iam_url:
        values["ENV_RAG_IAM_URL"] = iam_url
    if issuer:
        values["ENV_RAG_IAM_ISSUER"] = issuer
    if client_id:
        values["ENV_RAG_IAM_CLIENT_ID"] = client_id
    if client_secret:
        values["ENV_RAG_IAM_CLIENT_SECRET"] = client_secret
    if deadline is not None:
        values["ENV_RAG_IAM_DEADLINE_SECONDS"] = str(deadline)
    keys = json.loads(keys_path.read_text(encoding="utf-8")) if keys_path.exists() else {}

    if mode == "local":
        from env_rag_final.access.providers import LocalProvider

        provider = LocalProvider(registry=registry)
    elif mode == "remote":
        from env_rag_final.access.providers import RemoteProvider
        from env_rag_final.access.remote import IamClient, RemoteConfig

        try:
            config = RemoteConfig.from_env(values)
        except ValueError as exc:
            # Fail at startup: a remote deployment never degrades into local.
            raise SystemExit(f"remote mode misconfigured: {exc}") from exc
        for entries in config.mapping.values():
            for workspace in entries.values():
                if registry.workspace(workspace) is None:
                    raise SystemExit("IAM mapping refers to an unknown technical workspace")
        provider = RemoteProvider(
            config=config,
            registry=registry,
            iam=IamClient(config),
            directory_version=registry.revision,
        )
    else:  # pragma: no cover - resolve_mode already guards
        raise SystemExit(f"invalid mode {mode!r}")

    return KnowledgeService(
        registry=registry,
        values=values,
        record_root=record_root,
        parsed_root=PARSED_ROOT,
        instance_keys=keys,
        instance_urls=json.loads(os.environ.get("ENV_RAG_INSTANCE_URLS", "{}")),
        auth_provider=provider,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="env-rag-access")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    parser.add_argument("--instance-keys", type=Path, default=DEFAULT_KEYS)
    parser.add_argument(
        "--record-root",
        type=Path,
        default=Path(os.environ.get("ENV_RAG_RECORD_ROOT") or DEFAULT_RECORDS),
    )
    parser.add_argument("--auth-mode", default=None, help="override ENV_RAG_AUTH_MODE")
    parser.add_argument("--iam-mapping", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.host not in ("127.0.0.1", "localhost"):
        raise SystemExit("Knowledge API must listen on loopback")
    mode = resolve_mode(args.auth_mode)
    ensure_isolated_record_root(mode, args.record_root)
    service = build_service(
        args.registry,
        args.env_file,
        args.instance_keys,
        args.record_root,
        mode=mode,
        mapping_path=args.iam_mapping,
    )
    app = create_app(service)
    web.run_app(app, host=args.host, port=args.port, access_log=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
