"""Incremental offline acceptance of declaration metadata and table boundaries.

Only fixture sidecars and actual production functions are used. No service is
contacted; the existing improvement tests and all old frozen tests stay intact.
"""

import asyncio
import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from env_rag_final import answer as an
from env_rag_final.enumerate_.contract import EnumResult
from env_rag_final.enumerate_.prose_enum import (
    UnitText,
    bind_citations,
    extract_clauses_regex,
    verify_citations,
)
from env_rag_final.search import expand


def fixture(tmp_path):
    first = "前言\n4.1.1 " + "合法正文。" * 40
    second = "合法续文。"
    assembled = first + "\n\n" + second
    units = [
        UnitText("u1", first, [], {}, 0, len(first), False, "parsed_block"),
        UnitText("u2", second, [], {}, len(first) + 2, len(assembled), False, "parsed_block"),
    ]
    item = bind_citations(
        extract_clauses_regex(assembled, ["4.1.1"]), "default", "doc-fixture", "s", units
    )[0]
    rows = [
        {"type": "meta"},
        {"type": "content", "blockid": "u1", "content": first},
        {"type": "content", "blockid": "u2", "content": second},
    ]
    (tmp_path / "fixture.blocks.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    return item, units, assembled


def both_reject(item, units, assembled, parsed):
    generated = verify_citations([copy.deepcopy(item)], assembled, units)[0]
    reread = copy.deepcopy(item)
    problems = an._reverify_prose_items([reread], parsed)
    assert generated["citation_verified"] is False
    assert problems and reread["citation_reverified"] is False


def test_legitimate_full_cross_unit_declaration_survives(tmp_path):
    item, units, assembled = fixture(tmp_path)
    assert verify_citations([item], assembled, units)[0]["citation_verified"] is True
    assert an._reverify_prose_items([item], tmp_path) == []
    assert item["citation_reverified"] is True


def test_separator_cannot_manufacture_source_text(tmp_path):
    item, units, assembled = fixture(tmp_path)
    item["citation"]["assembly_separator"] = "停车场允许无条件排放污水。"
    raw_by_id = {u.unit_id: u.text for u in units}
    pieces = [
        raw_by_id[s["unit_id"]][s["rel_start"] : s["rel_end"]]
        for s in item["citation"]["unit_segments"]
    ]
    item["text"] = item["citation"]["assembly_separator"].join(pieces)
    assert "停车场" not in assembled
    assert item["citation"]["quote"] in assembled
    both_reject(item, units, assembled, tmp_path)


def test_non_string_separator_refuses_without_crashing(tmp_path):
    item, units, assembled = fixture(tmp_path)
    item["citation"]["assembly_separator"] = 7
    both_reject(item, units, assembled, tmp_path)


@pytest.mark.parametrize("change", ["null_start", "string_start", "missing_end"])
def test_malformed_declared_numeric_span_cannot_downgrade_to_quote_only(tmp_path, change):
    item, units, assembled = fixture(tmp_path)
    item["text"] += "停车场允许无条件排放污水。"
    if change == "null_start":
        item["citation"]["char_start"] = None
    elif change == "string_start":
        item["citation"]["char_start"] = "0"
    else:
        item["citation"].pop("char_end")
    assert item["source"] == "regex_clause_split"
    both_reject(item, units, assembled, tmp_path)


def test_genuine_quote_only_model_path_remains_supported(tmp_path):
    _item, units, assembled = fixture(tmp_path)
    item = {
        "text": "合法续文。",
        "citation": {"kind": "char_span", "quote": "合法续文。"},
        "citation_verified": True,
    }
    bind_citations([item], "default", "doc-fixture", "s", units)
    assert "char_start" not in item["citation"] and "char_end" not in item["citation"]
    assert verify_citations([item], assembled, units)[0]["citation_verified"] is True
    assert an._reverify_prose_items([item], tmp_path) == []
    assert item["citation_reverified"] is True


def test_embedded_table_and_continuation_cannot_be_silently_omitted_with_complete():
    text = (
        "4.1 本条限值如下，表内规定属于本条：\n"
        '<table id="tb-inner"><tr><td>总汞</td><td>0.05</td></tr></table>\n'
        "本条补充要求：每日监测一次。\n4.2 下一条要求。"
    )
    unit = UnitText("u", text, [], {}, 0, len(text), False, "parsed_block")

    async def read(*args, **kwargs):
        return [unit], EnumResult(
            "q",
            "prose",
            "default",
            "s",
            "fp",
            scope_ids=["d:scope:4"],
            members_total=1,
            members_processed=1,
            coverage_status="complete",
            read_status="complete",
        )

    async def current(*args, **kwargs):
        return {"state": "current", "catalog_snapshot_id": "s"}

    with (
        patch("env_rag_final.enumerate_.prose_enum.read_prose_scope", read),
        patch.object(expand, "check_search_stale", current),
    ):
        result = asyncio.run(
            expand._expand_prose(None, "default", "d", "d:scope:4", None, requested_clauses=["4.1"])
        )
    body = "\n".join(it["text"] for it in result["items"])
    if result["coverage_status"] == "complete":
        assert "总汞" in body and "0.05" in body and "每日监测一次" in body
    else:
        assert result["coverage_status"] in ("partial", "ambiguous")
        assert result.get("warnings") or result.get("fail_stage")


def test_replay_inputs_do_not_take_requested_children_from_expected_answer(monkeypatch):
    # Inspect the submitted replay's input seam without editing gold or running
    # the replay. The original question asks section 4.3, not these four IDs.
    import importlib.util

    root = Path(__file__).resolve().parents[3]
    path = root / "tests/test_phase4_improvement1_prose_integrity.py"
    spec = importlib.util.spec_from_file_location("submitted_improvement1", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []

    async def observed(*args, **kwargs):
        calls.append(kwargs.get("requested_clauses"))
        return {"items": []}

    monkeypatch.setattr(module.expand, "_expand_prose", observed)
    module._replay("prose-enum-003")
    assert len(calls) == 1
    assert calls[0] not in (["4.3.1", "4.3.2", "4.3.3", "4.3.4"],)
