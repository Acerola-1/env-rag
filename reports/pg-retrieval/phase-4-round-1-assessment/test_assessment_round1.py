"""Offline tests for the round-1 assessment rules (no network, artifacts read-only).

Proves: (1) copied-then-tampered deliveries are REJECTED by the scorer —
wrong value in a real row, moved grid row index, wrong-document row;
(2) real passing artifacts still PASS (the scorer is not all-reject);
(3) masked-cell artifacts are pending, not fabricated pass/fail.
"""

import copy
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("assess_round1", HERE / "assess_round1.py")
assess = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assess)

GOLD = json.loads(assess.GOLD_PATH.read_text(encoding="utf-8"))
GOLD_BY = {q["query_id"]: q for q in GOLD["questions"]}
DOC_REG = assess.doc_registry()


def load_items(path_seg, qid):
    items, meta = assess.answer_items(path_seg, qid)
    return items, meta


def entry_for(items, coverage):
    return {
        "category": "table_enum",
        "items": items,
        "meta": {"runtime": "ok", "coverage": coverage, "model": {}},
        "budget_failure": None,
    }


def test_real_table_enum_001_pg_passes():
    items, meta = load_items("pg", "table-enum-001")
    v = assess.score_row(
        "table-enum-001",
        "pg",
        entry_for(items, meta["coverage"]),
        GOLD_BY["table-enum-001"],
        False,
        DOC_REG,
    )
    assert v["judgement"] == "pass_mechanical", v


def test_tampered_value_fails():
    items, meta = load_items("pg", "table-enum-001")
    bad = copy.deepcopy(items)
    row = next(r for r in bad if "总汞" in json.dumps(r.get("cells"), ensure_ascii=False))
    row["cells"] = ["1", "总汞", "0.999"]  # copied-then-tampered limit value
    v = assess.score_row(
        "table-enum-001",
        "pg",
        entry_for(bad, "complete"),
        GOLD_BY["table-enum-001"],
        False,
        DOC_REG,
    )
    assert v["judgement"] != "pass_mechanical" and not v["projection"]["ok"], v


def test_wrong_document_row_fails():
    items, meta = load_items("pg", "table-enum-001")
    bad = copy.deepcopy(items)
    for r in bad:
        (r.get("citation") or {})["doc_id"] = (
            "doc-257d8cf3fdf90e76c31908c4f92fc1a1"  # another standard
        )
    r0 = bad[0]
    r0["seq"] = "x"  # force identity mismatch beyond doc check as well
    v = assess.score_row(
        "table-enum-001",
        "pg",
        entry_for(bad, "complete"),
        GOLD_BY["table-enum-001"],
        False,
        DOC_REG,
    )
    assert v["judgement"] in (
        "foreign_doc_rows",
        "projection_mismatch",
        "unverified_citation",
        "pending_artifact_masking",
    ), v


def test_moved_grid_index_detected():
    items, meta = load_items("pg", "table-enum-001")
    bad = copy.deepcopy(items)
    for r in bad:
        cit = r.get("citation") or {}
        if isinstance(cit.get("row_in_fragment"), int):
            cit["row_in_fragment"] += 1  # re-numbered position lies to the raw grid
    v = assess.score_row(
        "table-enum-001",
        "pg",
        entry_for(bad, "complete"),
        GOLD_BY["table-enum-001"],
        False,
        DOC_REG,
    )
    assert v["all_citations_verified"] is False and v["judgement"] in (
        "unverified_citation",
        "pending_artifact_masking",
        "projection_mismatch",
    ), v


def test_masked_cells_are_pending_not_fabricated():
    # table-enum-003 pg/fusion rows contain sanitizer-collided cells offline
    items, meta = load_items("pg", "table-enum-003")
    adj = json.loads((HERE / "adjudication.json").read_text(encoding="utf-8"))
    row = next(v for v in adj["rows"] if v["qid"] == "table-enum-003" and v["path"] == "pg")
    assert row["judgement"] == "pending_artifact_masking"
    assert row["masked_citations"] > 0


def test_prose_out_of_scope_extras_caught():
    # prose-enum-001 local: 13 delivered from other documents with complete
    # coverage must be a projection mismatch (extra), not a pass
    adj = json.loads((HERE / "adjudication.json").read_text(encoding="utf-8"))
    row = next(v for v in adj["rows"] if v["qid"] == "prose-enum-001" and v["path"] == "local")
    assert row["judgement"] == "projection_mismatch"
    assert row["extra_out_of_scope"] == 13
