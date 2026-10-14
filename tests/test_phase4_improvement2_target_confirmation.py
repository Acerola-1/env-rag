"""Phase-4 improvement group 2: target identity confirmation & discovery isolation.

Every scenario drives the OWNING entries offline — evaluation._synthesized_fused_result
(conversion) and answer.run_answer (publication) — over explicit fake READ-ONLY
catalog connections and stored artifacts. Service boundary: real asyncpg.connect,
httpx posting, write SQL and unknown SQL all blow up; allow_model=False and
transport=None; zero network/DB/model. Nothing retrieval- or verification-related
is mocked to a constant; assertions check the FINAL published answer, not one helper.

Canonical identities for the stored round-1 legs are derived with the catalog's
OWN accepted extractor (``extract_document_metadata``) over the real doc names +
cover lines of the ORIGINAL parsed artifacts — the same derivation that produced
the documents table in the first place — and cross-checked to the requested code
branches. Synthetic documents use explicitly declared fixture rows (labelled
构造); nothing is fabricated from a filename and then claimed as a live catalog
read. Gold is consulted only post-hoc; expected child lists are never inputs.
"""

import asyncio
import hashlib
import json
import re
from pathlib import Path

import pytest
import test_answer as fx

from env_rag_final import answer as an
from env_rag_final import evaluation as ev
from env_rag_final.audit import identity as aid
from env_rag_final.catalog.metadata import extract_document_metadata
from env_rag_final.enumerate_.prose_enum import _unit_text_from_blocks

ROOT = Path(".")
B = ROOT / "reports/pg-retrieval/phase-4-round-1"
GOLD = json.loads(
    (ROOT / "reports/pg-retrieval/gate-2/review-r5/gold-approved.json").read_text(encoding="utf-8")
)


def _run(coro):
    return asyncio.run(coro)


def _sha(t):
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def _derived_identity(file_path: str) -> tuple[str | None, str | None]:
    """Canonical self_code/version per the catalog's own extraction rules over
    the REAL name + cover lines of the ORIGINAL sidecar (provenance: the same
    function that built the documents table)."""
    pdir = aid.PARSED_ROOT / f"{file_path}.parsed"
    bf = sorted(pdir.glob("*.blocks.jsonl"))
    cover = ""
    if bf:
        rows = [json.loads(x) for x in bf[0].read_text(encoding="utf-8").splitlines()[1:6]]
        cover = "\n".join((x.get("content") or "") for x in rows)
    rec = extract_document_metadata(file_path, cover)
    return rec.get("self_code"), rec.get("self_code_version")


IDENT = {
    "matches_frozen": True,
    "problems": [],
    "counts": {"lightrag_doc_chunks": 5709},
    "source_fingerprint": fx.FP,
    "catalog_active": {"run_id": fx.RUN, "snapshot_id": fx.SNAP},
    "search_active": fx.SEARCH,
    "gold_sha": fx.GOLD_SHA,
    "env_sha": "env-1",
}


class GatedConn:
    """Fake read-only catalog for both stored and synthetic legs.

    cat = {"docs": {doc_id: {"file_path", "self_code", "self_code_version",
                              "row_missing"?}},
           "scopes": {(doc_id, number): row}, "scope_units": {scope_id: [uid]},
           "units": {(doc_id, uid): row}, "table_units": {doc_id: [rows]}}
    """

    def __init__(self, cat: dict):
        self.cat = cat
        self.queries: list[tuple[str, str, tuple]] = []

    async def fetch(self, sql: str, *args):
        self.queries.append(("fetch", sql, args))
        u = sql.upper()
        assert "INSERT" not in u and "UPDATE" not in u and "DELETE" not in u and "CREATE" not in u
        if "scope_units su" in sql:
            return [{"unit_id": x} for x in self.cat["scope_units"].get(args[2], [])]
        if "FROM env_rag.scopes" in sql and "number=$4" in sql:
            row = self.cat["scopes"].get((args[2], args[3]))
            return [dict(row)] if row else []
        if "unit_kind='table'" in sql:
            return [dict(r) for r in self.cat.get("table_units", {}).get(args[2], [])]
        if "unit_chunk_links" in sql:
            return []
        raise AssertionError(f"unexpected SQL: {sql!r}")

    async def fetchrow(self, sql: str, *args):
        self.queries.append(("fetchrow", sql, args))
        u = sql.upper()
        assert "INSERT" not in u and "UPDATE" not in u and "DELETE" not in u
        if "requires_span" in sql:
            return self.cat["units"].get((args[2], args[3]))
        if "self_code_version FROM env_rag.documents" in sql:
            meta = self.cat["docs"].get(args[2])
            if meta is None or meta.get("row_missing"):
                return None
            return {
                "doc_name": meta["file_path"],
                "self_code": meta.get("self_code"),
                "self_code_version": meta.get("self_code_version"),
            }
        raise AssertionError(f"unexpected SQL: {sql!r}")

    async def fetchval(self, sql: str, *args):
        self.queries.append(("fetchval", sql, args))
        if "doc_name FROM env_rag.documents" in sql:
            meta = self.cat["docs"].get(args[2])
            return meta["file_path"] if meta else None
        raise AssertionError(f"unexpected SQL: {sql!r}")

    async def close(self):
        pass


