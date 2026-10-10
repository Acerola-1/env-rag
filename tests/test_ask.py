"""Offline acceptance tests for the owning free-form enumeration API.

Catalog rows and sidecars here are constructed fixtures, not live corpus facts.
The owner is exercised with a fake read-only connection; retrieval expansion is
stubbed only to provide controlled member sets. Source re-read and publication
rendering remain the real implementations.
"""

from __future__ import annotations

import asyncio
import builtins
import json
from pathlib import Path

import pytest

from env_rag_final import ask
from env_rag_final.search.query import SearchResult

WORKSPACE = "default"
SNAPSHOT = "catalog-fixture"
FINGERPRINT = "source-fixture"
SEARCH_ID = "search-fixture"


def _run(coro):
    return asyncio.run(coro)


def _doc(doc_id, doc_name, code, version):
    return {
        "doc_id": doc_id,
        "doc_name": doc_name,
        "title": doc_name,
        "self_code": code,
        "self_code_version": version,
    }


class ReadOnlyConn:
    """Routes only the catalog reads used by ask.py and answer rendering."""

    def __init__(self, docs, table_units=None):
        self.docs = [dict(row) for row in docs]
        self.by_id = {row["doc_id"]: row for row in self.docs}
        self.table_units = {key: list(value) for key, value in (table_units or {}).items()}
        self.queries = []
        self.closed = False

    def _record(self, method, sql):
        upper = sql.upper()
        assert not any(word in upper for word in ("INSERT", "UPDATE", "DELETE", "CREATE", "DROP"))
        self.queries.append((method, sql))

    async def fetch(self, sql, *args):
        self._record("fetch", sql)
        if "FROM env_rag.documents" in sql:
            return [dict(row) for row in self.docs]
        if "FROM env_rag.source_units" in sql and "unit_kind='table'" in sql:
            return [dict(row) for row in self.table_units.get(args[2], [])]
        raise AssertionError(f"unexpected catalog read: {sql!r}")

    async def fetchval(self, sql, *args):
        self._record("fetchval", sql)
        if "doc_name FROM env_rag.documents" in sql:
            row = self.by_id.get(args[2])
            return row["doc_name"] if row else None
        raise AssertionError(f"unexpected catalog read: {sql!r}")

    async def fetchrow(self, sql, *args):
        self._record("fetchrow", sql)
        raise AssertionError(f"unexpected catalog read: {sql!r}")

    async def close(self):
        self.closed = True


def _current(search_id=SEARCH_ID):
    return {
        "state": "current",
        "search_id": search_id,
        "catalog_snapshot_id": SNAPSHOT,
        "source_fingerprint": FINGERPRINT,
    }


def _install_owner(
    monkeypatch,
    conn,
    *,
    run_candidates=(),
    expansion_builder=None,
    stale_states=None,
):
    calls = {"stale": 0, "run": [], "expand": []}
    states = list(stale_states or (_current(), _current()))

    async def check_stale(_conn, _workspace):
        assert _conn is conn
        index = calls["stale"]
        calls["stale"] += 1
        return dict(states[min(index, len(states) - 1)])

    async def run_query(_conn, query, *, top_k, workspace, source_values):
        assert _conn is conn
        calls["run"].append({"query": query, "top_k": top_k, "workspace": workspace})
        result = SearchResult("search-result-fixture", workspace)
        result.query_text = query
        result.search_id = SEARCH_ID
        result.catalog_snapshot_id = SNAPSHOT
        result.source_snapshot_id = FINGERPRINT
        result.candidates = [dict(candidate) for candidate in run_candidates]
        return result

    async def expand_candidates(
        _conn, result, workspace, values, *, scope_id=None, table_number=None, expand_docs=False
    ):
        assert _conn is conn
        if expansion_builder is None:
            raise AssertionError("expansion must not run for this acceptance case")
        calls["expand"].append(
            {"scope_id": scope_id, "table_number": table_number, "expand_docs": expand_docs}
        )
        expansions = expansion_builder(result, scope_id, table_number, expand_docs)
        result.trace.append({"stage": "scope_expansion", "expansions": expansions})

    monkeypatch.setattr(ask, "check_search_stale", check_stale)
    monkeypatch.setattr(ask, "run_query", run_query)
    monkeypatch.setattr(ask, "expand_candidates", expand_candidates)
    return calls


