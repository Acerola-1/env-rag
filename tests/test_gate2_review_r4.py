"""Fourth Gate2 review: source-bound fallback and complete scoring provenance."""

import asyncio
from types import SimpleNamespace

from env_rag_final.enumerate_.contract import EnumResult
from env_rag_final.enumerate_.prose_enum import UnitText
from env_rag_final.search import eval as evaluation
from env_rag_final.search import expand, gold, query


def run(coro):
    return asyncio.run(coro)


def patch_plain_scope(monkeypatch, body):
    import env_rag_final.enumerate_.prose_enum as prose

    text = "## 4.2 环境空气功能区质量要求\n" + body
    unit = UnitText("u", text, ["c"], {"blockid": "u"}, 0, len(text), False, "parsed_block")

    async def current(*a, **kw):
        return {"state": "current", "catalog_snapshot_id": "catalog"}

    async def read(*a, **kw):
        return [unit], EnumResult(
            "q",
            "prose",
            "default",
            "catalog",
            "source",
            members_total=1,
            members_processed=1,
            coverage_status="ambiguous",
            read_status="complete",
        )

    monkeypatch.setattr(expand, "check_search_stale", current)
    monkeypatch.setattr(prose, "read_prose_scope", read)
    return text


def test_no_subclause_fallback_binds_a_rereadable_raw_span(monkeypatch):
    source = patch_plain_scope(monkeypatch, "一类区执行一级限值，二类区执行二级限值。")
    result = run(expand._expand_prose(None, "default", "d", "d:scope:4.2", None))
    assert result["coverage_status"] == "complete"
    citation = result["items"][0]["citation"]
    assert all(citation.get(k) for k in ("workspace", "doc_id", "snapshot_id", "unit_id"))
    assert (
        source[citation["unit_rel_start"] : citation["unit_rel_end"]]
        .strip()
        .startswith(citation["quote"])
    )


def test_plain_scope_over_four_hundred_chars_is_not_silently_complete(monkeypatch):
    body = "必须执行相应的空气质量标准并保留全部适用条件。" * 30 + "最后一项要求必须保留。"
    patch_plain_scope(monkeypatch, body)
    result = run(expand._expand_prose(None, "default", "d", "d:scope:4.2", None))
    assert result["coverage_status"] != "complete" or body in result["items"][0]["text"]


def test_full_row_projection_does_not_consume_fabricated_extra_same_name_row():
    question = {
        "category": "table_enum",
        "gold": {
            "expected_items": [
                {"cells": ["1", "总汞", "0.05"]},
            ]
        },
    }
    result = evaluation._evaluate_enum_set(
        question,
        [
            {
                "coverage_status": "complete",
                "items": [
                    {"cells": ["1", "总汞", "0.05"], "citation_verified": True},
                    {"cells": ["99", "总汞", "999"], "citation_verified": True},
                ],
            }
        ],
    )
    assert result["exact_match"] is False
    assert result["extra"]


def test_table_gold_real_row_plus_fabricated_tail_is_rejected(monkeypatch):
    html = "<table><tr><td>1</td><td>总汞</td><td>0.05</td></tr></table>"
    monkeypatch.setattr(gold, "tables_of", lambda *a: {"t": {"content": html}})
    problems = gold.verify_typed_targets(
        {
            "questions": [
                {
                    "query_id": "q",
                    "target_docs": [{"doc_id": "d", "doc_name": "file.pdf"}],
                    "gold": {
                        "target_evidence": [
                            {
                                "doc_id": "d",
                                "unit_id": "t",
                                "quote": "1 | 总汞 | 0.05 | 原文不存在的附加限值999",
                            }
                        ]
                    },
                }
            ]
        }
    )
    assert problems


def test_partial_document_enumeration_cannot_be_an_exact_answer(monkeypatch):
    async def fake(*a, **kw):
        result = query.SearchResult("q", "default")
        result.status = "partial"
        result.candidates = [
            {"doc_id": "d", "discovery": "document_enumeration", "citation_verified": True}
        ]
        result.trace = [
            {
                "stage": "document_enumeration",
                "coverage_status": "partial",
                "fail_stage": "budget_exhausted",
                "members_total": 2,
                "members_processed": 1,
            }
        ]
        return result

    monkeypatch.setattr(evaluation, "run_query", fake)
    result = run(
        evaluation.run_benchmark(
            None,
            {
                "questions": [
                    {
                        "query_id": "q",
                        "question": "所有文件",
                        "category": "file_enum",
                        "gold_review_status": "approved",
                        "gold": {"expected_doc_ids": ["d"]},
                    }
                ]
            },
            expand=True,
        )
    )
    assert result["rows"][0]["enum_set_check"]["exact_match"] is False


def test_full_enumeration_does_not_rescue_a_zero_discovery_recall(monkeypatch):
    async def fake(*a, **kw):
        result = query.SearchResult("q", "default")
        result.candidates = (
            [{"doc_id": "d", "discovery": "document_enumeration", "citation_verified": True}]
            if kw.get("expand_docs")
            else []
        )
        payload = result.to_dict()
        payload["discovery_candidates"] = []
        return SimpleNamespace(to_dict=lambda: payload)

    monkeypatch.setattr(evaluation, "run_query", fake)
    result = run(
        evaluation.run_benchmark(
            None,
            {
                "questions": [
                    {
                        "query_id": "q",
                        "question": "所有文件",
                        "category": "file_enum",
                        "gold_review_status": "approved",
                        "gold": {"expected_doc_ids": ["d"], "target_evidence": [{"doc_id": "d"}]},
                    }
                ]
            },
            expand=True,
        )
    )
    assert result["rows"][0]["enum_set_check"]["exact_match"] is True
    assert result["evidence_recall_at_k_reviewed"] == 0
    assert result["list_doc_recall_at_k_reviewed"] == 0


def test_current_43_gold_does_not_score_keyword_prefixes_as_complete_requirements():
    import json
    from pathlib import Path

    dataset = json.loads(Path("reports/pg-retrieval/phase-2/gold-candidates.json").read_text())
    question = next(q for q in dataset["questions"] if q["query_id"] == "prose-enum-003")
    fabricated = [
        {
            "clause": clause,
            "text": text,
            "citation_verified": True,
        }
        for clause, text in [
            ("4.3.1", "4.3.1 同一排放口可以任意排放，无须计算混合污水标准。"),
            ("4.3.2", "4.3.2 工业污水不存在排放负荷限制。"),
            ("4.3.3", "4.3.3 污染物最高允许年排放总量不作任何计算。"),
            ("4.3.4", "4.3.4 放射性污水不必遵守任何辐射防护规定。"),
        ]
    ]
    result = evaluation._evaluate_enum_set(
        question, [{"coverage_status": "complete", "items": fabricated}]
    )
    assert result["exact_match"] is False
