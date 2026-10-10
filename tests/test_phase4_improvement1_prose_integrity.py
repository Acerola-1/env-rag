"""Phase-4 improvement generation 1 (r2): prose scope integrity (I1).

Covers the production fixes with constructed positives/negatives and an
OFFLINE replay through the formal prose expansion entry — real parsed
sidecars are read-only inputs; there is NO network, NO model, NO database.

1. clause boundaries: an INDEPENDENT structure (table-kind unit, line-start
   <table>, pure table caption, appendix heading) ends a clause body — with
   the F3/F3-a attribution rule: a colon intro naming a 表/图 object keeps
   the table inside the clause (the announcement is looked up through the
   table's own title lines — a caption cannot reset it — and never crosses
   into the next independent clause); an announced-but-undecidable boundary
   surfaces partial with a warning instead of a silent complete;
2. cross-unit segments are declared in ASSEMBLED order with an explicit
   assembly_separator mapping; BOTH verifiers reconstruct only with the
   PROTOCOL join "\\n\\n" (F1) — a fabricated or non-string separator cannot
   manufacture source text;
3. both the generation-side verify_citations and the answer-side
   _reverify_prose_items re-read the WHOLE delivered text (whitespace
   collapsed, not stripped), and a numeric-span declaration keyed on key
   PRESENCE must be well-formed ints or it REFUSES instead of downgrading
   to quote-only (F2); the genuine quote-only model path is unchanged;
4. F4: replay INPUTS derive from the original question text (never from
   gold.expected_items — gold is post-hoc verification only), and every
   replayed question is checked ONE-TO-ONE by 编号+全文+来源 with missing /
   extra sets listed (no len>=3, no any-hit).

Evidence labels: [构造测试] uses tmp parsed fixtures; [原始产物离线读取] uses
the real __parsed__ sidecars + round-1 artifacts read-only; every assertion
drives the real pipeline functions (nothing is mocked to constant True).
"""

import asyncio
import json
import re
from pathlib import Path

import pytest

from env_rag_final import answer as an
from env_rag_final.audit import identity as sid
from env_rag_final.enumerate_.contract import EnumResult
from env_rag_final.enumerate_.prose_enum import (
    UnitText,
    bind_citations,
    extract_clauses_regex,
    structural_boundaries,
    structural_cut_positions,
    verify_citations,
)
from env_rag_final.search import expand


def run(coro):
    return asyncio.run(coro)


async def _current(*_a, **_kw):
    return {
        "state": "current",
        "active_snapshot_id": "snap-1",
        "catalog_snapshot_id": "snap-1",
        "stored_fingerprint": "fp",
    }