def _write_table_sidecar(root: Path, doc_name: str, doc_id: str, pollutant: str):
    table_id = f"tb-{doc_id}-0001"
    parsed = root / f"{doc_name}.parsed"
    parsed.mkdir(parents=True, exist_ok=True)
    html = (
        "<table><tr><th>序号</th><th>污染物</th></tr>"
        f"<tr><td>1</td><td>{pollutant}</td></tr></table>"
    )
    payload = {
        "tables": {
            table_id: {
                "id": table_id,
                "caption": "表 1 构造测试表",
                "heading": "4 构造测试范围",
                "content": html,
            }
        }
    }
    (parsed / f"{doc_name}.tables.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    return table_id, ["1", pollutant]


def _table_expansions(rows_by_doc, *, citation_verified=True, status="complete"):
    def build(result, _scope_id, table_number, _expand_docs):
        out = []
        for doc in result.candidates:
            doc_id = doc["doc_id"]
            if doc_id not in rows_by_doc:
                continue
            table_id, cells = rows_by_doc[doc_id]
            out.append(
                {
                    "kind": "table",
                    "doc_id": doc_id,
                    "table_number": table_number or "1",
                    "status": status,
                    "coverage_status": status,
                    "members_total": 1,
                    "members_processed": 1,
                    "items": [
                        {
                            "seq": "1",
                            "cells": list(cells),
                            "citation": {
                                "kind": "table_row",
                                "workspace": WORKSPACE,
                                "doc_id": doc_id,
                                "snapshot_id": SNAPSHOT,
                                "table_id": table_id,
                                "row_in_fragment": 1,
                                "locator": table_id,
                            },
                            "citation_verified": citation_verified,
                        }
                    ],
                }
            )
        return out

    return build


def _write_prose_sidecar(root: Path, doc_name: str, doc_id: str, unit_id: str, raw: str):
    parsed = root / f"{doc_name}.parsed"
    parsed.mkdir(parents=True, exist_ok=True)
    rows = [
        {"type": "meta", "document_name": doc_name, "doc_id": doc_id},
        {"type": "content", "blockid": unit_id, "format": "plain_text", "content": raw},
    ]
    (parsed / f"{doc_name}.blocks.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _prose_expansion(
    doc_id,
    unit_id,
    raw,
    *,
    members_total=1,
    members_processed=1,
    status="complete",
    citation_verified=True,
):
    def build(_result, _scope_id, _table_number, _expand_docs):
        return [
            {
                "kind": "prose",
                "doc_id": doc_id,
                "scope_id": "3",
                "status": status,
                "coverage_status": status,
                "members_total": members_total,
                "members_processed": members_processed,
                "fail_stage": "missing_fragment" if status == "partial" else "",
                "items": [
                    {
                        "clause": "3.1",
                        "text": raw,
                        "citation": {
                            "kind": "prose_block",
                            "workspace": WORKSPACE,
                            "doc_id": doc_id,
                            "snapshot_id": SNAPSHOT,
                            "unit_id": unit_id,
                            "unit_rel_start": 0,
                            "unit_rel_end": len(raw),
                            "quote": raw,
                        },
                        "citation_verified": citation_verified,
                    }
                ],
            }
        ]

    return build


def _no_models(result):
    assert result["model_calls_used"] == 0
    assert result["embedding_calls"] == 0
    assert result["rerank_calls"] == 0


def _forbid_gold_access(monkeypatch):
    original_builtin_open = builtins.open
    original_path_open = Path.open

    def check_path(value):
        path = str(value).replace("\\", "/").casefold()
        assert "gold-approved.json" not in path
        assert "/reports/pg-retrieval/" not in path

    def guarded_builtin_open(file, *args, **kwargs):
        check_path(file)
        return original_builtin_open(file, *args, **kwargs)

    def guarded_path_open(path, *args, **kwargs):
        check_path(path)
        return original_path_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_builtin_open)
    monkeypatch.setattr(Path, "open", guarded_path_open)


def test_unsupported_same_table_judgment_refuses_before_backend_or_gold(monkeypatch):
    conn = ReadOnlyConn([])
    calls = _install_owner(monkeypatch, conn)
    _forbid_gold_access(monkeypatch)
    request = ask.Question("GB 3838-2002 的表 1 与 GB 3095-2012 的表 1 是同一张表吗？")

    result = _run(ask.ask_question(request, {}, conn=conn))

    assert result["coverage_status"] == "ambiguous"
    assert result["answer"]["items"] == []
    assert result["query_id"].startswith("ask-")  # generated here; no benchmark qid input
    assert not hasattr(request, "qid")
    assert "qid" not in result
    assert "gold_sha" not in result
    assert calls == {"stale": 0, "run": [], "expand": []}
    assert conn.queries == []
    _no_models(result)


