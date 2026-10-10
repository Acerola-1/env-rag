"""Gate2 third review: fixed-set scoring and production expansion boundaries."""

import asyncio

from env_rag_final.enumerate_.contract import EnumResult
from env_rag_final.enumerate_.prose_enum import UnitText
from env_rag_final.search import eval as evaluation
from env_rag_final.search import expand, gold, query


def run(coro):
    return asyncio.run(coro)


def enum_question(category, expected):
    return {"category": category, "gold": {"expected_items": expected}}


def test_table_wrong_pollutant_and_value_cannot_score_exact():
    question = enum_question("table_enum", [{"seq": "1", "cells": ["1", "总汞", "0.05"]}])
    result = evaluation._evaluate_enum_set(
        question,
        [
            {
                "coverage_status": "complete",
                "items": [{"cells": ["1", "总铅", "999"], "citation_verified": True}],
            }
        ],
    )
    assert result["exact_match"] is False


def test_rowspan_missing_average_time_row_cannot_score_exact():
    question = enum_question(
        "table_enum",
        [
            {"seq": "1", "cells": ["1", "二氧化硫", "年平均", "20"]},
            {"seq": "1", "cells": ["1", "二氧化硫", "小时平均", "100"]},
        ],
    )
    result = evaluation._evaluate_enum_set(
        question,
        [
            {
                "coverage_status": "complete",
                "items": [{"cells": ["1", "二氧化硫", "年平均", "20"], "citation_verified": True}],
            }
        ],
    )
    assert result["exact_match"] is False


def test_prose_correct_clause_number_with_wrong_requirement_cannot_score_exact():
    question = enum_question("prose_enum", ["4.1.2 特定传染病医疗机构执行表1限值"])
    result = evaluation._evaluate_enum_set(
        question,
        [
            {
                "coverage_status": "complete",
                "items": [
                    {"clause": "4.1.2", "text": "所有医疗机构免予处理", "citation_verified": True}
                ],
            }
        ],
    )
    assert result["exact_match"] is False


def test_file_expected_doc_ids_have_an_exact_set_check():
    question = {"category": "file_enum", "gold": {"expected_doc_ids": ["d1", "d2"]}}
    result = evaluation._evaluate_enum_set(
        question,
        [
            {
                "coverage_status": "complete",
                "items": [
                    {"doc_id": "d1", "citation_verified": True},
                    {"doc_id": "foreign", "citation_verified": True},
                ],
            }
        ],
    )
    assert result is not None
    assert result["exact_match"] is False
    assert "d2" in result["missing"] and "foreign" in result["extra"]


def test_benchmark_routes_file_question_to_full_document_enumeration(monkeypatch):
    observed = []

    async def fake(conn, text, **kwargs):
        observed.append(kwargs)
        return query.SearchResult("q", "default")

    monkeypatch.setattr(evaluation, "run_query", fake)
    run(
        evaluation.run_benchmark(
            None,
            {
                "questions": [
                    {
                        "query_id": "file",
                        "question": "列出所有年报",
                        "category": "file_enum",
                        "gold_review_status": "unreviewed",
                        "gold": {"expected_doc_ids": ["d"]},
                    }
                ]
            },
            expand=True,
        )
    )
    assert observed[0].get("expand_docs") is True


def test_missing_requested_clause_is_not_overwritten_by_successful_read(monkeypatch):
    import env_rag_final.enumerate_.prose_enum as prose

    async def current(*a, **kw):
        return {"state": "current", "catalog_snapshot_id": "catalog"}

    text = "4.1.1 应当执行限值。"
    unit = UnitText("u", text, ["c"], {"blockid": "u"}, 0, len(text), False, "parsed_block")

    async def read(*a, **kw):
        return [unit], EnumResult(
            "q",
            "prose",
            "default",
            "catalog",
            "source",
            members_total=1,
            members_processed=1,
            coverage_status="partial",
            read_status="complete",
            warnings=["requested clauses missing: 4.1.7"],
        )

    monkeypatch.setattr(expand, "check_search_stale", current)
    monkeypatch.setattr(prose, "read_prose_scope", read)
    result = run(
        expand._expand_prose(
            None,
            "default",
            "d",
            "d:scope:4.1",
            None,
            requested_clauses=["4.1.1", "4.1.7"],
        )
    )
    assert result["coverage_status"] != "complete"


def test_gold_quote_matching_first_eighty_chars_does_not_validate_fabricated_tail(monkeypatch):
    source = "监测要求应当遵守原始规定。" * 20
    quote = source[:80] + "这里是原文中从未出现的编造要求。"
    monkeypatch.setattr(gold, "tables_of", lambda *a: {})
    monkeypatch.setattr(gold, "blocks_of", lambda *a: [{"blockid": "u", "content": source}])
    problems = gold.verify_typed_targets(
        {
            "questions": [
                {
                    "query_id": "q",
                    "target_docs": [{"doc_id": "d", "doc_name": "file.pdf"}],
                    "gold": {"target_evidence": [{"doc_id": "d", "unit_id": "u", "quote": quote}]},
                }
            ]
        }
    )
    assert problems


def test_fixed_six_question_enum_denominator_keeps_ambiguous_failures(monkeypatch):
    async def fake(conn, text, **kwargs):
        result = query.SearchResult("q", "default")
        result.status = "ok" if text == "q0" else "ambiguous"
        result.candidates = [{"doc_id": "d", "chunk_id": "c"}]
        result.trace = [
            {
                "stage": "scope_expansion",
                "expansions": [
                    {
                        "coverage_status": "complete" if text == "q0" else "ambiguous",
                        "items": [{"cells": ["1"], "citation_verified": True}]
                        if text == "q0"
                        else [],
                    }
                ],
            }
        ]
        return result

    monkeypatch.setattr(evaluation, "run_query", fake)
    dataset = {
        "questions": [
            {
                "query_id": f"q{n}",
                "question": f"q{n}",
                "category": "table_enum",
                "gold_review_status": "approved",
                "gold": {
                    "expected_items": [{"seq": "1"}],
                    "target_evidence": [{"doc_id": "d", "chunk_id": "c"}],
                },
            }
            for n in range(6)
        ]
    }
    summary = run(evaluation.run_benchmark(None, dataset, expand=True))
    # A refused answer is a failed fixed question, even though its candidates
    # cannot be credited as usable evidence. It must not shrink Gate2's /6.
    assert summary["enum_set_checks"]["table_enum"]["questions"] == 6
    assert summary["enum_set_checks"]["table_enum"]["exact_match"] == 1


def test_requested_chapter_without_di_prefix_is_recognized():
    result = query.SearchResult("q", "default")
    result.query_text = "GB18466-2005 中 3 章定义了哪些术语？"
    targets = expand._requested_targets(result)
    assert any(t["kind"] == "chapter" and t["value"] == "3" for t in targets)
