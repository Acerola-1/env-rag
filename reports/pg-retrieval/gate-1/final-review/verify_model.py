"""Verify saved authorized model output against raw blocks and SELECT-only state."""

import asyncio
import json
from pathlib import Path

import asyncpg

from env_rag_final.audit.identity import PARSED_ROOT
from env_rag_final.catalog.builder import check_stale
from env_rag_final.config import read_environment

OUT = Path(__file__).parent


async def main():
    result = json.loads((OUT / "model-live.json").read_text())
    expected = {"门诊", "病房", "手术室", "各类检验室", "病理解剖室", "放射室", "洗衣房", "太平间"}
    assert {item["place"] for item in result["items"]} == expected
    assert len(result["items"]) == 8 and result["coverage_status"] == "complete"
    assert len(result["model_calls"]) == 1 and result["model_calls"][0]["ok"]
    citations = []
    for item in result["items"]:
        citation = item["citation"]
        root = PARSED_ROOT / citation["locator"]["parsed_dir"]
        blocks = [
            json.loads(line) for line in next(root.glob("*.blocks.jsonl")).read_text().splitlines()
        ]
        block = next(block for block in blocks if block.get("blockid") == citation["unit_id"])
        quote = block["content"][citation["unit_rel_start"] : citation["unit_rel_end"]]
        assert quote == citation["quote"] and item["place"] in quote
        assert item["citation_verified"] is True
        citations.append(
            {"place": item["place"], "raw_quote_exact": True, "unit_id": citation["unit_id"]}
        )
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
        counts = {}
        for table in (
            "doc_full",
            "doc_chunks",
            "doc_status",
            "llm_cache",
            "entity_chunks",
            "full_entities",
            "full_relations",
            "relation_chunks",
        ):
            counts[table] = await conn.fetchval(f"SELECT count(*) FROM public.lightrag_{table}")
        state = await check_stale(conn)
        previous = json.loads((OUT / "replay.json").read_text())["live"]
        assert counts == previous["public_before"]
        assert state == previous["start"] and state["state"] == "current"
        directory = {}
        for table in ("documents", "source_units", "unit_chunk_links", "scopes", "scope_units"):
            directory[table] = await conn.fetchval(
                f"SELECT count(*) FROM env_rag.{table} WHERE workspace='default'"
            )
        record = {
            "model_calls_authorized": 1,
            "model_calls_observed": 1,
            "model": result["model_calls"][0]["model"],
            "latency_ms": result["model_calls"][0]["latency_ms"],
            "scope": "GB18466 3.2 explicitly named places; 等 remains open",
            "exact_set": True,
            "citations": citations,
            "public_after_model": counts,
            "public_unchanged": True,
            "source_and_active_unchanged": True,
            "state_after_model": state,
            "directory_counts": directory,
            "readonly": True,
        }
        (OUT / "model-verification.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n"
        )
        print(json.dumps(record, ensure_ascii=False))
    finally:
        await conn.close()


asyncio.run(main())