def _install(monkeypatch, cat, ident=None):
    conn = GatedConn(cat)
    # 已存身份材料：stored legs pass their replay file's own identity_before;
    # synthetic fixtures fall back to the declared fixture identity.
    ib = dict(ident or IDENT)

    async def capture(_v):
        return {
            "identity": {
                "public_counts": ib["counts"],
                "catalog_active": ib["catalog_active"],
                "source_fingerprint": ib["source_fingerprint"],
                "search_active": ib["search_active"],
                "gold_sha": ib["gold_sha"],
                "env_sha": ib["env_sha"],
            },
            "problems": [],
            "matches_frozen": True,
        }

    monkeypatch.setattr(an, "_capture_identity", capture)

    def guard(values, workspace):
        if any(k in values for k in ("QDRANT_WORKSPACE", "NEO4J_WORKSPACE", "POSTGRES_WORKSPACE")):
            raise an.AdapterError("workspace override env forbidden")

    monkeypatch.setattr(an, "verify_config_guard", guard)
    monkeypatch.setattr(an, "verify_gold_guard", lambda p: fx.GOLD_SHA)
    gold_path = Path("reports/pg-retrieval/gate-2/review-r5/gold-approved.json")
    monkeypatch.setattr(an, "GOLD_PATH", gold_path)

    async def current(_c, **_kw):
        return {
            "state": "current",
            "active_snapshot_id": ib["catalog_active"]["snapshot_id"],
            "stored_fingerprint": ib["source_fingerprint"],
        }

    import env_rag_final.catalog.builder as builder
    import env_rag_final.catalog.source as source_mod
    import env_rag_final.enumerate_.table_enum as table_enum_mod
    import env_rag_final.search.expand as expand_mod

    monkeypatch.setattr(builder, "check_stale", current)
    monkeypatch.setattr(table_enum_mod, "check_stale", current)

    async def no_fp(_c, _w):
        return ""

    monkeypatch.setattr(builder, "_live_source_fingerprint", no_fp)

    async def fresh(_c, _w, parsed_root=None):
        return {
            "state": "current",
            "catalog_snapshot_id": ib["catalog_active"]["snapshot_id"],
            "search_id": ib["search_active"],
        }

    monkeypatch.setattr(expand_mod, "check_search_stale", fresh)
    monkeypatch.setattr(source_mod, "SourceAdapter", fx.FakeAdapter)

    def boom(**_kw):
        raise AssertionError("no real DB connection in offline diagnosis")

    monkeypatch.setattr(an.asyncpg, "connect", boom)

    def http_boom(*_a, **_k):
        raise AssertionError("no HTTP in offline diagnosis")

    monkeypatch.setattr(an.httpx.AsyncClient, "post", http_boom)
    return conn


VALUES = dict(fx.VALUES)
VALUES["EMBEDDING_MODEL"] = __import__(
    "env_rag_final.local_adapter", fromlist=["EMBEDDING_MODEL"]
).EMBEDDING_MODEL
VALUES["EMBEDDING_DIM"] = str(
    __import__("env_rag_final.local_adapter", fromlist=["EMBEDDING_DIM"]).EMBEDDING_DIM
)


def _stored_cat(qid: str) -> tuple[dict, dict]:
    """Build the fake catalog for one STORED round-1 local leg: prose rows from
    the leg's own runtime, table rows from the ORIGINAL sidecars, doc identities
    derived with the catalog extractor over real artifacts."""
    rt = json.loads((B / f"legs/r1/local/{qid}/answer/answer-runtime-latest.json").read_text())
    fused = json.loads((B / f"inputs/local/{qid}-fusion.json").read_text())
    fr = fused["results"][0]
    doc_fp = {u["doc_id"]: u["file_path"] for u in fr["usable"] if u.get("file_path")}
    cat = {"docs": {}, "scopes": {}, "scope_units": {}, "units": {}, "table_units": {}}
    for d, fp in doc_fp.items():
        code, ver = _derived_identity(fp)
        cat["docs"][d] = {"file_path": fp, "self_code": code, "self_code_version": ver}
    for e in rt["results"][0]["expansions"]:
        doc_id, sid_, uids = e.get("doc_id"), e.get("scope_id"), e.get("unit_ids") or []
        if not doc_id:
            continue
        if sid_:
            cat["scope_units"][sid_] = list(uids)
            num = sid_.rsplit(":", 1)[-1]
            cat["scopes"][(doc_id, num)] = {
                "scope_id": sid_,
                "scope_kind": "chapter" if "." not in num else "clause",
                "title": None,
                "number": num,
                "confirm_status": "confirmed",
            }
            pdir = aid.PARSED_ROOT / f"{doc_fp[doc_id]}.parsed"
            for uid in uids:
                text = _unit_text_from_blocks(pdir, uid) or ""
                cat["units"][(doc_id, uid)] = {
                    "unit_id": uid,
                    "unit_kind": "block",
                    "heading": "",
                    "requires_span": False,
                    "content_length": len(text),
                    "locator": json.dumps({"blockid": uid}),
                }
        if e.get("kind") == "table" and e.get("table_number"):
            pdir = aid.PARSED_ROOT / f"{doc_fp[doc_id]}.parsed"
            tj = sorted(pdir.glob("*.tables.json"))
            tables = json.loads(tj[0].read_text(encoding="utf-8")).get("tables") or {}
            rows = []
            for order, (tid, entry) in enumerate(
                sorted(tables.items(), key=lambda kv: int(str(kv[0]).rsplit("-", 1)[-1])), start=1
            ):
                cap = (entry or {}).get("caption") or ""
                m = re.search(r"[表图]\s*[0-9０-９]+", cap)
                rows.append(
                    {
                        "unit_id": tid,
                        "unit_order": order,
                        "table_seq": int(re.sub(r"\D", "", m.group(0))) if m else None,
                        "caption": cap or None,
                        "heading": (entry or {}).get("heading") or None,
                        "locator": json.dumps({"blockid": (entry or {}).get("blockid") or tid}),
                    }
                )
            cat["table_units"][doc_id] = rows
    return cat, {"runtime": rt, "fused": fused}


