"""Fourth Gate2 review: production queries over SELECT-only PG; no models."""

import asyncio
import json
from pathlib import Path

import asyncpg

from env_rag_final.catalog.builder import check_stale
from env_rag_final.catalog.source import SourceAdapter
from env_rag_final.config import read_environment
from env_rag_final.enumerate_.prose_enum import read_prose_scope
from env_rag_final.search.index import check_search_stale
from env_rag_final.search.query import run_query

OUT = Path(__file__).parent


async def main():
    v = read_environment(Path(".env"))
    conn = await asyncpg.connect(
        host=v["POSTGRES_HOST"],
        port=int(v["POSTGRES_PORT"]),
        user=v["POSTGRES_USER"],
        password=v["POSTGRES_PASSWORD"],
        database=v["POSTGRES_DATABASE"],
        statement_cache_size=0,
        server_settings={"default_transaction_read_only": "on", "statement_timeout": "30000"},
    )
    try:
        tables = (
            "doc_full",
            "doc_chunks",
            "doc_status",
            "llm_cache",
            "entity_chunks",
            "full_entities",
            "full_relations",
            "relation_chunks",
        )

        async def counts():
            return {
                t: await conn.fetchval(f"SELECT count(*) FROM public.lightrag_{t}") for t in tables
            }

        result = {
            "readonly": True,
            "model_calls": 0,
            "public_before": await counts(),
            "catalog_before": await check_stale(conn),
            "search_before": await check_search_stale(conn),
            "runs": [],
        }
        adapter = SourceAdapter(
            {
                "host": v["POSTGRES_HOST"],
                "port": int(v["POSTGRES_PORT"]),
                "user": v["POSTGRES_USER"],
                "password": v["POSTGRES_PASSWORD"],
                "database": v["POSTGRES_DATABASE"],
                "server_settings": {"default_transaction_read_only": "on"},
            }
        )
        cases = [
            (
                "prose-enum-004",
                "doc-91f9049decde09153368d4b69f280e78",
                "3",
                "GB 3838-2002 的水域功能是如何分类的？列出全部类别。",
            ),
            (
                "prose-enum-005",
                "doc-d6d711b0614234635955480a53f52a10",
                "4.1",
                "GB 14554-93 对恶臭污染物厂界标准值的分级别规定了哪几级？",
            ),
        ]
        snap = result["catalog_before"]["active_snapshot_id"]
        for name, doc, num, question in cases:
            scope = doc + ":scope:" + num
            structure = [
                dict(r)
                for r in await conn.fetch(
                    "SELECT scope_id,number,title,confirm_status FROM env_rag.scopes WHERE workspace='default' AND snapshot_id=$1 AND scope_id=$2",
                    snap,
                    scope,
                )
            ]
            members = [
                dict(r)
                for r in await conn.fetch(
                    "SELECT u.unit_id,u.content_length,u.requires_span FROM env_rag.scope_units s JOIN env_rag.source_units u USING (workspace,snapshot_id,unit_id,doc_id) WHERE s.workspace='default' AND s.snapshot_id=$1 AND s.scope_id=$2 ORDER BY s.seq",
                    snap,
                    scope,
                )
            ]
            units, read = await read_prose_scope(
                adapter, conn, "default", doc, snap, scope_id=scope
            )
            explicit = await run_query(conn, question, source_values=v, expand=True, scope_id=scope)
            result["runs"].append(
                {
                    "name": name,
                    "catalog_structure": structure,
                    "catalog_members": members,
                    "read_result": read.to_dict(),
                    "raw_units": [{"unit_id": u.unit_id, "text": u.text} for u in units],
                    "explicit_scope_query": explicit.to_dict(),
                }
            )
            print(
                name,
                structure,
                "read",
                read.read_status,
                read.members_processed,
                read.members_total,
                "explicit",
                explicit.status,
                flush=True,
            )
        result["catalog_after"] = await check_stale(conn)
        result["search_after"] = await check_search_stale(conn)
        result["public_after"] = await counts()
        result["source_and_active_unchanged"] = result["catalog_before"] == result["catalog_after"]
        result["public_unchanged"] = result["public_before"] == result["public_after"]
        (OUT / "scope-cause-and-final-source.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
    finally:
        await conn.close()


asyncio.run(main())
