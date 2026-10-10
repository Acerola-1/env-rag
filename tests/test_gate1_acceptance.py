"""Independent Gate 1 acceptance criteria; no live DB or model calls.

These tests assert required behavior through the owning entry/citation path.
They intentionally expose the residual defects found in the third review.
"""

import argparse
import asyncio
import json
from unittest.mock import patch

import pytest

from env_rag_final.audit import identity
from env_rag_final.cli import _run_enum
from env_rag_final.enumerate_.contract import EnumResult
from env_rag_final.enumerate_.doc_enum import _set_token
from env_rag_final.enumerate_.prose_enum import (
    UnitText,
    bind_citations,
    extract_clauses_regex,
    extract_items_with_model,
    verify_citations,
)
from env_rag_final.enumerate_.table_enum import enumerate_table


def unit(text, *, start=0, offset=0, uid="u"):
    return UnitText(
        uid,
        text,
        ["c"],
        {"blockid": uid},
        start,
        start + len(text),
        bool(offset),
        "parsed_block",
        offset,
    )


def test_model_quote_without_coordinates_gets_exact_source_span():
    text = "3.2 医疗机构污水\n门诊、病房等处排出的污水。"
    item = {"place": "门诊", "citation": {"quote": "门诊"}, "citation_verified": True}
    bound = bind_citations([item], "default", "d", "s", [unit(text)])[0]["citation"]
    assert bound["unit_id"] == "u"
    assert text[bound["unit_rel_start"] : bound["unit_rel_end"]] == "门诊"


def test_sliced_unit_citation_uses_original_offset():
    prefix = "父块引言\n7.1 其他条款。\n"
    wanted = "7.5 请求条款。"
    raw = prefix + wanted + "\n7.6 下一条。"
    items = extract_clauses_regex(wanted, ["7.5"])
    cit = bind_citations(items, "default", "d", "s", [unit(wanted, offset=len(prefix))])[0][
        "citation"
    ]
    assert raw[cit["unit_rel_start"] : cit["unit_rel_end"]].strip() == wanted


def test_separator_whitespace_never_creates_negative_unit_coordinate():
    first, second = "3.2 前一条。", "## 3.3 污泥\n沉淀污泥。"
    items = extract_clauses_regex(first + "\n\n" + second, ["3.3"])
    units = [unit(first, uid="a"), unit(second, start=len(first) + 2, uid="b")]
    cit = bind_citations(items, "default", "d", "s", units)[0]["citation"]
    assert cit["unit_id"] == "b"
    assert 0 <= cit["unit_rel_start"] < cit["unit_rel_end"] <= len(second)
    assert cit["quote"] in second[cit["unit_rel_start"] : cit["unit_rel_end"]]


def test_pending_extraction_warning_cannot_authorize_complete_answer():
    result = EnumResult(
        "q",
        "prose",
        "default",
        "s",
        "f",
        members_total=1,
        members_processed=1,
        items=[],
        coverage_status="complete",
        warnings=["items pending extraction"],
    )
    with pytest.raises(ValueError):
        result.validate()


class Reply:
    def __init__(self, item):
        self.item = item

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": json.dumps([self.item], ensure_ascii=False)}}]}


def http_client(item, on_post=lambda: None):
    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            on_post()
            return Reply(item)

    return Client


def test_partial_word_overlap_does_not_verify_extra_claim():
    item = {"place": "门诊停车场", "citation": {"quote": "门诊、病房"}}
    with patch("httpx.AsyncClient", lambda **kwargs: http_client(item)()):
        items, _, error = asyncio.run(
            extract_items_with_model(
                "本定义列明门诊、病房。",
                "列出明确点名场所",
                {
                    "LLM_BINDING_HOST": "http://fixture",
                    "LLM_BINDING_API_KEY": "fixture",
                    "LLM_MODEL": "fixture",
                },
            )
        )
    assert error and "unsupported" in error
    assert items[0]["citation_verified"] is False


def test_quote_presence_does_not_erase_ambiguous_source_location():
    units = [unit("污水", uid="a"), unit("污水", start=4, uid="b")]
    item = {"text": "污水", "citation": {"quote": "污水"}, "citation_verified": True}
    items = bind_citations([item], "default", "d", "s", units)
    assert items[0]["citation"]["locator_ambiguous"] is True
    assert items[0]["citation_verified"] is False
    verify_citations(items, "污水\n\n污水")
    assert items[0]["citation_verified"] is False


def test_text_item_cannot_add_an_unsupported_name_or_change_a_number():
    for claim, quote, source in (
        ("门诊、停车场", "门诊、病房", "本定义列明门诊、病房。"),
        ("总汞限值为999", "总汞限值为0.01", "总汞限值为0.01。"),
    ):
        item = {"text": claim, "citation": {"quote": quote}}
        with patch("httpx.AsyncClient", lambda **kwargs: http_client(item)()):
            items, _, error = asyncio.run(
                extract_items_with_model(
                    source,
                    "逐字抽取条目",
                    {
                        "LLM_BINDING_HOST": "http://fixture",
                        "LLM_BINDING_API_KEY": "fixture",
                        "LLM_MODEL": "fixture",
                    },
                )
            )
        assert error and "unsupported" in error
        assert items[0]["citation_verified"] is False


