"""6.1 remaining issuance/anchor contracts, all I/O replaced or absent."""

import asyncio
import copy
import hashlib
import json
from pathlib import Path

import pytest
import test_answer as fx
from dotenv import dotenv_values
from test_evaluation_review_r1 import setup as _setup_fixture

from env_rag_final import evaluation as ev


@pytest.fixture
def setup(monkeypatch, tmp_path):
    return _setup_fixture.__wrapped__(monkeypatch, tmp_path)


def fusion_input(setup):
    return {
        "results": [
            fx._fused(
                setup.q["query_id"],
                setup.q["question"],
                [fx._usable(fx.C1, fx.DOC_8978, fx.CHUNKS[fx.C1]["content"])],
            )
        ]
    }


@pytest.mark.parametrize("outcome", ["pre_http_exception", "source_refusal"])
def test_rerank_http_not_issued_on_before_http_refusal(monkeypatch, setup, outcome):
    async def fusion(*args, **kwargs):
        return fusion_input(setup)

    async def rerank(*args, **kwargs):
        if outcome == "pre_http_exception":
            raise ev.AdapterError("source read-back failed before HTTP")
        return {
            "results": [
                {
                    "query_id": "fact-001",
                    "status": "degraded",
                    "ordered": [],
                    "degraded": ["source-verification-failed"],
                    "call": None,
                }
            ]
        }

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
    assert report["budget_snapshot_end"]["issued_total"].get("rerank", 0) == 0, report


def test_executed_failed_rerank_still_counts_positive(monkeypatch, setup):
    async def fusion(*args, **kwargs):
        return fusion_input(setup)

    async def rerank(*args, **kwargs):
        return {
            "results": [
                {
                    "query_id": "fact-001",
                    "status": "degraded",
                    "ordered": [],
                    "degraded": ["http_401"],
                    "call": {
                        "service": "rerank",
                        "status": "failure",
                        "error": "http_401",
                        "status_code": 401,
                        "latency_ms": 2,
                    },
                }
            ]
        }

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
    assert report["budget_snapshot_end"]["issued_total"]["rerank"] == 1


@pytest.fixture
def anchor_case(tmp_path):
    # A hypothetical newly approved generation is built ONLY in tmp_path.
    # Real secrets are never copied into fixtures or reports.
    original = json.loads(ev.CONFIG_ANCHOR.read_text())
    anchor = copy.deepcopy(original)
    for name in anchor["code_anchors"]:
        if name.endswith(".py"):
            anchor["code_anchors"][name] = hashlib.sha256(
                (Path("src/env_rag_final") / name).read_bytes()
            ).hexdigest()
    whitelist = [
        "QUERY_LLM_MODEL",
        "KEYWORD_LLM_MODEL",
        "LLM_MODEL",
        "EMBEDDING_MODEL",
        "EMBEDDING_DIM",
        "RERANK_MODEL",
        "LLM_BINDING_HOST",
        "EMBEDDING_BINDING_HOST",
        "RERANK_BINDING_HOST",
    ]
    environment = dotenv_values(".env")
    values = {key: environment.get(key) for key in whitelist}
    path = tmp_path / "anchor.json"
    path.write_text(json.dumps(anchor))
    return path, values, anchor


def test_keyword_model_drift_is_rejected_by_frozen_anchor(anchor_case):
    path, values, anchor = anchor_case
    values = dict(values)
    values["KEYWORD_LLM_MODEL"] = anchor["model_config"]["keyword_llm"]["value"] + "-changed"
    with pytest.raises(ev.AdapterError):
        ev.validate_phase4_anchor(anchor_path=path, values=values)


@pytest.mark.parametrize("section", ["code_anchors", "frozen_budgets"])
def test_missing_complete_anchor_section_is_rejected(anchor_case, section):
    path, values, anchor = anchor_case
    anchor[section] = {}
    path.write_text(json.dumps(anchor))
    with pytest.raises(ev.AdapterError):
        ev.validate_phase4_anchor(anchor_path=path, values=values)


def test_full_matching_anchor_validates_positive(anchor_case):
    path, values, anchor = anchor_case
    expected = ev.validate_phase4_anchor(anchor_path=path, values=values)
    assert expected["gold_sha256"] == anchor["frozen_identity"]["gold_sha256"]
    assert expected["catalog_run_snapshot"] == anchor["frozen_identity"]["catalog_run_snapshot"]
