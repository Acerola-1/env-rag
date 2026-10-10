"""Remaining S1/S2 contracts; no real backend or model calls."""

import asyncio
import json
from pathlib import Path

import pytest
import test_answer as fx
import test_evaluation_review_r3 as prior

from env_rag_final import evaluation as ev


@pytest.fixture
def setup(monkeypatch, tmp_path):
    return prior.setup.__wrapped__(monkeypatch, tmp_path)


@pytest.fixture
def anchor_case(tmp_path):
    return prior.anchor_case.__wrapped__(tmp_path)


@pytest.mark.parametrize("foreign_receipt", [False, True])
def test_exception_receipt_unknown_is_explicit_and_never_borrows_other_qid(
    monkeypatch, setup, foreign_receipt
):
    async def fusion(*args, **kwargs):
        return prior.fusion_input(setup)

    async def rerank(report_dir, query_ids, **kwargs):
        if foreign_receipt:
            runtime = Path(report_dir) / "rerank-runtime-latest.json"
            runtime.parent.mkdir(parents=True, exist_ok=True)
            runtime.write_text(
                json.dumps(
                    {
                        "failure": {"stage": "rerank", "detail": "different question"},
                        "failure_service_records": {
                            "query_id": "another-question",
                            "call_records": [{"service": "rerank", "status": "failure"}],
                        },
                    }
                )
            )
        raise ev.AdapterError("no usable receipt for THIS question")

    monkeypatch.setattr(ev, "_run_fusion", fusion)
    monkeypatch.setattr(ev, "_run_rerank", rerank)
    report = asyncio.run(
        ev.run_evaluation(
            setup.out,
            paths=["fusion"],
            gold_path=setup.gold,
            values=fx.VALUES,
            conn=setup.conn,
        )
    )
    assert report["budget_snapshot_end"]["reserved_total"]["rerank"] == 1
    assert report["budget_snapshot_end"]["issued_total"].get("rerank", 0) == 0
    assert report["results"][0].get("rerank_issuance") == "unknown-no-receipt", report
    terminal = json.loads((setup.out / "eval-runtime-latest.json").read_text())
    assert terminal["results"][0]["rerank_issuance"] == "unknown-no-receipt"


def test_anchor_temperature_must_match_actual_generation(anchor_case):
    path, values, anchor = anchor_case
    anchor["frozen_budgets"]["answer_temperature"] = 1
    path.write_text(json.dumps(anchor))
    with pytest.raises(ev.AdapterError, match="temperature"):
        ev.validate_phase4_anchor(anchor_path=path, values=values)


def test_anchor_temperature_zero_matching_positive(anchor_case):
    path, values, anchor = anchor_case
    assert anchor["frozen_budgets"]["answer_temperature"] == 0
    expected = ev.validate_phase4_anchor(anchor_path=path, values=values)
    assert expected["gold_sha256"] == anchor["frozen_identity"]["gold_sha256"]