def _write_parsed(root: Path, doc_name: str, units: list[tuple[str, str]]) -> Path:
    pdir = root / f"{doc_name}.parsed"
    pdir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"type": "meta", "doc_id": doc_name})]
    for uid, text in units:
        lines.append(json.dumps({"type": "content", "blockid": uid, "content": text}))
    (pdir / "x.blocks.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return pdir


# ---------------------------------------------------------------------------
# 1. assembled order + explicit separator mapping [构造测试]
# ---------------------------------------------------------------------------


def _continuation_units():
    t1 = "5.1.1 第一条款内容。\n5.1.2 续文跨单元的前半部分"
    u1 = UnitText("u1", t1, [], {"blockid": "u1"}, 0, len(t1), False, "parsed_block")
    t2 = "后半部分在此结束并给出要求。\n5.2 下一条款开始"
    # the assembly joins units with "\n\n": u2 starts at len(u1)+2
    u2 = UnitText(
        "u2", t2, [], {"blockid": "u2"}, len(t1) + 2, len(t1) + 2 + len(t2), False, "parsed_block"
    )
    return [u1, u2]


def _bind_continuation(units):
    text = "\n\n".join(u.text for u in units)
    items = extract_clauses_regex(text, ["5.1.2"], hard_ends=structural_cut_positions(units, text))
    items = bind_citations(items, "default", "d", "snap-1", units)
    items = verify_citations(items, text, units)
    return items


def test_cross_unit_continuation_declares_assembled_order_and_separator():
    units = _continuation_units()
    items = _bind_continuation(units)
    assert len(items) == 1
    it = items[0]
    segs = it["citation"]["unit_segments"]
    # [构造测试] first unit has a NON-ZERO rel start, second starts at 0 — the
    # legacy rel_start sort would emit [u2,u1]; the contract is assembled order
    assert [s["unit_id"] for s in segs] == ["u1", "u2"]
    assert it["citation"]["assembly_separator"] == "\n\n"
    assert it["citation_verified"] is True
    # independent re-read across the real gap reproduces the whole text
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        pdir = _write_parsed(Path(td), "fixture.pdf", [(u.unit_id, u.text) for u in units])
        problems = an._reverify_prose_items([it], pdir)
    assert problems == []
    assert it["citation_reverified"] is True


def test_permuted_duplicated_and_short_segments_are_detected():
    units = _continuation_units()
    it = _bind_continuation(units)[0]

    permuted = json.loads(json.dumps(it))
    permuted["citation"]["unit_segments"] = list(reversed(permuted["citation"]["unit_segments"]))
    text_assembled = "\n\n".join(u.text for u in units)
    out = verify_citations([permuted], text_assembled, units)
    assert out[0]["citation_verified"] is False  # declared order refuses

    dup = json.loads(json.dumps(it))
    dup["citation"]["unit_segments"].append(dup["citation"]["unit_segments"][1])
    out2 = verify_citations([dup], text_assembled, units)
    assert out2[0]["citation_verified"] is False

    missing = json.loads(json.dumps(it))
    missing["citation"]["unit_segments"] = missing["citation"]["unit_segments"][:1]
    out3 = verify_citations([missing], text_assembled, units)
    assert out3[0]["citation_verified"] is False

    # the independent reader refuses the same three shapes
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        pdir = _write_parsed(Path(td), "fixture.pdf", [(u.unit_id, u.text) for u in units])
        for bad in (permuted, dup, missing):
            item = json.loads(json.dumps(bad))
            probs = an._reverify_prose_items([item], pdir)
            assert probs and item["citation_reverified"] is False


def test_real_quote_cannot_back_appended_fabricated_tail():
    """[构造测试] The ≤120-char quote stays verbatim and inside the span; only
    the FULL-text re-read can catch the appended unsourced sentence."""
    units = _continuation_units()
    it = _bind_continuation(units)[0]
    bad = json.loads(json.dumps(it))
    bad["text"] += "停车场允许无条件排放污水。"
    text_assembled = "\n\n".join(u.text for u in units)
    assert bad["citation"]["quote"] in text_assembled  # quote alone looks fine
    assert verify_citations([bad], text_assembled, units)[0]["citation_verified"] is False

    import tempfile

    with tempfile.TemporaryDirectory() as td:
        pdir = _write_parsed(Path(td), "fixture.pdf", [(u.unit_id, u.text) for u in units])
        item2 = json.loads(json.dumps(bad))
        probs = an._reverify_prose_items([item2], pdir)
        assert probs and item2["citation_reverified"] is False


def test_wrong_coordinates_refuse_on_both_sides():
    units = _continuation_units()
    it = _bind_continuation(units)[0]
    shifted = json.loads(json.dumps(it))
    for seg in shifted["citation"]["unit_segments"]:
        seg["rel_start"] += 1
    text_assembled = "\n\n".join(u.text for u in units)
    assert verify_citations([shifted], text_assembled, units)[0]["citation_verified"] is False

    import tempfile

    with tempfile.TemporaryDirectory() as td:
        pdir = _write_parsed(Path(td), "fixture.pdf", [(u.unit_id, u.text) for u in units])
        item2 = json.loads(json.dumps(shifted))
        probs = an._reverify_prose_items([item2], pdir)
        assert probs and item2["citation_reverified"] is False


# ---------------------------------------------------------------------------
# 2. last clause must not swallow independent tables [构造测试]
# ---------------------------------------------------------------------------


def test_last_clause_ends_at_line_start_table_not_eof():
    u = UnitText(
        "u1",
        '5.1.1 要求一。\n5.1.2 要求二。\n<table id="tb-x" format="html"><tr><td>1</td></tr></table>',
        [],
        {"blockid": "u1"},
        0,
        60,
        False,
        "parsed_block",
    )
    u.char_end = len(u.text)
    text = u.text
    items = extract_clauses_regex(text, hard_ends=structural_cut_positions([u], text))
    by = {it["clause"]: it for it in items}
    assert "5.1.2" in by
    assert "<table" not in by["5.1.2"]["text"]
    assert by["5.1.2"]["text"] == "5.1.2 要求二。"
    assert by["5.1.1"]["text"] == "5.1.1 要求一。"
    # the cut keeps the span re-readable (body ⊆ declared span)
    bound = verify_citations(
        bind_citations([dict(it) for it in items], "default", "d", "s", [u]), text, [u]
    )
    assert all(b["citation_verified"] for b in bound)


def test_table_kind_unit_and_caption_are_hard_ends_but_inline_html_survives():
    u = UnitText(
        "u1",
        "5.1.1 浓度按 c<sub>x</sub> 计算并执行表1的规定（引用不算边界）。\n表 1\n<table id=t>…",
        [],
        {"blockid": "u1"},
        0,
        60,
        False,
        "parsed_block",
    )
    u.char_end = len(u.text)
    cuts = structural_cut_positions([u], u.text)
    items = extract_clauses_regex(u.text, hard_ends=cuts)
    body = items[0]["text"]
    assert "c<sub>x</sub>" in body  # 内嵌证据不被删
    assert "表1的规定" in body  # 句中引用不是行首表题
    assert "<table" not in body

    tu = UnitText(
        "t1",
        "<table>…</table>",
        [],
        {"blockid": "t1"},
        0,
        0,
        False,
        "parsed_block",
        unit_kind="table",
    )
    tu.char_start = len(u.text) + 2
    tu.char_end = tu.char_start + len(tu.text)
    assert tu.char_start in structural_cut_positions([u, tu], "\n\n".join([u.text, tu.text]))


# ---- F3 attribution: not every line-start table / table-unit is independent


def test_attributed_colon_intro_is_not_a_boundary_but_bare_colon_annotates():
    """[构造测试] The attribution trichotomy on the clause text BEFORE the
    marker: colon + 表/图 reference → attributed (NOT a cut, table and its
    following prose stay inside the clause); colon without an object reference
    → cut WITH an ambiguity note (the caller must not claim complete);
    anything else → clean independent cut."""
    attributed = (
        "4.1 本条限值如下，表内规定属于本条：\n"
        '<table id="t-a"><tr><td>总汞</td><td>0.05</td></tr></table>\n'
        "本条补充要求：每日监测一次。\n4.2 下一条。"
    )
    ua = UnitText(
        "ua", attributed, [], {"blockid": "ua"}, 0, len(attributed), False, "parsed_block"
    )
    cuts, notes = structural_boundaries([ua], attributed)
    assert cuts == [] and notes == []
    items = extract_clauses_regex(attributed, ["4.1"], hard_ends=cuts)
    assert len(items) == 1
    body = items[0]["text"]
    assert "总汞" in body and "每日监测一次" in body  # 表内值与后续正文都属于本条

    bare = attributed.replace("，表内规定属于本条", "")
    ub = UnitText("ub", bare, [], {"blockid": "ub"}, 0, len(bare), False, "parsed_block")
    cuts_b, notes_b = structural_boundaries([ub], bare)
    assert cuts_b == [bare.index("<table")]  # announced but undecidable → cut
    assert notes_b and notes_b[0]["pos"] == cuts_b[0]
    items_b = extract_clauses_regex(bare, ["4.1"], hard_ends=cuts_b)
    assert "<table" not in items_b[0]["text"]  # cut is still safe by default

    plain = '4.1 本条要求独立成句。\n<table id="t-c"><tr><td>x</td></tr></table>\n4.2 下一条。'
    uc = UnitText("uc", plain, [], {"blockid": "uc"}, 0, len(plain), False, "parsed_block")
    cuts_c, notes_c = structural_boundaries([uc], plain)
    assert cuts_c == [plain.index("<table")] and notes_c == []  # sentence end → clean cut


def test_caption_lines_carry_attribution_but_never_cross_a_clause():
    """[构造测试] F3-a: the table's own title ("表 1" plain or "## 表 1 限值"
    markdown) sits between the attributed colon intro and the HTML body —
    title and body are ONE object, so attribution passes through the title.
    The walk is bounded: a LATER caption after the next clause's own sentence
    stays an independent cut, and the first intro never reaches it."""
    kept = (
        "4.1 本条限值见下表：\n表 1\n"
        '<table id="t-a"><tr><td>总汞</td><td>0.05</td></tr></table>\n'
        "本条补充要求：每日监测一次。\n4.2 下一条独立要求。"
    )
    u = UnitText("u", kept, [], {"blockid": "u"}, 0, len(kept), False, "parsed_block")
    cuts, notes = structural_boundaries([u], kept)
    assert cuts == [] and notes == []  # caption + body both attributed → not boundaries
    items = extract_clauses_regex(kept, ["4.1"], hard_ends=cuts)
    body = items[0]["text"]
    assert "总汞" in body and "0.05" in body and "每日监测一次" in body

    md = kept.replace("表 1\n", "## 表 1 限值\n")
    um = UnitText("um", md, [], {"blockid": "um"}, 0, len(md), False, "parsed_block")
    cuts_m, notes_m = structural_boundaries([um], md)
    assert cuts_m == [] and notes_m == []

    # negative: attribution must NOT cross the next independent clause
    crossed = (
        '4.1 本条限值见下表：\n<table id="t-a"><tr><td>甲</td></tr></table>\n'
        "本条补充要求。\n4.2 另一条已独立成句。\n表 9\n"
        '<table id="t-b"><tr><td>乙</td></tr></table>\n4.3 再下一条。'
    )
    ux = UnitText("ux", crossed, [], {"blockid": "ux"}, 0, len(crossed), False, "parsed_block")
    cuts_x, notes_x = structural_boundaries([ux], crossed)
    cap9 = crossed.index("表 9")
    t_b = crossed.index('<table id="t-b"')
    assert cap9 in cuts_x and t_b in cuts_x  # walk stops at 4.2's sentence → independent
    assert notes_x == []  # sentence-marked context → clean cut, no ambiguity claim
    by = {it["clause"]: it["text"] for it in extract_clauses_regex(crossed, hard_ends=cuts_x)}
    assert "甲" in by["4.1"] and "本条补充要求。" in by["4.1"]  # own attributed table kept
    assert by["4.2"] == "4.2 另一条已独立成句。"  # its later caption cuts, no bleed-in
    assert "乙" not in by["4.2"] and "乙" not in by["4.1"]


def test_table_kind_unit_with_attributed_intro_is_kept_not_cut():
    """[构造测试] A PHYSICAL table-kind catalog unit preceded by an attributed
    colon intro ("表内规定属于本条：") is NOT automatically an independent
    appendix table — the clause body runs through it until the next clause
    head. Without the attribution (e.g. page-header before the unit) it is
    still cut."""
    intro = "5.1 本条限值如下，表内规定属于本条："
    tbl = '<table id="t1"><tr><td>总汞</td><td>0.05</td></tr></table>'
    nxt = "5.2 下一条。"
    u1 = UnitText("u1", intro, [], {"blockid": "u1"}, 0, len(intro), False, "parsed_block")
    t1 = UnitText(
        "t1",
        tbl,
        [],
        {"blockid": "t1"},
        len(intro) + 2,
        len(intro) + 2 + len(tbl),
        False,
        "parsed_block",
        unit_kind="table",
    )
    t1.char_end = len(intro) + 2 + len(tbl)
    tail = UnitText(
        "u2",
        nxt,
        [],
        {"blockid": "u2"},
        t1.char_end + 2,
        t1.char_end + 2 + len(nxt),
        False,
        "parsed_block",
    )
    units = [u1, t1, tail]
    text = "\n\n".join(u.text for u in units)
    cuts, notes = structural_boundaries(units, text)
    assert t1.char_start not in cuts  # attributed table-unit stays in the clause
    items = extract_clauses_regex(text, ["5.1"], hard_ends=cuts)
    assert "总汞" in items[0]["text"] and "0.05" in items[0]["text"]

    # the same unit after a page-header-style sentence end IS independent
    u1p = UnitText(
        "u1", "5.1 本条要求见页眉上下文。", [], {"blockid": "u1"}, 0, 15, False, "parsed_block"
    )
    u1p.text = "5.1 本条要求见页眉上下文。"
    u1p.char_end = len(u1p.text)
    t1p = UnitText(
        "t1",
        tbl,
        [],
        {"blockid": "t1"},
        len(u1p.text) + 2,
        len(u1p.text) + 2 + len(tbl),
        False,
        "parsed_block",
        unit_kind="table",
    )
    text_p = "\n\n".join([u1p.text, t1p.text])
    cuts_p, _ = structural_boundaries([u1p, t1p], text_p)
    assert t1p.char_start in cuts_p


def test_expand_prose_ambiguous_boundary_forces_partial_with_warning():
    """[构造测试+正式入口] F3 完整性：'本条限值如下：'（冒号宣告但未指认对象）
    + 内嵌表 + '本条补充要求' 经正式 _expand_prose —— 无法判断归属时整题必须
    partial 且警告随结果发布；带对象指认的孪生例则 complete 且表内容与后续
    要求都在交付文本里。"""
    from unittest.mock import patch

    ambiguous = (
        '4.1 本条限值如下：\n<table id="t"><tr><td>总汞</td><td>0.05</td></tr></table>\n'
        "本条补充要求：每日监测一次。\n4.2 下一条独立要求。"
    )
    attributed = ambiguous.replace("本条限值如下：", "本条限值如下，表内规定属于本条：")

    def _drive(text):
        unit = UnitText("u", text, [], {"blockid": "u"}, 0, len(text), False, "parsed_block")

        async def read(*_a, **_kw):
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

        with (
            patch("env_rag_final.enumerate_.prose_enum.read_prose_scope", read),
            patch.object(expand, "check_search_stale", _current),
        ):
            return run(
                expand._expand_prose(
                    None, "default", "d", "d:scope:4", None, requested_clauses=["4.1"]
                )
            )

    res = _drive(ambiguous)
    assert res["coverage_status"] == "partial", res
    assert res["boundary_ambiguities"], res
    assert any("cannot be determined" in w for w in res["warnings"]), res["warnings"]

    res2 = _drive(attributed)
    assert res2["coverage_status"] == "complete", res2
    assert res2["boundary_ambiguities"] == []
    body = res2["items"][0]["text"]
    assert "总汞" in body and "0.05" in body and "每日监测一次" in body
    assert all(it["citation_verified"] for it in res2["items"])


def test_requires_span_nonzero_offset_still_binds_raw_coordinates():
    """[构造测试] 验收4: a requires_span unit read at a NON-ZERO located clause
    offset keeps raw unit-relative coordinates correct end to end."""
    raw = "开头导语\n6.1.1 定位到的条款正文。\n后续 6.1.2 另一条款。"
    from env_rag_final.enumerate_.prose_enum import locate_span

    span = locate_span(raw, "6.1.1")
    assert span and span[0] > 0  # non-zero located start
    sliced = UnitText(
        "u1",
        raw[span[0] : span[1]],
        [],
        {"blockid": "u1"},
        0,
        span[1] - span[0],
        True,
        "parsed_block",
        span_offset_in_unit=span[0],
    )
    items = extract_clauses_regex(sliced.text)
    bound = bind_citations(items, "default", "d", "s", [sliced])
    out = verify_citations(bound, sliced.text, [sliced])
    assert out[0]["citation_verified"] is True
    # raw coordinates include the offset: a reader slicing the RAW text finds it
    seg = out[0]["citation"]
    assert raw[seg["unit_rel_start"] : seg["unit_rel_end"]].strip().startswith("6.1.1")
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        pdir = _write_parsed(Path(td), "fixture.pdf", [("u1", raw)])
        probs = an._reverify_prose_items([dict(out[0])], pdir)
        assert probs == []


# ---------------------------------------------------------------------------
# 3. boundary-preserving behaviours that must NOT regress [构造测试]
# ---------------------------------------------------------------------------


def test_budget_and_shortage_semantics_unchanged():
    """验收4: budget exhaustion stays partial with the unprocessed hint; a
    missing requested clause and an empty scope keep their semantics."""
    units = _continuation_units()

    async def fake_read(
        _adapter, conn, workspace, doc_id, snapshot, scope_id=None, requested_clauses=None, **_kw
    ):
        return list(units), EnumResult(
            "q",
            "prose",
            "default",
            snapshot,
            "fp",
            scope_ids=[scope_id],
            members_total=len(units),
            members_processed=len(units),
            coverage_status="partial",
            read_status="partial",
            warnings=["budget: members 2/4, remaining range starts at u3"],
            fail_stage="budget",
        )

    from unittest.mock import patch

    import env_rag_final.enumerate_.prose_enum as pe

    orig = pe.read_prose_scope
    with patch.object(expand, "check_search_stale", _current):
        pe.read_prose_scope = fake_read
        try:
            result = run(
                expand._expand_prose(
                    None,
                    "default",
                    "d",
                    "d:scope:5.1",
                    None,
                    requested_clauses=["5.1.1", "5.1.2", "5.2"],
                )
            )
        finally:
            pe.read_prose_scope = orig
    assert result["coverage_status"] == "partial"
    assert result["fail_stage"] == "budget"

    # empty scope read keeps ambiguous/partial (never complete)
    async def empty_read(*a, **kw):
        return [], EnumResult(
            "q", "prose", "default", "s", "fp", coverage_status="ambiguous", fail_stage="snapshot"
        )

    with patch.object(expand, "check_search_stale", _current):
        orig2 = pe.read_prose_scope
        pe.read_prose_scope = empty_read
        try:
            r2 = run(expand._expand_prose(None, "default", "d", "d:scope:9", None))
        finally:
            pe.read_prose_scope = orig2
    assert r2["coverage_status"] != "complete"


# ---------------------------------------------------------------------------
# 4. OFFLINE REPLAY against the ORIGINAL parsed sidecars [原始产物离线读取]
# ---------------------------------------------------------------------------

GOLD_PATH = Path("reports/pg-retrieval/gate-2/review-r5/gold-approved.json")
R1 = Path("reports/pg-retrieval/phase-4-round-1")

_GB_CODE_RE = re.compile(r"GB\s*\d+(?:\s*[-—–]\s*\d{4})?")


def _request_from_question(question: str, scope_number: str) -> list[str] | None:
    """F4-a: the replay INPUT comes from the ORIGINAL question text, never
    from gold.expected_items. Clause numbers DEEPER than the requested scope
    bound the extraction (an explicit range request like 4.1.1/4.1.2); a
    section/chapter request passes None so the sub-items are discovered from
    the SOURCE structure by the extraction layer itself — exactly like the
    stored round-1 traces, where 4 of these 5 questions ran with
    requested_clauses=None."""
    stripped = _GB_CODE_RE.sub(" ", question)
    targets = re.findall(r"\d+(?:\.\d+)+", stripped)
    depth = scope_number.count(".") + 1
    clauses = [t for t in targets if t.count(".") + 1 > depth]
    return clauses or None


def _collapse(s: str) -> str:
    return " ".join((s or "").split())


def _gold_clause_text(e) -> tuple[str | None, str]:
    if isinstance(e, dict):
        return e.get("clause") or e.get("number"), _collapse(e.get("text") or "")
    s = str(e)
    head = s.split(" ")[0]
    return (head if head[:1].isdigit() else None), _collapse(s)


def _set_match(gold_items, delivered, doc_id, unit_ids, require_clause=True):
    """F4-a: one-to-one set verification by 编号+全文+来源. Each gold item
    pairs with at most one delivered item (same clause number when required,
    gold full text contained in the delivered full text, citation bound to
    this doc/this stored unit set and verified + reverified); every delivered
    item must pair. Returns (missing, extra) — BOTH must be empty; len>=3 or
    any-hit can never hide a lost or an added item.

    require_clause=False is only for the OCR roman-class question whose
    gold labels were canonicalized while the contract keeps the source
    markers verbatim (e.g. Ⅱ/Ⅲ rendered as Ⅰ): the pairing there is by full
    text + source, still one-to-one with missing/extra listed."""
    matched: set[int] = set()
    missing: list[str] = []
    for e in gold_items:
        gc, gt = _gold_clause_text(e)
        hit = None
        for idx, it in enumerate(delivered):
            if idx in matched:
                continue
            cit = it.get("citation") or {}
            source_ok = (
                cit.get("doc_id") == doc_id
                and cit.get("workspace") == "default"
                and (
                    cit.get("unit_id") in unit_ids
                    or {s.get("unit_id") for s in cit.get("unit_segments") or []} <= set(unit_ids)
                )
                and it.get("citation_verified") is True
                and it.get("citation_reverified") is True
            )
            if not source_ok:
                continue
            if require_clause and gc is not None and (it.get("clause") or "") != gc:
                continue
            if not gt or gt not in _collapse(it.get("text") or ""):
                continue
            hit = idx
            break
        if hit is None:
            missing.append(gc or gt[:24])
        else:
            matched.add(hit)
    extra = [
        it.get("clause") or it.get("place") or _collapse(str(it.get("text"))[:24])
        for idx, it in enumerate(delivered)
        if idx not in matched
    ]
    return missing, extra


class ReplayConn:
    """Explicit FAKE read-only adapter over ORIGINAL artifacts: the member
    order and doc name come from the stored round-1 expansion + frozen gold;
    unit texts are re-read live from the ORIGINAL blocks.jsonl. No database,
    no network — a construction, not a live catalog read."""

    def __init__(self, doc_id, doc_name, unit_ids, table_unit_ids=()):
        self.doc_id, self.doc_name = doc_id, doc_name
        self.units = list(unit_ids)
        self.table_ids = set(table_unit_ids)
        self._texts = {}
        pdir = sid.PARSED_ROOT / f"{doc_name}.parsed"
        bf = sorted(pdir.glob("*.blocks.jsonl"))[0]
        for line in bf.read_text(encoding="utf-8").splitlines()[1:]:
            b = json.loads(line)
            if b.get("type") == "content":
                self._texts[b.get("blockid")] = b.get("content") or ""

    async def fetch(self, sql, *args):
        if "scope_units" in sql:
            return [{"unit_id": u} for u in self.units]
        if "unit_chunk_links" in sql:
            return []
        return []

    async def fetchrow(self, sql, *args):
        uid = args[-1] if args else None
        kind = "table" if uid in self.table_ids else "block"
        return dict(
            unit_id=uid,
            unit_kind=kind,
            heading="",
            requires_span=False,
            content_length=len(self._texts.get(uid, "")),
            locator={"blockid": uid},
        )

    async def fetchval(self, sql, *args):
        if "documents" in sql:
            return self.doc_name
        return None


def _replay(qid, path="pg"):
    """Drive the FORMAL prose expansion entry + the answer-side independent
    reader against ORIGINAL sidecars; returns the expansion + problems.

    F4-a: the INPUT request (scope id + requested clauses) comes from the
    stored round-1 trace's scope and the ORIGINAL question text — never from
    gold.expected_items. The gold stays for POST-HOC one-to-one verification
    in the test bodies."""
    d = json.loads((R1 / "legs/r1" / path / qid / "answer/answer-runtime-latest.json").read_text())
    res = d["results"][0]
    exp = next(e for e in res["expansions"] if e.get("selected") and e.get("kind") == "prose")
    doc_id = exp["doc_id"]
    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    q = next(x for x in gold["questions"] if x["query_id"] == qid)
    doc_name = next(t["doc_name"] for t in q["target_docs"] if t["doc_id"] == doc_id)
    scope_number = exp["scope_id"].rsplit(":", 1)[-1]
    clauses = _request_from_question(q["question"], scope_number)
    conn = ReplayConn(doc_id, doc_name, exp["unit_ids"])
    from unittest.mock import patch

    with (
        patch("env_rag_final.catalog.builder.check_stale", _current),
        patch.object(expand, "check_search_stale", _current),
    ):
        result = run(
            expand._expand_prose(
                conn,
                "default",
                doc_id,
                exp["scope_id"],
                None,
                requested_clauses=clauses,
            )
        )
    pdir = sid.PARSED_ROOT / f"{doc_name}.parsed"
    items = [json.loads(json.dumps(it)) for it in result["items"]]
    probs = an._reverify_prose_items(items, pdir)
    return result, items, probs, q


def test_replay_prose003_431_to_434_full_gold_text_without_table_tail():
    """[原始产物离线读取] The original failure: 4.3.4 delivered 20,636 chars
    (归一20,631) that the 6 declared segments could not support. After I1 the
    clause is its own sentence, the item set matches gold ONE-TO-ONE (no
    missing, no extra), and the independent raw re-read accepts all of them."""
    result, items, probs, q = _replay("prose-enum-003")
    assert probs == [], probs
    assert all(it["citation_reverified"] for it in items)
    assert result["coverage_status"] == "complete", result
    missing, extra = _set_match(
        q["gold"]["expected_items"], items, result["doc_id"], result["unit_ids"]
    )
    assert missing == [] and extra == [], (missing, extra)
    assert len(items) == 4, [it.get("clause") for it in items]
    for it in items:
        assert "<table" not in it["text"]
        assert "石油沥青" not in it["text"]  # 后续表尾不再被吞入
    assert all(isinstance(it["citation"].get("char_start"), int) for it in items)


@pytest.mark.parametrize("qid", ["prose-enum-001", "prose-enum-002", "prose-enum-006"])
def test_replay_correct_contrasts_stay_supported(qid):
    """[原始产物离线读取] 验收5+6 对照面：3.1–3.4 术语、4.1 两条、4.2 无子条款
    正文在新边界/新顺序/全文回读下仍全部受支持（拒收不是全局性）。F4-a: the
    request is parsed from the ORIGINAL question (prose-002 explicitly names
    4.1.1 and 4.1.2; the others are scope requests), and the delivered set is
    checked one-to-one against gold with missing/extra listed."""
    result, items, probs, q = _replay(qid)
    assert probs == [], probs
    assert result["coverage_status"] == "complete", result
    missing, extra = _set_match(
        q["gold"]["expected_items"], items, result["doc_id"], result["unit_ids"]
    )
    assert missing == [] and extra == [], (missing, extra)


def test_replay_prose004_category_projection_survives():
    """[原始产物离线读取] GB3838 五类功能正文（C5 类别投影）在无数字子条款的
    正文路径上保持逐项全文可回读。F4-a: 一对一集合核验——gold 的五条类别文本
    必须各自配到恰好一个交付项（编号按既有合同保留 OCR 原样标签，配对以全文+
    来源为主，见 _set_match 说明），多余的交付项同样必须列空。"""
    result, items, probs, q = _replay("prose-enum-004")
    assert probs == [], probs
    assert result["coverage_status"] == "complete"
    missing, extra = _set_match(
        q["gold"]["expected_items"],
        items,
        result["doc_id"],
        result["unit_ids"],
        require_clause=False,
    )
    assert missing == [] and extra == [], (missing, extra)
    assert len(items) == len(q["gold"]["expected_items"]), [it.get("clause") for it in items]


def test_replay_generalization_other_clause_and_tamper_detection():
    """[原始产物离线读取+构造] 验收6：同文件不同条款请求仍边界正确；把长条款
    尾部数值改动（quote 前 120 字不变）必须被全文回读拒绝——只验 quote 的旧
    语义救不回来。"""
    # 只请求 4.3.1 —— 边界/装配不受其它条款影响
    import env_rag_final.enumerate_.prose_enum as pe  # noqa: F401  (module identity)

    result, items, probs, _ = _replay("prose-enum-002")
    assert probs == []
    long_item = next(it for it in items if len(it["text"]) > 120)
    tampered = json.loads(json.dumps(long_item))
    tampered["text"] = tampered["text"][:-4] + "九十九。"
    assert tampered["citation"]["quote"][:120] == long_item["citation"]["quote"][:120]
    pdir = sid.PARSED_ROOT / next(p.name for p in sid.PARSED_ROOT.glob("water-09*.parsed"))
    tp = an._reverify_prose_items([tampered], pdir)
    assert tp and tampered["citation_reverified"] is False

    # 数值改（8978 场景）：4.3.4 引用 GB 8703—88 → 89，quote 短整句完整包含，
    # 但全文回读仍须拒
    result3, items3, probs3, _ = _replay("prose-enum-003")
    assert probs3 == []
    it = next(i for i in items3 if i["clause"] == "4.3.4")
    bad = json.loads(json.dumps(it))
    bad["text"] = bad["text"].replace("GB 8703—88", "GB 8703—89")
    pdir3 = sid.PARSED_ROOT / next(p.name for p in sid.PARSED_ROOT.glob("water-11*GB8978*.parsed"))
    tp3 = an._reverify_prose_items([bad], pdir3)
    assert tp3 and bad["citation_reverified"] is False
