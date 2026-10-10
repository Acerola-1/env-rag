"""Gate 1 acceptance counterexamples. Live mode is SELECT-only; no model calls."""

import argparse
import asyncio
import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import asyncpg

from env_rag_final.audit import identity
from env_rag_final.catalog.builder import check_stale
from env_rag_final.catalog.source import SourceAdapter
from env_rag_final.catalog.units import parse_blocks
from env_rag_final.config import read_environment
from env_rag_final.enumerate_.contract import EnumResult
from env_rag_final.enumerate_.doc_enum import enumerate_documents
from env_rag_final.enumerate_.prose_enum import (
    extract_clauses_regex,
    extract_items_with_model,
    prose_scope_read,
)
from env_rag_final.enumerate_.table_enum import enumerate_table
from env_rag_final.enumerate_.tables import link_logical_tables

OUT = Path(__file__).parent
GB8978 = "doc-b45c510232ed4d2452b0f5b2a13434e4"
GB18466 = "doc-68a03b50e1ba1ffc6a0116529f694fe1"
PUBLIC_TABLES = (
    "doc_full",
    "doc_chunks",
    "doc_status",
    "llm_response_cache",
    "entity_chunks",
    "full_entities",
    "full_relations",
    "relation_chunks",
)


async def current(*args, **kwargs):
    return {"state": "current", "active_snapshot_id": "s", "stored_fingerprint": "f"}