def test_document_token_covers_every_returned_metadata_field():
    row = dict(
        doc_id="d",
        doc_name="a",
        title="A",
        self_code=None,
        self_code_version=None,
        doc_type="standard",
        title_confidence="extracted",
        unknown_fields=[],
    )
    changed = dict(row, doc_type="report", title_confidence="unknown", unknown_fields=["title"])
    assert _set_token([row]) != _set_token([changed])


class TableConn:
    def __init__(self, missing_first=False):
        self.missing_first = missing_first

    async def fetchval(self, sql, *args):
        return "fixture.pdf"

    async def fetch(self, sql, *args):
        if "source_units" in sql:
            rows = [
                dict(
                    unit_id="a",
                    unit_order=1,
                    table_seq=1,
                    caption="表 1 甲",
                    heading="4",
                    locator={"blockid": "u"},
                )
            ]
            if self.missing_first:
                rows.append(
                    dict(
                        unit_id="b",
                        unit_order=2,
                        table_seq=2,
                        caption="表 1(完)",
                        heading="4",
                        locator={"blockid": "v"},
                    )
                )
            return rows
        return [{"chunk_id": "c"}]


def table_files(tmp_path, missing_first=False):
    p = tmp_path / "fixture.pdf.parsed"
    p.mkdir()
    html = "<table><tr><th>序号</th><th>项目</th></tr><tr><td>1</td><td>甲</td></tr></table>"
    data = {"a": {"content": "" if missing_first else html}}
    if missing_first:
        data["b"] = {"content": "<table><tr><td>2</td><td>乙</td></tr></table>"}
    (p / "fixture.tables.json").write_text(json.dumps({"tables": data}))


def test_table_rechecks_source_before_complete(tmp_path):
    table_files(tmp_path)
    calls = []

    async def guard(*args, **kwargs):
        calls.append(1)
        return dict(
            state="current" if len(calls) == 1 else "stale",
            active_snapshot_id="s",
            stored_fingerprint="f",
        )

    with (
        patch.object(identity, "PARSED_ROOT", tmp_path),
        patch("env_rag_final.enumerate_.table_enum.check_stale", guard),
    ):
        result = asyncio.run(enumerate_table(TableConn(), "default", "d", "1"))
    assert len(calls) >= 2
    assert result.coverage_status == "stale"


def test_missing_first_fragment_returns_partial_with_correct_remaining_source(tmp_path):
    table_files(tmp_path, True)

    async def guard(*args, **kwargs):
        return dict(state="current", active_snapshot_id="s", stored_fingerprint="f")

    with (
        patch.object(identity, "PARSED_ROOT", tmp_path),
        patch("env_rag_final.enumerate_.table_enum.check_stale", guard),
    ):
        result = asyncio.run(
            enumerate_table(TableConn(True), "default", "d", "1", allow_partial=True)
        )
    assert result.coverage_status == "partial"
    assert result.fail_stage == "missing_fragment"
    assert result.items[0]["citation"]["table_id"] == "b"
    assert result.items[0]["cells"] == ["2", "乙"]


def test_prose_cli_rechecks_source_after_model_extraction(tmp_path, capsys):
    p = tmp_path / "fixture.pdf.parsed"
    p.mkdir()
    text = "3.2 定义\n门诊。"
    (p / "fixture.blocks.jsonl").write_text(
        json.dumps({}) + "\n" + json.dumps(dict(type="content", blockid="u", content=text))
    )
    state = {"changed": False}

    async def guard(*args, **kwargs):
        return dict(
            state="stale" if state["changed"] else "current",
            active_snapshot_id="s",
            stored_fingerprint="f",
        )

    class Conn:
        async def fetchval(self, sql, *args):
            return "fixture.pdf"

        async def fetch(self, sql, *args):
            return [{"unit_id": "u"}] if "scope_units" in sql else [{"chunk_id": "c"}]

        async def fetchrow(self, sql, *args):
            return dict(
                unit_id="u",
                unit_kind="block",
                heading="3.2",
                requires_span=False,
                content_length=len(text),
                locator={"blockid": "u"},
            )

        async def close(self):
            pass

    async def connect(**kwargs):
        return Conn()

    item = {
        "clause": "3.2",
        "text": "门诊",
        "citation": {
            "quote": "门诊",
            "char_start": text.index("门诊"),
            "char_end": text.index("门诊") + 2,
        },
    }
    args = argparse.Namespace(
        command="enum-prose",
        doc_id="d",
        scope_id="scope",
        clause_wanted=None,
        with_model=True,
        predicate="列出门诊",
        out=None,
    )
    values = dict(
        POSTGRES_HOST="fixture",
        POSTGRES_PORT="5432",
        POSTGRES_USER="fixture",
        POSTGRES_PASSWORD="fixture",
        POSTGRES_DATABASE="fixture",
        LLM_BINDING_HOST="http://fixture",
        LLM_BINDING_API_KEY="fixture",
        LLM_MODEL="fixture",
    )

    def changed():
        state["changed"] = True

    with (
        patch.object(identity, "PARSED_ROOT", tmp_path),
        patch("asyncpg.connect", connect),
        patch("env_rag_final.catalog.builder.check_stale", guard),
        patch("httpx.AsyncClient", lambda **kwargs: http_client(item, changed)()),
    ):
        _run_enum(args, values)
    result = json.loads(capsys.readouterr().out)
    assert result["coverage_status"] == "stale"
