"""Independent Gate 2 SELECT-only replay; no model calls or DB mutations."""

import asyncio
import json
from pathlib import Path

import asyncpg

from env_rag_final.catalog.builder import check_stale
from env_rag_final.config import read_environment
from env_rag_final.search.index import check_search_stale
from env_rag_final.search.query import explain_query, run_query

OUT = Path(__file__).parent


async def main():
    values = read_environment(Path(".env"))
    conn = await asyncpg.connect(
        host=values["POSTGRES_HOST"],
        port=int(values["POSTGRES_PORT"]),
        user=values["POSTGRES_USER"],
        password=values["POSTGRES_PASSWORD"],
        database=values["POSTGRES_DATABASE"],
        statement_cache_size=0,
        server_settings={"default_transaction_read_only": "on", "statement_timeout": "30000"},
    )
    try:
        evidence = {"readonly": True, "model_calls": 0, "runs": []}
        tables = [
            "doc_full",
            "doc_chunks",
            "doc_status",
            "llm_cache",
            "entity_chunks",
            "full_entities",
            "full_relations",
            "relation_chunks",
        ]

        async def counts():
            return {
                t: await conn.fetchval(f"SELECT count(*) FROM public.lightrag_{t}") for t in tables
            }

        evidence["public_before"] = await counts()
        evidence["catalog_before"] = await check_stale(conn)
        evidence["search_before"] = await check_search_stale(conn)
        cases = [
            ("ascii_fact", "GB3095-2012 二氧化硫年平均", {}),
            ("fullwidth_absent", "ＧＢ３０９５－１９９６ 二级标准年均限值", {}),
            ("partial_absent", "GB3095-2012 与 GB3095-1996 对比", {}),
            ("bare_absent", "GB50014 环境空气", {}),
            ("version_docs", "GB3095-2012", {"expand_docs": True}),
            ("yearbook_docs", "库内有哪些中国移动源环境管理年报", {"expand_docs": True}),
            ("auto_scope", "GB18466-2005 第3章有哪些术语", {"expand": True, "top_k": 1}),
            (
                "manual_scope",
                "GB18466-2005 第3章有哪些术语",
                {
                    "expand": True,
                    "top_k": 1,
                    "scope_id": "doc-68a03b50e1ba1ffc6a0116529f694fe1:scope:3",
                },
            ),
            ("table_top1", "GB8978-1996 表1", {"expand": True, "top_k": 1, "table_number": "1"}),
            ("caption_pollution", "GB8978-1996 表6", {}),
        ]
        for name, query, kwargs in cases:
            result = await run_query(conn, query, source_values=values, **kwargs)
            record = {"name": name, "query": query, "kwargs": kwargs, "result": result.to_dict()}
            evidence["runs"].append(record)
            print(name, result.status, len(result.candidates), flush=True)
        evidence["caption_attachment"] = [
            dict(r)
            for r in await conn.fetch(
                """SELECT s.chunk_id,s.captions,position('表6' in c.content)>0 AS raw_mentions_table6,
                      position('表 6' in c.content)>0 AS raw_mentions_spaced_table6
               FROM env_rag.search_chunks s JOIN public.lightrag_doc_chunks c
                 ON c.workspace=s.workspace AND c.id=s.chunk_id
               WHERE s.workspace='default' AND s.search_id=$1 AND s.doc_id=$2 ORDER BY s.chunk_order""",
                evidence["search_before"]["search_id"],
                "doc-b45c510232ed4d2452b0f5b2a13434e4",
            )
        ]
        evidence["file005_predicate"] = [
            dict(r)
            for r in await conn.fetch(
                """SELECT doc_id,doc_name,self_code,self_code_version FROM env_rag.documents
               WHERE workspace='default' AND snapshot_id=$1 AND (self_code='GB18466' OR doc_name LIKE '%GB18466%') ORDER BY doc_name""",
                evidence["catalog_before"]["active_snapshot_id"],
            )
        ]
        evidence["explain"] = await explain_query(
            conn, evidence["search_before"]["search_id"], "'医疗机构' & '水污染物'"
        )
        evidence["catalog_after"] = await check_stale(conn)
        evidence["search_after"] = await check_search_stale(conn)
        evidence["public_after"] = await counts()
        evidence["public_unchanged"] = evidence["public_before"] == evidence["public_after"]
        evidence["source_and_active_unchanged"] = (
            evidence["catalog_before"] == evidence["catalog_after"]
        )
        (OUT / "replay.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    finally:
        await conn.close()


asyncio.run(main())
