"""Independent 5.3 acceptance at the owning orchestration entry; no services."""

import asyncio
import json

import pytest
import test_fusion as base

from env_rag_final import fusion as fu
from env_rag_final.local_adapter import AdapterError, verify_gold_guard


def _install_local(monkeypatch, tmp_path, pg, chunks=(), rows=()):
    class Impl:
        async def fetch(self, *args, **kwargs):
            return base._local_result(chunks=chunks)

    return base._install(monkeypatch, tmp_path, pg, adapter_factory=Impl, chunk_rows=rows)


def test_explicit_related_route_allows_proven_amendment_without_self_code(monkeypatch, tmp_path):
    related = {
        "doc_id": base.DOC_B,
        "doc_name": "GB 8978-1996 修改单.pdf",
        "self_code": None,
        "self_code_version": None,
        "discovery": "doc_attribution",
        "membership_basis": "name/title-explicit code attribution",
        "citation": {"kind": "catalog_row", "workspace": "default"},
        "citation_verified": True,
    }
    pg = base._pg_result(
        targets=[related],
        trace=base.TRACE_RESOLVED_1996
        + [{"stage": "doc_attribution", "codes": ["gb8978"], "emitted": 1}],
    )
    _install_local(
        monkeypatch,
        tmp_path,
        pg,
        chunks=[{"chunk_id": base.CHUNK_B, "doc_id": base.DOC_B}],
        rows=[base._row(base.CHUNK_B, base.DOC_B)],
    )
    gold = json.loads(fu.GOLD_PATH.read_text())
    gold["questions"][0]["question"] = "GB 8978-1996 含修改单的相关文件有哪些？"
    fu.GOLD_PATH.write_text(json.dumps(gold))
    report = asyncio.run(fu.run_fusion(tmp_path, ["q-merge"]))
    result = report["results"][0]
    assert base.CHUNK_B in {c["chunk_id"] for c in result["usable"]}
    assert result["typed_targets"][0]["self_code"] is None


def test_each_table_path_keeps_physical_unit_and_locator(monkeypatch, tmp_path):
    targets = [
        {
            "doc_id": base.DOC_A,
            "unit_id": unit,
            "table_id": unit,
            "heading": "same heading",
            "chunk_ids": [base.CHUNK_A],
            "discovery": "table_range_binding",
            "citation_verified": True,
            "citation": {
                "kind": "table_unit",
                "workspace": "default",
                "snapshot_id": "snap",
                "table_id": unit,
                "locator": locator,
            },
        }
        for unit, locator in [("table-fragment-a", "page:1"), ("table-fragment-b", "page:2")]
    ]
    pg = base._pg_result(targets=targets, trace=base.TRACE_RESOLVED_1996)
    _install_local(monkeypatch, tmp_path, pg, rows=[base._row(base.CHUNK_A, base.DOC_A)])
    report = asyncio.run(fu.run_fusion(tmp_path, ["q-merge"], pg_only=True))
    paths = report["results"][0]["usable"][0]["paths"]
    identities = {p.get("unit_id") or (p.get("citation") or {}).get("table_id") for p in paths}
    assert identities == {"table-fragment-a", "table-fragment-b"}
    assert all((p.get("citation") or {}).get("snapshot_id") == "snap" for p in paths)


def test_readback_failure_retains_completed_local_service_receipts(monkeypatch, tmp_path):
    pg = base._pg_result(chunks=[{"doc_id": base.DOC_A, "chunk_id": base.CHUNK_A}])
    _install_local(monkeypatch, tmp_path, pg)

    async def fail_readback(*args, **kwargs):
        raise OSError("readback unavailable after local completed")

    monkeypatch.setattr(fu, "_verify_chunks", fail_readback)
    with pytest.raises(AdapterError):
        asyncio.run(fu.run_fusion(tmp_path, ["q-merge"]))
    terminal = json.loads((tmp_path / "fusion-runtime-latest.json").read_text())
    assert "finished_at" not in terminal
    assert terminal["identity_after"]["matches_frozen"]
    assert "readback unavailable" in terminal["failure"]["detail"]
    receipts = terminal["failure_service_records"]
    assert any(r["service"] == "llm" for r in receipts["call_records"])


def test_config_rejection_happens_before_backend_identity_reads(monkeypatch, tmp_path):
    pg = base._pg_result()
    _install_local(monkeypatch, tmp_path, pg)
    captures = []

    async def capture(values):
        captures.append("backend identity read")
        return base._identity()

    monkeypatch.setattr(fu, "_capture_identity", capture)
    monkeypatch.setenv("QDRANT_WORKSPACE", "unverified-override")
    with pytest.raises(AdapterError):
        asyncio.run(fu.run_fusion(tmp_path, ["q-merge"]))
    assert captures == [], "invalid configuration must be rejected before any backend read"
    assert (tmp_path / "fusion-runtime-latest.json").exists()


