"""Necessary positive/negative tests for the r2 offline scorer.

These assert the CORRECTED policy (A1-A6 of the fixes-r1 handoff). The
original six tests in ../phase-4-round-1-assessment/ are kept unchanged as
history; their "any masking makes the whole row pending" assertion is the
policy being corrected — here a decisive non-complete whole question is FAIL
while masked citation details stay recorded as pending.

Zero network, zero model/DB calls; local artifacts + in-memory copies only.
"""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("assess_r2", HERE / "assess_round1.py")
assess = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assess)
GOLD = json.loads(assess.GOLD_PATH.read_text(encoding="utf-8"))
QUESTIONS = {q["query_id"]: q for q in GOLD["questions"]}
REGISTRY = assess.doc_registry()


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


def test_masked_details_pending_but_incomplete_question_fails():
    items, meta = assess.answer_items("pg", "table-enum-003")
    v = score("table-enum-003", items, meta)
    assert meta["coverage"] != "complete"
    assert v["masked_citations"] > 0  # 局部引用证据 unknown 保留记录
    assert v["judgement"] != "pending_artifact_masking"  # 整题不因细项 unknown 转待审
    assert v["final_status"] == "FAIL"


def test_prose_real_delivery_passes_but_fabricated_clause_fails():
    items, meta = assess.answer_items("pg", "prose-enum-002")
    assert score("prose-enum-002", items, meta)["judgement"] == "pass_mechanical"
    bad = copy.deepcopy(items)
    bad[0]["clause"] = "9.9.9"
    v = score("prose-enum-002", bad, meta)
    assert v["judgement"] != "pass_mechanical"
    assert v["final_status"] == "FAIL"


def test_seq_name_real_rows_pass_but_extra_genuine_source_row_fails():
    qid = "table-enum-004"
    items, meta = assess.answer_items("pg", qid)
    assert score(qid, items, meta)["judgement"] == "pass_mechanical"
    bad = copy.deepcopy(items)
    extra = copy.deepcopy(items[0])
    citation = extra["citation"]
    parsed = assess.an._doc_parsed_dir(REGISTRY[citation["doc_id"]]["file_path"])
    sidecar = assess.an._tables_sidecar(parsed)[citation["table_id"]]
    grid = assess.an.read_html_table(sidecar["content"])
    extra["cells"] = grid[0]
    extra["seq"] = "序号"
    citation["row_in_fragment"] = 0
    assert assess.verify_citations([extra], REGISTRY)[0]["verified"]  # 源行真实
    bad.append(extra)
    v = score(qid, bad, meta)
    assert v["projection"]["extra_rows"] > 0
    assert v["final_status"] == "FAIL"


def test_catalog_name_forged_fails_real_and_gap_located_pass():
    items, meta = assess.answer_items("pg", "file-enum-001")
    bad = copy.deepcopy(items)
    for item in bad:
        item["citation"]["doc_name"] = "完全伪造的文件名.pdf"
    v = score("file-enum-001", bad, meta)
    assert v["all_citations_verified"] is False
    assert v["final_status"] == "FAIL"
    # 真实交付通过
    assert score("file-enum-001", items, meta)["judgement"] == "pass_mechanical"
    # citation 缺冗余 doc_name：借 SHA 守卫的独立输入定位 → 不判错也不空过
    items5, meta5 = assess.answer_items("pg", "file-enum-005")
    v5 = score("file-enum-005", items5, meta5)
    assert v5["citation_gaps"] > 0
    assert v5["all_citations_verified"] is True
    assert v5["judgement"] == "pass_mechanical"


def test_wrong_workspace_fails_for_table_prose_and_catalog():
    for qid in ("table-enum-001", "prose-enum-001", "file-enum-001"):
        items, meta = assess.answer_items("pg", qid)
        bad = copy.deepcopy(items)
        for item in bad:
            item["citation"]["workspace"] = "foreign"
        v = score(qid, bad, meta)
        assert v["all_citations_verified"] is False
        assert v["final_status"] == "FAIL"


