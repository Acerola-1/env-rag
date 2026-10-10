import asyncio
import json
from pathlib import Path

import asyncpg

from env_rag_final.config import read_environment
from env_rag_final.search.index import check_search_stale


async def main():
    v = read_environment(Path(".env"))
    c = await asyncpg.connect(
        host=v["POSTGRES_HOST"],
        port=int(v["POSTGRES_PORT"]),
        user=v["POSTGRES_USER"],
        password=v["POSTGRES_PASSWORD"],
        database=v["POSTGRES_DATABASE"],
        statement_cache_size=0,
        server_settings={"default_transaction_read_only": "on", "statement_timeout": "30000"},
    )
    try:
        state = await check_search_stale(c)
        sid = state["search_id"]
        out = {"readonly": True, "search": state, "counts": {}, "plans": [], "caption_links": []}
        for table in ("search_documents", "search_chunks"):
            out["counts"][table] = await c.fetchval(
                f"SELECT count(*) FROM env_rag.{table} WHERE workspace=$1 AND search_id=$2",
                "default",
                sid,
            )
        out["indexes"] = [
            dict(r)
            for r in await c.fetch(
                "SELECT indexname,indexdef FROM pg_indexes WHERE schemaname='env_rag' AND tablename IN ('search_documents','search_chunks') ORDER BY indexname"
            )
        ]
        for tsq in ("'医疗机构' & '水污染物'", "'环境空气' & '浓度限值'", "'gb3095' <-> '-2012'"):
            rows = await c.fetch(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) SELECT chunk_id,ts_rank_cd(tsv,to_tsquery('simple',$1)) FROM env_rag.search_chunks WHERE workspace='default' AND search_id=$2 AND tsv @@ to_tsquery('simple',$1) ORDER BY ts_rank_cd(tsv,to_tsquery('simple',$1)) DESC LIMIT 20",
                tsq,
                sid,
            )
            out["plans"].append({"tsquery": tsq, "lines": [r[0] for r in rows]})
        rows = await c.fetch(
            "SELECT chunk_id,captions FROM env_rag.search_chunks WHERE workspace='default' AND search_id=$1 AND doc_id='doc-b45c510232ed4d2452b0f5b2a13434e4' AND captions <> '' ORDER BY chunk_id",
            sid,
        )
        for row in rows:
            links = await c.fetch(
                "SELECT u.caption FROM env_rag.unit_chunk_links l JOIN env_rag.source_units u USING(workspace,snapshot_id,doc_id,unit_id) WHERE l.workspace='default' AND l.snapshot_id=$1 AND l.chunk_id=$2 AND u.unit_kind='table' ORDER BY u.unit_id",
                state["catalog_snapshot_id"],
                row["chunk_id"],
            )
            out["caption_links"].append(
                {
                    "chunk_id": row["chunk_id"],
                    "captions": row["captions"],
                    "linked_captions": [r["caption"] for r in links],
                }
            )
        Path(__file__).with_name("index-readonly.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2) + "\n"
        )
        print(out["counts"], len(out["caption_links"]))
    finally:
        await c.close()


asyncio.run(main())