async def offline():
    evidence = {}
    r = EnumResult(
        "q",
        "prose",
        "default",
        "s",
        "f",
        members_total=1,
        members_processed=1,
        items=[{"citation": {"quote": "x"}}],
        coverage_status="complete",
    )
    r.validate()
    evidence["missing_verified_flag_accepted"] = r.to_dict()
    units = [
        {"unit_id": "base4", "unit_order": 1, "caption": "表 1 甲", "heading": "4", "locator": {}},
        {
            "unit_id": "continuation7",
            "unit_order": 9,
            "caption": "表 1(完)",
            "heading": "7",
            "locator": {},
        },
    ]
    groups = link_logical_tables(units)
    evidence["cross_chapter_continuation"] = [
        {"number": g.number, "status": g.status, "fragments": [f.table_id for f in g.fragments]}
        for g in groups
    ]

    class DocConn:
        def __init__(self):
            self.snapshot, self.active_reads = "s1", 0

        async def fetchval(self, sql, *args):
            if "corpus_runs" in sql:
                self.active_reads += 1
                return self.snapshot
            return 1

        async def fetch(self, sql, *args):
            row = dict(
                doc_id="d1",
                doc_name="a",
                title="A",
                title_confidence="extracted",
                self_code=None,
                self_code_version=None,
                doc_type="other",
                unknown_fields=[],
            )
            if "LIMIT 100 " in sql:
                self.snapshot = "s2"  # replacement after fetching the final page
            return [row]

    dc = DocConn()
    result = await enumerate_documents(dc, "TRUE")
    evidence["final_page_snapshot_replaced"] = {
        "result": result.to_dict(),
        "current_snapshot": dc.snapshot,
        "active_snapshot_checks": dc.active_reads,
    }

    class ProseConn:
        async def fetch(self, sql, *args):
            if "scope_units" in sql:
                return [{"unit_id": "u"}]
            return []

        async def fetchrow(self, sql, *args):
            return dict(
                unit_id="u",
                unit_kind="block",
                heading="3",
                requires_span=True,
                content_length=99,
                locator={},
            )

    with patch("env_rag_final.catalog.builder.check_stale", current):
        _, result, _ = await prose_scope_read(None, ProseConn(), "default", "d", "s", "scope")
    evidence["no_chunk_text_processed_complete"] = result.to_dict()

    class SpanConn(ProseConn):
        async def fetch(self, sql, *args):
            if "scope_units" in sql:
                return [{"unit_id": "u"}]
            return [{"chunk_id": "c", "chunk_order": 0}]

    class SpanAdapter:
        async def get_chunk(self, *args):
            return {"content": "Annex 4\n未定位子条款\nAnnex 5\n范围外内容"}

    with patch("env_rag_final.catalog.builder.check_stale", current):
        span_units, span_result, _ = await prose_scope_read(
            SpanAdapter(), SpanConn(), "default", "d", "s", "scope"
        )
    evidence["requires_span_not_enforced"] = {
        "result": span_result.to_dict(),
        "read_text": span_units[0].text,
        "catalog_requires_span": True,
    }

    class OldSnapshotConn(ProseConn):
        async def fetch(self, sql, *args):
            return []

    with patch("env_rag_final.catalog.builder.check_stale", current):
        _, result, _ = await prose_scope_read(
            None, OldSnapshotConn(), "default", "d", "old", "scope"
        )
    evidence["old_snapshot_empty_complete"] = result.to_dict()
    overlap = "4.1.1 条款开始但chunk在此截断\n\n4.1.1 条款开始但chunk在此截断，后续重要条件只在第二片出现。\n4.1.2 下一条。"
    evidence["first_duplicate_discards_tail"] = extract_clauses_regex(overlap, ["4.1.1"])

    class TableConn:
        async def fetchval(self, sql, *args):
            return "fixture.pdf"

        async def fetch(self, sql, *args):
            if "source_units" in sql:
                return [
                    dict(
                        unit_id="tb-x",
                        unit_order=1,
                        caption="表 1 项目",
                        heading="4",
                        locator={"blockid": "b"},
                    )
                ]
            return [{"chunk_id": "c"}]

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        p = root / "fixture.pdf.parsed"
        p.mkdir()
        tables = p / "fixture.tables.json"
        tables.write_text(
            json.dumps(
                {
                    "tables": {
                        "tb-x": {
                            "content": "<table><tr><th>项目</th><th>限值</th></tr><tr><td>pH</td><td>6～9</td></tr><tr><td>总汞</td><td>0.05</td></tr></table>"
                        }
                    }
                }
            )
        )
        with (
            patch("env_rag_final.enumerate_.table_enum.check_stale", current),
            patch.object(identity, "PARSED_ROOT", root),
        ):
            result = await enumerate_table(TableConn(), "default", "d", "1", parsed_root=root)
        evidence["unnumbered_table_empty_complete"] = result.to_dict()

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps([{"text": "unsupported claim", "citation": {}}])
                        }
                    }
                ]
            }

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            return Response()

    with patch("httpx.AsyncClient", lambda **kwargs: Client()):
        items, _, err = await extract_items_with_model(
            "实际原文",
            "列出条目",
            {
                "LLM_BINDING_HOST": "http://fixture",
                "LLM_BINDING_API_KEY": "fixture",
                "LLM_MODEL": "fixture",
            },
        )
    evidence["model_missing_quote_accepted"] = {"items": items, "error": err}
    return evidence


