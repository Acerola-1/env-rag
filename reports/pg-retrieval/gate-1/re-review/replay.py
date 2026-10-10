"""Second Gate 1 review: SELECT-only live replay and isolated counterexamples."""

import argparse
import asyncio
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import asyncpg

from env_rag_final.audit import identity as sid
from env_rag_final.audit.identity import PARSED_ROOT
from env_rag_final.catalog.builder import check_stale
from env_rag_final.catalog.source import SourceAdapter
from env_rag_final.config import read_environment
from env_rag_final.enumerate_.contract import EnumResult
from env_rag_final.enumerate_.doc_enum import enumerate_documents
from env_rag_final.enumerate_.prose_enum import (
    bind_citations,
    extract_clauses_regex,
    extract_items_with_model,
    read_prose_scope,
    verify_citations,
)
from env_rag_final.enumerate_.table_enum import enumerate_table
from env_rag_final.enumerate_.tables import read_html_table

OUT = Path(__file__).parent
GB8978 = "doc-b45c510232ed4d2452b0f5b2a13434e4"
GB18466 = "doc-68a03b50e1ba1ffc6a0116529f694fe1"
TABLES = (
    "doc_full",
    "doc_chunks",
    "doc_status",
    "llm_cache",
    "entity_chunks",
    "full_entities",
    "full_relations",
    "relation_chunks",
)


