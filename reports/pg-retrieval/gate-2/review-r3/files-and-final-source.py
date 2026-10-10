"""Third Gate2 review: production queries over SELECT-only PG; no models."""

import asyncio
import json
from pathlib import Path

import asyncpg

from env_rag_final.catalog.builder import check_stale
from env_rag_final.config import read_environment
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
        gold = json.loads(Path("reports/pg-retrieval/phase-2/gold-candidates.json").read_text())
        for q in gold["questions"]:
            if q["category"] != "file_enum":
                continue
            r = await run_query(conn, q["question"], source_values=v, expand_docs=True)
            got = {c["doc_id"] for c in r.candidates}
            want = set(q["gold"]["expected_doc_ids"])
            result["runs"].append(
                {
                    "name": q["query_id"],
                    "result": r.to_dict(),
                    "doc_set_equal": got == want,
                    "missing": sorted(want - got),
                    "extra": sorted(got - want),
                }
            )
            print(q["query_id"], r.status, len(got), got == want, flush=True)
        result["catalog_after"] = await check_stale(conn)
        result["search_after"] = await check_search_stale(conn)
        result["public_after"] = await counts()
        result["source_and_active_unchanged"] = result["catalog_before"] == result["catalog_after"]
        result["public_unchanged"] = result["public_before"] == result["public_after"]
        (OUT / "files-and-final-source.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
    finally:
        await conn.close()


asyncio.run(main())