async def live():
    v = read_environment(Path(".env"))
    dsn = dict(
        host=v["POSTGRES_HOST"],
        port=int(v["POSTGRES_PORT"]),
        user=v["POSTGRES_USER"],
        password=v["POSTGRES_PASSWORD"],
        database=v["POSTGRES_DATABASE"],
        statement_cache_size=0,
        timeout=15,
        server_settings={"default_transaction_read_only": "on", "statement_timeout": "30000"},
    )
    conn = await asyncpg.connect(**dsn)
    evidence = {}
    try:

        async def counts():
            return {
                name: await conn.fetchval(f"SELECT count(*) FROM public.lightrag_{name}")
                for name in PUBLIC_TABLES
            }

        evidence["public_before"] = await counts()
        evidence["start"] = await check_stale(conn)
        snapshot = evidence["start"]["active_snapshot_id"]
        evidence["tables"] = {}
        for number in ("1", "2"):
            r = await enumerate_table(conn, "default", GB8978, number)
            evidence["tables"][number] = r.to_dict()

        adapter = SourceAdapter(dsn)
        scope = await conn.fetchrow(
            "SELECT * FROM env_rag.scopes WHERE workspace='default' AND snapshot_id=$1 AND doc_id=$2 AND number='3'",
            snapshot,
            GB18466,
        )
        units, r, _ = await prose_scope_read(
            adapter, conn, "default", GB18466, snapshot, scope["scope_id"]
        )
        text = "\n\n".join(u.text for u in units)
        items = extract_clauses_regex(text, ["3.1", "3.2", "3.3", "3.4"])
        doc_name = await conn.fetchval(
            "SELECT doc_name FROM env_rag.documents WHERE workspace='default' AND snapshot_id=$1 AND doc_id=$2",
            snapshot,
            GB18466,
        )
        _, raw_blocks = parse_blocks(identity.PARSED_ROOT / f"{doc_name}.parsed")
        raw = "\n\n".join(b.get("content") or "" for b in raw_blocks)
        raw_items = {
            i["clause"]: i for i in extract_clauses_regex(raw, ["3.1", "3.2", "3.3", "3.4"])
        }
        evidence["prose_chapter3"] = {
            "result": r.to_dict(),
            "units": [
                {"unit_id": u.unit_id, "chunk_ids": u.chunk_ids, "length": len(u.text)}
                for u in units
            ],
            "unrestricted_clauses": [i["clause"] for i in extract_clauses_regex(text)],
            "items": items,
            "raw_items": raw_items,
            "exact_source_text_match": {
                i["clause"]: i["text"] == raw_items[i["clause"]]["text"] for i in items
            },
        }
        _, wrong, _ = await prose_scope_read(
            adapter, conn, "default", "doc-not-the-scope-owner", snapshot, scope["scope_id"]
        )
        evidence["wrong_doc_scope_accepted"] = wrong.to_dict()
        _, missing, _ = await prose_scope_read(
            adapter, conn, "default", GB18466, "retired-or-wrong-snapshot", scope["scope_id"]
        )
        evidence["wrong_snapshot_empty_complete"] = missing.to_dict()

        scope4 = await conn.fetchrow(
            "SELECT * FROM env_rag.scopes WHERE workspace='default' AND snapshot_id=$1 AND doc_id=$2 AND number='4.1'",
            snapshot,
            GB18466,
        )
        units4, r4, _ = await prose_scope_read(
            adapter, conn, "default", GB18466, snapshot, scope4["scope_id"]
        )
        wanted4 = [f"4.1.{i}" for i in range(1, 6)]
        r4.items = extract_clauses_regex("\n\n".join(u.text for u in units4), wanted4)
        r4.validate()
        raw4 = {i["clause"]: i for i in extract_clauses_regex(raw, wanted4)}
        evidence["prose_clause4"] = {
            "result": r4.to_dict(),
            "exact_source_text_match": {
                i["clause"]: i["text"] == raw4[i["clause"]]["text"] for i in r4.items
            },
            "raw_items": raw4,
        }

        evidence["documents"] = {}
        for label, predicate, size in (
            ("yearbooks", "doc_name LIKE '%中国移动源环境管理年报%'", 2),
            ("water_bulletins", "doc_name LIKE '%中国水资源公报%'", 2),
            ("GB3095", "self_code='GB3095'", 1),
        ):
            r = await enumerate_documents(conn, predicate, page_size=size)
            r.validate()
            evidence["documents"][label] = r.to_dict()
        evidence["end"] = await check_stale(conn)
        evidence["public_after"] = await counts()
        evidence["public_unchanged"] = evidence["public_before"] == evidence["public_after"]
        evidence["read_only"] = await conn.fetchval("SHOW default_transaction_read_only")
    finally:
        await conn.close()
    return evidence


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    result = {"offline": await offline()}
    if args.live:
        result["live"] = await live()
    result["code_sha256"] = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(Path("src/env_rag_final/enumerate_").glob("*.py"))
    }
    output = OUT / ("counterexamples-live.json" if args.live else "counterexamples-offline.json")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {
                "output": str(output),
                "offline_cases": len(result["offline"]),
                "live": args.live,
                "public_unchanged": result.get("live", {}).get("public_unchanged"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
