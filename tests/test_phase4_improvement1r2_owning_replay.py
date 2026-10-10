"""Improvement-1 r2 (F4-b): OFFLINE replay of the OWNING answer entry.

Every scenario drives ``env_rag_final.answer.run_answer`` itself over the
prose pipeline with an EXPLICIT fake read-only connection/storage and the
identity material stored by the accepted round-1 generation (the same
offline-harness pattern the frozen answer suites use via ``import test_answer
as fx``). expand and every verifier run FOR REAL — nothing is mocked to
constant True. HTTP/model boundaries explode on use, the real asyncpg.connect
is replaced by an assertion, and no service is contacted.

Cases:
1. REAL-DATA PASS-THROUGH [原始产物读取 + 离线answer入口回放]: prose-enum-003's
   ORIGINAL stored request trace + its stored 5.3/5.4 replay reports expand
   against the ORIGINAL parsed sidecars; the published result must be
   complete, four items, free of the swallowed table tail, with the stored
   identity published unchanged and zero model calls.
2. LEGITIMATE CROSS-UNIT [构造读取注入 + 离线answer入口回放]: a clause body that
   genuinely crosses the protocol "\\n\\n" gap between two blocks is published
   complete with assembled-order segments; the owning-side independent
   re-read passes.
3/4. TAMPERED DECLARATIONS [构造篡改注入]: a fabricated separator (with the
   text re-joined by it) or a malformed numeric coordinate injected AFTER
   the real expansion must be refused by the owning entry's own independent
   re-read — the published coverage becomes partial, the problem is
   recorded, and complete is never claimed.
5. STRUCTURE ATTRIBUTION [构造读取注入]: a colon intro naming the 表/图 object
   keeps the embedded table AND its following prose inside the clause and
   publishes complete; a colon intro without the object reference is an
   undecidable boundary — published partial with the boundary recorded,
   never silent-complete.
6. ATTRIBUTION THROUGH THE TABLE'S OWN TITLE (F3-a) [构造读取注入]: a caption
   ("表 1"/"## 表 1 限值") between the attributed intro and the table body
   cannot reset the attribution; the proven attribution never crosses into
   the NEXT independent clause — a later captioned table of another clause
   stays an independent cut while the whole answer publishes complete with
   zero problems.

Gold is used ONLY post-hoc (case 1 verification); no input sub-clause list
is ever derived from an expected answer.
"""

import asyncio
import json
from pathlib import Path

import test_answer as fx

from env_rag_final import answer as an
from env_rag_final.audit import identity as audit_identity
from env_rag_final.enumerate_.prose_enum import ASSEMBLY_SEPARATOR, _unit_text_from_blocks

REAL_PARSED_ROOT = audit_identity.PARSED_ROOT
INPUTS = Path("reports/pg-retrieval/phase-4-round-1/inputs/pg")
FUSED_FILE = INPUTS / "prose-enum-003-fusion.json"
RERANK_FILE = INPUTS / "prose-enum-003-rerank.json"
RUNTIME = Path(
    "reports/pg-retrieval/phase-4-round-1/legs/r1/pg/prose-enum-003/answer/answer-runtime-latest.json"
)
GOLD = json.loads(
    Path("reports/pg-retrieval/gate-2/review-r5/gold-approved.json").read_text(encoding="utf-8")
)


def _run(coro):
    return asyncio.run(coro)