def _run_stored(monkeypatch, tmp_path, qid):
    cat, meta = _stored_cat(qid)
    conn = _install(monkeypatch, cat, ident=meta["fused"]["identity_before"])
    fused_p = B / f"inputs/local/{qid}-fusion.json"
    rerank_p = B / f"inputs/local/{qid}-rerank.json"
    rt = meta["runtime"]
    q = rt["results"][0]["query"]
    cat_over = {qid: ev.COUNTER_CATEGORIES[qid]} if qid in ev.COUNTER_CATEGORIES else None
    report = _run(
        an.run_answer(
            tmp_path / "run",
            [qid],
            rerank_report_path=rerank_p,
            fused_report_path=fused_p,
            conn=conn,
            values=VALUES,
            allow_model=False,
            transport=None,
            category_overrides=cat_over,
        )
    )
    return report, q


# ---------------------------------------------------------------------------
# matrix 1: stored round-1 legs replayed on the ORIGINAL path inputs
# ---------------------------------------------------------------------------

_PROSE001 = "doc-68a03b50e1ba1ffc6a0116529f694fe1"
_PROSE006 = "doc-257d8cf3fdf90e76c31908c4f92fc1a1"
_GB8978 = "doc-b45c510232ed4d2452b0f5b2a13434e4"
_FOREIGN_68A0 = "doc-68a03b50e1ba1ffc6a0116529f694fe1"


def _audit_of(out):
    ss = out.get("scope_selection") or {}
    return ss.get("target_confirmation") or {}


def _pub_docs(out):
    return {it.get("doc_id") for it in (out.get("answer") or {}).get("items") or []}


def test_stored_prose001_gate_confirms_goal_and_excludes_foreign(monkeypatch, tmp_path):
    """[存量产物读取] prose-001/local: goal GB18466-2005 确认，GB8978 rejected、
    含修改单整合版 self_code 未知 unresolved；答案恰为该章 4 条，外来 0。"""
    report, _q = _run_stored(monkeypatch, tmp_path, "prose-enum-001")
    out = report["results"][0]
    tc = _audit_of(out)
    assert tc.get("allowed") and set(tc["allowed"]) == {_PROSE001}, tc
    assert _pub_docs(out) == {_PROSE001}
    clauses = [it.get("clause") for it in out["answer"]["items"]]
    assert sorted(clauses) == ["3.1", "3.2", "3.3", "3.4"], clauses
    assert all(
        it.get("citation_verified") and it.get("citation_reverified")
        for it in out["answer"]["items"]
    )
    assert out["coverage_status"] == "complete", out
    assert out["reverification"]["problems"] == []
    # 允许集与排除原因可复算：foreign doc 的 canonical 身份与问题分支不符
    reasons = json.dumps(tc, ensure_ascii=False)
    assert "GB8978" in reasons  # rejected doc carries its real canonical code
    assert report["model_calls_used"] == 0


def test_stored_prose006_wrong_versions_and_unknown_identity_excluded(monkeypatch, tmp_path):
    """[存量产物读取] prose-006/local: 仅 GB3095-2012 确认；同码 2026 版与
    HJ2.2 rejected、EPA 文档（self_code 未知）unresolved；答案恰 1 条 4.2。"""
    report, _q = _run_stored(monkeypatch, tmp_path, "prose-enum-006")
    out = report["results"][0]
    tc = _audit_of(out)
    assert set(tc["allowed"]) == {_PROSE006}, tc
    assert _pub_docs(out) == {_PROSE006}
    assert [it.get("clause") for it in out["answer"]["items"]] == ["4.2"]
    assert out["coverage_status"] == "complete", out
    assert all(
        "2026" in r or "HJ2.2" in r or "self_code" in r or "row" in r
        for r in [str(x) for x in tc["rejected"] + tc["unresolved"]]
    )


def test_stored_neg004_foreign_table_rows_never_enter_answer(monkeypatch, tmp_path):
    """[存量产物读取] neg-004/local：GB18466 表1 的 31 行属于另一文档，
    不进入答案集合；13 目标行保留、verified+reverified。"""
    report, _q = _run_stored(monkeypatch, tmp_path, "neg-004")
    out = report["results"][0]
    tc = _audit_of(out)
    assert set(tc["allowed"]) == {_GB8978}, tc
    assert _pub_docs(out) == {_GB8978}
    items = out["answer"]["items"]
    assert len(items) == 13, len(items)
    assert all(it.get("citation_verified") and it.get("citation_reverified") for it in items)
    assert out["coverage_status"] == "complete", out
    blob = json.dumps(items, ensure_ascii=False)
    assert "粪大肠菌群" not in blob  # GB18466 行不再出现在答案里


