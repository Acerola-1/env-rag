"""Independent 5.4 owning-entry acceptance; no network or real credentials."""

import asyncio
import hashlib
import json

import pytest
import test_rerank as base

from env_rag_final import rerank as rr


def _setup(monkeypatch, tmp_path, chunks=None):
    values = base._install(monkeypatch, tmp_path)
    chunks = chunks or [base._usable(base.C1, base.DOC_A, "full body", 0)]
    for chunk in chunks:
        chunk["content_sha256"] = hashlib.sha256(chunk["content"].encode()).hexdigest()
    fused = base._fused(chunks)
    fused.update(
        {
            "workspace": "default",
            "query": "问题",
            "source_snapshot_id": "fp",
            "catalog_snapshot_id": "s",
        }
    )
    identity = {
        "matches_frozen": True,
        "source_fingerprint": "fp",
        "catalog_active": {"run_id": "r", "snapshot_id": "s"},
        "search_active": "sid",
        "gold_sha": "g",
        "env_sha": "e",
    }
    body = {
        "identity_before": identity,
        "identity_after": identity,
        "results": [fused],
        "finished_at": "fixture",
    }
    path = tmp_path / "fused.json"
    path.write_text(json.dumps(body))
    return values, fused, body, path


def _invoke(tmp_path, path, transport, ids=None):
    return asyncio.run(
        rr.run_rerank(tmp_path, ids or ["q-rerank"], fused_report_path=path, transport=transport)
    )


@pytest.mark.parametrize("corruption", ["frozen_source", "content_sha", "workspace", "unverified"])
def test_untrusted_replay_never_reaches_reranker(monkeypatch, tmp_path, corruption):
    _, fused, body, path = _setup(monkeypatch, tmp_path)
    if corruption == "frozen_source":
        body["identity_after"] = {**body["identity_after"], "source_fingerprint": "other-source"}
    elif corruption == "content_sha":
        fused["usable"][0]["content"] = "replaced body with unchanged source hash"
    elif corruption == "workspace":
        fused["usable"][0]["workspace"] = "other"
    else:
        fused["usable"][0]["verified"] = False
    path.write_text(json.dumps(body))
    calls = []

    async def transport(query, documents):
        calls.append(documents)
        return base._resp(base._ok_payload(len(documents)))

    try:
        _invoke(tmp_path, path, transport)
    except Exception:
        pass  # rejection or explicit skip is acceptable; service contact is not
    assert calls == [], f"{corruption} must be rejected before rerank service contact"


def test_missing_full_text_cannot_shrink_set_and_claim_success(monkeypatch, tmp_path):
    _, fused, body, path = _setup(
        monkeypatch,
        tmp_path,
        [
            base._usable(base.C1, base.DOC_A, "full body", 0),
            base._usable(base.C2, base.DOC_A, "second body", 1),
        ],
    )
    fused["usable"][1]["content"] = None
    path.write_text(json.dumps(body))

    async def transport(query, documents):
        return base._resp(base._ok_payload(len(documents)))

    try:
        report = _invoke(tmp_path, path, transport)
    except Exception:
        return
    assert report["results"][0]["status"] != "ok", "incomplete input is never full rerank success"


@pytest.mark.parametrize("service_failure", [False, True])
def test_typed_targets_and_all_provenance_survive_success_and_fallback(
    monkeypatch, tmp_path, service_failure
):
    _, fused, _, path = _setup(monkeypatch, tmp_path)

    async def transport(query, documents):
        return base._resp(
            {} if service_failure else base._ok_payload(1),
            status_code=401 if service_failure else 200,
        )

    result = _invoke(tmp_path, path, transport)["results"][0]
    assert result.get("typed_targets") == fused["typed_targets"]
    entry = result["ordered"][0]
    source = fused["usable"][0]
    for field in ["workspace", "chunk_id", "doc_id", "content_sha256", "paths"]:
        assert entry.get(field) == source[field], f"{field} lost on ordering/fallback"


@pytest.mark.parametrize(
    "failure", ["malformed_gold", "unknown_id", "broken_fused", "bad_structure"]
)
def test_preflight_and_replay_errors_always_write_terminal(monkeypatch, tmp_path, failure):
    _, _, _, path = _setup(monkeypatch, tmp_path)
    ids = ["q-rerank"]
    if failure == "malformed_gold":
        rr.GOLD_PATH.write_text("{bad json")
    elif failure == "unknown_id":
        ids = ["not-in-gold"]
    elif failure == "broken_fused":
        path.write_text("{bad json")
    else:
        rr.GOLD_PATH.write_text(json.dumps({"questions": None}))

    async def transport(query, documents):
        raise AssertionError("invalid input must not reach service")

    with pytest.raises(Exception):
        _invoke(tmp_path, path, transport, ids)
    terminal = tmp_path / "rerank-runtime-latest.json"
    assert terminal.exists(), "all input refusal paths need a failure terminal"
    report = json.loads(terminal.read_text())
    assert "finished_at" not in report
    assert report["failure_service_records"]["call_records"] == []
    if failure == "broken_fused" and report.get("identity_before"):
        assert "identity_after" in report or "identity_after_error" in report


def test_oversized_numeric_score_degrades_with_real_call_receipt(monkeypatch, tmp_path):
    _, _, _, path = _setup(monkeypatch, tmp_path)

    async def transport(query, documents):
        return base._resp({"results": [{"index": 0, "relevance_score": 10**400}]})

    try:
        report = _invoke(tmp_path, path, transport)
    except Exception:
        report = json.loads((tmp_path / "rerank-runtime-latest.json").read_text())
        receipts = report["failure_service_records"]
        assert receipts["call_records"], "completed HTTP call cannot disappear from failed terminal"
    else:
        result = report["results"][0]
        assert result["status"] == "degraded"
        assert result["call"]["status_code"] == 200
        assert result["ordered"][0]["rerank_score"] is None


def test_raw_response_is_preserved_for_independent_index_score_check(monkeypatch, tmp_path):
    _, _, _, path = _setup(monkeypatch, tmp_path)
    payload = base._ok_payload(1)

    async def transport(query, documents):
        return base._resp(payload)

    result = _invoke(tmp_path, path, transport)["results"][0]
    response_candidates = [result.get("response"), result.get("raw_response")]
    response_candidates.extend(
        result["call"].get(k) for k in ["payload", "raw_response", "response_evidence"]
    )
    assert any(
        isinstance(x, dict) and x.get("results") == payload["results"] for x in response_candidates
    ), "id/count alone cannot verify actual response scores"


def test_error_evidence_does_not_publish_configured_api_key(monkeypatch, tmp_path):
    values, _, _, path = _setup(monkeypatch, tmp_path)
    values["RERANK_BINDING_API_KEY"] = "fixture-secret-api-key-never-publish"

    async def transport(query, documents):
        return base._resp(
            {}, status_code=401, text="invalid bearer " + values["RERANK_BINDING_API_KEY"]
        )

    _invoke(tmp_path, path, transport)
    terminal = (tmp_path / "rerank-runtime-latest.json").read_text()
    assert values["RERANK_BINDING_API_KEY"] not in terminal
