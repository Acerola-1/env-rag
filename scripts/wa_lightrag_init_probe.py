#!/usr/bin/env python
"""Isolated probe: what does LightRAG storage initialisation actually do?

Runs ``LightRAG.initialize_storages()`` against an **isolated** PostgreSQL
clone of the production schema (``--pg-port``), with a throwaway workspace
name, and records:

* the PG schema before/after (table definitions, indexes, constraints),
* the Qdrant collection configuration before/after,
* the Neo4j labels and indexes before/after.

Nothing here writes to the production PostgreSQL.  Qdrant/Neo4j are shared
services, so the probe only ever *reads* their pre-existing state and reports
exactly what changed; the point is to learn whether initialisation is
additive before letting a real ingestion touch them.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def pg_snapshot(exec_argv: list[str]) -> dict:
    sql = """
select t.table_schema||'.'||t.table_name as tbl,
       coalesce(pg_get_tabledef, '') as def
from information_schema.tables t,
lateral (select '' as pg_get_tabledef) x
where t.table_schema in ('public','env_rag') and t.table_type='BASE TABLE'
order by 1;
"""
    cols = """
select table_schema||'.'||table_name||'.'||column_name||':'||data_type||':'||is_nullable
from information_schema.columns where table_schema in ('public','env_rag')
order by 1;
"""
    idx = """
select schemaname||'.'||indexname||'='||indexdef from pg_indexes
where schemaname in ('public','env_rag') order by 1;
"""
    con = """
