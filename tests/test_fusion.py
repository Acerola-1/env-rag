"""5.3 fusion entry-level contract tests: merge/dedup/paths/version constraints.

All through the real entry (run_fusion): PG discovery fake + local adapter fake;
no model/Qdrant/Neo4j/PG traffic. Production identity guards are the real code
paths, with only the capture and gold read redirected to fixtures.
"""

import asyncio
import json

from env_rag_final import fusion as fu
from env_rag_final.local_adapter import Candidate, LocalCandidateResult
from env_rag_final.search.query import SearchResult

VALUES = {
    "POSTGRES_HOST": "test.invalid",
    "POSTGRES_PORT": "5432",
    "POSTGRES_USER": "fixture",
    "POSTGRES_PASSWORD": "fixture",
    "POSTGRES_DATABASE": "rag",
    "EMBEDDING_MODEL": "Qwen/Qwen3-Embedding-4B",
    "EMBEDDING_DIM": "2560",
    "EMBEDDING_TOKEN_LIMIT": "8192",
    "EMBEDDING_BINDING_HOST": "https://embedding.invalid/v1",
    "EMBEDDING_BINDING_API_KEY": "k-embed",
    "LLM_MODEL": "deepseek-v4.1-flash",
    "KEYWORD_LLM_MODEL": "",
    "LLM_BINDING_HOST": "http://llm.invalid/v1",
    "LLM_BINDING_API_KEY": "k-llm",
    "QDRANT_URL": "http://qdrant.invalid:6333",
    "NEO4J_URI": "bolt://neo4j.invalid:7687",
    "NEO4J_USERNAME": "fixture",
    "NEO4J_PASSWORD": "fixture",
}

DOC_A = "doc-aaa"
DOC_B = "doc-bbb"
CHUNK_A = "doc-aaa-chunk-000"
CHUNK_B = "doc-bbb-chunk-000"


