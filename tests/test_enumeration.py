"""Enumeration tests — every Gate 1 counterexample (E1–E7) becomes an
entry-level regression. Offline: fake connections/tmp fixtures, no real DB."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from env_rag_final.audit import identity as audit_identity
from env_rag_final.enumerate_.contract import EnumResult
from env_rag_final.enumerate_.doc_enum import _set_token, enumerate_documents
from env_rag_final.enumerate_.prose_enum import (
    extract_clauses_regex,
    extract_items_with_model,
    locate_span,
    read_prose_scope,
)
from env_rag_final.enumerate_.table_enum import enumerate_table
from env_rag_final.enumerate_.tables import (
    enumerate_logical_table,
    link_logical_tables,
    parse_caption,
    read_html_table,
)


def _run(coro):
    import asyncio

    return asyncio.run(coro)


async def _current(*args, **kwargs):
    return {"state": "current", "active_snapshot_id": "s", "stored_fingerprint": "f"}


# ==========================================================================
# 3.1 caption classification + chapter-scoped linking (E2)
# ==========================================================================


def test_caption_kinds():
    assert parse_caption("表 1 第一类污染物最高允许排放浓度") == (
        "1",
        "第一类污染物最高允许排放浓度",
        "base",
    )
    assert parse_caption("表 1(完)")[2] == "continuation"
    assert parse_caption("续表 2")[0] == "2"
    assert parse_caption("(1997年12月31日之前建设的单位)")[2] == "other"
    assert parse_caption("") == (None, None, "empty")


def _unit(tid, order, caption, heading="4", table_seq=None, blockid="blk"):
    return {
        "unit_id": tid,
        "unit_order": order,
        "table_seq": table_seq,
        "caption": caption,
        "heading": heading,
        "locator": json.dumps({"blockid": blockid}),
    }


def test_e2_cross_chapter_same_number_continuation_not_merged():
    """Gate-1 E2 counterexample: base in ch4 + (完) in ch7 must NOT merge."""
    units = [
        _unit("base4", 1, "表 1 甲", heading="4"),
        _unit("continuation7", 9, "表 1(完)", heading="7"),
    ]
    groups = link_logical_tables(units)
    merged = [g for g in groups if g.number == "1" and len(g.fragments) == 2]
    assert not merged, "cross-chapter continuation must not join ch4 base"
    g4 = next(g for g in groups if g.number == "1" and g.scope_key == "4")
    assert [f.table_id for f in g4.fragments] == ["base4"]
    assert g4.status == "confirmed"


def test_same_chapter_continuation_joins():
    units = [
        _unit("a", 1, "表 1 甲", heading="4"),
        _unit("b", 2, "表 1(完)", heading="4"),
    ]
    groups = link_logical_tables(units)
    g = next(g for g in groups if g.number == "1")
    assert [f.table_id for f in g.fragments] == ["a", "b"] and g.status == "confirmed"


def test_two_same_number_groups_require_scope_disambiguation():
    units = [
        _unit("t1-ch4", 1, "表 1 甲", heading="4"),
        _unit("t1-ch4w", 2, "表 1(完)", heading="4"),
        _unit("t1-ch7", 9, "表 1 乙", heading="7"),
    ]
    groups = link_logical_tables(units)
    ones = [g for g in groups if g.number == "1"]
    assert len(ones) == 2, "two chapters, two logical tables"
    assert {g.scope_key for g in ones} == {"4", "7"}


# ==========================================================================
# 3.2 HTML expansion + header recognition (E3)
# ==========================================================================


def test_rowspan_colspan_expansion():
    html = (
        '<table><tr><td rowspan="2">序号</td><td rowspan="2">污染物</td>'
        '<td colspan="2">浓度限值</td></tr>'
        "<tr><td>一级</td><td>二级</td></tr>"
        "<tr><td>1</td><td>总汞</td><td>0.01</td><td>0.02</td></tr></table>"
    )
    grid = read_html_table(html)
    assert len(grid) == 3 and all(len(r) == 4 for r in grid)
    assert grid[1][0] == "序号" and grid[1][2] == "一级"


def test_e3_unnumbered_table_yields_data_rows_not_empty():
    """pH/总汞 rows without numeric first column are DATA rows (E3)."""
    html = (
        "<table><tr><th>项目</th><th>限值</th></tr>"
        "<tr><td>pH</td><td>6～9</td></tr><tr><td>总汞</td><td>0.05</td></tr></table>"
    )
    rows = enumerate_logical_table(
        [
            type(
                "F",
                (),
                {"table_id": "x", "caption": "表 1", "grid": lambda self: read_html_table(html)},
            )()
        ]
    )
    assert rows.rows == [["项目", "限值"], ["pH", "6～9"], ["总汞", "0.05"]] or len(rows.rows) == 2
    assert rows.rows, "unnumbered table must not collapse to empty"


def test_e3_sequence_gap_flags_partial():
    html = (
        "<table><tr><td>1</td><td>甲</td></tr><tr><td>2</td><td>乙</td></tr>"
        "<tr><td>5</td><td>丙</td></tr></table>"
    )
    rows = enumerate_logical_table(
        [
            type(
                "F",
                (),
                {"table_id": "x", "caption": "表", "grid": lambda self: read_html_table(html)},
            )()
        ]
    )
    assert rows.sequence_ok is False


def test_repeated_header_dropped():
    base = "<table><tr><th>序号</th><th>项目</th></tr><tr><td>1</td><td>甲</td></tr></table>"
    cont = "<table><tr><th>序号</th><th>项目</th></tr><tr><td>2</td><td>乙</td></tr></table>"
    rows = enumerate_logical_table(
        [
            type(
                "F",
                (),
                {"table_id": "a", "caption": "表", "grid": lambda self: read_html_table(base)},
            )(),
            type(
                "F",
                (),
                {"table_id": "b", "caption": "表(完)", "grid": lambda self: read_html_table(cont)},
            )(),
        ]
    )
    assert [r[0] for r in rows.rows] == ["1", "2"]


# ==========================================================================
# 3.3 prose clause extraction (E1 extraction semantics)
# ==========================================================================

GB18466_CH3 = (
    "## 3 术语和定义\n本标准采用下列定义。\n"
    "3.1 医疗机构 medical organization\n指从事疾病诊断、治疗活动的医院、卫生院、疗养院、门诊部、诊所、卫生急救站等。\n"
    "## 3.3 污泥 sludge\n指医疗机构污水处理过程中产生的栅渣、沉淀污泥和化粪池污泥。\n"
)


def test_extract_with_markdown_prefix_and_range():
    items = extract_clauses_regex(GB18466_CH3, wanted=["3.1", "3.3"])
    assert [i["clause"] for i in items] == ["3.1", "3.3"]


def test_e1_duplicate_keeps_longest_body_not_first():
    overlap = (
        "4.1.1 条款开始但chunk在此截断\n\n"
        "4.1.1 条款开始但chunk在此截断，后续重要条件只在第二片出现。\n4.1.2 下一条。"
    )
    items = extract_clauses_regex(overlap, ["4.1.1"])
    assert len(items) == 1
    assert "后续重要条件" in items[0]["text"], "tail from the second fragment must survive"


def test_locate_span():
    big = "Annex 4\n" + "填充\n" * 100 + "\n7.5 特殊条款。\n" + "尾\n" * 50
    span = locate_span(big, "7.5")
    assert span and "特殊条款" in big[span[0] : span[1]]
    assert locate_span("没有", "9.9.9") is None


# ==========================================================================
# E6: contract strictness
# ==========================================================================


def test_e6_missing_verified_flag_rejected():
    r = EnumResult(
        "q",
        "prose",
        "default",
        "s",
        "f",
        members_total=1,
        members_processed=1,
        items=[{"citation": {"quote": "x", "snapshot_id": "s", "doc_id": "d", "workspace": "w"}}],
        coverage_status="complete",
    )
    with pytest.raises(ValueError, match="citation_verified"):
        r.validate()


def test_e6_citation_missing_identity_rejected():
    r = EnumResult(
        "q",
        "prose",
        "default",
        "s",
        "f",
        members_total=1,
        members_processed=1,
        items=[{"citation": {"quote": "x"}, "citation_verified": True}],
        coverage_status="complete",
    )
    with pytest.raises(ValueError, match="bind"):
        r.validate()


def test_e6_no_chunk_text_not_processed_complete():
    """E1: unit without readable text must not count as processed."""

    class ProseConn:
        async def fetch(self, sql, *args):
            if "scope_units" in sql:
                return [{"unit_id": "u"}]
            return []

        async def fetchval(self, sql, *args):
            return "fixture.pdf"

        async def fetchrow(self, sql, *args):
            return dict(
                unit_id="u",
                unit_kind="block",
                heading="3",
                requires_span=False,
                content_length=99,
                locator={},
            )

    with patch("env_rag_final.catalog.builder.check_stale", _current):
        _units, result = _run(read_prose_scope(None, ProseConn(), "default", "d", "s", "scope"))
    assert result.members_processed == 0 and result.members_total == 1
    assert result.coverage_status == "partial"
    assert result.fail_stage == "missing_fragment"
    result.validate()  # partial validates; the gate is coverage != complete


def test_e1_requires_span_unenforced_returns_partial():
    """E1: requires_span unit without locatable range → partial/unresolved_span."""

    class SpanConn:
        async def fetch(self, sql, *args):
            if "scope_units" in sql:
                return [{"unit_id": "u"}]
            return [{"chunk_id": "c", "chunk_order": 0}]

        async def fetchrow(self, sql, *args):
            return dict(
                unit_id="u",
                unit_kind="block",
                heading="3",
                requires_span=True,
                content_length=99,
                locator={"blockid": "u"},
            )

        async def fetchval(self, sql, *args):
            return "fixture.pdf"

    class SpanAdapter:
        async def get_chunk(self, *args):
            return {"content": "Annex 4\n未定位子条款\nAnnex 5\n范围外内容", "full_doc_id": "d"}

    with (
        patch("env_rag_final.catalog.builder.check_stale", _current),
        patch.object(audit_identity, "PARSED_ROOT", Path("/nonexistent-root-for-test")),
    ):
        units, result = _run(
            read_prose_scope(SpanAdapter(), SpanConn(), "default", "d", "s", "scope")
        )
    assert result.coverage_status == "partial"
    assert result.fail_stage == "unresolved_span"
    assert result.members_processed == 0


def test_e5_old_snapshot_rejected_not_empty_complete():
    """E5: a retired snapshot id must not produce 0/0 complete."""

    class OldConn:
        async def fetch(self, sql, *args):
            return []

        async def fetchrow(self, sql, *args):
            return None

        async def fetchval(self, sql, *args):
            return "fixture.pdf"

    with patch("env_rag_final.catalog.builder.check_stale", _current):
        _units, result = _run(read_prose_scope(None, OldConn(), "default", "d", "old", "scope"))
    # 'old' is not the active snapshot 's' → stale, zero members never complete
    assert result.coverage_status in ("stale", "ambiguous")
    assert result.fail_stage == "snapshot_mismatch"
    result.validate()


# ==========================================================================
# E5: document enumeration guards
# ==========================================================================


def test_e5_final_page_snapshot_replacement_detected():
    class DocConn:
        def __init__(self):
            self.snapshot, self.active_reads = "s1", 0

        async def fetchval(self, sql, *args):
            if "corpus_runs" in sql:
                self.active_reads += 1
                return self.snapshot
            return 1

        async def fetchrow(self, sql, *args):
            if "corpus_runs" in sql:
                self.active_reads += 1
                return {"snapshot_id": self.snapshot, "source_fingerprint": '{"value": "f"}'}
            return None

        async def fetch(self, sql, *args):
            row = dict(
                doc_id="d1",
                doc_name="a",
                title="A",
                title_confidence="extracted",
                self_code=None,
                self_code_version=None,
                doc_type="other",
                unknown_fields=[],
            )
            if "LIMIT 100 " in sql or "LIMIT 100" in sql:
                self.snapshot = "s2"  # active replaced after the final page
            return [row]

    async def _fake_live(conn, workspace="default"):
        return "f"  # live source unchanged; the ACTIVE snapshot replacement is the trigger

    with (
        patch("env_rag_final.catalog.builder._live_source_fingerprint", _fake_live),
        patch("env_rag_final.catalog.builder.check_stale", _current),
    ):
        result = _run(
            enumerate_documents(
                DocConn(), "TRUE", predicate_text="TRUE", page_size=100, max_pages=1
            )
        )
    # after the final page the active snapshot changed → result must be
    # stale, NOT complete (E5 final-page guard)
    assert result.coverage_status == "stale"
    assert result.fail_stage == "snapshot_mismatch"
    assert result.warnings and "replaced" in result.warnings[-1]


def test_doc_set_token_changes_on_membership():
    rows_a = [
        Row(doc_id="doc-1", doc_name="a.pdf", self_code="GB1", self_code_version="2020", title="甲")
    ]
    rows_b = rows_a + [
        Row(doc_id="doc-2", doc_name="b.pdf", self_code="GB2", self_code_version="2021", title="乙")
    ]
    assert _set_token(rows_a) != _set_token(rows_b)
    assert _set_token(list(reversed(rows_a))) == _set_token(rows_a)


class Row(dict):
    def __getitem__(self, key):
        return super().__getitem__(key)


# ==========================================================================
# E6: model output verification
# ==========================================================================


def test_e6_model_missing_quote_rejected():

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps([{"text": "unsupported claim", "citation": {}}])
                        }
                    }
                ]
            }

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            return Response()

    with patch("httpx.AsyncClient", lambda **kwargs: Client()):
        items, _logs, err = _run(
            extract_items_with_model(
                "实际原文",
                "列出条目",
                {
                    "LLM_BINDING_HOST": "http://fixture",
                    "LLM_BINDING_API_KEY": "k",
                    "LLM_MODEL": "m",
                },
            )
        )
    assert err is not None and "invalid_item_shape" in err


def test_r5_unsupported_claim_rejected_even_with_real_quote():
    """R5 counterexample: "原文明确列出停车场" + real quote "门诊、病房" —
    the quote exists verbatim but does NOT support the claim."""

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                [
                                    {
                                        "text": "原文明确列出停车场",
                                        "citation": {"quote": "门诊、病房"},
                                    }
                                ]
                            )
                        }
                    }
                ]
            }

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            return Response()

    with patch("httpx.AsyncClient", lambda **kwargs: Client()):
        _items, _logs, err = _run(
            extract_items_with_model(
                "本定义列明门诊、病房。",
                "列出场所",
                {"LLM_BINDING_HOST": "http://x", "LLM_BINDING_API_KEY": "k", "LLM_MODEL": "m"},
            )
        )
    assert err is not None and "unsupported_or_fabricated_citation" in err


def test_r5_supported_place_claim_passes():

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                [
                                    {
                                        "place": "门诊",
                                        "citation": {"quote": "本定义列明门诊、病房。"},
                                    }
                                ]
                            )
                        }
                    }
                ]
            }

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            return Response()

    with patch("httpx.AsyncClient", lambda **kwargs: Client()):
        items, _logs, err = _run(
            extract_items_with_model(
                "本定义列明门诊、病房。",
                "列出场所",
                {"LLM_BINDING_HOST": "http://x", "LLM_BINDING_API_KEY": "k", "LLM_MODEL": "m"},
            )
        )
    assert err is None
    assert all(it["citation_verified"] for it in items)


def test_e6_model_invalid_json_rejected():

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "不是 JSON"}}]}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            return Response()

    with patch("httpx.AsyncClient", lambda **kwargs: Client()):
        _items, _logs, err = _run(
            extract_items_with_model(
                "原文",
                "抽取",
                {"LLM_BINDING_HOST": "http://x", "LLM_BINDING_API_KEY": "k", "LLM_MODEL": "m"},
            )
        )
    assert err == "model_failure:invalid_json"


def test_e6_model_fabricated_citation_rejected():

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                [{"text": "unsupported claim", "citation": {"quote": "编造的引句"}}]
                            )
                        }
                    }
                ]
            }

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            return Response()

    with patch("httpx.AsyncClient", lambda **kwargs: Client()):
        _items, _logs, err = _run(
            extract_items_with_model(
                "实际原文",
                "列出条目",
                {"LLM_BINDING_HOST": "http://x", "LLM_BINDING_API_KEY": "k", "LLM_MODEL": "m"},
            )
        )
    assert err is not None and "fabricated_citation" in err


# ==========================================================================
# E2/E4: table entry — chapter disambiguation + row coordinates
# ==========================================================================


class TableConn:
    def __init__(self, doc_name="fixture.pdf"):
        self._doc = doc_name

    async def fetchval(self, sql, *args):
        return self._doc

    async def fetchrow(self, sql, *args):
        return None

    async def fetch(self, sql, *args):
        if "source_units" in sql:
            return [
                dict(
                    unit_id="tb-x",
                    unit_order=1,
                    table_seq=1,
                    caption="表 1 项目",
                    heading="4",
                    locator=json.dumps({"blockid": "b"}),
                ),
            ]
        return [{"chunk_id": "c"}]


def _table_fixture(tmp_path: Path, table_html: str):
    root = tmp_path / "fixture.pdf.parsed"
    root.mkdir()
    (root / "fixture.tables.json").write_text(
        json.dumps({"tables": {"tb-x": {"content": table_html}}}), encoding="utf-8"
    )
    return root


def test_e3_unnumbered_table_entry_yields_rows_and_citations(tmp_path):
    html = (
        "<table><tr><th>项目</th><th>限值</th></tr>"
        "<tr><td>pH</td><td>6～9</td></tr><tr><td>总汞</td><td>0.05</td></tr></table>"
    )
    _table_fixture(tmp_path, html)
    with (
        patch("env_rag_final.enumerate_.table_enum.check_stale", _current),
        patch.object(audit_identity, "PARSED_ROOT", tmp_path),
    ):
        result = _run(enumerate_table(TableConn(), "default", "d", "1", parsed_root=tmp_path))
    assert result.coverage_status == "complete"
    assert len(result.items) == 2, "pH and 总汞 rows are data rows"
    cit = result.items[0]["citation"]
    assert cit["fragment_index"] == 0 and cit["row_in_fragment"] >= 0
    assert cit["table_id"] == "tb-x" and cit["doc_id"] == "d" and cit["workspace"] == "default"


def test_e3_empty_table_html_is_ambiguous_not_complete(tmp_path):
    _table_fixture(tmp_path, "")
    with (
        patch("env_rag_final.enumerate_.table_enum.check_stale", _current),
        patch.object(audit_identity, "PARSED_ROOT", tmp_path),
    ):
        result = _run(enumerate_table(TableConn(), "default", "d", "1", parsed_root=tmp_path))
    assert result.coverage_status == "ambiguous"
    assert result.fail_stage == "ambiguous"
    result.validate()  # ambiguous coverage is a valid, non-complete outcome


def test_r2_row_coordinates_are_raw_grid_indices(tmp_path):
    """R2: row_in_fragment must point at the RAW grid row (header offset kept),
    so an independent re-read of the fragment at that index yields the cells."""
    html = (
        "<table><tr><th>序号</th><th>污染物</th></tr>"
        "<tr><td>1</td><td>总汞</td></tr><tr><td>2</td><td>总镉</td></tr></table>"
    )
    _table_fixture(tmp_path, html)
    with (
        patch("env_rag_final.enumerate_.table_enum.check_stale", _current),
        patch.object(audit_identity, "PARSED_ROOT", tmp_path),
    ):
        result = _run(enumerate_table(TableConn(), "default", "d", "1", parsed_root=tmp_path))
    # raw grid: row 0 = header, row 1 = 总汞, row 2 = 总镉
    tables = json.loads((tmp_path / "fixture.pdf.parsed" / "fixture.tables.json").read_text())[
        "tables"
    ]
    from env_rag_final.enumerate_.tables import read_html_table as rht

    raw = rht(tables["tb-x"]["content"])
    for it in result.items:
        cit = it["citation"]
        raw_row = raw[cit["row_in_fragment"]]
        assert raw_row == it["cells"], (
            f"citation row {cit['row_in_fragment']} must re-read to the item cells"
        )


def test_e4_row_citations_point_to_real_fragments(tmp_path):
    html = (
        "<table><tr><th>序号</th><th>污染物</th></tr>"
        "<tr><td>1</td><td>总汞</td></tr><tr><td>2</td><td>总镉</td></tr></table>"
    )
    _table_fixture(tmp_path, html)
    with (
        patch("env_rag_final.enumerate_.table_enum.check_stale", _current),
        patch.object(audit_identity, "PARSED_ROOT", tmp_path),
    ):
        result = _run(enumerate_table(TableConn(), "default", "d", "1", parsed_root=tmp_path))
    assert result.coverage_status == "complete"
    fis = {it["citation"]["fragment_index"] for it in result.items}
    assert fis == {0}, "single physical fragment: all row citations bind fragment 0"
    ris = [it["citation"]["row_in_fragment"] for it in result.items]
    assert ris == sorted(ris) and len(set(ris)) == len(ris), "row coordinates unique and ordered"
    # fragment_index must never exceed the physical fragment count
    assert all(it["citation"]["fragment_index"] < result.members_total for it in result.items)
