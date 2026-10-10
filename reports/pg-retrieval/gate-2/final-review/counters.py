"""Final Gate2 review: production queries over SELECT-only PG; no models."""

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
        cases = [
            ("absent_version", "GB3095-1996 的限值", {}),
            ("absent_bare_code", "GB50014 雨水管渠重现期", {}),
            ("absent_fullwidth_version", "ＧＢ３０９５－１９９６ 年平均", {}),
            ("mixed_version_missing", "GB3095-2012 与 GB3095-1996", {}),
            ("own_code_not_citation", "自身编号为 GB3838-2002 的文档有哪些", {"expand_docs": True}),
            ("fragmented_table_complete", "GB8978-1996 表1有哪些污染物", {"expand": True}),
            ("uncertain_base_fragment", "GB8978-1996 表2有哪些污染物", {"expand": True}),
            ("unresolved_request", "医疗机构污水执行要求", {"expand": True}),
        ]
        for name, question, kwargs in cases:
            r = await run_query(conn, question, source_values=v, **kwargs)
            doc = r.to_dict()
            ex = [
                e
                for step in r.trace
                if step.get("stage") == "scope_expansion"
                for e in step.get("expansions", [])
            ]
            if name.startswith("absent_"):
                ok = r.status == "missing" and not r.candidates
            elif name == "mixed_version_missing":
                ok = r.status == "missing" and {c["doc_id"] for c in r.candidates} == {
                    "doc-257d8cf3fdf90e76c31908c4f92fc1a1"
                }
            elif name == "own_code_not_citation":
                ok = r.status == "ok" and {c["doc_id"] for c in r.candidates} == {
                    "doc-91f9049decde09153368d4b69f280e78"
                }
            elif name == "fragmented_table_complete":
                items = ex[0]["items"]
                ok = (
                    ex[0]["coverage_status"] == "complete"
                    and len(items) == 13
                    and {int(it["cells"][0]) for it in items} == set(range(1, 14))
                    and all(it.get("citation_verified") for it in items)
                )
            elif name == "uncertain_base_fragment":
                ok = r.status == "ambiguous" and ex[0]["coverage_status"] == "ambiguous"
            else:
                ok = r.status == "ambiguous" and not ex
            result["runs"].append(
                {
                    "name": name,
                    "query": question,
                    "kwargs": kwargs,
                    "behavior_assertion_passed": ok,
                    "result": doc,
                }
            )
            print(name, ok, r.status, flush=True)
        result["catalog_after"] = await check_stale(conn)
        result["search_after"] = await check_search_stale(conn)
        result["public_after"] = await counts()
        result["source_and_active_unchanged"] = result["catalog_before"] == result["catalog_after"]
        result["public_unchanged"] = result["public_before"] == result["public_after"]
        (OUT / "counterexamples-full.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
    finally:
        await conn.close()


asyncio.run(main())
