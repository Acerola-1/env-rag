"""Independent Gate 2 counterexamples through production entry points.

These tests require no live service and never mutate the real database.
"""

import asyncio
from contextlib import asynccontextmanager

import pytest

from env_rag_final.search import clean, expand, index, query
from env_rag_final.search import eval as evaluation
from env_rag_final.search import tokenizer as tk


def run(coro):
    return asyncio.run(coro)


DOC = {
    "doc_id": "d2012",
    "doc_name": "GB3095-2012.pdf",
    "title": "环境空气质量标准",
    "self_code": "GB3095",
    "self_code_version": "2012",
    "doc_type": "standard",
}


class QueryConn:
    def __init__(self):
        self.docs = [dict(DOC)]

    async def fetchrow(self, sql, *args):
        # active-catalog lookup for the publication guard (improvement-3):
        # returns the snapshot identity, distinct columns from the search-state
        # row. The old search-state shape is preserved for original callers.
        if "corpus_runs" in sql:
            return {"snapshot_id": "catalog", "source_fingerprint": {"value": "source"}}
        return {
            "search_id": "search",
            "catalog_snapshot_id": "catalog",
            "source_fingerprint": "source",
        }

    async def fetch(self, sql, *args):
        if "self_code=$3" in sql:
            return [d for d in self.docs if d["self_code"] == args[2]]
        if "search_documents" in sql:
            return []
        if "search_chunks" in sql:
            return [
                {
                    "chunk_id": "c-other",
                    "doc_id": "d2012",
                    "heading": "环境空气",
                    "chunk_order": 0,
                    "rank": 1.0,
                }
            ]
        return []


def patch_query_state(monkeypatch, stale_after_first=False):
    calls = []

    async def state(conn, workspace, parsed_root=None):
        calls.append(True)
        return {
            "state": "stale" if stale_after_first and len(calls) > 1 else "current",
            "search_id": "search",
            "catalog_snapshot_id": "catalog",
            "reasons": [],
        }

    monkeypatch.setattr(query, "check_search_stale", state)
    return calls


def test_mixed_present_and_missing_versions_cannot_be_ok(monkeypatch):
    patch_query_state(monkeypatch)
    result = run(query.run_query(QueryConn(), "GB3095-2012 与 GB3095-1996"))
    assert result.status == "missing"


def test_absent_bare_code_cannot_return_unrelated_keyword_candidates(monkeypatch):
    patch_query_state(monkeypatch)
    result = run(query.run_query(QueryConn(), "GB50014 环境空气"))
    assert result.status == "missing" and not result.candidates


def test_fullwidth_code_uses_exact_route_before_keyword_relaxation():
    ascii_codes, _ = query._split_codes("GB3095-1996 年均限值")
    wide_codes, _ = query._split_codes("ＧＢ３０９５－１９９６ 年均限值")
    assert [(c["code"], c["version"]) for c in wide_codes] == [
        (c["code"], c["version"]) for c in ascii_codes
    ]


def test_query_detects_source_or_active_replacement_before_return(monkeypatch):
    patch_query_state(monkeypatch, stale_after_first=True)
    result = run(query.run_query(QueryConn(), "GB3095-2012"))
    assert result.status == "stale"


def test_document_expansion_preserves_version_and_workspace(monkeypatch):
    from env_rag_final.enumerate_ import doc_enum
    from env_rag_final.enumerate_.contract import EnumResult

    seen = {}

    async def enumerate_docs(conn, predicate, args=(), **kw):
        seen.update(predicate=predicate, args=args, workspace=kw.get("workspace", "default"))
        version_bound = "2012" in args
        items = (
            []
            if version_bound
            else [
                {
                    **DOC,
                    "doc_id": "d2026",
                    "self_code_version": "2026",
                    "citation": {},
                    "citation_verified": True,
                }
            ]
        )
        return EnumResult("q", "document", "tenant2", "catalog", "source", items=items)

    monkeypatch.setattr(doc_enum, "enumerate_documents", enumerate_docs)

    class GuardConn:
        """read-only active-catalog response for the publication guard
        (improvement-3); no other SQL is answered — unknown SQL raises."""

        async def fetchrow(self, sql, *args):
            assert "corpus_runs" in sql
            return {"snapshot_id": "catalog", "source_fingerprint": {"value": "source"}}

    result = query.SearchResult("q", "tenant2")
    result.parsed_code = {"code": "GB3095", "version": "2012"}
    result.parsed_codes = [result.parsed_code]
    run(expand.expand_candidates(GuardConn(), result, "tenant2", {}, expand_docs=True))
    assert not any(c["self_code_version"] == "2026" for c in result.candidates)
    assert seen["workspace"] == "tenant2"


