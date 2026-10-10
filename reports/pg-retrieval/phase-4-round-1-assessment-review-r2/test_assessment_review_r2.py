"""Incremental offline acceptance: declaration support, counter finals, guards.

The r1 matrix stays frozen. ENV_RAG_ASSESSMENT_SCRIPT selects a corrected copy.
No production query, answer runner, network or database operation is invoked.
"""

import copy
import importlib.util
import json
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = Path(
    os.environ.get(
        "ENV_RAG_ASSESSMENT_SCRIPT",
        str(REPO / "reports/pg-retrieval/phase-4-round-1-assessment-r2/assess_round1.py"),
    )
)
spec = importlib.util.spec_from_file_location("assessment_review_target_r2", SCRIPT)
assess = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assess)
GOLD = json.loads(assess.GOLD_PATH.read_text(encoding="utf-8"))
QUESTIONS = {q["query_id"]: q for q in GOLD["questions"]}
REGISTRY = assess.doc_registry()


def score(qid, items, meta):
    return assess.score_row(
        qid,
        "pg",
        {
            "category": QUESTIONS[qid]["category"],
            "items": items,
            "meta": meta,
            "budget_failure": None,
        },
        QUESTIONS[qid],
        False,
        REGISTRY,
    )


def canonical_row(qid, path="pg"):
    data = json.loads(SCRIPT.with_name("adjudication.json").read_text(encoding="utf-8"))
    return next(r for r in data["rows"] if r["qid"] == qid and r["path"] == path)


@pytest.mark.parametrize("qid", ["prose-enum-001", "prose-enum-002", "table-enum-001"])
def test_real_proven_deliveries_still_pass(qid):
    items, meta = assess.answer_items("pg", qid)
    assert score(qid, items, meta)["final_status"] == "PASS"


def test_string_gold_binds_declared_clause_too():
    items, meta = assess.answer_items("pg", "prose-enum-001")
    bad = copy.deepcopy(items)
    bad[0]["clause"] = "9.9.9"
    assert score("prose-enum-001", bad, meta)["final_status"] == "FAIL"


def test_real_quote_cannot_support_appended_fabricated_answer_text():
    items, meta = assess.answer_items("pg", "prose-enum-001")
    bad = copy.deepcopy(items)
    bad[0]["text"] += "停车场允许无条件排放污水。"
    assert score("prose-enum-001", bad, meta)["final_status"] == "FAIL"


@pytest.mark.parametrize("qid", ["prose-enum-001", "table-enum-001"])
def test_declared_item_doc_and_citation_doc_must_agree(qid):
    items, meta = assess.answer_items("pg", qid)
    bad = copy.deepcopy(items)
    bad[0]["doc_id"] = "doc-not-the-source"
    assert score(qid, bad, meta)["final_status"] == "FAIL"


def test_actual_cross_unit_delivery_is_not_supported_by_its_declared_order():
    qid = "prose-enum-003"
    items, meta = assess.answer_items("pg", qid)
    item = next(i for i in items if i["clause"] == "4.3.4")
    citation = item["citation"]
    parsed = assess.an._doc_parsed_dir(REGISTRY[citation["doc_id"]]["file_path"])
    pieces = []
    for seg in citation["unit_segments"]:
        raw = assess.an._unit_text_from_blocks(parsed, seg["unit_id"])
        pieces.append(raw[seg["rel_start"] : seg["rel_end"]])
    # Independent position-level proof using the original unedited artifact.
    assert assess.norm(item["text"]) not in assess.norm("".join(pieces))
    assert score(qid, items, meta)["final_status"] != "PASS"


def test_failed_counter_leg_is_not_a_successful_missing_response():
    v = {
        "judgement": "no_answer_artifact",
        "runtime": "failure",
        "coverage": "partial",
        "delivered": 0,
        "counter_expected_status": "missing",
    }
    assert assess.finalize_counter(v)["final_status"] != "PASS"


def test_observed_empty_leg_is_not_proof_of_isolation_contract():
    assert canonical_row("neg-002")["final_status"] == "PENDING"


def test_guard_budget_refusal_is_not_completed_member_budget_contract():
    row = canonical_row("neg-008")
    assert row["coverage"] is None
    assert row["final_status"] == "PENDING"


def test_partial_is_not_the_frozen_ambiguous_behaviour():
    row = canonical_row("neg-007")
    assert row["coverage"] == "partial"
    assert row["final_status"] == "FAIL"


@pytest.mark.parametrize("qid", ["neg-009", "neg-010"])
def test_known_unanswered_expected_answer_is_whole_question_failure(qid):
    row = canonical_row(qid)
    assert row["delivered"] == 0
    assert row["final_status"] == "FAIL"


def test_true_but_off_topic_neg010_fragments_do_not_answer_replacement_relation():
    row = canonical_row("neg-010", "fusion")
    assert row["delivered"] == 4
    assert row["final_status"] == "FAIL"


def test_real_explicit_missing_response_keeps_positive_counter_evidence():
    row = canonical_row("neg-001")
    assert row["coverage"] == "missing"
    assert row["final_status"] == "PASS"


def test_post_identity_is_mandatory_even_for_a_finished_run(monkeypatch):
    terminal = copy.deepcopy(assess.load_terminal())
    terminal.pop("identity_after")
    assert terminal["finished_at"]
    monkeypatch.setattr(assess, "load_terminal", lambda: terminal)
    assert assess.verify_inputs()["ok"] is False


def test_corrupt_manifest_has_rejection_diagnostic_without_adjudication(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    (run / "pilot-manifest.json").write_text("{ corrupt json")
    monkeypatch.setattr(assess, "ROUND1", run)
    monkeypatch.setattr(assess, "__file__", str(tmp_path / "assess_round1.py"))
    with pytest.raises(Exception):
        assess.main()
    assert (tmp_path / "input-rejection.json").exists()
    assert not (tmp_path / "adjudication.json").exists()