def test_top_k_limits_discovery_but_not_all_canonical_editions(monkeypatch, tmp_path):
    docs = [
        _doc("fixture-doc-2012", "air-02-fixture.pdf", "GB3095", "2012"),
        _doc("fixture-doc-2026", "air-03-fixture.pdf", "GB3095", "2026"),
    ]
    conn = ReadOnlyConn(docs)
    rows = {}
    units = {}
    for doc, pollutant in zip(docs, ("二氧化硫-2012", "二氧化硫-2026")):
        table_id, cells = _write_table_sidecar(tmp_path, doc["doc_name"], doc["doc_id"], pollutant)
        rows[doc["doc_id"]] = (table_id, cells)
        units[doc["doc_id"]] = [
            {"unit_id": table_id, "caption": "表 1 构造测试表", "heading": "4 构造测试范围"}
        ]
    conn.table_units = units
    calls = _install_owner(
        monkeypatch,
        conn,
        run_candidates=[docs[0]],  # constructed top-1 discovery result
        expansion_builder=_table_expansions(rows),
    )
    monkeypatch.setattr(ask.an.sid, "PARSED_ROOT", tmp_path)

    _forbid_gold_access(monkeypatch)
    request = ask.Question(
        "GB 3095 表 1 有哪些污染物？",
        kind="table",
        code="GB3095",
        table_number="1",
        top_k=1,
    )

    result = _run(ask.ask_question(request, {}, conn=conn))

    assert calls["run"][0]["top_k"] == 1
    assert [row["doc_id"] for row in result["selected_documents"]] == [
        "fixture-doc-2012",
        "fixture-doc-2026",
    ]
    assert {item["doc_id"] for item in result["answer"]["items"]} == {
        "fixture-doc-2012",
        "fixture-doc-2026",
    }
    assert [item["citation_reverified"] for item in result["answer"]["items"]] == [True, True]
    assert result["reverification"] == {"items_checked": 2, "problems": []}
    assert result["coverage_status"] == "complete"
    assert result["original_local_baseline"] == "unverified"
    _no_models(result)


def test_explicit_document_with_mismatched_canonical_code_is_not_expanded(monkeypatch):
    doc = _doc("fixture-water-doc", "water-04-fixture.pdf", "GB3838", "2002")
    conn = ReadOnlyConn([doc])
    calls = _install_owner(monkeypatch, conn)
    request = ask.Question(
        "GB 3095-2012 表 1 有哪些项目？",
        kind="table",
        document=doc["doc_name"],
        code="GB3095-2012",
        table_number="1",
    )

    result = _run(ask.ask_question(request, {}, conn=conn))

    assert result["coverage_status"] == "ambiguous"
    assert result["selected_documents"] == []
    assert result["answer"]["items"] == []
    assert calls["run"] == []  # explicit-document path is catalog-bound
    assert calls["expand"] == []
    _no_models(result)


def test_unconfirmed_scope_does_not_promote_keyword_candidates(monkeypatch):
    doc = _doc("fixture-noise", "noise.pdf", "GB3838", "2002")
    conn = ReadOnlyConn([doc])
    calls = _install_owner(monkeypatch, conn, run_candidates=[doc])

    result = _run(ask.ask_question(ask.Question("库内有哪些污染物？"), {}, conn=conn))

    assert result["coverage_status"] == "ambiguous"
    assert result["selected_documents"] == []
    assert result["answer"]["items"] == []
    assert calls["expand"] == []
    _no_models(result)


def test_missing_explicit_target_is_not_substituted_by_a_resolved_code(monkeypatch):
    doc = _doc("fixture-doc-2012", "air-02-fixture.pdf", "GB3095", "2012")
    conn = ReadOnlyConn([doc])
    calls = _install_owner(monkeypatch, conn, run_candidates=[doc])
    request = ask.Question(
        "GB 3095-2012 和 GB 50014-2021 表 1 有哪些项目？",
        kind="table",
        table_number="1",
    )

    result = _run(ask.ask_question(request, {}, conn=conn))

    assert result["coverage_status"] == "missing"
    assert [row["doc_id"] for row in result["selected_documents"]] == [doc["doc_id"]]
    assert result["answer"]["items"] == []
    assert calls["expand"] == []
    assert any("不替代版本" in note for note in result["flags"])
    _no_models(result)


