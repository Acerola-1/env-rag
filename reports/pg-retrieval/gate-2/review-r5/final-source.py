"""Fifth Gate2 review: production queries over SELECT-only PG; no models."""

import asyncio
import json
from pathlib import Path

import asyncpg

from env_rag_final.catalog.builder import check_stale
from env_rag_final.config import read_environment
from env_rag_final.search.index import check_search_stale

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
        result["catalog_after"] = await check_stale(conn)
        result["search_after"] = await check_search_stale(conn)
        result["public_after"] = await counts()
        prior = json.loads((OUT / "replay.json").read_text())
        result["matches_initial_public"] = result["public_after"] == prior["public_before"]
        result["matches_initial_catalog"] = result["catalog_after"] == prior["catalog_before"]
        result["matches_initial_search"] = result["search_after"] == prior["search_before"]
        (OUT / "final-source.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
        print(
            result["matches_initial_public"],
            result["matches_initial_catalog"],
            result["matches_initial_search"],
        )
    finally:
        await conn.close()


asyncio.run(main())
