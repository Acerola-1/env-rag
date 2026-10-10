"""Phase 1 isolated tests — corrected per structure review S1–S7.

Every fix is verified by a behavior counterexample reproducing the exact
review finding (offline / fake connections / tmp fixtures). No real database
writes, no modifications to public objects or corpus artifacts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from env_rag_final.catalog import metadata
from env_rag_final.catalog import schema as cat_schema
from env_rag_final.catalog import scopes as scopes_mod
from env_rag_final.catalog import source as source_mod
from env_rag_final.catalog import units as units_mod


def _run(coro):
    import asyncio

    return asyncio.run(coro)


class Row(dict):
    def __getitem__(self, key):
        return super().__getitem__(key)


# ==========================================================================
# S1: schema ownership — rejects before ANY SQL executes
# ==========================================================================


class RecordingConn:
    """Captures executed SQL and query order; emulates schema_migrations."""

    def __init__(self, schema_exists=False, foreign_tables=0):
        self.executed: list[str] = []  # DDL statements (execute calls)
        self.queried: list[str] = []  # SELECT statements (fetch/fetchval calls)
        self._migrated: set[str] = set()
        self.schema_exists = schema_exists
        self.foreign_tables = foreign_tables

    class _Tx:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    def transaction(self):
        return self._Tx()

    async def execute(self, sql, *args):
        self.executed.append(" ".join(sql.split()))
        if "INSERT INTO env_rag.schema_migrations" in sql and args:
            self._migrated.add(args[0])
        return "OK"

    def _route(self, sql):
        flat = " ".join(sql.split())
        self.queried.append(flat)
        if "FROM env_rag.schema_migrations" in flat:
            return [{"name": n} for n in sorted(self._migrated)]
        if "information_schema.schemata" in flat:
            return [{"count": 1 if self.schema_exists else 0}]
        if "information_schema.tables" in flat:
            return [{"count": self.foreign_tables}]
        return []

    async def fetch(self, sql, *args):
        return self._route(sql)

    async def fetchval(self, sql, *args):
        rows = await self.fetch(sql, *args)
        return rows[0]["count"] if rows else 0


def test_s1_schema_guard_rejects_public_and_injection_without_sql():
    conn = RecordingConn()
    for bad in (
        "public",
        "pg_catalog",
        "information_schema",
        "pg_toast",
        "env_rag; DROP SCHEMA x",
        "env_rag ",
        '"env_rag"',
        "Env_Rag",
        "",
    ):
        with pytest.raises(cat_schema.MigrationError, match="no SQL was executed"):
            cat_schema.validate_schema_name(bad)
    assert conn.executed == [], "rejected names must not reach the database"


def test_s1_teardown_aborts_on_foreign_tables_before_drop():
    conn = RecordingConn(schema_exists=True, foreign_tables=1)
    with pytest.raises(cat_schema.MigrationError, match="ownership cannot be proven"):
        _run(cat_schema.teardown(conn))
    assert not any("DROP SCHEMA" in s for s in conn.executed), "no DROP before ownership proof"


def test_s1_teardown_happy_path_drop_after_ownership_proof():
    conn = RecordingConn(schema_exists=True, foreign_tables=0)
    _run(cat_schema.teardown(conn))
    drop_idx = next(i for i, s in enumerate(conn.executed) if "DROP SCHEMA" in s)
    # order: schemata existence → tables ownership → DROP
    assert conn.queried[0].startswith("SELECT count(*) FROM information_schema.schemata")
    assert "information_schema.tables" in conn.queried[1], "ownership verified before drop"
    assert drop_idx == 0, "DROP is the only executed statement, after both checks"


def test_s1_migration_ddl_never_references_public_or_lightrag():
    conn = RecordingConn()
    applied = _run(cat_schema.migrate(conn))
    assert applied
    for sql in conn.executed:
        lowered = sql.lower()
        if any(op in lowered for op in ("create table", "create index", "create schema", "drop")):
            assert "env_rag" in lowered, sql
            assert "public." not in lowered, sql
            assert "lightrag" not in lowered, sql


def test_s1_migration_rerun_is_noop():
    conn = RecordingConn()
    first = _run(cat_schema.migrate(conn))
    second = _run(cat_schema.migrate(conn))
    assert first and not second


def test_s1_missing_schema_teardown_refuses():
    conn = RecordingConn(schema_exists=False)
    with pytest.raises(cat_schema.MigrationError, match="does not exist"):
        _run(cat_schema.teardown(conn))


# ==========================================================================
# S3: metadata — replacement lines, reference-only docs, cover window
# ==========================================================================


def test_s3_gb18466_partial_replace_line_is_not_title():
    content = (
        "{{LRdoc}}# 中 华 人 民 共 和 国 国 家 环 境 保 护 标 准\n"
        "GB 18466—2005\n"
        "部分代替 GB 8978—1996\n"
        "代替 GB 18466-2002\n"
        "# 医疗机构水污染物排放标准\n"
        "Discharge standard of water pollutants for medical organization\n"
        "2005-05-08 发布 2005-07-01 实施\n"
    )
    rec = metadata.extract_document_metadata("water-09_…GB18466-2005.pdf", content)
    assert rec["title"] == "医疗机构水污染物排放标准", rec
    assert rec["self_code"] == "GB18466"
    assert rec["self_code_version"] == "2005"


def test_s3_reference_only_doc_has_no_self_code():
    content = "# 本文件\n依据 GB 3838-2002 执行\n引用 GB/T 18883-2002"
    rec = metadata.extract_document_metadata("unknown-doc.pdf", content)
    assert rec["self_code"] is None
    assert "self_code" in rec["unknown_fields"]
    assert "GB3838-2002" in rec["referenced_codes"]
    assert "GBT18883-2002" in rec["referenced_codes"]
    prov = rec["field_provenance"]["self_code"]
    assert prov["confidence"] == "unknown"
    assert "cites other standards" in prov.get("note", "")


def test_s3_cover_replacement_line_not_self_code():
    content = "# 某标准\nGB 9999—2001\n代替 GB 8978—88\n正文"
    rec = metadata.extract_document_metadata("x.pdf", content)
    assert rec["self_code"] == "GB9999"
    assert rec["self_code_version"] == "2001"
    assert "GB8978-88" in rec["referenced_codes"]


def test_s3_provenance_has_line_quote_confidence():
    content = "# 医疗机构水污染物排放标准\n2005-05-08 发布 2005-07-01 实施\nGB 18466—2005"
    rec = metadata.extract_document_metadata("water-09_….pdf", content)
    tp = rec["field_provenance"]["title"]
    assert tp["confidence"] == "extracted" and "quote" in tp and "line" in tp
    assert rec["field_provenance"]["publish_date"]["quote"].endswith("发布")
    assert rec["field_provenance"]["implement_date"]["quote"].endswith("实施")


def test_s3_dates_only_from_cover_window_not_body():
    filler = "\n".join(f"填充行 {i}" for i in range(60))
    content = "# 某标准\n" + filler + "\n2020-01-01 发布 2021-01-01 实施\nGB 1234—2020"
    rec = metadata.extract_document_metadata("x.pdf", content)
    assert rec["publish_date"] is None and rec["implement_date"] is None
    assert "publish_date" in rec["unknown_fields"]


def test_s3_dates_separated_and_stats_period_unknown():
    content = "# 标准名\n2012-02-29 发布 2016-01-01 实施\nGB 1234—2012"
    rec = metadata.extract_document_metadata("x.pdf", content)
    assert rec["publish_date"] == "2012-02-29"
    assert rec["implement_date"] == "2016-01-01"
    assert "stats_period" in rec["unknown_fields"]


def test_s3_unknown_fields_recorded_not_invented():
    rec = metadata.extract_document_metadata("unknown-doc.pdf", "# 只有标题\n正文没有编号")
    assert "self_code" in rec["unknown_fields"]
    assert "publish_date" in rec["unknown_fields"]
    assert "implement_date" in rec["unknown_fields"]
    assert "stats_period" in rec["unknown_fields"]


def test_s3_two_digit_year_code_line_is_not_title():
    """air-06 real case: "GB 14554—93" standalone line is a code, not a title."""
    content = (
        "# 中华人民共和国国家标准\nGB 14554—93\n\n# 恶臭污染物排放标准\n"
        "1993-08-06 发布 1994-01-15 实施"
    )
    rec = metadata.extract_document_metadata("air-06_….pdf", content)
    assert rec["title"] == "恶臭污染物排放标准"
    assert rec["self_code"] == "GB14554"
    assert rec["self_code_version"] == "93"


def test_s3_replacement_line_without_space_is_not_title():
    """water-14 real case: "代替GB 4287—2012、GB 28936—2012等"."""
    content = (
        "# 中 华 人 民 共 和 国 国 家 标 准\nGB 4287—2026\n"
        "代替GB 4287—2012、GB 28936—2012等\n\n# 纺织工业水污染物排放标准"
    )
    rec = metadata.extract_document_metadata("water-14_….pdf", content)
    assert rec["title"] == "纺织工业水污染物排放标准"
    assert rec["self_code"] == "GB4287" and rec["self_code_version"] == "2026"


def test_s5_recipe_bump_required_for_algorithm_change():
    """The S5 trap itself: metadata algorithm changed ⇒ recipe must change."""
    from env_rag_final.catalog.builder import RECIPE_ID, build_identity

    # v3 marks the corrected metadata pass; skipping a rebuild with the same
    # recipe would reuse stale metadata rows.
    assert RECIPE_ID != "phase-1-v2-hierarchical-scopes-span-guard-strict-table-ids"
    assert build_identity("fp", RECIPE_ID) != build_identity(
        "fp", "phase-1-v2-hierarchical-scopes-span-guard-strict-table-ids"
    )


def test_s3_gb8978_title_and_code():
    content = (
        "{{LRdoc}}# 中 华 人 民 共 和 国 国 家 标 准\nGB 8978—1996\n代替 GB 8978—88\n"
        "# 污水综合排放标准\nIntegrated wastewater discharge standard\n正文"
    )
    rec = metadata.extract_document_metadata("water-11_….pdf", content)
    assert rec["title"] == "污水综合排放标准"
    assert rec["self_code"] == "GB8978" and rec["self_code_version"] == "1996"


# ==========================================================================
# S2: hierarchical scopes
# ==========================================================================


def _blocks_like_gb3095_ch4() -> list[dict]:
    return [
        {
            "blockid": "b4intro",
            "heading": "4 环境空气功能区分类和质量要求",
            "level": 2,
            "content": "## 4 环境空气功能区分类和质量要求\n引导正文",
        },
        {"blockid": "b41", "heading": "4.1 环境空气功能区分类", "level": 2, "content": "## 4.1 …"},
        {
            "blockid": "b42",
            "heading": "4.2 环境空气功能区质量要求",
            "level": 2,
            "content": "## 4.2 …",
        },
        {"blockid": "b5", "heading": "5 监测", "level": 2, "content": "## 5 监测"},
    ]


def test_s2_parent_chapter_includes_sub_scope_members():
    scopes = scopes_mod.build_scopes("doc-x", "snap", _blocks_like_gb3095_ch4())
    ch4 = next(s for s in scopes if s["number"] == "4")
    assert ch4["confirm_status"] == "confirmed"
    members = set(ch4["_members"])
    assert {"b4intro", "b41", "b42"} <= members, "chapter 4 must contain 4.1/4.2 blocks"
    assert "b5" not in members, "chapter 4 must exclude chapter 5"
    ch41 = next(s for s in scopes if s["number"] == "4.1")
    assert ch41["parent_scope_id"] == ch4["scope_id"]
    assert ch41["_members"] == ["b41"], "leaf boundary stays exact"


def test_s2_parent_scope_created_even_without_heading_block():
    blocks = [
        {"blockid": "p41", "heading": "4.1 子范围", "level": 2, "content": "## 4.1"},
        {"blockid": "other", "heading": "9 其他", "level": 2, "content": "## 9"},
    ]
    scopes = scopes_mod.build_scopes("doc-x", "snap", blocks)
    parent = next(s for s in scopes if s["number"] == "4")
    assert parent["note"] and "聚合" in parent["note"]
    assert parent["_members"] == ["p41"]


def test_s2_deep_chain_without_intermediate_headings():
    """Real-data case (GB4915 amendment): 4.2.1.1 headings with no 4.2 block."""
    blocks = [
        {"blockid": "x1", "heading": "4.2.1.1 矿山开采", "level": 3, "content": "x"},
        {"blockid": "x2", "heading": "4.2.1.2 物料储存", "level": 3, "content": "x"},
    ]
    scopes = scopes_mod.build_scopes("doc-h", "snap", blocks)
    numbers = {s["number"] for s in scopes if s["number"]}
    assert {"4.2.1.1", "4.2.1.2", "4.2.1", "4.2", "4"} <= numbers
    chain42 = next(s for s in scopes if s["number"] == "4.2")
    assert chain42["note"] and "聚合" in chain42["note"]
    assert set(chain42["_members"]) == {"x1", "x2"}
    ch4 = next(s for s in scopes if s["number"] == "4")
    assert set(ch4["_members"]) == {"x1", "x2"}


def test_s2_gb18466_single_block_cross_chunk_unchanged():
    blocks = [
        {
            "blockid": "b41",
            "heading": "4.1 污水排放要求",
            "level": 2,
            "content": "## 4.1 污水排放要求\n4.1.1 …\n4.1.2 …\n4.1.3 …\n4.1.4 …\n4.1.5 …\n4.1.6 …",
        },
        {"blockid": "b42", "heading": "4.2 废气排放要求", "level": 2, "content": "## 4.2"},
    ]
    scopes = scopes_mod.build_scopes("doc-gb18466", "snap", blocks)
    s41 = next(s for s in scopes if s["number"] == "4.1")
    assert s41["confirm_status"] == "confirmed", "single block spanning chunks stays confirmed"
    assert s41["_members"] == ["b41"]


def test_s2_requires_span_persisted_not_just_warning():
    big = {
        "blockid": "big",
        "heading": "Annex 4 Sanitation estimates",
        "level": 2,
        "content": "Annex 4\n2.1.1 某条款\n" + "x" * 60_000,
    }
    scopes = scopes_mod.build_scopes("doc-who", "snap", [big])
    annex = next(s for s in scopes if s["title"].startswith("Annex 4"))
    updated = scopes_mod.persist_span_requirements("doc-who", "snap", [big], scopes, {"big": 273})
    assert annex in updated
    assert annex["confirm_status"] == "requires_span"
    assert "字符跨度" in annex["note"] and "273" in annex["note"]


def test_s2_small_block_never_requires_span():
    blocks = [{"blockid": "s", "heading": "2.1 小节", "level": 2, "content": "正文"}]
    scopes = scopes_mod.build_scopes("doc-y", "snap", blocks)
    assert not scopes_mod.persist_span_requirements("doc-y", "snap", blocks, scopes, {"s": 273})
    assert scopes[0]["confirm_status"] == "confirmed"


# ==========================================================================
# S7: strict inline table id matching
# ==========================================================================


def test_s7_prose_mention_does_not_link():
    assert units_mod.extract_table_ids("见表 tb-abc-0001 的说明（纯文字提及）") == set()


def test_s7_prefix_similar_id_kept_full_but_exact_compare_rejects():
    ids = units_mod.extract_table_ids('<table id="tb-abc-00011">x</table>')
    assert ids == {"tb-abc-00011"}  # full value; 'tb-abc-0001' not in it


def test_s7_real_single_and_double_quoted_attrs_match():
    assert units_mod.extract_table_ids('<td>前文</td><table id="tb-abc-0001">') == {"tb-abc-0001"}
    assert units_mod.extract_table_ids("<table id='tb-abc-0002'>") == {"tb-abc-0002"}


def test_s7_malformed_fragment_yields_no_link():
    assert units_mod.extract_table_ids("<table id=tb-abc-0003") == set()


def test_s7_link_requires_exact_attribute_match(fixture_parsed: Path):
    chunks = [
        _chunk(
            "doc-abc-chunk-009",
            9,
            "{}",
            content='正文提到 tb-doc-abc-0001 和 <table id="tb-doc-abc-00011">',
        ),
    ]
    units, links = units_mod.build_units_and_links(
        "doc-abc", "doc-abc_test.pdf", "snap1", chunks, fixture_parsed
    )
    assert [lk for lk in links if lk["match_basis"] == "inline_table_id"] == []


# ==========================================================================
# S6: adapter composite-key + order gaps + pagination epoch
# ==========================================================================


def test_s6_same_doc_id_in_two_workspaces_resolves_both(monkeypatch):
    adapter = source_mod.SourceAdapter({})

    async def fake_read_one(stmt, *args, fetch="val"):
        if "workspace=$1 AND id=$2" in " ".join(stmt.split()):
            return 1
        return None

    monkeypatch.setattr(adapter, "_read_one", fake_read_one)
    assert _run(adapter.doc_exists("ws-a", "doc-1")) is True
    assert _run(adapter.doc_exists("ws-b", "doc-1")) is True


def test_s6_wrong_workspace_diagnosed_after_composite_miss(monkeypatch):
    adapter = source_mod.SourceAdapter({})

    async def fake_read_one(stmt, *args, fetch="val"):
        flat = " ".join(stmt.split())
        if "workspace=$1 AND id=$2" in flat:
            return 0
        if "workspace<>$2" in flat:
            return "other-ws"
        return None

    monkeypatch.setattr(adapter, "_read_one", fake_read_one)
    with pytest.raises(source_mod.CrossWorkspaceError):
        _run(adapter.doc_exists("ws-x", "doc-1"))


def test_s6_missing_doc_after_composite_and_elsewhere_miss(monkeypatch):
    adapter = source_mod.SourceAdapter({})

    async def fake_read_one(stmt, *args, fetch="val"):
        return 0 if fetch == "val" else None

    monkeypatch.setattr(adapter, "_read_one", fake_read_one)
    assert _run(adapter.doc_exists("ws-a", "doc-404")) is False


def test_s6_order_gap_detected_not_just_null_dup():
    with pytest.raises(source_mod.OrderAnomalyError, match="contiguous"):
        source_mod.SourceAdapter._check_orders([0, 1, 3])
    with pytest.raises(source_mod.OrderAnomalyError, match="duplicate"):
        source_mod.SourceAdapter._check_orders([0, 1, 1])
    with pytest.raises(source_mod.OrderAnomalyError, match="NULL"):
        source_mod.SourceAdapter._check_orders([0, None, 2])
    source_mod.SourceAdapter._check_orders([0, 1, 2])


def test_s6_pagination_epoch_mismatch_raises_stale():
    adapter = source_mod.SourceAdapter({})

    class FakeConn:
        class _Tx:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *exc):
                return False

        def transaction(self, **kw):
            return self._Tx()

        async def execute(self, *a):
            return "OK"

        async def fetchval(self, sql, *a):
            return "epoch-2"

        async def fetchrow(self, sql, *a):
            return {"n": 1}

        async def fetch(self, sql, *a):
            return []

        async def close(self):
            return None

    class FakeSession:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, *exc):
            return False

    async def session1():
        return FakeConn()

    adapter._session = session1  # noqa: SLF001
    with pytest.raises(source_mod.SourceChangedError):
        _run(adapter.read_chunks_ordered("default", "doc-a", expected_epoch="epoch-1"))


def test_s6_pagination_returns_epoch_for_chained_reads():
    adapter = source_mod.SourceAdapter({})

    class FakeConn:
        class _Tx:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *exc):
                return False

        def transaction(self, **kw):
            return self._Tx()

        async def execute(self, *a):
            return "OK"

        async def fetchval(self, sql, *a):
            return "epoch-1"

        async def fetchrow(self, sql, *a):
            return {"n": 1}

        async def fetch(self, sql, *a):
            return []

        async def close(self):
            return None

    class FakeSession:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, *exc):
            return False

    async def session2():
        return FakeConn()

    adapter._session = session2  # noqa: SLF001
    page = _run(adapter.read_chunks_ordered("default", "doc-a"))
    assert len(page.snapshot_epoch) == 64
    continuation = _run(
        adapter.read_chunks_ordered(
            "default",
            "doc-a",
            offset=10,
            expected_epoch=page.snapshot_epoch,
        )
    )
    assert continuation.snapshot_epoch == page.snapshot_epoch


# ==========================================================================
# S4/S5: builder guard and identity
# ==========================================================================


def test_s5_build_identity_binds_recipe():
    from env_rag_final.catalog.builder import RECIPE_ID, build_identity

    a = build_identity("fp-1", RECIPE_ID)
    b = build_identity("fp-1", "other-recipe")
    assert a != b, "recipe change must produce a new build identity"
    assert build_identity("fp-1") == build_identity("fp-1")


def test_s5_recipe_constant_changed_for_correction():
    from env_rag_final.catalog.builder import RECIPE_ID

    assert RECIPE_ID.startswith("phase-1-v"), "recipe is versioned (currently v3)"


def test_s4_derive_fails_hard_on_missing_sources():
    from env_rag_final.catalog import builder as builder_mod

    rows = {
        "docs": [
            Row(
                id="doc-x",
                doc_name="missing.pdf",
                content="c",
                content_hash="h",
                meta=None,
                sidecar_location=None,
                parse_format="lightrag",
                parse_engine="mineru",
                chunk_options={},
            )
        ],
        "chunks": [],
        "statuses": [],
    }
    with pytest.raises(builder_mod.BuildVerificationError, match="no readable parsed source"):
        builder_mod._derive(rows, "snap", Path("/nonexistent-root-xyz"), "default")


def test_s4_verify_rejects_links_to_unknown_chunks():
    from env_rag_final.catalog import builder as builder_mod

    class Conn:
        class _Tx:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *exc):
                return False

        def transaction(self):
            return self._Tx()

        async def execute(self, *a):
            return "OK"

        async def fetchval(self, sql, *a):
            return 0

        async def fetch(self, sql, *a):
            return [{"unit_id": "u1", "chunk_id": "doc-a-chunk-999", "doc_id": "doc-a"}]

    rows = {
        "chunks": [
            Row(
                id="doc-a-chunk-000",
                full_doc_id="doc-a",
                chunk_order_index=0,
                tokens=1,
                content="c",
                heading=None,
                sidecar="{}",
            )
        ]
    }
    with pytest.raises(builder_mod.BuildVerificationError, match="links_to_unknown_chunks=1"):
        _run(builder_mod._verify(Conn(), "snap", "default", rows))


# ==========================================================================
# units fixtures
# ==========================================================================


@pytest.fixture()
def fixture_parsed(tmp_path: Path) -> Path:
    d = tmp_path / "doc-abc_test.pdf.parsed"
    d.mkdir()
    blocks = [
        {"type": "meta", "doc_id": "doc-abc", "blocks": 3},
        {
            "type": "content",
            "blockid": "b1",
            "heading": "中华人民共和国国家标准",
            "level": 1,
            "parent_headings": [],
            "content": "# 封面",
        },
        {
            "type": "content",
            "blockid": "b2",
            "heading": "3 术语和定义",
            "level": 2,
            "parent_headings": ["x"],
            "content": "## 3 术语和定义\n3.1 甲\n3.2 乙",
        },
        {
            "type": "content",
            "blockid": "b3",
            "heading": "3.3 丙",
            "level": 2,
            "parent_headings": ["x"],
            "content": '## 3.3 丙 <table id="tb-doc-abc-0001">',
        },
    ]
    (d / "doc-abc_test.pdf.blocks.jsonl").write_text(
        "\n".join(json.dumps(b, ensure_ascii=False) for b in blocks), encoding="utf-8"
    )
    (d / "doc-abc_test.pdf.tables.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "tables": {
                    "tb-doc-abc-0001": {
                        "id": "tb-doc-abc-0001",
                        "blockid": "b3",
                        "caption": "表 1 示例",
                        "dimension": [2, 3],
                        "heading": "3.3 丙",
                        "content": "<table></table>",
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return d


def _chunk(cid, idx, sidecar, content=""):
    return {
        "id": cid,
        "full_doc_id": "doc-abc",
        "chunk_order_index": idx,
        "tokens": 10,
        "content": content,
        "heading": None,
        "sidecar": sidecar,
    }


def test_units_links_many_to_many(fixture_parsed: Path):
    chunks = [
        _chunk("doc-abc-chunk-000", 0, json.dumps({"refs": [{"id": "b1", "type": "block"}]})),
        _chunk("doc-abc-chunk-001", 1, "{}", content='has <table id="tb-doc-abc-0001"> inline'),
        _chunk(
            "doc-abc-chunk-002",
            2,
            json.dumps({"refs": [{"id": "b2", "type": "block"}, {"id": "b3", "type": "block"}]}),
        ),
    ]
    units, links = units_mod.build_units_and_links(
        "doc-abc", "doc-abc_test.pdf", "snap1", chunks, fixture_parsed
    )
    assert {u["unit_kind"] for u in units} == {"block", "table"}
    link_pairs = {(lk["unit_id"], lk["chunk_id"], lk["match_basis"]) for lk in links}
    assert ("b3", "doc-abc-chunk-002", "sidecar_ref") in link_pairs
    assert ("tb-doc-abc-0001", "doc-abc-chunk-001", "inline_table_id") in link_pairs
    chunks2 = chunks + [
        _chunk("doc-abc-chunk-003", 3, json.dumps({"refs": [{"id": "b2", "type": "block"}]}))
    ]
    _u2, links2 = units_mod.build_units_and_links(
        "doc-abc", "doc-abc_test.pdf", "snap1", chunks2, fixture_parsed
    )
    assert {lk["chunk_id"] for lk in links2 if lk["unit_id"] == "b2"} == {
        "doc-abc-chunk-002",
        "doc-abc-chunk-003",
    }


def test_units_table_basis_inline_only(fixture_parsed: Path):
    chunks = [
        _chunk("doc-abc-chunk-001", 1, "{}", content='has <table id="tb-doc-abc-0001"> inline')
    ]
    units, links = units_mod.build_units_and_links(
        "doc-abc", "doc-abc_test.pdf", "snap1", chunks, fixture_parsed
    )
    table_links = [lk for lk in links if lk["unit_id"] == "tb-doc-abc-0001"]
    assert table_links and all(lk["match_basis"] == "inline_table_id" for lk in table_links)


def test_scopes_leaf_membership_from_blocks(fixture_parsed: Path):
    _meta, blocks = units_mod.parse_blocks(fixture_parsed)
    scopes = scopes_mod.build_scopes("doc-abc", "snap", blocks)
    clause_scopes = [s for s in scopes if s["scope_kind"] == "clause"]
    numbers = {s["number"] for s in clause_scopes}
    assert "3" in numbers and "3.3" in numbers
    scope3 = next(s for s in clause_scopes if s["number"] == "3")
    # scope 3.3 is its child: parent aggregation includes b3 (source order)
    assert scope3["_members"] == ["b2", "b3"]
    leaf33 = next(s for s in clause_scopes if s["number"] == "3.3")
    assert leaf33["_members"] == ["b3"], "leaf boundary stays exact"


def test_content_epoch_stable_across_transactions_and_sensitive_to_source():
    import copy

    class Conn:
        def __init__(self):
            self.doc = {"id": "doc-a", "content": "body", "content_hash": "stored"}
            self.chunks = [
                {
                    "id": "chunk-a",
                    "chunk_order_index": 0,
                    "content": "text",
                    "sidecar": {"refs": [{"id": "b1"}]},
                }
            ]

        async def fetchrow(self, *args):
            return self.doc

        async def fetch(self, *args):
            return self.chunks

    first, second = Conn(), Conn()
    token = _run(source_mod.SourceAdapter._content_epoch(first, "default", "doc-a"))
    assert token == _run(source_mod.SourceAdapter._content_epoch(second, "default", "doc-a"))
    for field, value in (
        ("content", "changed"),
        ("chunk_order_index", 1),
        ("sidecar", {"refs": [{"id": "b2"}]}),
    ):
        changed = Conn()
        changed.chunks = copy.deepcopy(first.chunks)
        changed.chunks[0][field] = value
        assert token != _run(source_mod.SourceAdapter._content_epoch(changed, "default", "doc-a"))
    second.doc["content"] = "new body"
    assert token != _run(source_mod.SourceAdapter._content_epoch(second, "default", "doc-a"))


def test_publish_failure_rolls_back_old_pointer_and_rows():
    import copy

    from env_rag_final.catalog.builder import _publish

    class Conn:
        def __init__(self):
            self.state = {"active": "old", "old_rows": True}
            self.events = []
            self.in_transaction = False

        def transaction(self):
            conn = self

            class Tx:
                async def __aenter__(self):
                    self.previous = copy.deepcopy(conn.state)
                    conn.in_transaction = True

                async def __aexit__(self, kind, *args):
                    if kind:
                        conn.state = self.previous
                    conn.in_transaction = False
                    return False

            return Tx()

        async def execute(self, sql, *args):
            assert self.in_transaction
            self.events.append(sql)
            if "pg_advisory_xact_lock" in sql:
                return
            if "status='active'" in sql and "finished_at" in sql:
                self.state["active"] = "new"
            if sql.startswith("DELETE FROM"):
                self.state["old_rows"] = False
                if "env_rag.scopes " in sql:
                    raise RuntimeError("fixture prune failure")

    conn = Conn()
    with pytest.raises(RuntimeError):
        _run(_publish(conn, "new", "new-snapshot", "default"))
    assert conn.state == {"active": "old", "old_rows": True}
    assert "pg_advisory_xact_lock" in conn.events[0]


def test_whole_build_lock_serializes_staging_and_releases_on_failure(monkeypatch):
    import asyncio

    from env_rag_final.catalog import builder

    async def scenario():
        lock = asyncio.Lock()
        events = []

        class Conn:
            def __init__(self, name):
                self.name = name

            async def execute(self, sql, *args):
                if "pg_advisory_unlock" in sql:
                    events.append((self.name, "unlock"))
                    lock.release()
                elif "pg_advisory_lock" in sql:
                    await lock.acquire()
                    events.append((self.name, "lock"))

        async def derive(conn, **kwargs):
            events.append((conn.name, "stage"))
            await asyncio.sleep(0)
            if conn.name == "first":
                raise RuntimeError("fixture failed build")
            events.append((conn.name, "publish"))
            return "complete"

        monkeypatch.setattr(builder, "_build_catalog_locked", derive)
        results = await asyncio.gather(
            builder.build_catalog(Conn("first")),
            builder.build_catalog(Conn("second")),
            return_exceptions=True,
        )
        assert isinstance(results[0], RuntimeError) and results[1] == "complete"
        assert events == [
            ("first", "lock"),
            ("first", "stage"),
            ("first", "unlock"),
            ("second", "lock"),
            ("second", "stage"),
            ("second", "publish"),
            ("second", "unlock"),
        ]

    _run(scenario())
