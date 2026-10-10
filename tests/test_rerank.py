"""5.4 joint-rerank acceptance matrix at the owning entry; no real services."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from env_rag_final import rerank as rr

# ---------------------------------------------------------------------------
# Fixtures: a fused 5.3 result (two-path merge incl. same-text two versions)
# ---------------------------------------------------------------------------

DOC_A = "doc-aaa"
DOC_B = "doc-bbb"
C1 = "doc-aaa-chunk-000"
C2 = "doc-aaa-chunk-001"
C3 = "doc-bbb-chunk-000"


def _register_source_row(chunk_id, doc_id, text, workspace="default"):
    """Register the explicit fake PG row backing a fixture candidate."""
    SOURCE_ROWS[chunk_id] = {
        "id": chunk_id,
        "workspace": workspace,
        "full_doc_id": doc_id,
        "content": text,
        "file_path": "a.pdf",
    }


# explicit fake PG rows: filled by _register_source_row (via _usable), served
# by the fake read-only connection installed in _install
SOURCE_ROWS = {}


def _usable(chunk_id, doc_id, text, order):
    """C1-compliant fixture candidate: the recorded content_sha256 is the
    REAL recomputable SHA of the body text (never a placeholder), and the
    explicit fake PG row backs the same text."""
    import hashlib

    _register_source_row(chunk_id, doc_id, text)
    return {
        "workspace": "default",
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "content": text,
        "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "content_len": len(text),
        "paths": [{"path": "pg", "score": {"kind": "pg_ts_rank", "value": 0.1}}],
        "verified": True,
    }


def _fused(chunks, status="ok"):
    """C1-compliant replay entry: query/workspace bound to the gold fixture
    question (问题/default) — the owning entry verifies this binding."""
    return {
        "query_id": "q-rerank",
        "query": "问题",
        "workspace": "default",
        "status": status,
        "usable": chunks,
        "rejected": [],
        "typed_targets": [{"target_type": "doc", "doc_id": DOC_A}],
    }


def _write_fused(tmp_path, fused):
    """Write a fused runtime body carrying the MATCHING production identity
    (same fields as the _install identity capture) plus the result."""
    body = {
        "identity_after": {
            "source_fingerprint": "fp",
            "catalog_active": {"run_id": "r", "snapshot_id": "s"},
            "search_active": "sid",
            "gold_sha": "g",
            "env_sha": "e",
        },
        "results": [fused],
    }
    path = tmp_path / "fused.json"
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return path


def _resp(payload, status_code=200, text=None):
    r = SimpleNamespace(status_code=status_code, text=text or json.dumps(payload))
    r.json = lambda: payload
    return r


def _ok_payload(n):
    # inverted-vs-input-order scores: higher score for a LATER input index so
    # the rerank genuinely changes the ordering
    return {
        "id": "resp-1",
        "results": [
            {"index": i, "relevance_score": 0.1 + i / (n * 10)} for i in reversed(range(n))
        ],
    }


def _install(monkeypatch, tmp_path, transport=None, identity=None):
    monkeypatch.setattr(rr, "GOLD_PATH", tmp_path / "gold.json")
    (tmp_path / "gold.json").write_text(
        json.dumps(
            {"questions": [{"query_id": "q-rerank", "question": "问题", "workspace": "default"}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(rr, "verify_gold_guard", lambda p: "gold-sha")
    ident = identity or {
        "identity": {
            "public_counts": {},
            "catalog_active": {"run_id": "r", "snapshot_id": "s"},
            "source_fingerprint": "fp",
            "search_active": "sid",
            "gold_sha": "g",
            "env_sha": "e",
        },
        "problems": [],
        "matches_frozen": True,
    }

    async def capture(values):
        return ident

    monkeypatch.setattr(rr, "_capture_identity", capture)

    # R1 fake read-only source: explicit PG rows backing the fixture texts.
    # Rows are registered via _register_source_row (module-level registry);
    # a candidate without a registered row is REJECTED by the real
    # verification path (no accidental zero-contact pass on missing sources).
    class FakeConn:
        async def fetch(self, sql, *args):
            if "lightrag_doc_chunks" in sql:
                ws, ids = args[0], args[1]
                return [r for r in SOURCE_ROWS.values() if r["workspace"] == ws and r["id"] in ids]
            return []

        async def close(self):
            pass

    async def fake_connect(**kwargs):
        return FakeConn()

    monkeypatch.setattr(rr.asyncpg, "connect", fake_connect)

    values = {
        # C3: synthetic credential values are LONG and collision-free — a
        # one-character placeholder that also occurs inside other secrets or
        # body text corrupts the sanitizer's longest-first replacement.
        "POSTGRES_HOST": "fixture-postgres-host-value-0001",
        "POSTGRES_USER": "fixture-postgres-user-value-0002",
        "POSTGRES_PASSWORD": "fixture-postgres-password-0003-not-a-real-secret",
        "POSTGRES_DATABASE": "fixture-postgres-database-0004",
        "EMBEDDING_MODEL": "fixture-embedding-model-0005",
        "EMBEDDING_DIM": "2560",
        "POSTGRES_PORT": "5432",
        "RERANK_BINDING_HOST": "https://rr.invalid",
        "RERANK_MODEL": "Qwen/Qwen3-Reranker-4B",
        "RERANK_BINDING_API_KEY": "fixture-rerank-api-key-0006-synthetic",
    }
    monkeypatch.setattr(rr, "dotenv_values", lambda path: values)
    monkeypatch.setattr(rr, "verify_config_guard", lambda v, ws: {"pg": ws})
    return values


# 1. one joint call over the whole merged set; response maps back by index;
#    different scores actually change the order; paths/sources retained.
def test_single_joint_call_maps_by_index_and_changes_order(monkeypatch, tmp_path):
    chunks = [
        _usable(C1, DOC_A, "文本甲", 0),
        _usable(C2, DOC_A, "文本乙", 1),
        _usable(C3, DOC_B, "文本丙", 2),
    ]
    fused_path = _write_fused(tmp_path, _fused(chunks))
    captured = {}

    async def transport(query, documents):
        captured["documents"] = documents
        return _resp(_ok_payload(3))

    _install(monkeypatch, tmp_path, transport)
    report = asyncio.run(
        rr.run_rerank(tmp_path, ["q-rerank"], fused_report_path=fused_path, transport=transport)
    )
    res = report["results"][0]
    assert res["status"] == "ok"
    assert len(captured["documents"]) == 3, "ONE call received the WHOLE merged set"
    assert captured["documents"] == ["文本甲", "文本乙", "文本丙"], "full text, not heads"
    ordered = res["ordered"]
    assert [o["input_index"] for o in ordered] == [2, 1, 0], "scores changed the order"
    assert all(o["rerank_score"] is not None for o in ordered)
    by_id = {o["chunk_id"]: o for o in ordered}
    assert by_id[C3]["paths"], "paths retained through rerank"
    # C1: the recorded SHA is the REAL recomputable body SHA (never a placeholder)
    assert (
        res["inputs"][0]["content_sha256"]
        == __import__("hashlib").sha256("文本甲".encode()).hexdigest()
    ), "input identity + real SHA recorded"


# 2. same text in two versions stays two sources; each response index maps to
#    the right version.
def test_same_text_two_versions_stay_two_sources(monkeypatch, tmp_path):
    chunks = [
        _usable(C1, DOC_A, "identical text", 0),
        _usable(C3, DOC_B, "identical text", 1),
    ]
    fused_path = _write_fused(tmp_path, _fused(chunks))

    async def transport(query, documents):
        assert len(documents) == 2
        return _resp(
            {
                "id": "x",
                "results": [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.1},
                ],
            }
        )

    _install(monkeypatch, tmp_path, transport)
    report = asyncio.run(
        rr.run_rerank(tmp_path, ["q-rerank"], fused_report_path=fused_path, transport=transport)
    )
    ordered = report["results"][0]["ordered"]
    assert ordered[0]["doc_id"] == DOC_B and ordered[1]["doc_id"] == DOC_A, (
        "mapping went through the response index, not text equality"
    )
    assert {o["doc_id"] for o in ordered} == {DOC_A, DOC_B}


# 3. 401 / timeout → real failure receipts + explicit degraded fallback in the
#    original fusion order, NO fabricated scores.
@pytest.mark.parametrize("failure", ["auth", "timeout", "http500"])
def test_service_failures_degrade_with_real_receipts(monkeypatch, tmp_path, failure):
    chunks = [_usable(C1, DOC_A, "text", 0), _usable(C2, DOC_A, "text2", 1)]
    fused_path = _write_fused(tmp_path, _fused(chunks))

    async def transport(query, documents):
        if failure == "auth":
            return _resp({"message": "Invalid token"}, status_code=401, text="401")
        if failure == "http500":
            return _resp({}, status_code=500, text="boom")
        raise TimeoutError("rerank service timed out")

    _install(monkeypatch, tmp_path, transport)
    report = asyncio.run(
        rr.run_rerank(tmp_path, ["q-rerank"], fused_report_path=fused_path, transport=transport)
    )
    res = report["results"][0]
    assert res["status"] == "degraded"
    call = res["call"]
    assert call["status"] == "failure"
    if failure == "auth":
        assert call["error"] == "HTTP 401"
    if failure == "timeout":
        assert "TimeoutError" in call["error"]
    assert all(o["rerank_score"] is None for o in res["ordered"]), "no fabricated scores"
    assert [o["input_index"] for o in res["ordered"]] == [0, 1], "original fusion order kept"


# 4. duplicate / missing / out-of-range indices, non-finite scores and
#    non-JSON are all rejected; the full set is never silently shrunk.
@pytest.mark.parametrize(
    "payload,label",
    [
        (
            {
                "results": [
                    {"index": 0, "relevance_score": 0.5},
                    {"index": 0, "relevance_score": 0.4},
                ]
            },
            "duplicate",
        ),
        ({"results": [{"index": 0, "relevance_score": 0.5}]}, "missing"),
        ({"results": [{"index": 5, "relevance_score": 0.5}]}, "out-of-range"),
        ({"results": [{"index": 0, "relevance_score": True}]}, "bool-score"),
        ({"results": [{"index": 0, "relevance_score": "0.5"}]}, "string-score"),
        ({"results": [{"index": 0, "relevance_score": float("nan")}]}, "nan"),
        ({"results": [{"index": 0, "relevance_score": float("inf")}]}, "inf"),
        ({}, "no-results"),
    ],
)
def test_invalid_responses_are_rejected_safely(monkeypatch, tmp_path, payload, label):
    chunks = [_usable(C1, DOC_A, "t1", 0), _usable(C2, DOC_A, "t2", 1)]
    fused_path = _write_fused(tmp_path, _fused(chunks))

    async def transport(query, documents):
        if label == "nan" or label == "inf":
            # NaN/Inf cannot ride through JSON; emulate a service returning them
            class R:
                status_code = 200

                @staticmethod
                def json():
                    return payload

                text = "nan"

            return R()
        return _resp(payload)

    _install(monkeypatch, tmp_path, transport)
    report = asyncio.run(
        rr.run_rerank(tmp_path, ["q-rerank"], fused_report_path=fused_path, transport=transport)
    )
    res = report["results"][0]
    assert res["status"] == "degraded", f"{label} must not claim rerank success"
    assert all(o["rerank_score"] is None for o in res["ordered"])
    assert len(res["ordered"]) == 2, "the full set is never silently shrunk"


def test_non_json_response_is_rejected(monkeypatch, tmp_path):
    chunks = [_usable(C1, DOC_A, "t1", 0)]
    fused_path = _write_fused(tmp_path, _fused(chunks))

    class R:
        status_code = 200
        text = "<html>gateway error</html>"

        @staticmethod
        def json():
            raise ValueError("not json")

    async def transport(query, documents):
        return R()

    _install(monkeypatch, tmp_path, transport)
    report = asyncio.run(
        rr.run_rerank(tmp_path, ["q-rerank"], fused_report_path=fused_path, transport=transport)
    )
    res = report["results"][0]
    assert res["status"] == "degraded"
    assert "non-JSON" in res["call"]["error"]


# 5. empty / missing / stale sets skip with zero calls; failures never borrow
#    the previous query's receipts.
def test_skip_paths_and_receipt_isolation(monkeypatch, tmp_path):
    # missing status → zero calls
    fused = _write_fused(tmp_path, _fused([], status="missing"))

    calls = []

    async def transport(query, documents):
        calls.append(1)
        return _resp(_ok_payload(1))

    _install(monkeypatch, tmp_path, transport)
    report = asyncio.run(
        rr.run_rerank(tmp_path, ["q-rerank"], fused_report_path=fused, transport=transport)
    )
    res = report["results"][0]
    assert res["status"] == "skipped" and calls == []
    assert "zero rerank calls" in res["skipped"]

    # second query failure must not borrow the first query's call record
    fused2_path = tmp_path / "fused2.json"
    fused2_path.write_text(
        json.dumps(
            {
                "identity_after": {
                    "source_fingerprint": "fp",
                    "catalog_active": {"run_id": "r", "snapshot_id": "s"},
                    "search_active": "sid",
                    "gold_sha": "g",
                    "env_sha": "e",
                },
                "results": [
                    _fused([_usable(C1, DOC_A, "t1", 0)], status="ok"),
                    {
                        **_fused([_usable(C2, DOC_A, "t2", 0)], status="ok"),
                        "query_id": "q-second",
                        "query": "问题二",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    # patch the gold to have two ids
    (tmp_path / "gold.json").write_text(
        json.dumps(
            {
                "questions": [
                    {"query_id": "q-rerank", "question": "问题", "workspace": "default"},
                    {"query_id": "q-second", "question": "问题二", "workspace": "default"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    state = {"n": 0}

    async def flaky_transport(query, documents):
        state["n"] += 1
        if state["n"] == 2:
            raise TimeoutError("second query rerank failed")
        return _resp(_ok_payload(len(documents)))

    # reuse the SAME monkeypatched environment (a second _install would
    # rewrite gold.json back to one query id); only swap the transport.
    report2 = asyncio.run(
        rr.run_rerank(
            tmp_path,
            ["q-rerank", "q-second"],
            fused_report_path=fused2_path,
            transport=flaky_transport,
        )
    )
    first, second = report2["results"]
    assert first["status"] == "ok"
    assert second["status"] == "degraded"
    assert second["call"]["error"] != first["call"].get("error"), (
        "each query keeps its own call receipt"
    )


def test_budget_refusal_over_40_inputs(monkeypatch, tmp_path):
    chunks = [_usable(f"doc-a-chunk-{i:03d}", DOC_A, f"t{i}", i) for i in range(41)]
    fused_path = _write_fused(tmp_path, _fused(chunks))

    async def transport(query, documents):
        raise AssertionError("must not call the service")

    _install(monkeypatch, tmp_path, transport)
    report = asyncio.run(
        rr.run_rerank(tmp_path, ["q-rerank"], fused_report_path=fused_path, transport=transport)
    )
    res = report["results"][0]
    assert res["status"] == "degraded"
    assert "refuses rather than silently truncating" in res["degraded"][0]


# D1: a replay declaring a catalog snapshot that disagrees with the verified
# active build is refused BEFORE service contact; a genuine empty candidate
# set skips enrichment with zero catalog reads.
def test_declared_snapshot_conflict_refused_before_service(monkeypatch, tmp_path):
    chunks = [_usable(C1, DOC_A, "body", 0)]
    fused = _fused(chunks)
    fused["pg"] = {"catalog_snapshot_id": "other-generation-snapshot"}
    fused_path = _write_fused(tmp_path, fused)
    calls = []

    async def transport(query, documents):
        calls.append(1)
        return _resp(_ok_payload(1))

    _install(monkeypatch, tmp_path, transport)
    with pytest.raises(rr.AdapterError) as err:
        asyncio.run(
            rr.run_rerank(tmp_path, ["q-rerank"], fused_report_path=fused_path, transport=transport)
        )
    assert "declared catalog snapshot" in str(err.value)
    assert calls == [], "conflicting provenance must be refused before service contact"


def test_empty_candidate_set_skips_enrichment_without_catalog_read(monkeypatch, tmp_path):
    fused = _fused([])
    fused["status"] = "ok"
    fused_path = _write_fused(tmp_path, fused)
    catalog_reads = []

    class Conn:
        async def fetch(self, sql, *args):
            if "unit_chunk_links" in sql:
                catalog_reads.append(1)
            return []

        async def close(self):
            pass

    async def connect(**kwargs):
        return Conn()

    monkeypatch.setattr(rr.asyncpg, "connect", connect)
    _install(monkeypatch, tmp_path, None)
    report = asyncio.run(
        rr.run_rerank(tmp_path, ["q-rerank"], fused_report_path=fused_path, transport=None)
    )
    res = report["results"][0]
    assert res["status"] == "skipped"
    assert catalog_reads == [], "an empty scored set must not touch the catalog"
