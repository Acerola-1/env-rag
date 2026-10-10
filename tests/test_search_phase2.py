"""Phase 2 behavior tests (tasks 4.1–4.4): tokenizer, routing, expansion.

No live DB or network: the router/expansion tests use small recording fakes so
the REAL entry functions run end-to-end.
"""

from __future__ import annotations

import asyncio
import json

from env_rag_final.search import clean
from env_rag_final.search import tokenizer as tk
from env_rag_final.search.index import index_identity
from env_rag_final.search.query import _split_codes, _version_matches, run_query

# --------------------------------------------------------------------------
# 4.1 tokenizer / vocabulary
# --------------------------------------------------------------------------


def test_code_year_forms_canonicalize_to_one_phrase():
    # R7: PG keeps dotted joins (hj2.2-2018) as ONE lexeme but splits gb3095
    # — the query matches BOTH shapes via (phrase | joined)
    for text in ("GB 3095—2012", "ＧＢ３０９５－２０１２", "gb3095/2012"):
        groups = tk.tokenize(text)
        assert len(groups) == 1, text
        assert groups[0].lexemes == ("gb3095", "-2012")
        tsq = groups[0].to_tsquery()
        assert "'gb3095' <-> '-2012'" in tsq and "'gb3095-2012'" in tsq


def test_bare_code_is_a_single_lexeme():
    groups = tk.tokenize("库内有哪些 GB 3095 标准的文档")
    lex = [g.lexemes for g in groups]
    assert ("gb3095",) in lex


def test_fullwidth_dash_space_year_variants_all_same_tokens_text():
    variants = ["GB 8978—1996", "GB8978-1996", "ＧＢ８９７８－１９９６", "gb8978/1996"]
    texts = {tk.tokens_text(v) for v in variants}
    assert texts == {"gb8978-1996"}


def test_clause_numbers_and_latin_compounds_are_protected():
    assert ("4.2.1",) in [g.lexemes for g in tk.tokenize("4.2.1 第一类污染物")]
    assert ("pm2.5",) in [g.lexemes for g in tk.tokenize("PM2.5 年平均浓度")]


def test_table_number_forms_are_protected():
    for text in ("表 1", "表1"):
        assert ("表1",) in [g.lexemes for g in tk.tokenize(text)]
    assert ("续表2",) in [g.lexemes for g in tk.tokenize("续表 2 项目")]


def test_controlled_vocab_makes_environment_terms_whole_words():
    lex = [g.render() for g in tk.tokenize("医疗机构水污染物排放标准")]
    assert "水污染物" in lex
    lex2 = [g.render() for g in tk.tokenize("最高允许排放浓度是多少")]
    assert "最高允许排放浓度" in lex2
    lex3 = [g.render() for g in tk.tokenize("臭气浓度的厂界标准值")]
    assert "厂界标准值" in lex3


def test_index_mode_is_a_superset_of_query_mode():
    """Every query-side maximal word must occur in the index token stream."""
    text = "医疗机构水污染物排放标准中化学需氧量的测定方法"
    idx = set(tk.tokens_text(text, mode="index").split())
    qry = {g.render() for g in tk.query_terms(text)}
    missing = {t for t in qry if " " not in t} - idx
    assert not missing, f"index is not a superset: missing {missing}"


def test_stopwords_remove_question_frame_but_keep_core_terms():
    terms = {g.render() for g in tk.query_terms("库内有哪些污水排放标准的文档？")}
    assert "排放标准" in terms or "污水" in terms
    assert "哪些" not in terms and "有" not in terms and "文档" not in terms


def test_vocab_sha_is_stable_and_part_of_identity():
    a = index_identity("cat", "src")
    assert a == index_identity("cat", "src")
    assert a != index_identity("cat2", "src")
    assert a != index_identity("cat", "src2", tokenizer_version="other")
    assert a != index_identity("cat", "src", vocab_sha="different")


