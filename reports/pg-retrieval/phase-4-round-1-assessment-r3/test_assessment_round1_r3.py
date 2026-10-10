"""Necessary tests for the r3 offline scorer (R1 declaration support,
R2 whole-question counter layering, R3 closed reject boundary).

Per the r2 fixes handoff, this generation's own tests call the NEW code and
read the NEW adjudication (the historical r2 tests read their own artifacts).
Zero network, zero model/DB calls; local artifacts + in-memory copies only.
"""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("assess_r3", HERE / "assess_round1.py")
assess = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assess)
GOLD = json.loads(assess.GOLD_PATH.read_text(encoding="utf-8"))
QUESTIONS = {q["query_id"]: q for q in GOLD["questions"]}
REGISTRY = assess.doc_registry()
REPORT = json.loads((HERE / "adjudication.json").read_text(encoding="utf-8"))
ROWS = {(r["qid"], r["path"]): r for r in REPORT["rows"]}


def score(qid, items, meta, path="pg"):
    return assess.score_row(
        qid,
        path,
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


# ---------------- R1: declaration support and identity ----------------


def test_real_prose_still_passes_with_full_text_backed_by_declared_span():
    for qid in ("prose-enum-001", "prose-enum-002", "prose-enum-006"):
        items, meta = assess.answer_items("pg", qid)
        v = score(qid, items, meta)
        assert v["final_status"] == "PASS", (qid, v.get("unsupported_declarations"))


def test_string_gold_number_binds_declared_clause():
    items, meta = assess.answer_items("pg", "prose-enum-001")
    bad = copy.deepcopy(items)
    bad[0]["clause"] = "9.9.9"
    assert score("prose-enum-001", bad, meta)["final_status"] == "FAIL"
    # number-less gold ("一级") must NOT get a fabricated clause requirement
    spec0 = assess._prose_spec("一级")
    assert spec0["clause"] == ""


def test_appended_fabricated_wording_breaks_declared_span_support():
    items, meta = assess.answer_items("pg", "prose-enum-001")
    bad = copy.deepcopy(items)
    bad[0]["text"] += "停车场允许无条件排放污水。"
    v = score("prose-enum-001", bad, meta)
    assert v["final_status"] == "FAIL"
    assert v.get("unsupported_declarations")


def test_genuine_4_3_4_recorded_as_position_source_problem():
    row = ROWS[("prose-enum-003", "pg")]
    assert row["final_status"] == "FAIL"
    uns = row.get("unsupported_declarations") or []
    assert uns and uns[0]["nsegs"] == 6
    # the stored artifact was NOT rewritten: 20,636-char delivery still present
    p = assess.ROUND1 / "legs/r1/pg/prose-enum-003/answer/answer-runtime-latest.json"
    items = json.loads(p.read_text())["results"][0]["answer"]["items"]
    assert max(len(i.get("text") or "") for i in items) > 20000


def test_declared_and_citation_docs_must_agree_in_prose_and_table():
    for qid in ("prose-enum-001", "table-enum-001"):
        items, meta = assess.answer_items("pg", qid)
        bad = copy.deepcopy(items)
        bad[0]["doc_id"] = "doc-not-the-source"
        assert score(qid, bad, meta)["final_status"] == "FAIL"


# ---------------- R2: whole question vs safety observations ----------------


def test_finalize_counter_runtime_failure_is_never_pass():
    v = {
        "judgement": "no_answer_artifact",
        "runtime": "failure",
        "coverage": "partial",
        "delivered": 0,
        "counter_expected_status": "missing",
    }
    assert assess.finalize_counter(v)["final_status"] != "PASS"


def test_counter_ruling_table_matches_adjudication():
    expect = {
        ("neg-001", "pg"): "PASS",
        ("neg-001", "local"): "FAIL",
        ("neg-006", "pg"): "PASS",
        ("neg-006", "local"): "FAIL",
        ("neg-002", "pg"): "PENDING",
        ("neg-002", "local"): "PENDING",
        ("neg-002", "fusion"): "PENDING",
        ("neg-003", "pg"): "PASS",
        ("neg-004", "pg"): "PASS",
        ("neg-004", "local"): "FAIL",
        ("neg-005", "pg"): "FAIL",
        ("neg-005", "fusion"): "FAIL",
        ("neg-005", "local"): "PENDING",
        ("neg-007", "pg"): "FAIL",
        ("neg-007", "local"): "FAIL",
        ("neg-007", "fusion"): "FAIL",
        ("neg-008", "pg"): "PENDING",
        ("neg-009", "pg"): "FAIL",
        ("neg-010", "pg"): "FAIL",
        ("neg-010", "local"): "FAIL",
        ("neg-010", "fusion"): "FAIL",
    }
    for k, want in expect.items():
        assert ROWS[k]["final_status"] == want, k
    # safety observations live in their own field, never as PASS conversion
    assert ROWS[("neg-007", "pg")]["local_safety_observations"] == ["保守拒绝，未编造表号"]
    assert any("额度闸门" in s for s in ROWS[("neg-008", "pg")]["local_safety_observations"])
    assert ROWS[("neg-008", "pg")]["coverage"] is None


def test_neg010_fusion_manual_review_carries_four_locations():
    row = ROWS[("neg-010", "fusion")]
    mr = row.get("manual_review") or {}
    assert mr.get("verdict") == "FAIL"
    locs = mr.get("delivered_item_citations") or []
    assert len(locs) == 4 and all(l["doc_id"] for l in locs)


def test_positive_synthesis_failures_unchanged():
    syn = [r for r in REPORT["rows"] if r["category"] == "synthesis" and not r["is_counter"]]
    assert len(syn) == 18
    assert all(r["final_status"] == "FAIL" and r.get("manual_review") for r in syn)


# ---------------- R3: closed reject boundary ----------------


def test_missing_post_identity_rejects(monkeypatch):
    terminal = copy.deepcopy(assess.load_terminal())
    terminal.pop("identity_after")
    assert terminal["finished_at"]
    monkeypatch.setattr(assess, "load_terminal", lambda: terminal)
    v = assess.verify_inputs()
    assert v["ok"] is False
    assert any("post-run identity" in p for p in v["problems"])


def test_parsed_content_drift_rejects(monkeypatch, tmp_path):
    monkeypatch.setattr(assess.audit_identity, "PARSED_ROOT", tmp_path)
    v = assess.verify_inputs()
    assert v["ok"] is False
    assert any("Gate-0 frozen component" in p for p in v["problems"])


def test_parse_error_writes_sanitized_rejection(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    (run / "pilot-manifest.json").write_text("{ corrupt json")
    monkeypatch.setattr(assess, "ROUND1", run)
    monkeypatch.setattr(assess, "__file__", str(tmp_path / "assess_round1.py"))
    with pytest.raises(Exception):
        assess.main()
    diag = json.loads((tmp_path / "input-rejection.json").read_text())
    assert diag["exception"]["type"] == "JSONDecodeError"
    assert not (tmp_path / "adjudication.json").exists()


def test_adjudication_canonical_and_summary_consistent():
    rows = REPORT["rows"]
    assert len(rows) == 123
    assert all(r["final_status"] in ("PASS", "FAIL", "PENDING") for r in rows)
    counts = {"positive": {}, "counter": {}}
    for r in rows:
        side = "counter" if r["is_counter"] else "positive"
        counts[side][r["final_status"]] = counts[side].get(r["final_status"], 0) + 1
    assert REPORT["summary"]["totals"]["positive"] == counts["positive"]
    assert REPORT["summary"]["totals"]["counter"] == counts["counter"]
    assert REPORT["inputs_verification"]["parsed"]["artifact_bytes_fingerprint"]["match"] is True