def test_file_enumeration_question_does_not_expand_to_entire_corpus(monkeypatch):
    from env_rag_final.enumerate_ import doc_enum
    from env_rag_final.enumerate_.contract import EnumResult

    async def enumerate_docs(conn, predicate, args=(), **kw):
        targeted = "中国移动源环境管理年报" in " ".join(map(str, args))
        items = [] if targeted else [{**DOC, "citation": {}, "citation_verified": True}]
        return EnumResult("q", "document", "default", "catalog", "source", items=items)

    patch_query_state(monkeypatch)
    monkeypatch.setattr(doc_enum, "enumerate_documents", enumerate_docs)
    result = run(query.run_query(QueryConn(), "库内有哪些中国移动源环境管理年报", expand_docs=True))
    assert not any(c["doc_type"] == "standard" for c in result.candidates)


def test_synonym_alternatives_are_or_choices_and_oov_can_use_synonym(monkeypatch):
    class SynConn(QueryConn):
        async def fetch(self, sql, *args):
            return []

        async def fetchval(self, sql, *args):
            return 1

    seen = []

    async def rank(conn, search_id, tsq, top_k, workspace, docs=None):
        seen.append(tsq)
        if "'废水'" in tsq and "'水污染'" in tsq and " | " in tsq:
            return [{"chunk_id": "c", "doc_id": "d", "heading": "h", "chunk_order": 0, "rank": 1}]
        return []

    monkeypatch.setattr(query, "_rank_chunks", rank)
    result = query.SearchResult("q", "default")
    result.search_id = "search"
    run(
        query._keyword_route(
            SynConn(),
            result,
            [tk.QueryToken(("污水",)), tk.QueryToken(("厂界标准值",))],
            "default",
            20,
        )
    )
    assert any("'废水'" in q and "'水污染'" in q and " | " in q for q in seen)
    assert result.candidates


def test_nonreviewed_status_does_not_enter_metrics(monkeypatch):
    async def fake_query(*a, **kw):
        result = query.SearchResult("q", "default")
        result.candidates = [{"doc_id": "d", "chunk_id": "wrong"}]
        return result

    monkeypatch.setattr(evaluation, "run_query", fake_query)
    gold = {
        "questions": [
            {
                "query_id": "q",
                "question": "test",
                "category": "fact",
                "target_doc": {"doc_id": "d"},
                "gold_review_status": "rejected",
            }
        ]
    }
    summary = run(evaluation.run_benchmark(None, gold))
    assert summary["questions_reviewed"] == 0 and summary["recall_at_k_reviewed"] is None


def test_document_match_without_target_evidence_is_not_evidence_recall(monkeypatch):
    async def fake_query(*a, **kw):
        result = query.SearchResult("q", "default")
        result.candidates = [{"doc_id": "d", "discovery": "code_exact", "citation_verified": True}]
        return result

    monkeypatch.setattr(evaluation, "run_query", fake_query)
    gold = {
        "questions": [
            {
                "query_id": "q",
                "question": "test",
                "category": "fact",
                "target_doc": {"doc_id": "d"},
                "gold_review_status": "reviewed",
                "gold": {"target_evidence": [{"doc_id": "d", "chunk_id": "c-answer"}]},
            }
        ]
    }
    summary = run(evaluation.run_benchmark(None, gold))
    # The old document-level diagnostic may remain, but must not masquerade as
    # the Gate2 evidence-recall metric.
    assert summary.get("evidence_recall_at_k_reviewed") == 0