@pytest.mark.parametrize(
    ("members_total", "members_processed", "status", "citation_verified", "expected_status"),
    [
        (2, 1, "partial", True, "partial"),  # a clause in the requested scope was unread
        (1, 1, "complete", False, "partial"),  # raw quote re-reads, but verified flag is absent
    ],
)
def test_prose_missing_member_or_unverified_citation_stays_partial(
    monkeypatch,
    tmp_path,
    members_total,
    members_processed,
    status,
    citation_verified,
    expected_status,
):
    doc = _doc("fixture-prose", "water-09-fixture.pdf", "GB18466", "2005")
    conn = ReadOnlyConn([doc])
    unit_id = "fixture-block-3-1"
    raw = "3.1 医疗机构"
    _write_prose_sidecar(tmp_path, doc["doc_name"], doc["doc_id"], unit_id, raw)
    calls = _install_owner(
        monkeypatch,
        conn,
        expansion_builder=_prose_expansion(
            doc["doc_id"],
            unit_id,
            raw,
            members_total=members_total,
            members_processed=members_processed,
            status=status,
            citation_verified=citation_verified,
        ),
    )
    monkeypatch.setattr(ask.an.sid, "PARSED_ROOT", tmp_path)
    request = ask.Question(
        "GB 18466-2005 第 3 章有哪些术语？",
        kind="prose",
        code="GB18466-2005",
        scope="第3章",
    )

    result = _run(ask.ask_question(request, {}, conn=conn))

    assert result["coverage_status"] == expected_status
    assert result["reverification"]["problems"] == []
    assert result["answer"]["items"][0]["citation_reverified"] is True
    assert result["answer"]["items"][0]["citation_verified"] is citation_verified
    assert calls["expand"]
    _no_models(result)


def test_publication_window_drift_marks_existing_answer_stale(monkeypatch, tmp_path):
    doc = _doc("fixture-drift", "air-drift-fixture.pdf", "GB3095", "2012")
    conn = ReadOnlyConn([doc])
    table_id, cells = _write_table_sidecar(tmp_path, doc["doc_name"], doc["doc_id"], "二氧化硫")
    conn.table_units = {
        doc["doc_id"]: [
            {"unit_id": table_id, "caption": "表 1 构造测试表", "heading": "4 构造测试范围"}
        ]
    }
    calls = _install_owner(
        monkeypatch,
        conn,
        run_candidates=[doc],
        expansion_builder=_table_expansions({doc["doc_id"]: (table_id, cells)}),
        stale_states=[_current(), _current(search_id="search-changed")],
    )
    monkeypatch.setattr(ask.an.sid, "PARSED_ROOT", tmp_path)
    request = ask.Question(
        "GB 3095 表 1 有哪些污染物？",
        kind="table",
        code="GB3095",
        table_number="1",
    )

    result = _run(ask.ask_question(request, {}, conn=conn))

    assert calls["stale"] == 2
    assert result["coverage_status"] == "stale"
    assert result["answer"]["items"]  # retained only as diagnostic output
    assert any("身份变化" in flag for flag in result["flags"])
    _no_models(result)


def test_write_result_refuses_to_overwrite_existing_output(tmp_path):
    destination = tmp_path / "existing-result.json"
    destination.write_text('{"preserve": true}\n', encoding="utf-8")

    with pytest.raises(FileExistsError):
        ask.write_result(destination, {"query": "new"})

    assert destination.read_text(encoding="utf-8") == '{"preserve": true}\n'


def test_selected_edition_refines_bare_code_without_union_of_other_editions():
    query, kind = ask.Question(
        "列出 GB3095 第4.2条的全部规定", code="GB3095", version="2012"
    ).prepare()
    assert kind == "prose"
    assert ask._split_codes(query)[0] == [
        {"raw": "GB3095-2012", "code": "GB3095", "version": "2012"}
    ]


def test_bare_code_option_keeps_stronger_question_edition():
    query, _ = ask.Question("列出 GB3095-2012 第4.2条的全部规定", code="GB3095").prepare()
    assert all(c["version"] == "2012" for c in ask._split_codes(query)[0])


@pytest.mark.parametrize(
    "options",
    [
        {"code": "GB3095-2026"},
        {"table_number": "2"},
        {"scope": "第3章"},
    ],
)
def test_explicit_constraints_cannot_silently_override_conflicting_question(options):
    with pytest.raises(ValueError):
        ask.Question("列出 GB3095-2012 表1的全部项目", **options).prepare()