select conrelid::regclass::text||':'||conname||':'||pg_get_constraintdef(oid)
from pg_constraint where connamespace::regnamespace::text in ('public','env_rag')
order by 1;
"""
    out = {}
    for name, query in (("tables", sql), ("columns", cols), ("indexes", idx), ("constraints", con)):
        res = subprocess.run(exec_argv + [query], capture_output=True, text=True)
        out[name] = sorted(line for line in res.stdout.splitlines() if line.strip())
    return out


def qdrant_snapshot(url: str, api_key: str | None) -> dict:
    import httpx

    headers = {"api-key": api_key} if api_key else {}
    snap: dict = {}
    cols = httpx.get(f"{url}/collections", headers=headers, timeout=30).json()["result"][
        "collections"
    ]
    for col in cols:
        name = col["name"]
        info = httpx.get(f"{url}/collections/{name}", headers=headers, timeout=30).json()["result"]
        snap[name] = {
            "points_count": info.get("points_count"),
            "config": info.get("config"),
            "payload_schema": sorted((info.get("payload_schema") or {}).keys()),
        }
    return snap


def neo4j_snapshot(uri: str, user: str, password: str, database: str) -> dict:
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session(database=database) as s:
            labels = sorted(r["label"] for r in s.run("CALL db.labels() YIELD label RETURN label"))
            indexes = sorted(
                str(r.data())
                for r in s.run("SHOW INDEXES YIELD name, labelsOrTypes, properties RETURN *")
            )
            return {"labels": labels, "indexes": indexes}
    finally:
        driver.close()


async def run_init(env: dict, workspace: str) -> dict:
    """Build a real LightRAG instance and initialise its storages."""
    import httpx
    from lightrag import LightRAG
    from lightrag.utils import EmbeddingFunc

    events: list[str] = []

    async def llm(prompt, system_prompt=None, history_messages=None, **kwargs):
        return "probe-no-llm"

    async def embed(texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=60) as client:
            res = await client.post(
                env["EMBEDDING_BINDING_HOST"].rstrip("/") + "/embeddings",
                headers={"Authorization": f"Bearer {env['EMBEDDING_BINDING_API_KEY']}"},
                json={"model": env["EMBEDDING_MODEL"], "input": list(texts)[:8]},
            )
            res.raise_for_status()
            return [d["embedding"] for d in res.json()["data"]]

    rag = LightRAG(
        working_dir=str(Path(".local/workspace-access/probe-work") / workspace),
        workspace=workspace,
        kv_storage="PGKVStorage",
        doc_status_storage="PGDocStatusStorage",
        vector_storage="QdrantVectorDBStorage",
        graph_storage="Neo4JStorage",
        llm_model_func=llm,
        embedding_func=EmbeddingFunc(
            embedding_dim=int(env["EMBEDDING_DIM"]),
            max_token_size=8192,
            func=embed,
        ),
    )
    try:
        await rag.initialize_storages()
        events.append("initialize_storages ok")
        from lightrag.kg.shared_storage import initialize_pipeline_status

        await initialize_pipeline_status()
        events.append("initialize_pipeline_status ok")
    finally:
        try:
            await rag.finalize_storages()
        except Exception as exc:  # pragma: no cover - probe reporting
            events.append(f"finalize_storages error: {type(exc).__name__}: {exc}")
    return {"events": events}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pg-port", default="55432")
    parser.add_argument("--pg-user", default="rag")
    parser.add_argument("--pg-password", default="probeonly")
    parser.add_argument("--pg-db", default="rag")
    parser.add_argument("--workspace", default="wa-probe")
    parser.add_argument("--out", required=True)
    parser.add_argument("--env-file", default=str(Path(".env")))
    args = parser.parse_args()

    from dotenv import dotenv_values

    base = dict(dotenv_values(args.env_file))
    # Redirect only PostgreSQL at the isolated clone; Qdrant/Neo4j stay real but
    # isolated by the throwaway workspace name.
    env = dict(base)
    env.update(
        {
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": args.pg_port,
            "POSTGRES_USER": args.pg_user,
            "POSTGRES_PASSWORD": args.pg_password,
            "POSTGRES_DATABASE": args.pg_db,
            "WORKSPACE": args.workspace,
            "POSTGRES_WORKSPACE": args.workspace,
            "QDRANT_WORKSPACE": args.workspace,
            "NEO4J_WORKSPACE": args.workspace,
            "NEO4J_DATABASE": "neo4j",
            "EMBEDDING_DIM": str(base.get("EMBEDDING_DIM", "2560")),
            "EMBEDDING_MODEL": base.get("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-4B"),
        }
    )
    import os

    for key in (
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DATABASE",
        "WORKSPACE",
        "POSTGRES_WORKSPACE",
        "QDRANT_WORKSPACE",
        "NEO4J_WORKSPACE",
        "NEO4J_DATABASE",
        "EMBEDDING_DIM",
        "EMBEDDING_MODEL",
        "QDRANT_URL",
        "NEO4J_URI",
        "NEO4J_USERNAME",
        "NEO4J_PASSWORD",
    ):
        os.environ[key] = str(env[key])

    qexec = [
        "container",
        "exec",
        "wa-probe-pg",
        "psql",
        "-U",
        args.pg_user,
        "-d",
        args.pg_db,
        "-tAc",
    ]
    before = {
        "pg": pg_snapshot(qexec),
        "qdrant": qdrant_snapshot(env["QDRANT_URL"], env.get("QDRANT_API_KEY")),
        "neo4j": neo4j_snapshot(
            env["NEO4J_URI"], env["NEO4J_USERNAME"], env["NEO4J_PASSWORD"], "neo4j"
        ),
    }
    result = asyncio.run(run_init(env, args.workspace))
    after = {
        "pg": pg_snapshot(qexec),
        "qdrant": qdrant_snapshot(env["QDRANT_URL"], env.get("QDRANT_API_KEY")),
        "neo4j": neo4j_snapshot(
            env["NEO4J_URI"], env["NEO4J_USERNAME"], env["NEO4J_PASSWORD"], "neo4j"
        ),
    }

    diff = {}
    for section in ("pg", "neo4j"):
        for key in before[section]:
            b, a = set(before[section][key]), set(after[section][key])
            if b != a:
                diff[f"{section}.{key}"] = {
                    "added": sorted(a - b),
                    "removed": sorted(b - a),
                }
    qdiff = {}
    for name, bef in before["qdrant"].items():
        aft = after["qdrant"].get(name)
        if aft != bef:
            qdiff[name] = {"before": bef, "after": aft}
    if qdiff:
        diff["qdrant.collections"] = qdiff
    added_collections = sorted(set(after["qdrant"]) - set(before["qdrant"]))
    if added_collections:
        diff["qdrant.new_collections"] = added_collections

    report = {
        "workspace": args.workspace,
        "pg_target": f"{env['POSTGRES_HOST']}:{env['POSTGRES_PORT']}/{env['POSTGRES_DATABASE']}",
        "events": result["events"],
        "diff": diff,
        "before_summary": {
            "pg_tables": len(before["pg"]["tables"]),
            "qdrant": {k: v["points_count"] for k, v in before["qdrant"].items()},
            "neo4j_labels": before["neo4j"]["labels"],
        },
        "after_summary": {
            "pg_tables": len(after["pg"]["tables"]),
            "qdrant": {k: v["points_count"] for k, v in after["qdrant"].items()},
            "neo4j_labels": after["neo4j"]["labels"],
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(
        json.dumps(
            {k: v for k, v in report.items() if k not in ("diff",)}, ensure_ascii=False, indent=1
        )
    )
    print("DIFF KEYS:", sorted(report["diff"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