def _install_common(monkeypatch, tmp_path, conn, questions, ident):
    """The accepted offline seams (same patch set as the frozen answer
    harness): stored identity instead of a live capture, fake catalog, real
    expand/verify/answer code. Nothing retrieval- or verification-related is
    replaced by a constant."""
    (tmp_path / "gold.json").write_text(
        json.dumps({"questions": questions, "counter_examples": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(an, "GOLD_PATH", tmp_path / "gold.json")
    monkeypatch.setattr(an, "verify_gold_guard", lambda p: ident["gold_sha"])

    def guard(values, workspace):
        if any(k in values for k in ("QDRANT_WORKSPACE", "NEO4J_WORKSPACE", "POSTGRES_WORKSPACE")):
            raise an.AdapterError("workspace override env forbidden")

    monkeypatch.setattr(an, "verify_config_guard", guard)

    async def capture(_values):
        # 已存身份材料: the identity the accepted round-1 generation recorded.
        return {
            "identity": {
                "public_counts": ident["counts"],
                "catalog_active": ident["catalog_active"],
                "source_fingerprint": ident["source_fingerprint"],
                "search_active": ident["search_active"],
                "gold_sha": ident["gold_sha"],
                "env_sha": ident["env_sha"],
            },
            "problems": [],
            "matches_frozen": True,
        }

    monkeypatch.setattr(an, "_capture_identity", capture)

    snap = ident["catalog_active"]["snapshot_id"]
    fp = ident["source_fingerprint"]

    async def current(_conn, **_kw):
        return {"state": "current", "active_snapshot_id": snap, "stored_fingerprint": fp}

    import env_rag_final.catalog.builder as builder
    import env_rag_final.catalog.source as source_mod
    import env_rag_final.enumerate_.table_enum as table_enum_mod
    import env_rag_final.search.expand as expand_mod

    monkeypatch.setattr(builder, "check_stale", current)
    monkeypatch.setattr(table_enum_mod, "check_stale", current)

    async def no_live_fp(_conn, _ws):
        return ""

    monkeypatch.setattr(builder, "_live_source_fingerprint", no_live_fp)

    async def fresh(_conn, _ws, parsed_root=None):
        return {
            "state": "current",
            "catalog_snapshot_id": snap,
            "search_id": ident["search_active"],
        }

    monkeypatch.setattr(expand_mod, "check_search_stale", fresh)
    monkeypatch.setattr(source_mod, "SourceAdapter", fx.FakeAdapter)

    def boom(**_kw):
        raise AssertionError("owning offline replay must never open a real DB connection")

    monkeypatch.setattr(an.asyncpg, "connect", boom)

    def http_boom(*_a, **_k):
        raise AssertionError("owning offline replay must never make an HTTP call")

    monkeypatch.setattr(an.httpx.AsyncClient, "post", http_boom)
    return conn


# ---------------------------------------------------------------------------
# 1. real-data pass-through: prose-enum-003 through run_answer itself
# ---------------------------------------------------------------------------


def _real_catalog():
    rt = json.loads(RUNTIME.read_text(encoding="utf-8"))
    exp = next(
        e for e in rt["results"][0]["expansions"] if e.get("selected") and e.get("kind") == "prose"
    )
    doc_id, scope_id, unit_ids = exp["doc_id"], exp["scope_id"], exp["unit_ids"]
    q = next(x for x in GOLD["questions"] if x["query_id"] == "prose-enum-003")
    doc_name = next(t["doc_name"] for t in q["target_docs"] if t["doc_id"] == doc_id)
    cat = fx._catalog()
    cat["scope_units"][scope_id] = list(unit_ids)
    number = scope_id.rsplit(":", 1)[-1]
    cat["scopes"][(doc_id, number)] = [
        {
            "scope_id": scope_id,
            "scope_kind": "chapter",
            "title": "其他规定",
            "number": number,
            "confirm_status": "confirmed",
        }
    ]
    pdir = REAL_PARSED_ROOT / f"{doc_name}.parsed"
    for uid in unit_ids:
        text = _unit_text_from_blocks(pdir, uid) or ""
        cat["units"][(doc_id, uid)] = {
            "unit_id": uid,
            "unit_kind": "block",
            "heading": "",
            "requires_span": False,
            "content_length": len(text),
            "locator": json.dumps({"blockid": uid}),
        }
    return rt, doc_id, scope_id, doc_name, cat, q, number


def test_owning_realdata_prose003_pass_through(monkeypatch, tmp_path):
    """[原始产物读取 + 离线answer入口回放] The original failing question is
    re-run end-to-end through run_answer over its OWN stored 5.3/5.4 replay
    reports and the ORIGINAL parsed sidecars (the read rows are the stored
    trace's units — a construction over stored artifacts, not a live catalog
    read). The published result must be complete, exactly the four gold
    clauses, table-tail free, with the stored identity unchanged and zero
    model/HTTP calls."""
    rt, doc_id, _scope_id, doc_name, cat, q, number = _real_catalog()
    ident = json.loads(FUSED_FILE.read_text(encoding="utf-8"))["identity_before"]
    monkeypatch.setitem(
        fx.DOCS, doc_id, {"doc_name": doc_name, "self_code": "GB8978", "self_code_version": "1996"}
    )
    conn = fx.FakeEnvConn(cat)
    question = q["question"]  # 原始请求文本，作为输入
    _install_common(
        monkeypatch,
        tmp_path,
        conn,
        [
            {
                "query_id": "prose-enum-003",
                "question": question,
                "workspace": "default",
                "category": "prose_enum",
            }
        ],
        ident,
    )
    # REAL parsed sidecars stay the read source (no tmp override for this case)
    monkeypatch.setattr(audit_identity, "PARSED_ROOT", REAL_PARSED_ROOT)

    report = _run(
        an.run_answer(
            tmp_path / "run",
            ["prose-enum-003"],
            rerank_report_path=RERANK_FILE,
            fused_report_path=FUSED_FILE,
            conn=conn,
            values=fx.VALUES,
            allow_model=False,
            transport=None,
        )
    )
    assert "failure" not in report, report.get("failure")
    assert report["identity_before"]["matches_frozen"] is True
    assert report["identity_before"]["counts"] == ident["counts"]
    assert report["identity_after"]["matches_frozen"] is True
    assert "identity_drift" not in report
    assert report["model_calls_used"] == 0
    # every catalog statement the owning entry issued is a read
    for _kind, sql in conn.queries:
        assert "INSERT" not in sql.upper() and "UPDATE" not in sql.upper(), sql
        assert "DELETE" not in sql.upper() and "CREATE" not in sql.upper(), sql

    out = report["results"][0]
    assert out["coverage_status"] == "complete", out
    assert out["status"] == "ok"
    assert out["reverification"]["problems"] == []
    prose = next(e for e in out["expansions"] if e.get("kind") == "prose" and e.get("selected"))
    assert prose["items_count"] == 4, prose
    got = out["answer"]
    blob = json.dumps(got, ensure_ascii=False)
    # gold used ONLY post-hoc: each expected clause is published verbatim,
    # nothing extra appears, and the swallowed table tail is gone
    assert "<table" not in blob
    assert "石油沥青" not in blob
    for e in q["gold"]["expected_items"]:
        assert e["clause"] in blob
        assert " ".join(e["text"].split()) in blob
    # exactly the gold set, no extra published prose items
    assert {it["clause"] for it in got["items"] if it.get("clause")} == {
        e["clause"] for e in q["gold"]["expected_items"]
    }


# ---------------------------------------------------------------------------
# 2-5. constructed read-data injections through the same owning entry
# ---------------------------------------------------------------------------

OWN_DOC = "doc-owning-r2"
OWN_SCOPE = "own:scope:4"


def _own_fixture(tmp_path, monkeypatch, unit_texts: dict):
    """[构造读取注入] A synthetic catalog + parsed blocks under tmp (the doc
    name is fixture-owned) driving the SAME owning entry. Returns
    (conn, question, fused/rerank report paths)."""
    monkeypatch.setattr(audit_identity, "PARSED_ROOT", tmp_path)
    pdir = tmp_path / "ownr2.pdf.parsed"
    pdir.mkdir(exist_ok=True)
    lines = ['{"meta": true}'] + [
        json.dumps({"type": "content", "blockid": uid, "content": text}, ensure_ascii=False)
        for uid, text in unit_texts.items()
    ]
    (pdir / "x.blocks.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setitem(
        fx.DOCS,
        OWN_DOC,
        {"doc_name": "ownr2.pdf", "self_code": "GB8978", "self_code_version": "1996"},
    )
    cat = fx._catalog()
    cat["scope_units"][OWN_SCOPE] = list(unit_texts)
    cat["scopes"][(OWN_DOC, "4")] = [
        {
            "scope_id": OWN_SCOPE,
            "scope_kind": "chapter",
            "title": "规定",
            "number": "4",
            "confirm_status": "confirmed",
        }
    ]
    for uid, text in unit_texts.items():
        cat["units"][(OWN_DOC, uid)] = {
            "unit_id": uid,
            "unit_kind": "block",
            "heading": "",
            "requires_span": False,
            "content_length": len(text),
            "locator": json.dumps({"blockid": uid}),
        }
    conn = fx.FakeEnvConn(cat)
    question = "GB 8978-1996 中 4 章规定了哪些要求？逐项列出编号。"
    usable = fx._usable("chunk-owning-r2", OWN_DOC, "4 章 规定 要求", discovery="code_exact")
    fused = fx._fused("own-q", question, [usable])
    rr = fx._rerank("own-q", [])
    fp, rp = fx._write_replay(tmp_path, [fused], [rr])
    return conn, question, fp, rp


def _own_run(monkeypatch, tmp_path, conn, question, fp, rp):
    _install_common(
        monkeypatch,
        tmp_path,
        conn,
        [
            {
                "query_id": "own-q",
                "question": question,
                "workspace": "default",
                "category": "prose_enum",
            }
        ],
        fx._identity(),
    )
    return _run(
        an.run_answer(
            tmp_path / "run",
            ["own-q"],
            rerank_report_path=rp,
            fused_report_path=fp,
            conn=conn,
            values=fx.VALUES,
            allow_model=False,
            transport=None,
        )
    )


_CROSS_UNITS = {
    "own-u1": "## 4 章规定\n4.1 跨单元条款的前半部分从这里开",
    "own-u2": "始，后半部分完整结束并给出要求。\n4.2 另一条独立要求。",
}


def test_owning_legitimate_cross_unit_publishes_complete(monkeypatch, tmp_path):
    """[构造读取注入] 验收F4-b1: a clause whose body genuinely crosses the
    real '\\n\\n' gap between two blocks is published COMPLETE through the
    owning entry: the segments are in assembled order, carry the protocol
    separator, and the independent raw re-read (answer._reverify over the
    blocks.jsonl) passes with zero problems."""
    conn, question, fp, rp = _own_fixture(tmp_path, monkeypatch, _CROSS_UNITS)
    report = _own_run(monkeypatch, tmp_path, conn, question, fp, rp)
    out = report["results"][0]
    assert out["reverification"]["problems"] == []
    assert out["coverage_status"] == "complete", out
    prose = next(e for e in out["expansions"] if e.get("kind") == "prose" and e.get("selected"))
    assert prose["items_count"] == 2  # 4.1 cross-unit + 4.2
    blob = json.dumps(out["answer"], ensure_ascii=False)
    assert "跨单元条款的前半部分" in blob and "后半部分完整结束" in blob
    # the PUBLISHED citation carries the contract: assembled-order segments,
    # the protocol separator declared, and every item verified + reverified
    cross = next(
        it for it in out["answer"]["items"] if (it.get("citation") or {}).get("unit_segments")
    )
    cit = cross["citation"]
    assert [s["unit_id"] for s in cit["unit_segments"]] == ["own-u1", "own-u2"]
    assert cit["assembly_separator"] == ASSEMBLY_SEPARATOR
    assert cross.get("citation_verified") is True


def test_owning_fabricated_separator_publishes_partial(monkeypatch, tmp_path):
    """[构造篡改注入] 验收F4-b2: after the REAL expansion produced an honest
    cross-unit item, a fabricated separator (with the delivered text rebuilt
    by joining through it, quote unchanged) is injected. The owning entry's
    own independent re-read must refuse: partial coverage, a recorded
    protocol problem, and never a silent complete."""
    conn, question, fp, rp = _own_fixture(tmp_path, monkeypatch, _CROSS_UNITS)
    real = an.expand_candidates

    async def tamper(c, result, ws, vals, **kw):
        await real(c, result, ws, vals, **kw)
        for stage in result.trace:
            for exp in stage.get("expansions") or []:
                if exp.get("doc_id") == OWN_DOC and exp.get("items"):
                    it = exp["items"][0]
                    cit = it["citation"]
                    assert "unit_segments" in cit, "fixture must yield a cross-unit item"
                    fake = "停车场允许无条件排放污水。"
                    raw = dict(_CROSS_UNITS)
                    parts = [
                        raw[s["unit_id"]][s["rel_start"] : s["rel_end"]]
                        for s in cit["unit_segments"]
                    ]
                    cit["assembly_separator"] = fake
                    it["text"] = fake.join(parts)

    monkeypatch.setattr(an, "expand_candidates", tamper)
    report = _own_run(monkeypatch, tmp_path, conn, question, fp, rp)
    out = report["results"][0]
    assert out["coverage_status"] == "partial", out
    probs = " | ".join(out["reverification"]["problems"])
    assert "protocol join" in probs, probs
    assert "停车场" not in json.dumps(out["replay"], ensure_ascii=False)  # not fabricated evidence
    blob = json.dumps(out["answer"], ensure_ascii=False)
    # the tampered item's delivered text is refused but must stay PUBLISHED
    # with the partial verdict — the contract never silently drops items to
    # fake a clean answer; its citation_reverified=False travels with it
    assert "停车场" in blob
    assert any(
        (it.get("citation") or {}).get("citation_reverified") is False
        or it.get("citation_reverified") is False
        for it in out["answer"]["items"]
    ), out["answer"]["items"]
    assert out["status"] != "ok"


def test_owning_malformed_numeric_span_cannot_downgrade(monkeypatch, tmp_path):
    """[构造篡改注入] 验收F4-b3: nulling char_start on a real delivered item
    (the quote stays intact and correct) must NOT downgrade the item to the
    quote-only path: the owning entry refuses the malformed declaration and
    the published coverage is partial."""
    conn, question, fp, rp = _own_fixture(tmp_path, monkeypatch, _CROSS_UNITS)
    real = an.expand_candidates

    async def tamper(c, result, ws, vals, **kw):
        await real(c, result, ws, vals, **kw)
        for stage in result.trace:
            for exp in stage.get("expansions") or []:
                if exp.get("doc_id") == OWN_DOC and exp.get("items"):
                    for it in exp["items"]:
                        it["citation"]["char_start"] = None

    monkeypatch.setattr(an, "expand_candidates", tamper)
    report = _own_run(monkeypatch, tmp_path, conn, question, fp, rp)
    out = report["results"][0]
    assert out["coverage_status"] == "partial", out
    probs = " | ".join(out["reverification"]["problems"])
    assert "malformed coordinates" in probs and "quote-only" in probs, probs


def test_owning_attributed_embedded_table_stays_and_publishes_complete(monkeypatch, tmp_path):
    """[构造读取注入] 验收F4-b4: a clause whose colon intro names the 表 object
    keeps the embedded table AND the following requirement prose; through the
    owning entry the answer is complete and every necessary piece is
    published — no silent omission behind a complete verdict."""
    units = {
        "own-u1": (
            "## 4 章规定\n4.1 本条限值如下，表内规定属于本条：\n"
            '<table id="tb-o"><tr><td>总汞</td><td>0.05</td></tr></table>\n'
            "本条补充要求：每日监测一次。\n4.2 下一条独立要求。"
        ),
    }
    conn, question, fp, rp = _own_fixture(tmp_path, monkeypatch, units)
    report = _own_run(monkeypatch, tmp_path, conn, question, fp, rp)
    out = report["results"][0]
    assert out["reverification"]["problems"] == []
    assert out["coverage_status"] == "complete", out
    blob = json.dumps(out["answer"], ensure_ascii=False)
    assert "总汞" in blob and "0.05" in blob and "每日监测一次" in blob


def test_owning_ambiguous_boundary_publishes_partial_with_record(monkeypatch, tmp_path):
    """[构造读取注入] 验收F4-b5: a colon intro that announces a structure
    WITHOUT naming a 表/图 object is undecidable: the owning entry must
    publish PARTIAL and RECORD the boundary explanation (warnings +
    boundary_ambiguities on the published expansion) — never a silent
    complete over a truncated requirement."""
    units = {
        "own-u1": (
            "## 4 章规定\n4.1 本条限值如下：\n"
            '<table id="tb-o"><tr><td>总汞</td><td>0.05</td></tr></table>\n'
            "本条补充要求：每日监测一次。\n4.2 下一条独立要求。"
        ),
    }
    conn, question, fp, rp = _own_fixture(tmp_path, monkeypatch, units)
    report = _own_run(monkeypatch, tmp_path, conn, question, fp, rp)
    out = report["results"][0]
    assert out["coverage_status"] == "partial", out
    prose = next(e for e in out["expansions"] if e.get("kind") == "prose" and e.get("selected"))
    assert prose.get("boundary_ambiguities"), prose.keys()
    assert any("cannot be determined" in w for w in prose.get("warnings") or []), prose.get(
        "warnings"
    )


def test_owning_attributed_caption_kept_and_later_caption_stays_independent(monkeypatch, tmp_path):
    """[构造读取注入] 验收F3-a（owning 双向）：4.1 的"见下表："+表题+表体+补充
    要求是一个被归属的表对象，穿过表题仍完整保留并独立回读通过；下一独立条款
    4.2 之后的"表 9"附表是另一个对象——4.1 的归属绝不跨界传播，4.2 保持短句、
    整题仍 complete 且零问题（无金标输入、无表内容缺失的静默通过）。"""
    units = {
        "own-u1": (
            "## 4 章规定\n4.1 本条限值见下表：\n表 1\n"
            '<table id="tb-a"><tr><td>总汞</td><td>0.05</td></tr></table>\n'
            "本条补充要求：每日监测一次。\n"
            "4.2 另一条已独立成句。\n表 9\n"
            '<table id="tb-b"><tr><td>乙</td></tr></table>\n4.3 再下一条要求。'
        ),
    }
    conn, question, fp, rp = _own_fixture(tmp_path, monkeypatch, units)
    report = _own_run(monkeypatch, tmp_path, conn, question, fp, rp)
    out = report["results"][0]
    assert out["reverification"]["problems"] == []
    assert out["coverage_status"] == "complete", out
    byc = {it.get("clause"): it for it in out["answer"]["items"]}
    assert "总汞" in byc["4.1"]["text"] and "每日监测一次" in byc["4.1"]["text"]
    assert byc["4.1"].get("citation_reverified") is True
    assert byc["4.2"]["text"] == "4.2 另一条已独立成句。"
    assert "乙" not in byc["4.2"]["text"] and "乙" not in byc["4.1"]["text"]