def test_same_snapshot_catalog_mutation_refuses_publication(monkeypatch, tmp_path):
    doc = _doc("fixture-metadata-drift", "air-fixture.pdf", "GB3095", "2012")
    conn = ReadOnlyConn([doc])
    tid, cells = _write_table_sidecar(tmp_path, doc["doc_name"], doc["doc_id"], "总汞")
    normal = _table_expansions({doc["doc_id"]: (tid, cells)})

    def mutate_after_selection(result, *args):
        expansions = normal(result, *args)
        conn.docs[0]["self_code_version"] = "2026"
        return expansions

    _install_owner(
        monkeypatch, conn, run_candidates=[doc], expansion_builder=mutate_after_selection
    )
    monkeypatch.setattr(ask.an.sid, "PARSED_ROOT", tmp_path)
    result = _run(ask.ask_question(ask.Question("列出 GB3095-2012 表1的全部项目"), {}, conn=conn))
    assert result["coverage_status"] == "stale"
    assert result["answer"]["items"]
    assert (
        result["catalog_selection"]["before_sha256"] != result["catalog_selection"]["after_sha256"]
    )


def test_ambiguous_scope_reason_is_visible_in_human_output(monkeypatch):
    doc = _doc("fixture-ambiguous", "table.pdf", "GB8978", "1996")
    conn = ReadOnlyConn([doc])

    def ambiguous(*args):
        return [
            {
                "doc_id": doc["doc_id"],
                "kind": "table",
                "coverage_status": "ambiguous",
                "members_total": 0,
                "members_processed": 0,
                "items": [],
                "warnings": ["base caption missing"],
                "fail_stage": "ambiguous",
            }
        ]

    _install_owner(monkeypatch, conn, run_candidates=[doc], expansion_builder=ambiguous)

    async def name(*args):
        return doc["doc_name"]

    monkeypatch.setattr(conn, "fetchval", name)
    # No items require a parsed file; table conditions are still source-free.
    result = _run(ask.ask_question(ask.Question("列出 GB8978-1996 表2的全部项目"), {}, conn=conn))
    assert result["coverage_status"] == "ambiguous"
    assert "base caption missing" in ask.format_answer(result)


def test_cli_accepts_question_with_only_postgres_config(monkeypatch, tmp_path, capsys):
    from env_rag_final import cli

    env = tmp_path / "pg-only.env"
    env.write_text(
        "POSTGRES_HOST=localhost\nPOSTGRES_PORT=5432\nPOSTGRES_USER=test\n"
        "POSTGRES_PASSWORD=test-password\nPOSTGRES_DATABASE=test\n"
    )

    async def fake_question(request, values):
        assert request.text == "列出第3章的全部术语"
        assert request.document == "source.pdf"
        assert not any(k.startswith("LLM_") for k in values)
        return {
            "query": request.text,
            "coverage_status": "ambiguous",
            "answer": {"items": []},
            "flags": ["范围未确认"],
        }

    monkeypatch.setattr(ask, "ask_question", fake_question)
    monkeypatch.setattr(
        "sys.argv",
        [
            "env-rag-final",
            "ask",
            "--query",
            "列出第3章的全部术语",
            "--document",
            "source.pdf",
            "--env-file",
            str(env),
        ],
    )
    cli.main()
    assert "范围未确认" in capsys.readouterr().out


def test_cli_existing_out_refused_before_question_execution(monkeypatch, tmp_path):
    from env_rag_final import cli

    output = tmp_path / "old.json"
    output.write_text("preserved")

    async def forbidden(*args, **kwargs):
        raise AssertionError("must refuse before any query")

    monkeypatch.setattr(ask, "ask_question", forbidden)
    monkeypatch.setattr(
        "sys.argv",
        ["env-rag-final", "ask", "--query", "列出GB8978表1的全部项目", "--out", str(output)],
    )
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    assert exit_info.value.code == 1
    assert output.read_text() == "preserved"


def test_citation_composite_identity_is_required_for_complete():
    result = SearchResult("request", WORKSPACE)
    result.catalog_snapshot_id = SNAPSHOT
    expansion = {"coverage_status": "complete", "members_total": 1, "members_processed": 1}
    item = {
        "doc_id": "doc-target",
        "citation_verified": True,
        "citation_reverified": True,
        "citation": {"workspace": WORKSPACE, "doc_id": "doc-foreign", "snapshot_id": SNAPSHOT},
    }
    assert ask._coverage(result, [expansion], None, [item], []) == "partial"
    item["citation"]["doc_id"] = "doc-target"
    assert ask._coverage(result, [expansion], None, [item], []) == "complete"