def test_stored_table001_control_unchanged(monkeypatch, tmp_path):
    """[存量产物读取] 正例对照：单目标发现腿修复前后发布一致（13 行、complete）。"""
    report, _q = _run_stored(monkeypatch, tmp_path, "table-enum-001")
    out = report["results"][0]
    tc = _audit_of(out)
    assert set(tc["allowed"]) == {_GB8978}
    assert len(out["answer"]["items"]) == 13
    assert out["coverage_status"] == "complete", out


# ---------------------------------------------------------------------------
# synthetic-leg harness (matrix 2-7): conversion + full entry
# ---------------------------------------------------------------------------


def _usable(doc_id, file_path, content, discovery="entity", membership=False):
    p = {
        "path": "local",
        "workspace": "default",
        "chunk_id": f"{doc_id}-chunk-001",
        "doc_id": doc_id,
        "file_path": file_path,
        "discovery": "doc_attribution" if membership else discovery,
        "score": None,
        "similarity_order": 0,
        "reached_via": ["entity:test"],
    }
    if membership:
        p["membership_basis"] = "cover attribution recorded by 5.3 route"
    return {
        "workspace": "default",
        "chunk_id": f"{doc_id}-chunk-001",
        "doc_id": doc_id,
        "file_path": file_path,
        "verified": True,
        "content_sha256": _sha(content),
        "content_len": len(content),
        "content": content,
        "paths": [p],
    }


