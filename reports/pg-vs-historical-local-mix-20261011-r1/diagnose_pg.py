"""Read-only diagnostics. Does not change the original-question verdict."""

import asyncio
import json
from pathlib import Path

import asyncpg

from env_rag_final.ask import Question, ask_question
from env_rag_final.config import read_environment
from env_rag_final.local_adapter import _capture_production_identity, _identity_drift
from env_rag_final.search.index import check_search_stale
from env_rag_final.search.query import run_query
from env_rag_final.web.service import sanitize

ROOT = Path("/Users/acerola/Dev/Python/RAG/env-rag-final")
OUT = Path(__file__).parent
values = read_environment(ROOT / ".env")
original = json.loads((OUT / "request.json").read_text())["query"]
filename = "air-47_European-Commission_Directive-2024-2881-Ambient-Air-Quality_2024.pdf"


async def main():
    before = await _capture_production_identity(values)
    conn = await asyncpg.connect(
        host=values["POSTGRES_HOST"],
        port=int(values["POSTGRES_PORT"]),
        user=values["POSTGRES_USER"],
        password=values["POSTGRES_PASSWORD"],
        database=values["POSTGRES_DATABASE"],
        timeout=15,
        server_settings={"default_transaction_read_only": "on", "statement_timeout": "30000"},
        statement_cache_size=0,
    )
    try:
        guard = await check_search_stale(conn)
        snapshot = guard["catalog_snapshot_id"]
        rows = await conn.fetch(
            "SELECT doc_id,doc_name,title,self_code,self_code_version FROM env_rag.documents WHERE workspace=$1 AND snapshot_id=$2 AND doc_name=$3",
            "default",
            snapshot,
            filename,
        )
        assert len(rows) == 1
        doc = dict(rows[0])
        docid = doc["doc_id"]
        units = [
            dict(r)
            for r in await conn.fetch(
                "SELECT unit_id,unit_kind,heading,caption,table_seq,locator FROM env_rag.source_units WHERE workspace=$1 AND snapshot_id=$2 AND doc_id=$3 AND unit_kind=$4 ORDER BY unit_order",
                "default",
                snapshot,
                docid,
                "table",
            )
        ]
        scopes = [
            dict(r)
            for r in await conn.fetch(
                "SELECT scope_id,scope_kind,title,number,confirm_status FROM env_rag.scopes WHERE workspace=$1 AND snapshot_id=$2 AND doc_id=$3 ORDER BY scope_id",
                "default",
                snapshot,
                docid,
            )
        ]
        discovery = (await run_query(conn, original, top_k=20, source_values=values)).to_dict()
        # Auxiliary experiment: explicit filename plus simplified question.
        # It is NOT the original natural-language request and cannot repair its verdict.
        diagnostic_query = original.replace("第 1 节", "")
        clarified = await ask_question(
            Question(diagnostic_query, document=filename), values, conn=conn
        )
    finally:
        await conn.close()
    after = await _capture_production_identity(values)
    assert before["matches_frozen"] is True and after["matches_frozen"] is True
    drift = _identity_drift(before["identity"], after["identity"])
    assert not drift
    result = {
        "evidence_mode": "fresh_production_readonly_diagnostic",
        "original_query": original,
        "doc": doc,
        "table_units": units,
        "scopes": scopes,
        "original_query_keyword_discovery": discovery,
        "clarified_request": {
            "query": diagnostic_query,
            "document": filename,
            "counted_as_original_success": False,
        },
        "clarified_enumeration": clarified,
        "identity_before": before,
        "identity_after": after,
        "identity_drift": drift,
        "model_calls": 0,
        "embedding_calls": 0,
        "rerank_calls": 0,
    }
    with (OUT / "pg-diagnostics.json").open("x") as f:
        json.dump(sanitize(result, values), f, ensure_ascii=False, indent=2, default=str)
    print(
        json.dumps(
            {
                "document": doc,
                "table_units": len(units),
                "captions_first6": [u["caption"] for u in units[:6]],
                "scopes": len(scopes),
                "keyword_status": discovery["status"],
                "keyword_doc_ids": sorted(
                    {c.get("doc_id") for c in discovery.get("candidates", []) if c.get("doc_id")}
                ),
                "target_document_found": any(
                    c.get("doc_id") == docid for c in discovery.get("candidates", [])
                ),
                "clarified_status": clarified["coverage_status"],
                "clarified_flags": clarified["flags"],
                "clarified_items": len(clarified["answer"]["items"]),
                "drift": drift,
            },
            ensure_ascii=False,
        )
    )


asyncio.run(main())