class BuildConn:
    def __init__(self):
        self.written = []

    @asynccontextmanager
    async def transaction(self, **kw):
        yield

    async def execute(self, sql, *args):
        self.written.append((sql, args))

    async def executemany(self, sql, rows):
        self.written.append((sql, list(rows)))

    async def fetchrow(self, sql, *args):
        return None

    async def fetch(self, sql, *args):
        if "public.lightrag_doc_full" in sql:
            return [{"id": "d", "doc_name": "doc.pdf", "content": "old"}]
        if "public.lightrag_doc_chunks" in sql:
            return [
                {
                    "id": "c",
                    "full_doc_id": "d",
                    "chunk_order_index": 0,
                    "content": "old",
                    "heading": None,
                }
            ]
        if "env_rag.documents" in sql:
            return [{**DOC, "doc_id": "d"}]
        return []

    async def fetchval(self, sql, *args):
        return 0 if "tsv = ''" in sql else 1


def test_search_build_rejects_source_change_during_derivation(monkeypatch):
    import env_rag_final.catalog.builder as builder

    changed = False

    async def cat(*a, **kw):
        return {"state": "current", "active_snapshot_id": "catalog", "stored_fingerprint": "source"}

    async def fingerprint(*a, **kw):
        return "changed" if changed else "source"

    def tokens(*a, **kw):
        nonlocal changed
        changed = True
        return "old"

    monkeypatch.setattr(builder, "check_stale", cat)
    monkeypatch.setattr(builder, "_live_source_fingerprint", fingerprint)
    monkeypatch.setattr(tk, "tokens_text", tokens)
    with pytest.raises(index.SearchBuildError):
        run(index.build_search_index(BuildConn()))


def test_cleaning_version_change_invalidates_search_index(monkeypatch):
    old_clean = clean.CLEAN_VERSION

    async def cat(*a, **kw):
        return {"state": "current", "active_snapshot_id": "catalog", "stored_fingerprint": "source"}

    old_search_id = index.index_identity("catalog", "source")

    async def active(*a, **kw):
        return {
            "search_id": old_search_id,
            "catalog_snapshot_id": "catalog",
            "source_fingerprint": "source",
            "tokenizer_version": tk.VERSION,
            "vocab_sha": tk.vocab_sha(),
            "index_recipe": index.INDEX_RECIPE,
        }

    import env_rag_final.catalog.builder as builder

    monkeypatch.setattr(builder, "check_stale", cat)
    monkeypatch.setattr(index, "active_search_build", active)
    monkeypatch.setattr(clean, "CLEAN_VERSION", old_clean + "-changed")
    assert run(index.check_search_stale(None))["state"] == "stale"


def test_consistency_probe_exercises_actual_index_tokenization(monkeypatch):
    from env_rag_final.search import probe

    def different_index_stream(text, mode="query"):
        # An inconsistent index must be detected even if the query-side stream
        # perfectly round-trips through PostgreSQL.
        return "unrelated" if mode == "index" else "污水"

    class ProbeConn:
        async def fetchval(self, sql, *args):
            if "@@" in sql:
                return "污水" in args[0]
            return args[0]

    monkeypatch.setattr(tk, "tokens_text", different_index_stream)
    monkeypatch.setattr(tk, "query_terms", lambda *a: [tk.QueryToken(("污水",))])
    result = run(probe._consistency(ProbeConn(), [{"text": "污水"}]))
    assert result[0]["pass"] is False


def test_recall_at_k_does_not_count_targets_after_the_budget(monkeypatch):
    async def fake_query(*a, **kw):
        result = query.SearchResult("q", "default")
        result.candidates = [{"doc_id": "wrong"}, {"doc_id": "target"}]
        return result

    monkeypatch.setattr(evaluation, "run_query", fake_query)
    gold = {
        "questions": [
            {
                "query_id": "q",
                "question": "test",
                "category": "file_enum",
                "target_doc": {"doc_id": "target"},
                "gold_review_status": "reviewed",
            }
        ]
    }
    summary = run(evaluation.run_benchmark(None, gold, top_k=1))
    assert summary["rows"][0]["candidate_docs_topk"] == ["wrong"]
    assert summary["recall_at_k_reviewed"] == 0
