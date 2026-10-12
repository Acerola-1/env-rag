"""Corrected reference, explicit file diagnostic; not an original-question success."""

import asyncio
import json
from pathlib import Path

import asyncpg

from env_rag_final.ask import Question, ask_question
from env_rag_final.config import read_environment
from env_rag_final.search.index import check_search_stale
from env_rag_final.web.service import sanitize

ROOT = Path("/Users/acerola/Dev/Python/RAG/env-rag-final")
OUT = Path(__file__).parent
values = read_environment(ROOT / ".env")


async def main():
    conn = await asyncpg.connect(
        host=values["POSTGRES_HOST"],
        port=int(values["POSTGRES_PORT"]),
        user=values["POSTGRES_USER"],
        password=values["POSTGRES_PASSWORD"],
        database=values["POSTGRES_DATABASE"],
        timeout=15,
        statement_cache_size=0,
        server_settings={"default_transaction_read_only": "on", "statement_timeout": "30000"},
    )
    try:
        before = await check_search_stale(conn)
        query = "欧盟指令 2024/2881 附件 I 表 3 规定了哪 4 项指标的目标值？请用英文名称列出这 4 项指标。"
        result = await ask_question(
            Question(
                query,
                document="air-47_European-Commission_Directive-2024-2881-Ambient-Air-Quality_2024.pdf",
            ),
            values,
            conn=conn,
        )
        after = await check_search_stale(conn)
        assert before["state"] == after["state"] == "current"
        assert all(
            before[k] == after[k]
            for k in ["catalog_snapshot_id", "search_id", "source_fingerprint"]
        )
        output = {
            "classification": "auxiliary_corrected_reference_and_explicit_file_not_original_success",
            "request": {
                "query": query,
                "document": "air-47_European-Commission_Directive-2024-2881-Ambient-Air-Quality_2024.pdf",
            },
            "result": result,
            "identity_before": before,
            "identity_after": after,
            "model_calls": 0,
        }
        with (OUT / "corrected-table3-diagnostic.json").open("x") as f:
            json.dump(sanitize(output, values), f, ensure_ascii=False, indent=2)
        print(
            json.dumps(
                {
                    "coverage_status": result["coverage_status"],
                    "flags": result["flags"],
                    "items": len(result["answer"]["items"]),
                    "model_calls": 0,
                },
                ensure_ascii=False,
            )
        )
    finally:
        await conn.close()


asyncio.run(main())