async def offline():
    evidence = {}
    r = EnumResult(
        "q",
        "prose",
        "w",
        "s",
        "f",
        members_total=1,
        members_processed=1,
        coverage_status="complete",
        warnings=["items pending extraction"],
    )
    r.validate()
    evidence["empty_pending_extraction_accepted_complete"] = r.to_dict()
    overlap = "4.1.1 短片\n4.1.1 更长的完整条款后半条件。\n4.1.2 下一条"
    item = extract_clauses_regex(overlap, ["4.1.1"])[0]
    evidence["duplicate_span_disagrees_with_text"] = {
        "item": item,
        "span_text": overlap[item["citation"]["char_start"] : item["citation"]["char_end"]],
    }

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                [
                                    {
                                        "text": "原文明确列出停车场",
                                        "citation": {"quote": "门诊、病房"},
                                    },
                                ]
                            )
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
        items, _, error = await extract_items_with_model(
            "本定义列明门诊、病房。",
            "列出明确点名场所",
            {
                "LLM_BINDING_HOST": "http://fixture",
                "LLM_BINDING_API_KEY": "fixture",
                "LLM_MODEL": "fixture",
            },
        )
    evidence["unsupported_claim_real_quote_accepted"] = {"items": items, "error": error}

    class FixtureConn:
        async def fetchval(self, sql, *args):
            return "fixture.pdf"

        async def fetchrow(self, sql, *args):
            return dict(
                unit_id="u",
                unit_kind="block",
                heading="Annex",
                requires_span=True,
                content_length=70,
                locator={"blockid": "u"},
            )

        async def fetch(self, sql, *args):
            if "scope_units" in sql:
                return [{"unit_id": "u"}]
            if "source_units" in sql:
                return [
                    dict(
                        unit_id="tb",
                        unit_order=1,
                        table_seq=1,
                        caption="表 1 甲",
                        heading="4",
                        locator={"blockid": "u"},
                    )
                ]
            return [{"chunk_id": "c"}]

    class Guard:
        def __init__(self, stale_on_second=False):
            self.calls = 0
            self.stale_on_second = stale_on_second

        async def __call__(self, *args, **kwargs):
            self.calls += 1
            return dict(
                state="stale" if self.stale_on_second and self.calls > 1 else "current",
                active_snapshot_id="s",
                stored_fingerprint="f",
            )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pdir = root / "fixture.pdf.parsed"
        pdir.mkdir()
        body = "Annex intro\n7.1 第一个条款。\n7.5 请求条款。\n7.6 下一条。"
        (pdir / "fixture.blocks.jsonl").write_text(
            json.dumps({})
            + "\n"
            + json.dumps(dict(type="content", blockid="u", content=body), ensure_ascii=False)
        )
        (pdir / "fixture.tables.json").write_text(
            json.dumps(
                {
                    "tables": {
                        "tb": {
                            "content": "<table><tr><th>序号</th><th>项目</th></tr><tr><td>1</td><td>总汞</td></tr><tr><td>2</td><td>总镉</td></tr></table>"
                        }
                    }
                }
            )
        )
        guard = Guard()
        with (
            patch.object(sid, "PARSED_ROOT", root),
            patch("env_rag_final.catalog.builder.check_stale", guard),
        ):
            units, result = await read_prose_scope(
                None, FixtureConn(), "default", "d", "s", scope_id="scope-requesting-7.5"
            )
        evidence["requires_span_selects_first_instead_of_requested"] = {
            "requested_scope": "scope-requesting-7.5",
            "raw_text": body,
            "returned_text": units[0].text,
            "result": result.to_dict(),
        }
        guard = Guard(stale_on_second=True)
        with (
            patch.object(sid, "PARSED_ROOT", root),
            patch("env_rag_final.enumerate_.table_enum.check_stale", guard),
        ):
            result = await enumerate_table(FixtureConn(), "default", "d", "1")
        evidence["table_final_guard_absent"] = {
            "result": result.to_dict(),
            "guard_calls": guard.calls,
            "next_guard_state": "stale",
        }

        class PartialConn(FixtureConn):
            async def fetch(self, sql, *args):
                if "source_units" in sql:
                    return [
                        dict(
                            unit_id="empty",
                            unit_order=1,
                            table_seq=1,
                            caption="表 1 甲",
                            heading="4",
                            locator={"blockid": "u"},
                        ),
                        dict(
                            unit_id="tail",
                            unit_order=2,
                            table_seq=2,
                            caption="表 1(完)",
                            heading="4",
                            locator={"blockid": "v"},
                        ),
                    ]
                return [{"chunk_id": "c"}]

        (pdir / "fixture.tables.json").write_text(
            json.dumps(
                {
                    "tables": {
                        "empty": {"content": ""},
                        "tail": {"content": "<table><tr><td>2</td><td>总镉</td></tr></table>"},
                    }
                }
            )
        )
        with (
            patch.object(sid, "PARSED_ROOT", root),
            patch("env_rag_final.enumerate_.table_enum.check_stale", Guard()),
        ):
            try:
                result = await enumerate_table(
                    PartialConn(), "default", "d", "1", allow_partial=True
                )
                evidence["missing_first_fragment_partial"] = {"result": result.to_dict()}
            except Exception as err:
                evidence["missing_first_fragment_partial"] = {"error_type": type(err).__name__}

    class DocConn:
        def __init__(self):
            self.query_workspaces = []

        async def fetchrow(self, sql, *args):
            return {"snapshot_id": "s", "source_fingerprint": {"value": "f"}}

        async def fetchval(self, sql, *args):
            self.query_workspaces.append(args[0])
            return 1

        async def fetch(self, sql, *args):
            self.query_workspaces.append(args[0])
            return [
                dict(
                    doc_id="d",
                    doc_name="a",
                    title="A",
                    self_code=None,
                    self_code_version=None,
                    unknown_fields=[],
                )
            ]

    conn = DocConn()
    guard = Guard(stale_on_second=True)
    with patch("env_rag_final.catalog.builder.check_stale", guard):
        result = await enumerate_documents(conn, "TRUE", workspace="another-workspace")
    evidence["document_live_source_guard_and_workspace_absent"] = {
        "result": result.to_dict(),
        "requested_workspace": "another-workspace",
        "data_query_workspaces": conn.query_workspaces,
        "source_guard_calls": guard.calls,
    }
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
                for name in TABLES
            }

        evidence["public_before"] = await counts()
        evidence["start"] = await check_stale(conn)
        snapshot = evidence["start"]["active_snapshot_id"]
        adapter = SourceAdapter(dsn)
        t1 = await enumerate_table(conn, "default", GB8978, "1")
        evidence["table1"] = t1.to_dict()
        name = await conn.fetchval(
            "SELECT doc_name FROM env_rag.documents WHERE workspace='default' AND snapshot_id=$1 AND doc_id=$2",
            snapshot,
            GB8978,
        )
        path = next((PARSED_ROOT / f"{name}.parsed").glob("*.tables.json"))
        raw_tables = json.loads(path.read_text())["tables"]
        evidence["row_citation_reread"] = []
        for item in t1.items:
            cit = item["citation"]
            grid = read_html_table(raw_tables[cit["table_id"]]["content"])
            row = grid[cit["row_in_fragment"]]
            evidence["row_citation_reread"].append(
                {
                    "seq": item["seq"],
                    "citation": cit,
                    "output_cells": item["cells"],
                    "cited_source_row": row,
                    "matches": row == item["cells"],
                }
            )
        evidence["table2"] = (await enumerate_table(conn, "default", GB8978, "2")).to_dict()

        scope = await conn.fetchrow(
            "SELECT * FROM env_rag.scopes WHERE workspace='default' AND snapshot_id=$1 AND doc_id=$2 AND number='3'",
            snapshot,
            GB18466,
        )
        evidence["scope3"] = dict(scope)
        units, r = await read_prose_scope(
            adapter, conn, "default", GB18466, snapshot, scope["scope_id"]
        )
        text = "\n\n".join(u.text for u in units)
        r.items = bind_citations(
            verify_citations(extract_clauses_regex(text, ["3.1", "3.2", "3.3", "3.4"]), text),
            "default",
            GB18466,
            snapshot,
            units,
        )
        r.validate()
        evidence["prose3_manually_bound"] = r.to_dict()
        command = [
            ".venv/bin/env-rag-final",
            "enum-prose",
            "--doc-id",
            GB18466,
            "--scope-id",
            scope["scope_id"],
            "--clause-wanted",
            "3.1,3.2,3.3,3.4",
        ]
        cli = subprocess.run(command, capture_output=True, text=True, timeout=60)
        evidence["prose_cli"] = {
            "command": command,
            "exit_code": cli.returncode,
            "stderr": cli.stderr,
            "stdout_tail": cli.stdout[-600:],
        }
        missing = subprocess.run(
            command[:-1] + ["9.9.9"], capture_output=True, text=True, timeout=60
        )
        evidence["missing_clause_cli"] = {
            "exit_code": missing.returncode,
            "stderr": missing.stderr,
            "stdout_tail": missing.stdout[-1500:],
        }

        big = await conn.fetchrow(
            "SELECT * FROM env_rag.scopes WHERE workspace='default' AND snapshot_id=$1 AND confirm_status='requires_span' ORDER BY title LIMIT 1",
            snapshot,
        )
        evidence["big_scope"] = dict(big)
        big_units, big_result = await read_prose_scope(
            adapter, conn, "default", big["doc_id"], snapshot, big["scope_id"]
        )
        evidence["big_scope_result"] = big_result.to_dict()
        evidence["big_scope_units"] = [
            dict(
                unit_id=u.unit_id,
                char_start=u.char_start,
                char_end=u.char_end,
                length=len(u.text),
                text=u.text[:2000],
                locator=u.locator,
            )
            for u in big_units
        ]
        member = await conn.fetchrow(
            "SELECT u.unit_id,u.content_length FROM env_rag.source_units u JOIN env_rag.scope_units su USING(workspace,doc_id,snapshot_id,unit_id) WHERE su.workspace='default' AND su.snapshot_id=$1 AND su.scope_id=$2 ORDER BY su.seq LIMIT 1",
            snapshot,
            big["scope_id"],
        )
        evidence["big_member_original"] = dict(member)

        evidence["documents"] = {}
        for label, pred, size in (
            ("yearbooks", "doc_name LIKE '%中国移动源环境管理年报%'", 2),
            ("water_bulletins", "doc_name LIKE '%中国水资源公报%'", 2),
            ("GB3095", "self_code='GB3095'", 1),
        ):
            evidence["documents"][label] = (
                await enumerate_documents(conn, pred, page_size=size)
            ).to_dict()
        evidence["end"] = await check_stale(conn)
        evidence["public_after"] = await counts()
        evidence["public_unchanged"] = evidence["public_before"] == evidence["public_after"]
        evidence["readonly"] = await conn.fetchval("SHOW default_transaction_read_only")
    finally:
        await conn.close()
    return evidence


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    evidence = {"offline": await offline()}
    if args.live:
        evidence["live"] = await live()
    evidence["code_sha256"] = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [
            *sorted(Path("src/env_rag_final/enumerate_").glob("*.py")),
            Path("src/env_rag_final/cli.py"),
        ]
    }
    name = "replay-live.json" if args.live else "replay-offline.json"
    (OUT / name).write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str))
    print(
        json.dumps(
            {
                "saved": str(OUT / name),
                "live": args.live,
                "public_unchanged": evidence.get("live", {}).get("public_unchanged"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
