#!/usr/bin/env python
"""Generate the two LightRAG instance environment files (local, ignored).

The instances share PostgreSQL, Qdrant and Neo4j but each is pinned to one
workspace.  ``WORKSPACE`` and the three backend overrides are written with the
*same* value so the effective namespace is unambiguous; the health check
re-verifies it at runtime.

Secrets come from ``.env`` plus the locally generated ``instance-keys.json``
and are written only under ``.local/`` (git-ignored).
"""

from __future__ import annotations

import json
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Addresses of the shared services as seen from a container on `lightrag-net`.
PG_HOST = "192.168.65.2"
HOST_GATEWAY = "192.168.65.1"  # host-published ports + the model gateway

PORTS = {"air": 9622, "water": 9623, "coastal": 9624}


def build_env(values: dict, workspace: str, api_key: str) -> dict:
    def v(key, default=None):
        value = values.get(key)
        return value if value not in (None, "") else default

    return {
        "WORKSPACE": workspace,
        "HOST": "0.0.0.0",
        "PORT": "9621",
        "WORKING_DIR": "/app/data/rag_storage",
        "INPUT_DIR": "/app/data/inputs",
        "LIGHTRAG_API_KEY": api_key,
        "LIGHTRAG_KV_STORAGE": "PGKVStorage",
        "LIGHTRAG_DOC_STATUS_STORAGE": "PGDocStatusStorage",
        "LIGHTRAG_VECTOR_STORAGE": "QdrantVectorDBStorage",
        "LIGHTRAG_GRAPH_STORAGE": "Neo4JStorage",
        "POSTGRES_HOST": PG_HOST,
        "POSTGRES_PORT": "5432",
        "POSTGRES_USER": v("POSTGRES_USER"),
        "POSTGRES_PASSWORD": v("POSTGRES_PASSWORD"),
        "POSTGRES_DATABASE": v("POSTGRES_DATABASE"),
        "POSTGRES_WORKSPACE": workspace,
        "QDRANT_URL": f"http://{HOST_GATEWAY}:6333",
        "QDRANT_WORKSPACE": workspace,
        "NEO4J_URI": f"bolt://{HOST_GATEWAY}:7687",
        "NEO4J_USERNAME": v("NEO4J_USERNAME"),
        "NEO4J_PASSWORD": v("NEO4J_PASSWORD"),
        "NEO4J_DATABASE": "neo4j",
        "NEO4J_WORKSPACE": workspace,
        "LLM_BINDING": "openai",
        "LLM_BINDING_HOST": f"http://{HOST_GATEWAY}:8787/v1",
        "LLM_BINDING_API_KEY": v("LLM_BINDING_API_KEY"),
        "LLM_MODEL": v("LLM_MODEL"),
        "KEYWORD_LLM_MODEL": v("KEYWORD_LLM_MODEL", v("LLM_MODEL")),
        "QUERY_LLM_MODEL": v("QUERY_LLM_MODEL", v("LLM_MODEL")),
        "EMBEDDING_BINDING": "openai",
        "EMBEDDING_BINDING_HOST": v("EMBEDDING_BINDING_HOST"),
        "EMBEDDING_BINDING_API_KEY": v("EMBEDDING_BINDING_API_KEY"),
        "EMBEDDING_MODEL": v("EMBEDDING_MODEL"),
        "EMBEDDING_DIM": v("EMBEDDING_DIM"),
        "EMBEDDING_TOKEN_LIMIT": v("EMBEDDING_TOKEN_LIMIT", "8192"),
        "RERANK_BINDING": v("RERANK_BINDING"),
        "RERANK_BINDING_HOST": v("RERANK_BINDING_HOST"),
        "RERANK_MODEL": v("RERANK_MODEL"),
        "RERANK_BINDING_API_KEY": v("RERANK_BINDING_API_KEY"),
        "CHUNK_SIZE": v("CHUNK_SIZE", "1500"),
        "CHUNK_OVERLAP": v("CHUNK_OVERLAP", "300"),
        "SUMMARY_LANGUAGE": v("SUMMARY_LANGUAGE", "Chinese"),
        "MAX_TOTAL_TOKENS": v("MAX_TOTAL_TOKENS", "32000"),
        "MAX_ENTITY_TOKENS": v("MAX_ENTITY_TOKENS", "6000"),
        "MAX_RELATION_TOKENS": v("MAX_RELATION_TOKENS", "8000"),
        "ENTITY_EXTRACTION_USE_JSON": "true",
        "MAX_PARALLEL_INSERT": v("MAX_PARALLEL_INSERT", "2"),
        "MAX_ASYNC_LLM": v("MAX_ASYNC_LLM", "8"),
        "LLM_TIMEOUT": v("LLM_TIMEOUT", "900"),
        "TIKTOKEN_CACHE_DIR": "/app/data/tiktoken",
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", action="append", help="only these workspaces")
    parser.add_argument(
        "--allow-new-key",
        action="store_true",
        help="generate a missing instance key for a new workspace",
    )
    args = parser.parse_args()

    from dotenv import dotenv_values

    values = dict(dotenv_values(ROOT / ".env"))
    keys_path = ROOT / ".local/workspace-access/instance-keys.json"
    if not keys_path.exists():
        raise SystemExit("missing .local/workspace-access/instance-keys.json")
    keys = json.loads(keys_path.read_text(encoding="utf-8"))
    out_dir = ROOT / ".local/workspace-access/env"
    out_dir.mkdir(parents=True, exist_ok=True)
    workspaces = args.workspace or ["air", "water"]
    for workspace in workspaces:
        if workspace not in keys:
            if not args.allow_new_key:
                raise SystemExit(f"no instance key for {workspace!r}")
            keys[workspace] = secrets.token_urlsafe(32)
            keys_path.write_text(json.dumps(keys, indent=1), encoding="utf-8")
        env = build_env(values, workspace, keys[workspace])
        missing = [k for k, val in env.items() if val in (None, "")]
        if missing:
            raise SystemExit(f"{workspace}: empty values for {missing}")
        path = out_dir / f"lightrag-{workspace}.env"
        path.write_text("\n".join(f"{k}={val}" for k, val in env.items()) + "\n", encoding="utf-8")
        path.chmod(0o600)
        print(f"wrote {path} (port {PORTS.get(workspace, 'unassigned')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