def test_fact_carrier_never_passes_mechanically_but_fragments_retained():
    items, meta = assess.answer_items("pg", "fact-002")
    v = score("fact-002", items, meta)
    assert v["exact_row_delivered"] is True
    assert v["judgement"] == "partial_fragment_correct"
    assert v["final_status"] == "FAIL"  # 片段正确但整题未答
    # prose 载体即便绑定 token 凑齐也不机械过（A2 无索引猜测）
    qid = "fact-005"
    fake = {
        "kind": "prose",
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
    v2 = score(qid, [fake], {"runtime": "ok", "coverage": "complete", "model": {}})
    assert v2["all_citations_verified"] is False
    assert v2["judgement"] != "pass_mechanical"
    real_items, real_meta = assess.answer_items("pg", "fact-004")
    v3 = score("fact-004", real_items, real_meta)
    assert v3["judgement"] == "pending_fact_carrier_review"
    assert v3["final_status"] == "PENDING"


def test_counter_needs_source_qualification_and_keeps_ok_behaviour():
    counter = next(c for c in GOLD["counter_examples"] if c["counter_id"] == "neg-003")
    items, meta = assess.answer_items("pg", "neg-003")
    entry = {"category": "file_enum", "items": items, "meta": meta, "budget_failure": None}
    v = assess.score_row("neg-003", "pg", entry, {"gold": {}, "target_docs": []}, True, REGISTRY)
    v = assess.score_counter_row("neg-003", "pg", v, entry, counter, REGISTRY, [])
    assert v["judgement"] == "behaviour_ok_mechanical"  # 真实通过保留
    bad = copy.deepcopy(items)
    for item in bad:
        item["citation"]["workspace"] = "foreign"
    entry_b = {"category": "file_enum", "items": bad, "meta": meta, "budget_failure": None}
    v2 = assess.score_row("neg-003", "pg", entry_b, {"gold": {}, "target_docs": []}, True, REGISTRY)
    v2 = assess.score_counter_row("neg-003", "pg", v2, entry_b, counter, REGISTRY, [])
    assert v2["judgement"] != "behaviour_ok_mechanical"


def test_typed_discovery_counts_and_zero_never_borrows(tmp_path, monkeypatch):
    monkeypatch.setattr(assess, "ROUND1", tmp_path)
    docs = assess.pre_expansion_docs("q-none", "pg")
    assert docs is None  # 无工件=unknown，不判零

    d = tmp_path / "legs/r1/pg/q-zero/fusion"
    d.mkdir(parents=True)
    (d / "fusion-runtime-latest.json").write_text(
        json.dumps(
            {
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
        )
    )
    assert assess.pre_expansion_docs("q-zero", "pg") == []


def test_real_typed_file_discovery_is_not_zero():
    # file-enum-005/pg：chunks=0 但 typed discovery=3 份（真实发现，非零召回）
    seg = assess._fusion_segments("file-enum-005", "pg")
    assert seg is not None
    assert len(seg["typed"]) == 3
    assert seg["chunk_docs"] == []
    docs = set(assess.pre_expansion_docs("file-enum-005", "pg"))
    expected = {t["doc_id"] for t in QUESTIONS["file-enum-005"]["target_docs"]}
    assert docs == expected


def test_adjudication_is_canonical_and_summary_consistent():
    report = json.loads((HERE / "adjudication.json").read_text(encoding="utf-8"))
    rows = report["rows"]
    assert len(rows) == 123
    pos = [r for r in rows if not r["is_counter"]]
    assert len(pos) == 93
    syn = [r for r in pos if r["category"] == "synthesis"]
    assert len(syn) == 18
    assert all(r["final_status"] == "FAIL" and r.get("manual_review") for r in syn)
    assert all(r["final_status"] in ("PASS", "FAIL", "PENDING") for r in rows)
    counts = {"positive": {}, "counter": {}}
    for r in rows:
        side = "counter" if r["is_counter"] else "positive"
        counts[side][r["final_status"]] = counts[side].get(r["final_status"], 0) + 1
    assert report["summary"]["totals"]["positive"] == counts["positive"]
    assert report["summary"]["totals"]["counter"] == counts["counter"]
    # A5: 旧均值撤下、分段口径、不合并统一 @20
    assert report["recall"]["withdrawn_previous_averages"]["pg"] == 0.959
    assert report["recall"]["published_aggregates"] is None
    fe5 = report["recall"]["per_question"]["file-enum-005"]["pg"]
    assert fe5["typed_coverage"] == 1.0 and fe5["chunk_n"] == 0
