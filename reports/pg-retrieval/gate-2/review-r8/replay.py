"""Eighth Gate2 review: production queries over SELECT-only PG; no models."""

import asyncio
import json
from pathlib import Path

import asyncpg

from env_rag_final.audit.identity import PARSED_ROOT
from env_rag_final.catalog.builder import check_stale
from env_rag_final.catalog.units import parse_blocks
from env_rag_final.config import read_environment
from env_rag_final.search.eval import run_benchmark
from env_rag_final.search.index import check_search_stale
from env_rag_final.search.probe import run_tokenizer_probes
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
        gold = json.loads(
            Path("reports/pg-retrieval/gate-2/review-r5/gold-approved.json").read_text()
        )
        cases = []
        for name, text, kwargs in cases:
            r = await run_query(conn, text, source_values=v, **kwargs)
            result["runs"].append(
                {"name": name, "query": text, "kwargs": kwargs, "result": r.to_dict()}
            )
            ex = [
                e
                for s in r.trace
                if s.get("stage") == "scope_expansion"
                for e in s.get("expansions", [])
            ]
            print(
                name,
                r.status,
                len(r.candidates),
                [(e.get("coverage_status", e.get("status")), e.get("items_count")) for e in ex],
                flush=True,
            )
        result["gold_units"] = []
        for q in gold["questions"]:
            for e in q["gold"].get("target_evidence", []):
                uid = e.get("unit_id")
                if not uid:
                    continue
                doc = await conn.fetchrow(
                    "SELECT doc_name FROM env_rag.documents WHERE workspace='default' AND snapshot_id=$1 AND doc_id=$2",
                    result["catalog_before"]["active_snapshot_id"],
                    e["doc_id"],
                )
                meta, bl = parse_blocks(PARSED_ROOT / (doc["doc_name"] + ".parsed"))
                raw = next((b.get("content", "") for b in bl if b.get("blockid") == uid), None)
                result["gold_units"].append(
                    {"query_id": q["query_id"], "target_evidence": e, "raw_block_quote": raw}
                )
        result["benchmark"] = await run_benchmark(
            conn, gold, expand=True, values=v, runs_path=OUT / "benchmark-runs.jsonl"
        )
        (OUT / "benchmark.json").write_text(
            json.dumps(result["benchmark"], ensure_ascii=False, indent=2) + "\n"
        )
        result["probes"] = await run_tokenizer_probes(conn, OUT, v)
        (OUT / "tokenizer-probes.json").write_text(
            json.dumps(result["probes"], ensure_ascii=False, indent=2) + "\n"
        )
        result["catalog_after"] = await check_stale(conn)
        result["search_after"] = await check_search_stale(conn)
        result["public_after"] = await counts()
        result["source_and_active_unchanged"] = result["catalog_before"] == result["catalog_after"]
        result["public_unchanged"] = result["public_before"] == result["public_after"]
        (OUT / "replay.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    finally:
        await conn.close()


asyncio.run(main())
