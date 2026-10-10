"""Fifth Gate2 review: category coordinates and an authoritative empty discovery."""

import asyncio

from env_rag_final.enumerate_.contract import EnumResult
from env_rag_final.enumerate_.prose_enum import UnitText
from env_rag_final.search import eval as evaluation
from env_rag_final.search import expand, query


def run(coro):
    return asyncio.run(coro)


def test_category_split_uses_original_assembled_coordinates(monkeypatch):
    import env_rag_final.enumerate_.prose_enum as prose

    source = (
        "## 3 水域功能和标准分类\n"
        "依据保护目标划分为三类：\n"
        "I 类 主要适用于源头水、自然保护区；\n"
        "II 类 主要适用于饮用水一级保护区；\n"
        "III 类 主要适用于饮用水二级保护区。"
    )
    unit = UnitText("u", source, ["c"], {"blockid": "u"}, 0, len(source), False, "parsed_block")

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
    result = run(expand._expand_prose(None, "default", "d", "d:scope:3", None))
    assert len(result["items"]) == 3
    for item in result["items"]:
        citation = item["citation"]
        assert item["citation_verified"] is True
        raw = source[citation["unit_rel_start"] : citation["unit_rel_end"]]
        assert raw.strip().startswith(citation["quote"].strip())


def test_empty_discovery_is_not_backfilled_by_post_enumeration_attribution(monkeypatch):
    async def fake(*a, **kw):
        result = query.SearchResult("q", "default")
        result.discovery_candidates = []  # authoritative zero discovery
        result.candidates = [
            {
                "doc_id": "d",
                "discovery": "doc_attribution",
                "citation_verified": True,
            }
        ]
        result.trace = [
            {
                "stage": "document_enumeration",
                "coverage_status": "complete",
                "members_total": 1,
                "members_processed": 1,
                "fail_stage": "",
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
                        "question": "列出相关文件",
                        "category": "file_enum",
                        "gold_review_status": "approved",
                        "gold": {
                            "expected_doc_ids": ["d"],
                            "target_evidence": [{"doc_id": "d"}],
                        },
                    }
                ]
            },
            expand=True,
        )
    )
    assert result["rows"][0]["enum_set_check"]["exact_match"] is True
    assert result["rows"][0]["discovery_candidates_total"] == 0
    assert result["evidence_recall_at_k_reviewed"] == 0
    assert result["list_doc_recall_at_k_reviewed"] == 0