def test_clean_markup_strips_tags_but_keeps_searchable_text():
    html = (
        '<table id="tb-1"><tr><td>总汞</td><td>0.05</td></tr></table>'
        "mg/m<sup>3</sup>"
        '<drawing id="im-1" caption="图3 排放口示意" path="a/b.jpg"/>'
        '<equation id="eq-1">$$x^2$$</equation>'
        "化学需氧量的测定"
    )
    out = clean.clean_markup(html)
    assert "总汞" in out and "0.05" in out
    assert "mg/m3" in out
    assert "图3 排放口示意" in out
    assert "b.jpg" not in out and "$$" not in out and "<table" not in out
    assert "化学需氧量的测定" in out


def test_heading_text_joins_parent_headings():
    raw = json.dumps({"heading": "4.1 污水排放要求", "parent_headings": ["4 技术内容"]})
    assert clean.heading_text(raw) == "4.1 污水排放要求 4 技术内容"


# --------------------------------------------------------------------------
# 4.3 code parsing + version matching
# --------------------------------------------------------------------------


def test_split_codes_extracts_code_and_version_and_strips_it():
    codes, rest = _split_codes("GB 3095-2012 中二氧化硫的年均限值")
    assert codes[0]["code"] == "GB3095" and codes[0]["version"] == "2012"
    assert "3095" not in rest


def test_version_matching_binds_year_and_legacy_two_digit():
    assert _version_matches("2012", "2012", strict=True)
    assert not _version_matches("2026", "2012", strict=True)
    assert _version_matches("93", "1993", strict=False)
    assert not _version_matches("93", "1993", strict=True)
    assert not _version_matches(None, "2012", strict=False)


# --------------------------------------------------------------------------
# 4.3/4.4 router + expansion through the real entry (fake connection)
# --------------------------------------------------------------------------


class FakeConn:
    """Answers the router's SQL shapes deterministically."""

    def __init__(self, docs=None, chunk_hits=None, scope_members=None, found_units=None):
        self.docs = docs or []
        self.chunk_hits = chunk_hits or {}
        self.scope_members = scope_members or []
        self.found_units = found_units or []
        self.executed: list[str] = []

    async def fetchval(self, sql, *args):
        if "corpus_runs" in sql:
            return {
                "snapshot_id": "snap-1",
                "source_fingerprint": json.dumps({"value": "fp-1"}),
            }
        if "search_builds" in sql:
            return None
        if "count(*)" in sql and "search_chunks" in sql:
            tq = args[2] if len(args) > 2 else ""
            return self.chunk_hits.get(tq, 0)
        if "count(*)" in sql:
            return 0
        return None

    async def fetchrow(self, sql, *args):
        if "env_rag.search_builds" in sql and "status='active'" in sql:
            return {
                "search_id": "search-1",
                "catalog_snapshot_id": "snap-1",
                "source_fingerprint": "fp-1",
            }
        if "corpus_runs" in sql:
            return {"snapshot_id": "snap-1", "source_fingerprint": json.dumps({"value": "fp-1"})}
        return None

    async def fetch(self, sql, *args):
        if "search_documents" in sql and "self_code=$3" in sql:
            target = args[2]
            return [d for d in self.docs if d["self_code"] == target]
        if "search_documents" in sql:
            return self.docs
        if "search_chunks" in sql:
            tq = args[2]
            return [
                {
                    "chunk_id": f"c-{i}",
                    "doc_id": "d-1",
                    "heading": "h",
                    "chunk_order": i,
                    "rank": 0.5,
                }
                for i in range(self.chunk_hits.get(tq, 0))
            ]
        return []


def _patch_stale(monkeypatch, state="current"):
    import env_rag_final.search.expand as ex
    import env_rag_final.search.query as q

    async def fake_check_search_stale(conn, workspace, parsed_root=None):
        if state != "current":
            return {"state": state, "search_id": "", "reasons": ["stale"]}
        return {
            "state": "current",
            "search_id": "search-1",
            "catalog_snapshot_id": "snap-1",
            "tokenizer_version": tk.VERSION,
            "vocab_sha": tk.vocab_sha(),
            "reasons": [],
        }

    # both modules hold their own imported binding
    monkeypatch.setattr(q, "check_search_stale", fake_check_search_stale)
    monkeypatch.setattr(ex, "check_search_stale", fake_check_search_stale)


