"""Read a real requires_span unit and compare bound raw coordinates with verification."""

import asyncio
import json
import re
from pathlib import Path

import asyncpg

from env_rag_final.audit.identity import PARSED_ROOT
from env_rag_final.catalog.units import parse_blocks
from env_rag_final.config import read_environment
from env_rag_final.enumerate_.prose_enum import bind_citations, read_prose_scope, verify_citations

OUT = Path(__file__).parent


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
        row = await c.fetchrow("""SELECT u.doc_id,u.unit_id,u.snapshot_id,d.doc_name FROM env_rag.source_units u
            JOIN env_rag.documents d USING(workspace,snapshot_id,doc_id)
            WHERE u.workspace='default' AND u.requires_span ORDER BY u.content_length DESC LIMIT 1""")
        _, blocks = parse_blocks(PARSED_ROOT / (row["doc_name"] + ".parsed"))
        raw = next(b["content"] for b in blocks if b["blockid"] == row["unit_id"])
        number = next(
            (
                m.group(1)
                for m in re.finditer(r"(?m)^\s*#{0,4}\s*(\d+(?:\.\d+)+)\s", raw)
                if m.start() > 100
            ),
            None,
        )
        if number is None:
            out = {
                "readonly": True,
                "state": "case_not_exercised",
                "doc_id": row["doc_id"],
                "unit_id": row["unit_id"],
                "reason": "Real requires_span block has no supported numbered sub-clause; do not fabricate a live positive case",
                "fixture_regression_is_not_a_confirmed_current_corpus_failure": True,
            }
            (OUT / "requires-span-live.json").write_text(json.dumps(out, indent=2) + "\n")
            print(out["state"])
            return
        units, result = await read_prose_scope(
            None,
            c,
            "default",
            row["doc_id"],
            row["snapshot_id"],
            member_unit_ids=[row["unit_id"]],
            requested_clauses=[number],
        )
        u = units[0]
        quote = u.text[:120]
        item = {
            "text": u.text,
            "citation_verified": True,
            "citation": {
                "kind": "char_span",
                "char_start": 0,
                "char_end": len(u.text),
                "quote": quote,
            },
        }
        bound = bind_citations([item], "default", row["doc_id"], row["snapshot_id"], units)
        citation = bound[0]["citation"]
        declared = raw[citation["unit_rel_start"] : citation["unit_rel_end"]]
        assert declared.startswith(quote)
        verified = verify_citations(bound, u.text, units)
        out = {
            "readonly": True,
            "doc_id": row["doc_id"],
            "doc_name": row["doc_name"],
            "unit_id": row["unit_id"],
            "requested_clause": number,
            "read_status": result.read_status,
            "span_offset_in_unit": u.span_offset_in_unit,
            "sliced_text_length": len(u.text),
            "quote": quote,
            "citation": citation,
            "independent_raw_span_supports_whole_quote": True,
            "production_verifier_result": verified[0]["citation_verified"],
        }
        (OUT / "requires-span-live.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2) + "\n"
        )
        print(
            {
                k: out[k]
                for k in [
                    "requested_clause",
                    "read_status",
                    "span_offset_in_unit",
                    "sliced_text_length",
                    "independent_raw_span_supports_whole_quote",
                    "production_verifier_result",
                ]
            }
        )
    finally:
        await c.close()


asyncio.run(main())