def _synth_leg(
    tmp_path,
    monkeypatch,
    question,
    docs: dict,
    qid="syn-q",
    typed_promotion=None,
    upstream=None,
    return_conn=False,
):
    """docs: doc_id -> {file_path, prose, self_code, self_code_version,
    identity_row: bool, membership: bool}. upstream is an optional callback
    that mutates the synthesized fused row into a REAL 5.3-published shape
    (typed doc_attribution targets, allowed_set_basis, resolution traces) —
    the shapes neg-010's stored fusion input exhibits verbatim."""
    cat = {"docs": {}, "scopes": {}, "scope_units": {}, "units": {}, "table_units": {}}
    usable = []
    for d, spec in docs.items():
        name = spec["file_path"]
        cat["docs"][d] = {
            "file_path": name,
            "self_code": spec.get("self_code"),
            "self_code_version": spec.get("self_code_version"),
            "row_missing": not spec.get("identity_row", True),
        }
        scope_id = f"{d}:scope:4"
        prose = spec["prose"]
        pdir = tmp_path / f"{name}.parsed"
        pdir.mkdir(exist_ok=True, parents=True)
        (pdir / "x.blocks.jsonl").write_text(
            "\n".join(
                [json.dumps({"type": "meta"})]
                + [
                    json.dumps(
                        {"type": "content", "blockid": f"{d}-u1", "content": prose},
                        ensure_ascii=False,
                    )
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        cat["scope_units"][scope_id] = [f"{d}-u1"]
        cat["scopes"][(d, "4")] = {
            "scope_id": scope_id,
            "scope_kind": "chapter",
            "title": None,
            "number": "4",
            "confirm_status": "confirmed",
        }
        cat["units"][(d, f"{d}-u1")] = {
            "unit_id": f"{d}-u1",
            "unit_kind": "block",
            "heading": "",
            "requires_span": False,
            "content_length": len(prose),
            "locator": json.dumps({"blockid": f"{d}-u1"}),
        }
        usable.append(_usable(d, name, prose, membership=spec.get("membership", False)))
    monkeypatch.setattr(aid, "PARSED_ROOT", tmp_path)
    conn = _install(monkeypatch, cat)
    q = {"query_id": qid, "question": question, "workspace": "default"}
    fused_result = ev._synthesized_fused_result(q, usable, path_label="local")
    if typed_promotion is not None:
        fused_result["typed_targets"] = typed_promotion
    if upstream is not None:
        upstream(fused_result)
    fp = tmp_path / "fusion-runtime-latest.json"
    rp = tmp_path / "rerank-runtime-latest.json"
    fp.write_text(
        json.dumps(
            {"task": "t", "identity_before": IDENT, "results": [fused_result]}, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    rp.write_text(
        json.dumps({"task": "t", "identity_before": IDENT, "results": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "gold2.json").write_text(
        json.dumps(
            {"questions": [dict(q, category="prose_enum")], "counter_examples": []},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(an, "GOLD_PATH", tmp_path / "gold2.json")
    report = _run(
        an.run_answer(
            tmp_path / "run",
            [qid],
            rerank_report_path=rp,
            fused_report_path=fp,
            conn=conn,
            values=VALUES,
            allow_model=False,
            transport=None,
        )
    )
    if return_conn:
        return report, fused_result, conn
    return report, fused_result


_G = "doc-synth-goal"
_X = "doc-synth-foreign"
_M = "doc-synth-modify"
_G_PROSE = "## 4 规定\n4.1 目标文档的要求一。\n4.2 目标文档的要求二。"
_X_PROSE = "## 4 规定\n4.1 外来文档的要求。\n4.2 另一条。"


def _goal_doc(**over):
    base = {
        "file_path": "synth-GB9001-2020.pdf",
        "prose": _G_PROSE,
        "self_code": "GB9001",
        "self_code_version": "2020",
    }
    base.update(over)
    return base


def _foreign_doc(**over):
    base = {
        "file_path": "synth-GB9002-2019.pdf",
        "prose": _X_PROSE,
        "self_code": "GB9002",
        "self_code_version": "2019",
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# REAL 5.3-published evidence shapes (r2 A). Field-for-field the shapes the
# accepted producers emit: search/query.py _doc_attribution_route records the
# membership_basis string and the catalog_row citation; fusion._allowed_docs
# republishes the typed target into allowed_set_basis.verified_attributions.
# neg-010's STORED pg fusion input (phase-4-round-1/inputs/pg/) exhibits both
# verbatim — these fixtures are 构造 from that存量读取 shape, never live reads.
# ---------------------------------------------------------------------------

_ATTR_BASIS = "doc name/title carries the requested code (self_code=None)"


def _typed_attribution(doc_id, doc_name, workspace="default", snapshot_id=None, **over):
    t = {
        "target_type": "doc",
        "workspace": workspace,
        "doc_id": doc_id,
        "doc_name": doc_name,
        "self_code": None,
        "self_code_version": None,
        "discovery": "doc_attribution",
        "membership_basis": _ATTR_BASIS,
        "citation": {
            "kind": "catalog_row",
            "workspace": workspace,
            "snapshot_id": (
                IDENT["catalog_active"]["snapshot_id"] if snapshot_id is None else snapshot_id
            ),
            "doc_id": doc_id,
        },
        "citation_verified": True,
    }
    t.update(over)
    return t


def _allowed_set_basis(goal_docs, attr_docs, basis=_ATTR_BASIS):
    return {
        "resolved_code_targets": [list(goal_docs)],
        "verified_attributions": [
            {
                "doc_id": d,
                "self_code": None,
                "self_code_version": None,
                "membership_basis": basis,
                "note": "verified doc_attribution target joins the allowed set; "
                "no self_code is fabricated",
            }
            for d in attr_docs
        ],
    }


# matrix 2 — conversion no longer promotes; full entry still confirms matches
def test_conversion_does_not_promote_and_entry_confirms_without_fallback(monkeypatch, tmp_path):
    report, fused = _synth_leg(
        tmp_path,
        monkeypatch,
        "GB 9001-2020 的 4 章规定了哪些要求？逐条列出。",
        {_G: _goal_doc(), _X: _foreign_doc()},
    )
    # discovery retained, nothing promoted, no fake 5.3 resolution
    assert fused["typed_targets"] == []
    assert fused["targets_resolved"] == []
    assert fused.get("targets_confirmed") is False
    assert fused.get("discovery_docs") == [_G, _X]
    out = report["results"][0]
    tc = _audit_of(out)
    # the gate must NOT silently fall back to all candidate docs
    assert set(tc["allowed"]) == {_G}, tc
    assert _pub_docs(out) == {_G}
    assert out["coverage_status"] == "complete", out
    # discovery list/paths preserved for audit (no PG calls, no injection)
    assert out["replay"]["typed_targets"] == []


def test_promotion_of_mismatched_code_cannot_bypass_gate(monkeypatch, tmp_path):
    """伪造 typed code_exact（或目录自报名称正确）不能绕过 canonical 确认。"""
    fake_typed = [
        {"target_type": "doc", "workspace": "default", "doc_id": _X, "discovery": "code_exact"}
    ]
    report, _f = _synth_leg(
        tmp_path,
        monkeypatch,
        "GB 9001-2020 的 4 章规定了哪些要求？逐条列出。",
        {_G: _goal_doc(), _X: _foreign_doc()},
        typed_promotion=fake_typed,
    )
    out = report["results"][0]
    tc = _audit_of(out)
    assert _X not in set(tc.get("allowed", [])), tc
    assert _pub_docs(out) == {_G}


# matrix 3 — foreign-only / wrong version / unknown / missing row
def test_only_foreign_discovery_is_unconfirmed_not_corpus_missing(monkeypatch, tmp_path):
    report, _f = _synth_leg(
        tmp_path,
        monkeypatch,
        "GB 9001-2020 的 4 章规定了哪些要求？逐条列出。",
        {_X: _foreign_doc()},
    )
    out = report["results"][0]
    assert out["answer"]["items"] == [] or out["coverage_status"] != "complete"
    assert out["coverage_status"] in ("partial", "ambiguous"), out
    assert out["coverage_status"] != "missing"
    assert any("not a verified" in f or "本路" in f or "unresolved" in f for f in out["flags"]), (
        out["flags"]
    )


def test_wrong_year_same_code_rejected_and_missing_row_unresolved(monkeypatch, tmp_path):
    report, _f = _synth_leg(
        tmp_path,
        monkeypatch,
        "GB 9001-2020 的 4 章规定了哪些要求？逐条列出。",
        {
            "doc-synth-oldver": _goal_doc(
                self_code_version="1990", file_path="synth-GB9001-1990.pdf"
            ),
            "doc-synth-norow": {
                "file_path": "synth-GB9001-norow.pdf",
                "prose": _G_PROSE,
                "identity_row": False,
            },
        },
    )
    out = report["results"][0]
    tc = _audit_of(out)
    assert tc.get("allowed", []) == []
    assert out["answer"]["items"] == []
    assert out["coverage_status"] in ("partial", "ambiguous"), out
    reasons = json.dumps(tc, ensure_ascii=False)
    assert "1990" in reasons and ("row" in reasons or "missing" in reasons)


def test_unknown_self_code_plain_request_excluded(monkeypatch, tmp_path):
    report, _f = _synth_leg(
        tmp_path,
        monkeypatch,
        "GB 9001-2020 的 4 章规定了哪些要求？逐条列出。",
        {_M: _goal_doc(self_code=None, self_code_version=None, file_path="synth-含修改单.pdf")},
    )
    out = report["results"][0]
    tc = _audit_of(out)
    assert tc.get("allowed", []) == []
    assert any("self_code" in str(x) for x in tc["unresolved"]), tc


# matrix 4 — legitimate multi-target comparison; partial confirmation never complete
def test_two_code_request_confirms_both_and_completes(monkeypatch, tmp_path):
    h = "doc-synth-two1"
    i = "doc-synth-two2"
    report, _f = _synth_leg(
        tmp_path,
        monkeypatch,
        "对比 GB 9001-2020 与 GB 9002-2019 的 4.1 条要求。",
        {
            h: _goal_doc(),
            i: _foreign_doc(),
        },
    )
    out = report["results"][0]
    tc = _audit_of(out)
    assert set(tc["allowed"]) == {h, i}, tc
    assert _pub_docs(out) == {h, i}
    assert out["coverage_status"] == "complete", out


def test_comparison_missing_one_target_keeps_items_but_not_complete(monkeypatch, tmp_path):
    report, _f = _synth_leg(
        tmp_path,
        monkeypatch,
        "对比 GB 9001-2020 与 GB 9002-2019 的 4.1 条要求。",
        {_G: _goal_doc()},
    )
    out = report["results"][0]
    tc = _audit_of(out)
    assert set(tc["allowed"]) == {_G}
    assert len(out["answer"]["items"]) == 1  # 题面点名 4.1 条：合法证据保留
    assert out["coverage_status"] != "complete", out
    assert any("9002" in f for f in out["flags"]), out["flags"]


# matrix 5 — attribution positive / negative pair
_M_NAME = "synth-GB9001-含2020修改单.pdf"


def _upstream_attributing():
    """Mutate the synthesized row into the REAL 5.3 published attribution
    shape: a typed doc_attribution target (catalog_row citation bound to this
    workspace + the active snapshot) cross-backed by
    allowed_set_basis.verified_attributions. NO candidate-side label: a single
    'recorded by 5.3' string on the candidate path is not positive evidence
    (improvement-2 r2 A1/A5)."""

    def upstream(row):
        row["typed_targets"] = [_typed_attribution(_M, _M_NAME)]
        row["allowed_set_basis"] = _allowed_set_basis([_G], [_M])
        row["path_provenance"] = {"path": "fusion", "discovery_only": False}
        return row

    return upstream


def test_attribution_evidence_honored_for_related_request(monkeypatch, tmp_path):
    report, _f = _synth_leg(
        tmp_path,
        monkeypatch,
        "GB 9001-2020 的 4 章规定了哪些要求？（含修改单、相关文件）",
        {
            _G: _goal_doc(),
            _M: _goal_doc(
                self_code=None,
                self_code_version=None,
                file_path="synth-GB9001-含2020修改单.pdf",
            ),
        },
        upstream=_upstream_attributing(),
    )
    out = report["results"][0]
    tc = _audit_of(out)
    assert set(tc["allowed"]) == {_G, _M}, tc
    assert _pub_docs(out) == {_G, _M}
    assert out["coverage_status"] == "complete", out


def test_self_code_request_never_relaxed_for_attribution_docs(monkeypatch, tmp_path):
    # the SAME full structured upstream evidence as the positive leg; only
    # the request predicate differs — 自身编号 must never borrow it.
    report, _f = _synth_leg(
        tmp_path,
        monkeypatch,
        "GB 9001-2020 自身编号的 4 章规定了哪些要求？",
        {
            _G: _goal_doc(),
            _M: _goal_doc(
                self_code=None,
                self_code_version=None,
                file_path="synth-GB9001-含2020修改单.pdf",
            ),
        },
        upstream=_upstream_attributing(),
    )
    out = report["results"][0]
    tc = _audit_of(out)
    assert set(tc["allowed"]) == {_G}, tc
    assert _pub_docs(out) == {_G}
    assert any("self_code unknown" in str(x) for x in tc["unresolved"]), tc


# r2 A — the closure is BIDIRECTIONAL: every component of the published
# attribution evidence is required; unbacked or misbound evidence refuses.
def test_typed_attribution_without_allowed_set_basis_refused(monkeypatch, tmp_path):
    def upstream(row):
        row["typed_targets"] = [_typed_attribution(_M, _M_NAME)]
        row["allowed_set_basis"] = _allowed_set_basis([_G], [])  # basis NOT published
        row["path_provenance"] = {"path": "fusion", "discovery_only": False}
        return row

    report, _f = _synth_leg(
        tmp_path,
        monkeypatch,
        "GB 9001-2020 的 4 章规定了哪些要求？（含修改单、相关文件）",
        {
            _G: _goal_doc(),
            _M: _goal_doc(self_code=None, self_code_version=None, file_path=_M_NAME),
        },
        upstream=upstream,
    )
    out = report["results"][0]
    tc = _audit_of(out)
    assert set(tc["allowed"]) == {_G}, tc
    assert _pub_docs(out) == {_G}


def test_allowed_set_basis_without_typed_target_refused(monkeypatch, tmp_path):
    def upstream(row):
        row["typed_targets"] = []
        row["allowed_set_basis"] = _allowed_set_basis([_G], [_M])
        row["path_provenance"] = {"path": "fusion", "discovery_only": False}
        return row

    report, _f = _synth_leg(
        tmp_path,
        monkeypatch,
        "GB 9001-2020 的 4 章规定了哪些要求？（含修改单、相关文件）",
        {
            _G: _goal_doc(),
            _M: _goal_doc(self_code=None, self_code_version=None, file_path=_M_NAME),
        },
        upstream=upstream,
    )
    out = report["results"][0]
    tc = _audit_of(out)
    assert set(tc["allowed"]) == {_G}, tc
    assert _pub_docs(out) == {_G}


@pytest.mark.parametrize("defect", ["stale-snapshot", "foreign-workspace", "basis-boolean"])
def test_attribution_evidence_binding_defects_refuse(monkeypatch, tmp_path, defect):
    """The citation must be bound to THIS workspace + the ACTIVE snapshot, and
    the membership_basis must be a recorded string — a stale snapshot, a
    foreign workspace or a bare boolean never qualifies (r2 A1/A2)."""

    def upstream(row):
        if defect == "stale-snapshot":
            typed = _typed_attribution(_M, _M_NAME, snapshot_id="snap-from-an-old-generation")
        elif defect == "foreign-workspace":
            typed = _typed_attribution(_M, _M_NAME, workspace="other")
        else:
            typed = _typed_attribution(_M, _M_NAME, membership_basis=True)
        row["typed_targets"] = [typed]
        row["allowed_set_basis"] = _allowed_set_basis([_G], [_M])
        row["path_provenance"] = {"path": "fusion", "discovery_only": False}
        return row

    report, _f = _synth_leg(
        tmp_path,
        monkeypatch,
        "GB 9001-2020 的 4 章规定了哪些要求？（含修改单、相关文件）",
        {
            _G: _goal_doc(),
            _M: _goal_doc(self_code=None, self_code_version=None, file_path=_M_NAME),
        },
        upstream=upstream,
    )
    out = report["results"][0]
    tc = _audit_of(out)
    assert set(tc["allowed"]) == {_G}, tc
    assert _pub_docs(out) == {_G}


def test_attribution_target_without_chunks_still_gets_full_read(monkeypatch, tmp_path):
    """r2 A3 own-entry mirror: the confirmed attribution document has NO
    usable chunk — it must still be registered and FULLY read, both targets
    delivered."""

    def upstream(row):
        row["usable"] = [u for u in row["usable"] if u["doc_id"] != _M]
        row["typed_targets"] = [_typed_attribution(_M, _M_NAME)]
        row["allowed_set_basis"] = _allowed_set_basis([_G], [_M])
        row["targets_resolved"] = [
            {"code": "GB9001", "version": "2020", "docs": [_G], "versions": ["2020"]}
        ]
        row["path_provenance"] = {"path": "fusion", "discovery_only": False}
        return row

    report, _f = _synth_leg(
        tmp_path,
        monkeypatch,
        "GB 9001-2020 的 4 章规定了哪些要求？含修改单和相关文件。",
        {
            _G: _goal_doc(),
            _M: _goal_doc(self_code=None, self_code_version=None, file_path=_M_NAME),
        },
        upstream=upstream,
    )
    out = report["results"][0]
    tc = _audit_of(out)
    assert set(tc["allowed"]) == {_G, _M}, tc
    assert _pub_docs(out) == {_G, _M}
    assert out["coverage_status"] == "complete", out
    assert any(_M in f and "FULL scope read" in f for f in out["flags"]), out["flags"]
    assert report["model_calls_used"] == 0


def test_similar_name_without_membership_evidence_excluded(monkeypatch, tmp_path):
    report, _f = _synth_leg(
        tmp_path,
        monkeypatch,
        "GB 9001-2020 的 4 章规定了哪些要求？（含修改单、相关文件）",
        {
            _G: _goal_doc(),
            "doc-synth-namewash": _goal_doc(
                self_code=None, self_code_version=None, file_path="synth-像GB9001的别的.pdf"
            ),
        },
    )
    out = report["results"][0]
    tc = _audit_of(out)
    assert set(tc["allowed"]) == {_G}, tc


# matrix 6 — code-less conservativism + multi-version contract preserved
def test_codeless_scopeless_discovery_never_silently_completes(monkeypatch, tmp_path):
    report, _f = _synth_leg(
        tmp_path,
        monkeypatch,
        "这一章的规定有哪些？逐条列出。",
        {_G: _goal_doc(), _X: _foreign_doc()},
    )
    out = report["results"][0]
    assert out["coverage_status"] == "ambiguous", out
    assert any(
        "no code branch" in f or "scope basis" in f or "never define the answer scope" in f
        for f in out["flags"]
    ), out["flags"]
    assert (out["answer"] or {}).get("items", []) == []


def test_codeless_trusted_upstream_resolution_still_confirms(monkeypatch, tmp_path):
    """r2 B3 owning POSITIVE, paired with the promotion refusals: a code-less
    question whose TRUSTWORTHY upstream replay carries the real 5.3 code_exact
    resolution shape (code+version+docs) keeps its scope — but the resolution
    is a PROPOSAL: every document is re-confirmed against the current catalog
    through the guarded connection, and discovered noise (the foreign doc) is
    still rejected by canonical identity."""

    def upstream(row):
        row["targets_resolved"] = [
            {"code": "GB9001", "version": "2020", "docs": [_G], "versions": ["2020"]}
        ]
        # a REAL 5.3 fusion row carries no local-discovery markers at all
        # (stored inputs/pg/neg-010-fusion.json: path_provenance/targets_
        # confirmed/discovery_docs absent — observed as None)
        row["path_provenance"] = {"path": "fusion", "discovery_only": False}
        row.pop("targets_confirmed", None)
        row.pop("discovery_docs", None)
        return row

    report, _f = _synth_leg(
        tmp_path,
        monkeypatch,
        "第 4 章规定了哪些要求？逐项列出。",
        {_G: _goal_doc(), _X: _foreign_doc()},
        upstream=upstream,
    )
    out = report["results"][0]
    tc = _audit_of(out)
    assert set(tc["allowed"]) == {_G}, tc
    assert _pub_docs(out) == {_G}
    assert out["coverage_status"] == "complete", out
    assert "upstream 5.3" in tc["branch_source"], tc["branch_source"]


def test_codeless_local_selfreport_resolution_ignored(monkeypatch, tmp_path):
    """r2 B1/B4: pure local input self-reporting a code-carrying
    targets_resolved confirms NOTHING — a discovery-only path cannot
    bootstrap its own scope. Explicit ambiguous, empty scope, the proposal
    and its refusal reason stay in the audit."""

    def upstream(row):
        row["targets_resolved"] = [
            {"code": "GB9001", "version": "2020", "docs": [_G], "versions": ["2020"]}
        ]
        return row

    report, _f = _synth_leg(
        tmp_path,
        monkeypatch,
        "第 4 章规定了哪些要求？逐项列出。",
        {_G: _goal_doc(), _X: _foreign_doc()},
        upstream=upstream,
    )
    out = report["results"][0]
    assert out["coverage_status"] == "ambiguous", out
    assert not ((out.get("answer") or {}).get("items") or [])
    assert not (out["scope_selection"].get("selected_docs") or [])
    tc = _audit_of(out)
    kept = tc["discovery_proposals_kept_for_audit"]
    assert any(p.get("kind") == "targets_resolved" and p.get("code") == "GB9001" for p in kept)
    assert "discovery-only" in tc["refusal_basis"], tc


def test_versionless_code_branch_allows_all_versions_completely(monkeypatch, tmp_path):
    v2 = "doc-synth-v2"
    report, _f = _synth_leg(
        tmp_path,
        monkeypatch,
        "GB 9001 这一标准的所有版本中 4 章各规定了什么？逐版列出。",
        {
            _G: _goal_doc(),
            v2: _goal_doc(
                self_code_version="2025", file_path="synth-GB9001-2025.pdf", prose=_X_PROSE
            ),
        },
    )
    out = report["results"][0]
    tc = _audit_of(out)
    assert set(tc["allowed"]) == {_G, v2}, tc
    assert out["coverage_status"] == "complete", out


def test_pg_upstream_missing_status_preserved(monkeypatch, tmp_path):
    """PG 路径验证过的 missing 保持 missing（本地零发现的保守态与其区分）。"""
    conn = _install(
        monkeypatch, {"docs": {}, "scopes": {}, "scope_units": {}, "units": {}, "table_units": {}}
    )
    q = {"query_id": "pgm", "question": "GB 9001-2020 的 4 章规定？", "workspace": "default"}
    (tmp_path / "gold3.json").write_text(
        json.dumps(
            {"questions": [dict(q, category="prose_enum")], "counter_examples": []},
            ensure_ascii=False,
        )
    )
    monkeypatch.setattr(an, "GOLD_PATH", tmp_path / "gold3.json")
    fused = {
        "query_id": "pgm",
        "query": q["question"],
        "workspace": "default",
        "pg": {"status": "missing", "discovery_total": 0},
        "targets_resolved": [],
        "typed_targets": [],
        "usable": [],
        "status": "missing",
        "degraded": [],
        "budget": {"limit": 40, "kept": 0, "truncated": []},
    }
    fp = tmp_path / "f.json"
    rp = tmp_path / "r.json"
    fp.write_text(
        json.dumps({"task": "t", "identity_before": IDENT, "results": [fused]}, ensure_ascii=False)
    )
    rp.write_text(json.dumps({"task": "t", "identity_before": IDENT, "results": []}))
    report = _run(
        an.run_answer(
            tmp_path / "run",
            ["pgm"],
            rerank_report_path=rp,
            fused_report_path=fp,
            conn=conn,
            values=VALUES,
            allow_model=False,
            transport=None,
        )
    )
    out = report["results"][0]
    assert out["coverage_status"] == "missing", out


# matrix 7 — noise never degrades a confirmed target
def test_noise_ambiguous_does_not_pollute_confirmed_answer(monkeypatch, tmp_path):
    noise_scopeless = "doc-synth-noise-amb"
    cat_noise = {
        "file_path": "synth-noise.pdf",
        "prose": "## 4 规定\n4.1 噪声文档要求。",
        "self_code": "GB9003",
        "self_code_version": "2001",
    }
    report, _f = _synth_leg(
        tmp_path,
        monkeypatch,
        "GB 9001-2020 的 4 章规定了哪些要求？逐条列出。",
        {_G: _goal_doc(), noise_scopeless: cat_noise},
    )
    out = report["results"][0]
    tc = _audit_of(out)
    assert set(tc["allowed"]) == {_G}
    assert _pub_docs(out) == {_G}
    assert out["coverage_status"] == "complete", out
    sel = [e for e in out["expansions"] if e.get("selected")]
    assert {e["doc_id"] for e in sel} == {_G}