def _run(coro):
    return asyncio.run(coro)


def test_router_reports_absent_version_instead_of_substituting(monkeypatch):
    _patch_stale(monkeypatch)
    docs = [
        {
            "doc_id": "d-2012",
            "doc_name": "GB3095-2012.pdf",
            "self_code": "GB3095",
            "self_code_version": "2012",
            "title": None,
            "doc_type": "standard",
        },
        {
            "doc_id": "d-2026",
            "doc_name": "GB3095-2026.pdf",
            "self_code": "GB3095",
            "self_code_version": "2026",
            "title": None,
            "doc_type": "standard",
        },
    ]
    conn = FakeConn(docs=docs, chunk_hits={"'限值'": 5})
    r = _run(run_query(conn, "GB 3095-1996 的二级标准年均限值", code="GB3095-1996"))
    assert r.status == "missing"
    assert r.candidates == []
    note = " ".join(r.notes)
    assert "GB3095-1996" in note and "NOT substituted" in note


def test_router_returns_all_versions_and_never_takes_first(monkeypatch):
    _patch_stale(monkeypatch)
    docs = [
        {
            "doc_id": "d-2012",
            "doc_name": "GB3095-2012.pdf",
            "self_code": "GB3095",
            "self_code_version": "2012",
            "title": None,
            "doc_type": "standard",
        },
        {
            "doc_id": "d-2026",
            "doc_name": "GB3095-2026.pdf",
            "self_code": "GB3095",
            "self_code_version": "2026",
            "title": None,
            "doc_type": "standard",
        },
    ]
    conn = FakeConn(docs=docs)
    r = _run(run_query(conn, "环境空气质量标准有哪些版本", code="GB3095"))
    versions = {c["self_code_version"] for c in r.candidates}
    assert versions == {"2012", "2026"}
    step = next(s for s in r.trace if s["stage"] == "code_exact")
    assert sorted(step["selected_versions"]) == ["2012", "2026"]


def test_router_restricts_keyword_search_to_code_docs(monkeypatch):
    _patch_stale(monkeypatch)
    docs = [
        {
            "doc_id": "d-1",
            "doc_name": "GB3095-2012.pdf",
            "self_code": "GB3095",
            "self_code_version": "2012",
            "title": None,
            "doc_type": "standard",
        },
    ]
    conn = FakeConn(docs=docs, chunk_hits={"'二氧化硫' & '年平均'": 1})
    r = _run(run_query(conn, "GB3095-2012 二氧化硫年平均", code="GB3095-2012"))
    step = next(s for s in r.trace if s["stage"] == "keyword_and")
    assert step["restricted_to_code_docs"] == ["d-1"]


def test_router_logs_every_relaxation_step_and_drops_oov_terms(monkeypatch):
    _patch_stale(monkeypatch)
    conn = FakeConn(chunk_hits={"'化学需氧量'": 3})
    r = _run(run_query(conn, "这个不存在的词 化学需氧量"))
    stages = [s["stage"] for s in r.trace]
    assert "keyword_and" in stages
    assert "keyword_and_diagnostics" in stages
    diag = next(s for s in r.trace if s["stage"] == "keyword_and_diagnostics")
    assert (
        "这个不存在的词" in diag["absent_terms"]
        or "不" in diag["absent_terms"]
        or diag["absent_terms"]
    )
    core = next(s for s in r.trace if s["stage"] == "keyword_core_and")
    assert core["dropped_absent_terms"]


