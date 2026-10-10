"""Frozen offline acceptance for the submitted round-1 scorer.

Run against a corrected copy with ENV_RAG_ASSESSMENT_SCRIPT=/absolute/path.py.
Only local artifacts and copied items are read; no production runner is invoked.
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
        str(REPO / "reports/pg-retrieval/phase-4-round-1-assessment/assess_round1.py"),
    )
)
spec = importlib.util.spec_from_file_location("assessment_review_target", SCRIPT)
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


@pytest.mark.parametrize("qid", ["table-enum-001", "prose-enum-002", "file-enum-001"])
def test_real_complete_deliveries_still_pass(qid):
    items, meta = assess.answer_items("pg", qid)
    assert score(qid, items, meta)["judgement"] == "pass_mechanical"


def test_correct_prose_text_cannot_support_fabricated_clause_number():
    items, meta = assess.answer_items("pg", "prose-enum-002")
    bad = copy.deepcopy(items)
    bad[0]["clause"] = "9.9.9"
    assert score("prose-enum-002", bad, meta)["judgement"] != "pass_mechanical"


def test_seq_name_projection_counts_unexpected_source_rows():
    qid = "table-enum-004"
    items, meta = assess.answer_items("pg", qid)
    bad = copy.deepcopy(items)
    extra = copy.deepcopy(items[0])
    citation = extra["citation"]
    parsed = assess.an._doc_parsed_dir(REGISTRY[citation["doc_id"]]["file_path"])
    sidecar = assess.an._tables_sidecar(parsed)[citation["table_id"]]
    grid = assess.an.read_html_table(sidecar["content"])
    extra["cells"] = grid[0]
    extra["seq"] = "序号"
    citation["row_in_fragment"] = 0
    # This is a genuine source row, so source existence alone cannot reject it.
    assert assess.verify_citations([extra], REGISTRY)[0]["verified"]
    bad.append(extra)
    verdict = score(qid, bad, meta)
    assert verdict["judgement"] != "pass_mechanical"
    assert verdict["projection"]["extra_rows"] > 0


def test_fact_prose_needs_verified_source_and_requested_value():
    qid = "fact-005"
    item = {
        "kind": "prose",
        # The question asks second-level 20/30. 10 is a different column.
        "text": "臭气浓度 无量纲 10 30",
        "citation": {
            "kind": "char_span",
            "workspace": "default",
            "doc_id": QUESTIONS[qid]["target_docs"][0]["doc_id"],
            "unit_id": "missing",
            "unit_rel_start": 0,
            "unit_rel_end": 8,
            "quote": "虚假引句",
        },
    }
    verdict = score(qid, [item], {"runtime": "ok", "coverage": "complete", "model": {}})
    assert verdict["all_citations_verified"] is False
    assert verdict["judgement"] != "pass_mechanical"


def test_fact_correct_real_fragment_is_retained_without_whole_answer_pass():
    items, meta = assess.answer_items("pg", "fact-002")
    verdict = score("fact-002", items, meta)
    assert verdict["exact_row_delivered"] is True
    assert verdict["all_citations_verified"] is True
    assert verdict["judgement"] == "partial_fragment_correct"


@pytest.mark.parametrize("qid", ["table-enum-001", "prose-enum-001", "file-enum-001"])
def test_wrong_workspace_is_not_verified(qid):
    items, meta = assess.answer_items("pg", qid)
    bad = copy.deepcopy(items)
    for item in bad:
        item["citation"]["workspace"] = "foreign"
    verdict = score(qid, bad, meta)
    assert verdict["all_citations_verified"] is False
    assert verdict["judgement"] != "pass_mechanical"


def test_nonempty_forged_catalog_name_is_not_source_proof():
    items, meta = assess.answer_items("pg", "file-enum-001")
    bad = copy.deepcopy(items)
    for item in bad:
        item["citation"]["doc_name"] = "完全伪造的文件名.pdf"
    verdict = score("file-enum-001", bad, meta)
    assert verdict["all_citations_verified"] is False
    assert verdict["judgement"] != "pass_mechanical"


def test_counter_behaviour_does_not_bypass_source_verification():
    qid = "neg-003"
    items, meta = assess.answer_items("pg", qid)
    bad = copy.deepcopy(items)
    for item in bad:
        item["citation"]["workspace"] = "foreign"
    entry = {"category": "file_enum", "items": bad, "meta": meta, "budget_failure": None}
    counter = next(c for c in GOLD["counter_examples"] if c["counter_id"] == qid)
    v = assess.score_row(qid, "pg", entry, {"gold": {}, "target_docs": []}, True, REGISTRY)
    v = assess.score_counter_row(qid, "pg", v, entry, counter, REGISTRY, [])
    assert v["judgement"] != "behaviour_ok_mechanical"


def test_known_incomplete_table_is_fail_even_when_some_cells_are_masked():
    items, meta = assess.answer_items("pg", "table-enum-003")
    assert meta["coverage"] == "ambiguous"
    verdict = score("table-enum-003", items, meta)
    assert verdict["masked_citations"] > 0
    assert verdict.get("final_status") == "FAIL"
    assert verdict["judgement"] != "pending_artifact_masking"


def test_catalog_discovery_is_not_lost_when_no_chunk_was_discovered():
    qid = "file-enum-005"
    expected = {t["doc_id"] for t in QUESTIONS[qid]["target_docs"]}
    docs = assess.pre_expansion_docs(qid, "pg")
    assert set(docs) == expected


def test_zero_discovery_does_not_borrow_resolved_or_answer_targets(tmp_path, monkeypatch):
    monkeypatch.setattr(assess, "ROUND1", tmp_path)
    directory = tmp_path / "legs/r1/pg/q-zero/fusion"
    directory.mkdir(parents=True)
    report = {
        "results": [
            {
                "query_id": "q-zero",
                "workspace": "default",
                "pg": {"discovery_total": 0, "discovery_captured": True},
                "candidates": [],
                "typed_targets": [],
                "usable": [{"doc_id": "must-not-borrow"}],
                "targets_resolved": [{"docs": ["must-not-borrow"]}],
            }
        ]
    }
    (directory / "fusion-runtime-latest.json").write_text(json.dumps(report))
    assert assess.pre_expansion_docs("q-zero", "pg") == []


def test_input_integrity_failure_prevents_scoring_and_publication(tmp_path, monkeypatch):
    monkeypatch.setattr(assess, "__file__", str(tmp_path / "assess_round1.py"))
    monkeypatch.setattr(assess, "GOLD_SHA", "0" * 64)
    terminal = assess.load_terminal()
    terminal["results"] = [
        r for r in terminal["results"] if r["query_id"] == "table-enum-001" and r["path"] == "pg"
    ]
    monkeypatch.setattr(assess, "load_terminal", lambda: terminal)
    calls = []
    original = assess.score_row

    def observed(*args, **kwargs):
        calls.append("score")
        return original(*args, **kwargs)

    monkeypatch.setattr(assess, "score_row", observed)
    with pytest.raises(Exception):
        assess.main()
    assert calls == []
    assert not (tmp_path / "adjudication.json").exists()


def test_manual_synthesis_failures_are_in_canonical_rows():
    report = json.loads(SCRIPT.with_name("adjudication.json").read_text(encoding="utf-8"))
    rows = [r for r in report["rows"] if r["category"] == "synthesis" and not r["is_counter"]]
    assert len(rows) == 18
    assert all(r.get("final_status") == "FAIL" for r in rows)
    assert all(r.get("manual_review") for r in rows)
