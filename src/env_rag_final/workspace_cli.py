"""CLI for the workspace-access feature (``env-rag-final workspace-*``).

Kept separate from the frozen retrieval CLI so the existing commands and their
contracts are untouched.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from env_rag_final.paths import PROJECT_ROOT

DEFAULT_MANIFEST = PROJECT_ROOT / "reports/workspace-access/wa-20261012-r1/corpus-manifest.jsonl"
DEFAULT_RUN_DIR = PROJECT_ROOT / "reports/workspace-access/wa-20261012-r1"
LOCAL_DIR = PROJECT_ROOT / ".local/workspace-access"


def _connect(values: dict):
    import asyncpg

    return asyncpg.connect(
        host=values["POSTGRES_HOST"],
        port=int(values["POSTGRES_PORT"]),
        user=values["POSTGRES_USER"],
        password=values["POSTGRES_PASSWORD"],
        database=values["POSTGRES_DATABASE"],
    )


def _values(env_file: Path) -> dict:
    from dotenv import dotenv_values

    return {k: v for k, v in dotenv_values(env_file).items() if v is not None}


def cmd_manifest(args) -> int:
    import subprocess

    from env_rag_final.manifest import build_manifest, summarize

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pg_ids = None
    if args.default_pg:
        res = subprocess.run(
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
                "select id from lightrag_doc_status where workspace='default';",
            ],
            capture_output=True,
            text=True,
        )
        pg_ids = {line.strip() for line in res.stdout.splitlines() if line.strip()}
    entries = build_manifest(Path(args.parsed_root), default_pg_doc_ids=pg_ids)
    with out.open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry.as_row(), ensure_ascii=False, sort_keys=True) + "\n")
    summary = summarize(entries)
    if args.summary:
        Path(args.summary).write_text(
            json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k not in ("air", "water")},
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0


def cmd_ingest(args) -> int:
    from env_rag_final.ingest.runner import IngestConfig, run_ingest

    values = _values(args.env_file)
    overrides = {}
    for item in args.set or []:
        key, _, value = item.partition("=")
        overrides[key] = value
    cfg = IngestConfig(
        workspace=args.workspace,
        values=values,
        parsed_root=Path(args.parsed_root),
        manifest_path=Path(args.manifest),
        ledger_path=Path(args.ledger or (LOCAL_DIR / f"ingest-{args.workspace}.jsonl")),
        source_workspace=args.source_workspace,
        dry_run=args.dry_run,
        only=args.doc_name or None,
        limit=args.limit,
        extra_docs=args.extra_doc or None,
        process_rounds=args.process_rounds,
        overrides=overrides,
    )
    summary = asyncio.run(run_ingest(cfg))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(
            json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
        )
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
    return 0


def cmd_catalog(args) -> int:
    import asyncio

    from env_rag_final.catalog import builder
    from env_rag_final.search import index as index_mod

    values = _values(args.env_file)

    async def run() -> dict:
        conn = await _connect(values)
        try:
            live = await builder._live_source_fingerprint(conn, args.workspace)
            if args.command == "workspace-catalog":
                result = await builder.build_catalog(
                    conn,
                    expected_fingerprint=live,
                    workspace=args.workspace,
                    force=args.force,
                )
                return {
                    "command": "catalog",
                    "workspace": args.workspace,
                    "snapshot_id": result.snapshot_id,
                    "fingerprint": result.fingerprint,
                    "docs": result.docs,
                    "units": result.units,
                    "links": result.links,
                    "scopes": result.scopes,
                    "published": result.published,
                }
            result = await index_mod.build_search_index(
                conn, workspace=args.workspace, force=args.force
            )
            return {
                "command": "index",
                "workspace": args.workspace,
                "search_id": result.search_id,
                "catalog_snapshot_id": result.catalog_snapshot_id,
                "documents": getattr(result, "documents", None),
                "chunks": getattr(result, "chunks", None),
            }
        finally:
            await conn.close()

    out = asyncio.run(run())
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    if args.out:
        Path(args.out).write_text(
            json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
        )
    return 0


def cmd_stale(args) -> int:
    import asyncio

    from env_rag_final.catalog import builder
    from env_rag_final.search.index import check_search_stale

    values = _values(args.env_file)

    async def run() -> dict:
        conn = await _connect(values)
        try:
            return {
                "workspace": args.workspace,
                "catalog": await builder.check_stale(conn, workspace=args.workspace),
                "search": await check_search_stale(conn, workspace=args.workspace),
            }
        finally:
            await conn.close()

    print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=1, default=str))
    return 0


def cmd_health(args) -> int:
    """Prove the effective workspace of PG / Qdrant / Neo4j for a workspace."""
    import asyncio

    import httpx
    from neo4j import AsyncGraphDatabase

    values = _values(args.env_file)

    async def run() -> dict:
        conn = await _connect(values)
        try:
            pg_rows = await conn.fetchval(
                "select count(*) from public.lightrag_doc_full where workspace=$1",
                args.workspace,
            )
            pg_chunks = await conn.fetchval(
                "select count(*) from public.lightrag_doc_chunks where workspace=$1",
                args.workspace,
            )
        finally:
            await conn.close()
        qurl = str(values["QDRANT_URL"]).rstrip("/")
        collections = httpx.get(f"{qurl}/collections", timeout=30).json()["result"]["collections"]
        qdrive = {}
        for col in collections:
            for ws in (args.workspace,):
                res = httpx.post(
                    f"{qurl}/collections/{col['name']}/points/count",
                    json={
                        "exact": True,
                        "filter": {"must": [{"key": "workspace_id", "match": {"value": ws}}]},
                    },
                    timeout=60,
                ).json()
                qdrive[col["name"]] = res.get("result", {}).get("count")
        driver = AsyncGraphDatabase.driver(
            values["NEO4J_URI"], auth=(values["NEO4J_USERNAME"], values["NEO4J_PASSWORD"])
        )
        try:
            async with driver.session(database=values.get("NEO4J_DATABASE") or "neo4j") as session:
                rec = await (
                    await session.run(f"MATCH (n:`{args.workspace}`) RETURN count(n) AS c")
                ).single()
                nodes = rec["c"] if rec else 0
                rel = await (
                    await session.run(f"MATCH (:`{args.workspace}`)-[r]->() RETURN count(r) AS c")
                ).single()
                edges = rel["c"] if rel else 0
        finally:
            await driver.close()
        return {
            "workspace": args.workspace,
            "postgres": {"doc_full": pg_rows, "doc_chunks": pg_chunks},
            "qdrant_by_workspace_id": qdrive,
            "neo4j_label": {"nodes": nodes, "relationships": edges},
        }

    out = asyncio.run(run())
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    if args.out:
        Path(args.out).write_text(
            json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="env-rag-final workspace")
    parser.add_argument(
        "command",
        choices=[
            "workspace-manifest",
            "workspace-ingest",
            "workspace-catalog",
            "workspace-index",
            "workspace-stale",
            "workspace-health",
        ],
    )
    parser.add_argument("--workspace")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--parsed-root", default=str(PROJECT_ROOT / "datasets/corpus/parsed"))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--ledger")
    parser.add_argument("--out")
    parser.add_argument("--summary")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--process-rounds", type=int, default=1)
    parser.add_argument("--source-workspace", default="default")
    parser.add_argument("--doc-name", action="append")
    parser.add_argument(
        "--extra-doc",
        action="append",
        help="real document this workspace also holds (explicitly shared copy)",
    )
    parser.add_argument("--set", action="append", metavar="KEY=VALUE")
    parser.add_argument(
        "--default-pg", action="store_true", help="manifest: read default PG membership"
    )
    args = parser.parse_args(argv)

    if args.command == "workspace-manifest":
        return cmd_manifest(args)
    if not args.workspace:
        parser.error(f"{args.command} requires --workspace")
    if args.command == "workspace-ingest":
        return cmd_ingest(args)
    if args.command in ("workspace-catalog", "workspace-index"):
        return cmd_catalog(args)
    if args.command == "workspace-stale":
        return cmd_stale(args)
    if args.command == "workspace-health":
        return cmd_health(args)
    return 2