def test_gold_rejection_writes_failure_terminal_without_backend_calls(monkeypatch, tmp_path):
    pg = base._pg_result()
    _install_local(monkeypatch, tmp_path, pg)

    monkeypatch.setattr(fu, "verify_gold_guard", verify_gold_guard)
    with pytest.raises(AdapterError):
        asyncio.run(fu.run_fusion(tmp_path, ["q-merge"]))
    terminal_path = tmp_path / "fusion-runtime-latest.json"
    assert terminal_path.exists(), "gold preflight refusal requires a failure terminal"
    terminal = json.loads(terminal_path.read_text())
    assert "finished_at" not in terminal
    assert "gold" in json.dumps(terminal["failure"])


def test_unrelated_version_still_rejected_positive_control(monkeypatch, tmp_path):
    pg = base._pg_result(trace=base.TRACE_RESOLVED_1996)
    _install_local(
        monkeypatch,
        tmp_path,
        pg,
        chunks=[{"chunk_id": base.CHUNK_B, "doc_id": base.DOC_B}],
        rows=[base._row(base.CHUNK_B, base.DOC_B)],
    )
    report = asyncio.run(fu.run_fusion(tmp_path, ["q-merge"]))
    assert not report["results"][0]["usable"]
    assert report["results"][0]["rejected"]


def test_self_code_request_never_relaxes_to_attribution(monkeypatch, tmp_path):
    """自身编号 request: a doc_attribution target must NOT join the allowed
    set — the strict code_exact-only contract survives F1."""
    related = {
        "doc_id": base.DOC_B,
        "doc_name": "GB 8978-1996 修改单.pdf",
        "self_code": None,
        "self_code_version": None,
        "discovery": "doc_attribution",
        "membership_basis": "name/title-explicit code attribution",
        "citation": {"kind": "catalog_row", "workspace": "default"},
        "citation_verified": True,
    }
    pg = base._pg_result(targets=[related], trace=base.TRACE_RESOLVED_1996)
    _install_local(
        monkeypatch,
        tmp_path,
        pg,
        chunks=[{"chunk_id": base.CHUNK_B, "doc_id": base.DOC_B}],
        rows=[base._row(base.CHUNK_B, base.DOC_B)],
    )
    report = asyncio.run(fu.run_fusion(tmp_path, ["q-merge"]))
    result = report["results"][0]
    assert not result["usable"], "self-code request keeps the strict target set"
    rejected_b = [c for c in result["rejected"] if c["chunk_id"] == base.CHUNK_B]
    assert rejected_b, "attribution doc's chunk is rejected without the explicit ask"
    basis = result.get("allowed_set_basis") or {}
    assert basis.get("verified_attributions") == [], "no attribution joined the allowed set"


def test_multi_query_failure_receipts_belong_to_current_query(monkeypatch, tmp_path):
    """A second-query read-back failure must serialize the SECOND query's own
    ledger — the first query's receipts are never substituted."""
    pg = base._pg_result(chunks=[{"doc_id": base.DOC_A, "chunk_id": base.CHUNK_A}])
    state = _install_local(monkeypatch, tmp_path, pg)

    marker = {"n": 0}

    class Impl:
        async def fetch(self, *args, **kwargs):
            marker["n"] += 1
            res = base._local_result(chunks=[{"chunk_id": base.CHUNK_A, "doc_id": base.DOC_A}])
            res.call_records = [
                {
                    "service": "llm",
                    "operation": "keyword_extraction",
                    "status": "success",
                    "q": marker["n"],
                }
            ]
            return res

    monkeypatch.setattr(fu, "LocalCandidateAdapter", lambda *a, **k: Impl())

    async def fail_on_second(values, workspace, entries):
        if marker["n"] >= 2:
            raise OSError("readback failed on the second query")
        return {"requested": 0, "verified": 0, "missing": 0, "attribution_conflict": 0}

    monkeypatch.setattr(fu, "_verify_chunks", fail_on_second)
    # the gold fixture only has q-merge; running it twice is enough — the
    # FIRST query completes, the SECOND fails in read-back.
    with pytest.raises(AdapterError):
        asyncio.run(fu.run_fusion(tmp_path, ["q-merge", "q-merge"]))
    terminal = json.loads((tmp_path / "fusion-runtime-latest.json").read_text())
    receipts = terminal["failure_service_records"]
    assert receipts["query_id"] == "q-merge"
    records = receipts["call_records"]
    assert records and records[0]["q"] == 2, "current query's own ledger, not the first query's"
    _ = state
