"""Run the Knowledge API gateway: ``python -m env_rag_final.access``."""

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


def build_service(registry_path: Path, env_file: Path, keys_path: Path, record_root: Path):
    from dotenv import dotenv_values

    from env_rag_final.access.gateway import KnowledgeService

    registry = load_registry(registry_path)
    values = {k: v for k, v in dotenv_values(env_file).items() if v is not None}
    values.update(
        {
            k: v
            for k, v in os.environ.items()
            if k in values and k.startswith(("POSTGRES_", "QDRANT_", "NEO4J_", "LLM_"))
        }
    )
    keys = json.loads(keys_path.read_text(encoding="utf-8")) if keys_path.exists() else {}
    return KnowledgeService(
        registry=registry,
        values=values,
        record_root=record_root,
        parsed_root=PARSED_ROOT,
        instance_keys=keys,
        instance_urls=json.loads(os.environ.get("ENV_RAG_INSTANCE_URLS", "{}")),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="env-rag-access")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    parser.add_argument("--instance-keys", type=Path, default=DEFAULT_KEYS)
    parser.add_argument("--record-root", type=Path, default=DEFAULT_RECORDS)
    args = parser.parse_args(argv)

    service = build_service(args.registry, args.env_file, args.instance_keys, args.record_root)
    app = create_app(service)
    web.run_app(app, host=args.host, port=args.port, access_log=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