def _gold_file(tmp_path):
    path = tmp_path / "gold.json"
    path.write_text(
        json.dumps(
            {
                "questions": [
                    {
                        "query_id": "q-merge",
                        "question": "GB 8978-1996 表 1 中总汞的最高允许排放浓度是多少？",
                        "workspace": "default",
                        "target_docs": [{"doc_id": DOC_A, "doc_name": "a.pdf"}],
                    },
                    {
                        "query_id": "q-dual",
                        "question": "对比 GB 3095-2012 与 GB 3095-2026 中 PM2.5 年平均浓度限值。",
                        "workspace": "default",
                        "target_docs": [
                            {"doc_id": DOC_A, "doc_name": "a.pdf"},
                            {"doc_id": DOC_B, "doc_name": "b.pdf"},
                        ],
                    },
                    {
                        "query_id": "q-missing",
                        "question": "GB 3095-1996 的二级标准年均限值是多少？",
                        "workspace": "default",
                        "target_docs": [],
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _identity():
    return {
        "identity": {
            "public_counts": {
                "lightrag_doc_full": 1,
                "lightrag_doc_chunks": 1,
                "lightrag_doc_status": 1,
                "lightrag_llm_cache": 1,
                "lightrag_entity_chunks": 1,
                "lightrag_full_entities": 1,
                "lightrag_full_relations": 1,
                "lightrag_relation_chunks": 1,
            },
            "catalog_active": {"run_id": "r", "snapshot_id": "s"},
            "source_fingerprint": "fp",
            "search_active": "sid",
            "gold_sha": "g",
            "env_sha": "e",
        },
        "problems": [],
        "matches_frozen": True,
    }


def _install(monkeypatch, tmp_path, pg_result, stale=None, adapter_factory=None, chunk_rows=None):
    """Wire the fusion entry to fakes; return captured state."""
    state = {"closed": 0, "local_calls": 0}

    monkeypatch.setattr(fu, "GOLD_PATH", _gold_file(tmp_path))
    monkeypatch.setattr(fu, "verify_gold_guard", lambda path: "frozen-gold-sha")
    monkeypatch.setattr(fu, "_capture_identity", lambda values: _async(_identity()))

    async def fake_stale(conn, workspace, parsed_root=None):
        return stale or {"state": "current", "search_id": "sid"}

    monkeypatch.setattr("env_rag_final.search.index.check_search_stale", fake_stale)

    async def fake_run_query(conn, query, **kwargs):
        return pg_result

    monkeypatch.setattr("env_rag_final.search.query.run_query", fake_run_query)

    class FakeConn:
        async def close(self):
            state["closed"] += 1

    async def fake_connect(**kwargs):
        return FakeConn()

    monkeypatch.setattr(fu.asyncpg, "connect", fake_connect)

    if adapter_factory is not None:

        class Adapter:
            def __init__(self, values, workspace="default"):
                state["local_calls"] += 1
                self._impl = adapter_factory()

            async def fetch(self, query, query_id=None, frozen_gold_sha=None):
                return await self._impl.fetch(query, query_id, frozen_gold_sha)

        monkeypatch.setattr(fu, "LocalCandidateAdapter", Adapter)

    # read-back rows for _verify_chunks
    rows = chunk_rows if chunk_rows is not None else []
    orig_connect = fu.asyncpg.connect

    class VerifyConn:
        async def fetch(self, sql, *args):
            if "lightrag_doc_chunks" in sql:
                ws, ids = args[0], args[1]
                return [r for r in rows if r["id"] in ids and r["workspace"] == ws]
            return []

        async def close(self):
            state["closed"] += 1

    counter = {"n": 0}

    async def dispatch_connect(**kwargs):
        counter["n"] += 1
        if counter["n"] % 2 == 1:
            return FakeConn()  # discovery connection
        return VerifyConn()

    monkeypatch.setattr(fu.asyncpg, "connect", dispatch_connect)
    state["_orig"] = orig_connect
    return state


def _async(value):
    async def _coro():
        return value

    return _coro()


def _pg_result(
    workspace="default",
    chunks=(),
    targets=(),
    trace=(),
    discovery=(),
    status="ok",
    enumeration=(),
    discovery_none=False,
):
    r = SearchResult("search-fixture", workspace)
    r.status = status
    r.search_id = "sid"
    r.catalog_snapshot_id = "snap"
    r.source_snapshot_id = "fp"
    r.trace = list(trace)
    items = []
    for c in chunks:
        items.append(
            {
                "doc_id": c["doc_id"],
                "chunk_id": c["chunk_id"],
                "heading": c.get("heading"),
                "chunk_order": c.get("chunk_order"),
                "score": c.get("score", 0.5),
                "discovery": c.get("discovery", "keyword_and"),
                "citation": {
                    "kind": "chunk_row",
                    "workspace": workspace,
                    "doc_id": c["doc_id"],
                    "chunk_id": c["chunk_id"],
                },
                "citation_verified": True,
            }
        )
    for t in targets:
        items.append(t)
    r.candidates = list(enumeration) if enumeration else list(items)
    r.discovery_candidates = None if discovery_none else list(items)
    return r


def _local_result(workspace="default", chunks=()):
    cands = []
    for i, c in enumerate(chunks):
        cands.append(
            Candidate(
                chunk_id=c["chunk_id"],
                workspace=c.get("workspace", workspace),
                full_doc_id=c.get("doc_id", DOC_A),
                file_path="a.pdf",
                content_head="head",
                content_len=100,
                verified=c.get("verified", True),
                verify_error=c.get("verify_error"),
                reached_via=["entity:X"],
                similarity_order=i,
                source_type="entity",
            )
        )
    return LocalCandidateResult(
        query="q",
        mode="local",
        workspace=workspace,
        query_id="qid",
        started_at="t0",
        finished_at="t1",
        keywords={"high_level": [], "low_level": []},
        entities=[],
        relations=[],
        candidates=cands,
        service_calls={"by_service": {"llm": {"attempt": 1, "success": 1, "failure": 0}}},
        call_records=[{"service": "llm", "operation": "keyword_extraction", "status": "success"}],
        sorting_sources={"chunk_pick": "vector-similarity"},
        degraded=[],
        errors=[],
        identity={},
    )


def _row(chunk_id, doc_id, content="text", workspace="default"):
    return {
        "id": chunk_id,
        "workspace": workspace,
        "full_doc_id": doc_id,
        "content": content,
        "file_path": "a.pdf",
    }


def _run(tmp_path, monkeypatch, pg_result, local_chunks=None, adapter_error=None, **kw):
    class Impl:
        async def fetch(self, *a, **kw):
            if adapter_error is not None:
                raise adapter_error
            return _local_result(chunks=local_chunks or [])

    def factory():
        return Impl()

    state = _install(monkeypatch, tmp_path, pg_result, adapter_factory=factory, **kw)
    report = asyncio.run(fu.run_fusion(tmp_path, ["q-merge"]))
    return report, state


TRACE_RESOLVED_1996 = [
    {
        "stage": "code_exact",
        "code": "GB8978",
        "version_requested": "1996",
        "selected_docs": [DOC_A],
        "selected_versions": ["1996"],
    }
]


def test_two_paths_merge_on_identity_and_keep_all_paths(tmp_path, monkeypatch):
    pg = _pg_result(chunks=[{"doc_id": DOC_A, "chunk_id": CHUNK_A}], trace=TRACE_RESOLVED_1996)
    report, _ = _run(
        tmp_path,
        monkeypatch,
        pg,
        local_chunks=[{"chunk_id": CHUNK_A, "doc_id": DOC_A}],
        chunk_rows=[_row(CHUNK_A, DOC_A)],
    )
    res = report["results"][0]
    usable = res["usable"]
    assert len(usable) == 1
    entry = usable[0]
    assert entry["chunk_id"] == CHUNK_A
    paths = {p["path"] for p in entry["paths"]}
    assert paths == {"pg", "local"}, "both paths kept"
    kinds = {p["score"]["kind"] for p in entry["paths"]}
    assert kinds == {"pg_ts_rank", "local_selection_order"}, "raw score kinds preserved, not summed"


def test_different_workspace_same_chunk_id_is_not_mixed(tmp_path, monkeypatch):
    pg = _pg_result(chunks=[{"doc_id": DOC_A, "chunk_id": CHUNK_A}], trace=TRACE_RESOLVED_1996)
    report, _ = _run(
        tmp_path,
        monkeypatch,
        pg,
        local_chunks=[{"chunk_id": CHUNK_A, "doc_id": DOC_A, "workspace": "other"}],
        chunk_rows=[_row(CHUNK_A, DOC_A), _row(CHUNK_A, DOC_A, workspace="other")],
    )
    res = report["results"][0]
    other = [e for e in res["rejected"] if e["workspace"] == "other"]
    assert other, "cross-workspace entry must be rejected"
    assert "cross-workspace" in (other[0]["rejected_reason"] or "") or "workspace" in (
        other[0].get("verify_error") or ""
    )
    assert all(e["workspace"] == "default" for e in res["usable"])


def test_same_content_different_versions_are_both_kept(tmp_path, monkeypatch):
    dual_trace = [
        {
            "stage": "code_exact",
            "code": "GB3095",
            "version_requested": "2012",
            "selected_docs": [DOC_A],
            "selected_versions": ["2012"],
        },
        {
            "stage": "code_exact",
            "code": "GB3095",
            "version_requested": "2026",
            "selected_docs": [DOC_B],
            "selected_versions": ["2026"],
        },
    ]
    pg = _pg_result(
        chunks=[
            {"doc_id": DOC_A, "chunk_id": CHUNK_A},
            {"doc_id": DOC_B, "chunk_id": CHUNK_B},
        ],
        trace=dual_trace,
    )
    report, _ = _run(
        tmp_path,
        monkeypatch,
        pg,
        chunk_rows=[
            _row(CHUNK_A, DOC_A, content="identical text"),
            _row(CHUNK_B, DOC_B, content="identical text"),
        ],
    )
    res = report["results"][0]
    assert {e["chunk_id"] for e in res["usable"]} == {CHUNK_A, CHUNK_B}, (
        "same content across versions must not be deduplicated away"
    )


def test_missing_requested_version_is_missing_and_local_skipped(tmp_path, monkeypatch):
    missing_trace = [
        {
            "stage": "code_exact",
            "code": "GB3095",
            "version_requested": "1996",
            "selected_docs": [],
            "selected_versions": [],
        }
    ]
    pg = _pg_result(trace=missing_trace)
    report, state = _run(
        tmp_path,
        monkeypatch,
        pg,
        local_chunks=[{"chunk_id": CHUNK_A, "doc_id": DOC_A}],  # nearby version exists locally
        chunk_rows=[_row(CHUNK_A, DOC_A)],
    )
    res = report["results"][0]
    assert res["status"] == "missing"
    assert state["local_calls"] == 0, "local must be skipped when ALL requested targets are missing"
    assert not res["usable"], "nearby local version must not be substituted"
    assert res["local"]["skipped_reason"]


def test_partial_dual_version_keeps_resolved_and_rejects_nearby(tmp_path, monkeypatch):
    dual = [
        {
            "stage": "code_exact",
            "code": "GB3095",
            "version_requested": "2012",
            "selected_docs": [DOC_A],
            "selected_versions": ["2012"],
        },
        {
            "stage": "code_exact",
            "code": "GB3095",
            "version_requested": "2026",
            "selected_docs": [],
            "selected_versions": [],
        },
    ]
    pg = _pg_result(chunks=[{"doc_id": DOC_A, "chunk_id": CHUNK_A}], trace=dual)
    report, _ = _run(
        tmp_path,
        monkeypatch,
        pg,
        local_chunks=[
            {"chunk_id": CHUNK_A, "doc_id": DOC_A},
            {"chunk_id": CHUNK_B, "doc_id": DOC_B},  # the missing 2026 doc
        ],
        chunk_rows=[_row(CHUNK_A, DOC_A), _row(CHUNK_B, DOC_B)],
    )
    res = report["results"][0]
    assert res["status"] == "missing", "missing target keeps the result incomplete"
    assert CHUNK_A in {e["chunk_id"] for e in res["usable"]}, "resolved 2012 evidence retained"
    rejected_b = [e for e in res["rejected"] if e["chunk_id"] == CHUNK_B]
    assert rejected_b, "2026 (unresolved) local candidate must be rejected, not substituted"


def test_unverified_local_and_attribution_conflict_are_rejected(tmp_path, monkeypatch):
    pg = _pg_result(chunks=[{"doc_id": DOC_A, "chunk_id": CHUNK_A}], trace=TRACE_RESOLVED_1996)
    report, _ = _run(
        tmp_path,
        monkeypatch,
        pg,
        local_chunks=[
            # in an ALLOWED doc, so the only rejection ground is the local
            # verification itself — unverified local never enters usable
            {"chunk_id": CHUNK_A, "doc_id": DOC_A, "verified": False, "verify_error": "missing"},
        ],
        chunk_rows=[_row(CHUNK_A, DOC_A)],
    )
    res = report["results"][0]
    assert all(e["chunk_id"] != CHUNK_A for e in res["usable"])
    rej = [e for e in res["rejected"] if e["chunk_id"] == CHUNK_A]
    assert rej and "rejected its candidate" in rej[0]["rejected_reason"]

    # same chunk, conflicting doc attribution across paths -> conflict reject
    pg2 = _pg_result(chunks=[{"doc_id": DOC_A, "chunk_id": CHUNK_A}], trace=TRACE_RESOLVED_1996)
    report2, _ = _run(
        tmp_path,
        monkeypatch,
        pg2,
        local_chunks=[{"chunk_id": CHUNK_A, "doc_id": DOC_B}],
        chunk_rows=[_row(CHUNK_A, DOC_A)],
    )
    res2 = report2["results"][0]
    conflict = [e for e in res2["rejected"] if e["chunk_id"] == CHUNK_A]
    assert conflict and "conflicting doc attribution" in conflict[0]["rejected_reason"]


def test_local_timeout_degrades_pg_only_with_receipts(tmp_path, monkeypatch):
    pg = _pg_result(chunks=[{"doc_id": DOC_A, "chunk_id": CHUNK_A}], trace=TRACE_RESOLVED_1996)
    report, _ = _run(
        tmp_path,
        monkeypatch,
        pg,
        adapter_error=TimeoutError("keyword service down"),
        chunk_rows=[_row(CHUNK_A, DOC_A)],
    )
    res = report["results"][0]
    assert res["status"] == "pg-only-degraded"
    assert "TimeoutError" in res["local"]["error"]
    assert res["local"]["receipts"] is not None
    assert res["usable"], "PG-only fallback still serves the PG discovery candidates"
    assert any("PG-only" in d for d in res["degraded"])


def test_pg_stale_rejects_before_local_and_no_upgrade(tmp_path, monkeypatch):
    pg = _pg_result(chunks=[{"doc_id": DOC_A, "chunk_id": CHUNK_A}], trace=TRACE_RESOLVED_1996)
    state = _install(
        monkeypatch,
        tmp_path,
        pg,
        stale={"state": "stale", "search_id": "old"},
        adapter_factory=None,
        chunk_rows=[_row(CHUNK_A, DOC_A)],
    )
    report = asyncio.run(fu.run_fusion(tmp_path, ["q-merge"]))
    res = report["results"][0]
    assert res["status"] == "stale"
    assert res["local"]["ran"] is False
    assert not res["usable"]
    assert any("stale" in d for d in res["degraded"])
    _ = state


def test_doc_targets_stay_typed_and_explicit_empty_discovery_is_not_backfilled(
    tmp_path, monkeypatch
):
    # enumeration output present in ``candidates`` must NOT be used
    enumeration = [
        {
            "doc_id": DOC_B,
            "chunk_id": "doc-bbb-chunk-777",
            "citation": {"kind": "chunk_row"},
            "citation_verified": True,
            "discovery": "enumeration",
            "score": None,
        }
    ]
    doc_target = {
        "doc_id": DOC_A,
        "doc_name": "a.pdf",
        "self_code": "GB3095",
        "self_code_version": "2012",
        "discovery": "doc_attribution",
        "citation": {"kind": "catalog_row", "workspace": "default", "doc_id": DOC_A},
        "citation_verified": True,
        "score": None,
    }
    pg = _pg_result(discovery=[], enumeration=enumeration + [doc_target], trace=TRACE_RESOLVED_1996)
    pg.discovery_candidates = []  # explicit authoritative empty
    report, state = _run(tmp_path, monkeypatch, pg, chunk_rows=[])
    res = report["results"][0]
    assert res["pg"]["discovery_total"] == 0
    assert not res["usable"], "enumeration answers must never backfill an explicit [] discovery"
    assert all(e["chunk_id"] != "doc-bbb-chunk-777" for e in res["usable"])


def test_pg_only_switch_skips_local_entirely(tmp_path, monkeypatch):
    pg = _pg_result(chunks=[{"doc_id": DOC_A, "chunk_id": CHUNK_A}], trace=TRACE_RESOLVED_1996)
    state = _install(
        monkeypatch, tmp_path, pg, adapter_factory=None, chunk_rows=[_row(CHUNK_A, DOC_A)]
    )
    report = asyncio.run(fu.run_fusion(tmp_path, ["q-merge"], pg_only=True))
    res = report["results"][0]
    assert res["local"]["ran"] is False
    assert res["local"]["skipped_reason"] == "pg-only switch"
    assert res["usable"], "PG-only switch still serves the PG discovery path"
    assert state["local_calls"] == 0


def test_incomplete_local_stage_is_surfaced_as_degraded(tmp_path, monkeypatch):
    pg = _pg_result(chunks=[{"doc_id": DOC_A, "chunk_id": CHUNK_A}], trace=TRACE_RESOLVED_1996)

    class Impl:
        async def fetch(self, *a, **kw):
            res = _local_result(chunks=[])
            res.sorting_sources = {
                "chunk_pick": "vector-similarity",  # optimistic global label
                "chunk_pick_vectors": {
                    "vector_backed": False,  # per-stage truth disagrees
                    "observed_calls": [
                        {
                            "stage": "entities",
                            "complete": False,
                            "vectors_requested": 3,
                            "vectors_effective": 1,
                        }
                    ],
                },
            }
            return res

    monkeypatch.setattr(fu, "LocalCandidateAdapter", lambda *a, **k: Impl())
    state = _install(
        monkeypatch, tmp_path, pg, adapter_factory=lambda: Impl(), chunk_rows=[_row(CHUNK_A, DOC_A)]
    )
    report = asyncio.run(fu.run_fusion(tmp_path, ["q-merge"]))
    res = report["results"][0]
    assert any("stage(s) incomplete" in d for d in res["degraded"])
    assert any("coverage is false" in d for d in res["degraded"])
    assert res["local"]["stage_completeness"][0]["complete"] is False
    _ = state