def test_router_relaxes_only_when_and_is_empty_and_keeps_code(monkeypatch):
    _patch_stale(monkeypatch)
    # both terms occur (so neither is dropped as OOV), but the AND fails
    conn = FakeConn(
        chunk_hits={
            "'恶臭'": 2,
            "'厂界标准值'": 2,
            "'恶臭' & '厂界标准值'": 0,
            "'臭气' & '厂界标准值'": 2,
        }
    )
    r = _run(run_query(conn, "恶臭 厂界标准值"))
    stages = [s["stage"] for s in r.trace]
    assert "keyword_and" in stages and "keyword_synonym_and" in stages
    syn = next(s for s in r.trace if s["stage"] == "keyword_synonym_and")
    assert syn["synonyms_applied"] and syn["synonyms_applied"][0]["canon"] == "恶臭"


def test_router_stale_index_is_reported_not_answered(monkeypatch):
    _patch_stale(monkeypatch, state="stale")
    conn = FakeConn()
    r = _run(run_query(conn, "任意查询"))
    assert r.status == "stale"
    assert r.candidates == []


# --------------------------------------------------------------------------
# 4.4 expansion: top-k never truncates the read
# --------------------------------------------------------------------------


def test_expansion_of_table_reads_all_fragments_despite_top_k(monkeypatch):
    _patch_stale(monkeypatch)

    import env_rag_final.enumerate_.table_enum as te
    import env_rag_final.search.expand as ex

    async def fake_enumerate_table(conn, workspace, doc_id, table_number, **kw):
        from env_rag_final.enumerate_.contract import EnumResult

        r = EnumResult(
            "q",
            "table",
            workspace,
            "snap-1",
            "fp-1",
            scope_ids=["tb-x"],
            members_total=2,
            members_processed=2,
            coverage_status="complete",
        )
        r.items = [
            {
                "seq": "1",
                "cells": ["1", "甲"],
                "citation": {"kind": "table_row"},
                "citation_verified": True,
            }
        ]
        return r

    monkeypatch.setattr(te, "enumerate_table", fake_enumerate_table)
    conn = FakeConn()
    result = type("R", (), {})()
    result.candidates = [{"doc_id": "d-1"}]
    result.trace = []
    result.parsed_code = None
    _run(ex.expand_candidates(conn, result, "default", {}, table_number="1"))
    step = result.trace[-1]
    assert step["stage"] == "scope_expansion"
    assert step["expansions"][0]["members_total"] == 2
    assert "not a limit" in step["note"]


def test_expansion_deduplicates_same_doc_candidates(monkeypatch):
    _patch_stale(monkeypatch)
    import env_rag_final.search.expand as ex

    calls = []

    async def fake_expand_one(
        conn, workspace, cand, scope_id, table_number, adapter, prose_budget=None
    ):
        calls.append(cand["doc_id"])
        return {"doc_id": cand["doc_id"], "status": "ok"}

    monkeypatch.setattr(ex, "_expand_one", fake_expand_one)
    conn = FakeConn()
    result = type("R", (), {})()
    result.candidates = [{"doc_id": "d-1"}, {"doc_id": "d-1"}, {"doc_id": "d-2"}]
    result.trace = []
    result.parsed_code = None
    _run(ex.expand_candidates(conn, result, "default", {}, table_number="1"))
    assert calls == ["d-1", "d-2"]


def test_unknown_scope_stays_ambiguous(monkeypatch):
    """A scope id that resolves to no members must not silently succeed."""
    _patch_stale(monkeypatch)

    async def fake_read_prose_scope(adapter, conn, workspace, doc_id, snap, scope_id=None, **kw):
        from env_rag_final.enumerate_.contract import EnumResult

        return [], EnumResult(
            "q",
            "prose",
            workspace,
            snap,
            "fp-1",
            scope_ids=[scope_id or ""],
            members_total=0,
            members_processed=0,
            coverage_status="ambiguous",
            fail_stage="snapshot_mismatch",
            warnings=["scope has no member units in the requested catalog snapshot"],
        )

    import env_rag_final.enumerate_.prose_enum as pe

    monkeypatch.setattr(pe, "read_prose_scope", fake_read_prose_scope)
    from env_rag_final.search.expand import _expand_prose

    out = _run(_expand_prose(FakeConn(), "default", "d-1", "no-such-scope", None))
    assert out["coverage_status"] == "ambiguous"
    assert out["members_total"] == 0
