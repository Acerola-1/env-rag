"""Improvement-3 OFFLINE diagnosis driver — file-enum-005/local missing docs.

Replays the four bounded samples (file-enum-005/local FAIL, file-enum-005/pg
CONTROL, file-enum-002/local annual-report pagination control,
file-enum-001/local same-code multi-version control) through the OWNING entry
answer.run_answer with allow_model=False and transport=None, over their OWN
stored fused/rerank replay files and stored identities. ZERO real
network/DB/model/embedding/rerank requests; writes are refused by the fake.

Catalog rows come VERBATIM from the SHA-protected stored
reports/pg-retrieval/gate-2/replay.json document_enumeration row set (221 rows
read from the frozen active catalog — 存量产物读取, not constructed). The two
68a0-style unknown_fields flags are backed by the stored expansion warnings of
round 1 (existence recorded; field names were not — flagged 离线重建).

Two labeled controlled variants isolate the causal parameters:
  * searchid-variant: identical stored local fused EXCEPT pg.search_id set to
    the ACTIVE frozen search id (构造参数对照) — proves the attribution route's
    dependence on the replayed search_id parameter with REAL call args.
  * pagesize-variant: real enumerate entry forced to page_size=2 (构造参数) —
    proves the annual-report set never depends on top-k.

Gold is consulted only POST-HOC for the set reconciliation; expected doc ids
are never inputs. PG data is never injected into the local inputs.

Regenerate: .venv/bin/python reports/pg-retrieval/phase-4-improvement-3-diagnosis/diagnose_file_enum_offline.py
"""

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import test_phase4_improvement2_target_confirmation as tc  # noqa: E402  (reuses VALUES/install pattern)

from env_rag_final import answer as an  # noqa: E402

OUT = Path(__file__).resolve().parent
B = ROOT / "reports/pg-retrieval/phase-4-round-1"
GOLD = json.loads(
    (ROOT / "reports/pg-retrieval/gate-2/review-r5/gold-approved.json").read_text(encoding="utf-8")
)
ACTIVE_SEARCH = "872d689343a9cbb6"


class MP:
    def __init__(self):
        self._ps = []

    def setattr(self, target, name, value=None):
        p = patch.object(target, name, value)
        p.start()
        self._ps.append(p)

    def undo(self):
        while self._ps:
            self._ps.pop().stop()


def catalog_rows_from_stored() -> dict[str, dict]:
    """221 rows VERBATIM from the SHA-protected gate-2 replay (存量产物读取)."""
    data = json.loads((ROOT / "reports/pg-retrieval/gate-2/replay.json").read_text())
    found: dict[str, dict] = {}

    def walk(o):
        if isinstance(o, dict):
            if o.get("discovery") == "document_enumeration" and o.get("doc_id"):
                found[o["doc_id"]] = {
                    "doc_id": o["doc_id"],
                    "doc_name": o.get("doc_name"),
                    "title": o.get("title"),
                    "self_code": o.get("self_code"),
                    "self_code_version": o.get("self_code_version"),
                    "doc_type": o.get("doc_type"),
                }
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)
    assert len(found) >= 200, len(found)
    # 68a0 unknown_fields existence is recorded by the stored round-1 expansion
    # warnings ("1 matched docs have unknown metadata fields") on BOTH legs —
    # the only field-level fact the historical artifacts prove; the concrete
    # field names were never published (flagged 离线重建).
    found["doc-68a03b50e1ba1ffc6a0116529f694fe1"]["unknown_fields"] = [
        "<存量 warning 证实存在；字段名未入历史工件>"
    ]
    return found


ALL_ROWS = catalog_rows_from_stored()


class EnumConn:
    """Fake read-only catalog/search connection evaluating the REAL predicate
    shapes over the stored row set; every call records its actual arguments."""

    def __init__(self, snapshot_id: str, active_search_id: str | None):
        self.snapshot_id = snapshot_id
        self.active_search_id = active_search_id
        self.queries: list[tuple] = []
        self.attribution_calls: list[dict] = []

    # ---- predicate evaluation (real SQL parameter positions) --------------
    def _matching(self, pred: str, pargs: tuple) -> list[dict]:
        code_branches = re.findall(
            r"\(self_code = \$(\d+)(?: AND self_code_version IN \(([^)]*)\))?\)", pred
        )
        like = re.search(r"doc_name LIKE '%' \|\| \$(\d+) \|\| '%'", pred)
        out_rows = []
        for row in ALL_ROWS.values():
            if code_branches:
                hit = False
                for n, vers in code_branches:
                    code = pargs[int(n) - 3]
                    if (row.get("self_code") or "") != code:
                        continue
                    if vers:
                        wanted = [pargs[int(v) - 3] for v in re.findall(r"\$(\d+)", vers)]
                        if (row.get("self_code_version") or "") not in wanted:
                            continue
                    hit = True
                    break
                if hit:
                    out_rows.append(row)
            elif like:
                phrase = pargs[int(like.group(1)) - 3]
                if phrase in (row.get("doc_name") or ""):
                    out_rows.append(row)
            else:
                raise AssertionError(f"unknown predicate shape: {pred!r}")
        out_rows.sort(key=lambda r: r.get("doc_name") or "")
        return out_rows

    async def fetch(self, sql: str, *args):
        self.queries.append(("fetch", sql, list(map(str, args))))
        u = sql.upper()
        assert "INSERT" not in u and "UPDATE" not in u and "DELETE" not in u and "CREATE" not in u
        if "FROM ENV_RAG.SEARCH_DOCUMENTS" in u:
            ws, sid = args[0], args[1]
            rec = {
                "workspace": ws,
                "search_id_arg": sid,
                "tsquery": [str(a) for a in args[2:4]],
                "limit": str(args[4]),
            }
            rows = (
                [dict(r) for r in ALL_ROWS.values() if r.get("doc_name")]
                if sid and sid == self.active_search_id
                else []
            )
            rec["returned_rows"] = len(rows)
            self.attribution_calls.append(rec)
            return rows
        m = re.search(
            r"FROM env_rag\.documents\s+WHERE workspace=\$1 AND snapshot_id=\$2 AND \((.*)\)\s+ORDER BY doc_name LIMIT (\d+) OFFSET (\d+)",
            sql,
        )
        if m and "UNKNOWN_FIELDS" in u:
            ws, snap, pred, limit, offset = (
                args[0],
                args[1],
                m.group(1),
                int(m.group(2)),
                int(m.group(3)),
            )
            assert ws == "default" and snap == self.snapshot_id, (ws, snap)
            rows = self._matching(pred, tuple(args[2:]))
            return [
                dict(
                    r,
                    title_confidence=1.0,
                    unknown_fields=list(r.get("unknown_fields") or []),
                )
                for r in rows[offset : offset + limit]
            ]
        if "unit_chunk_links" in sql:
            return []
        raise AssertionError(f"unexpected SQL: {sql[:120]!r}")

    async def fetchval(self, sql: str, *args):
        self.queries.append(("fetchval", sql, list(map(str, args))))
        u = sql.upper()
        assert "INSERT" not in u and "UPDATE" not in u and "DELETE" not in u
        m = re.search(
            r"SELECT count\(\*\) FROM env_rag\.documents\s+WHERE workspace=\$1 AND snapshot_id=\$2 AND \((.*)\)",
            sql,
        )
        if m:
            assert args[1] == self.snapshot_id
            return len(self._matching(m.group(1), tuple(args[2:])))
        if "DOC_NAME FROM ENV_RAG.DOCUMENTS" in u:
            row = ALL_ROWS.get(args[2])
            return row["doc_name"] if row else None
        raise AssertionError(f"unexpected SQL: {sql[:120]!r}")

    async def fetchrow(self, sql: str, *args):
        self.queries.append(("fetchrow", sql, list(map(str, args))))
        u = sql.upper()
        assert "INSERT" not in u and "UPDATE" not in u and "DELETE" not in u
        if "CORPUS_RUNS" in u:
            assert args[0] == "default" and "ACTIVE" in u
            return {"snapshot_id": self.snapshot_id, "source_fingerprint": {"value": "fp-offline"}}
        if "SELF_CODE_VERSION FROM ENV_RAG.DOCUMENTS" in u:
            row = ALL_ROWS.get(args[2])
            if not row:
                return None
            return {
                "doc_name": row["doc_name"],
                "self_code": row["self_code"],
                "self_code_version": row["self_code_version"],
            }
        raise AssertionError(f"unexpected SQL: {sql[:120]!r}")

    async def close(self):
        pass


def _install(mp, conn, ident):
    """Same owning seams as the accepted improvement-2 harness (fake identity
    capture from the STORED fused file's own identity_before; service bombs)."""
    ib = dict(ident)

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

    mp.setattr(an, "_capture_identity", capture)

    def guard(values, workspace):
        if any(k in values for k in ("QDRANT_WORKSPACE", "NEO4J_WORKSPACE", "POSTGRES_WORKSPACE")):
            raise an.AdapterError("workspace override env forbidden")

    mp.setattr(an, "verify_config_guard", guard)
    mp.setattr(an, "verify_gold_guard", lambda p: tc.fx.GOLD_SHA)
    mp.setattr(
        an,
        "GOLD_PATH",
        Path("reports/pg-retrieval/gate-2/review-r5/gold-approved.json"),
    )

    async def current(_c, **_kw):
        return {
            "state": "current",
            "active_snapshot_id": ib["catalog_active"]["snapshot_id"],
            "stored_fingerprint": ib["source_fingerprint"],
        }

    import env_rag_final.catalog.builder as builder
    import env_rag_final.catalog.source as source_mod

    mp.setattr(builder, "check_stale", current)

    async def no_fp(_c, _w):
        return ""

    mp.setattr(builder, "_live_source_fingerprint", no_fp)
    mp.setattr(source_mod, "SourceAdapter", tc.fx.FakeAdapter)

    def boom(**_kw):
        raise AssertionError("no real DB connection in the offline diagnosis")

    mp.setattr(an.asyncpg, "connect", boom)

    def http_boom(*_a, **_k):
        raise AssertionError("no HTTP in the offline diagnosis")

    mp.setattr(an.httpx.AsyncClient, "post", http_boom)
    return conn


def _replay_one(qid, fused_p, rerank_p, mutate=None, page_size=None):
    fused = json.loads(Path(fused_p).read_text(encoding="utf-8"))
    ident = fused["identity_before"]
    if mutate:
        fused = mutate(fused)
    tmp = Path(tempfile.mkdtemp())
    fp = tmp / "fusion-runtime-latest.json"
    rp = tmp / "rerank-runtime-latest.json"
    if mutate:
        fp.write_text(json.dumps(fused, ensure_ascii=False), encoding="utf-8")
    else:
        shutil.copy(fused_p, fp)
    shutil.copy(rerank_p, rp)
    conn = EnumConn(
        ident["catalog_active"]["snapshot_id"],
        ACTIVE_SEARCH,
    )
    mp = MP()
    try:
        _install(mp, conn, ident)
        if page_size is not None:
            import env_rag_final.enumerate_.doc_enum as doc_enum_mod

            real = doc_enum_mod.enumerate_documents

            async def sized(*a, **kw):
                kw["page_size"] = page_size
                return await real(*a, **kw)

            mp.setattr(doc_enum_mod, "enumerate_documents", sized)
        report = tc._run(
            an.run_answer(
                tmp / "run",
                [qid],
                rerank_report_path=rp,
                fused_report_path=fp,
                conn=conn,
                values=tc.VALUES,
                allow_model=False,
                transport=None,
            )
        )
    finally:
        mp.undo()
    term = tmp / "run" / "answer-runtime-latest.json"
    out = report["results"][0]
    enum_stage = next(
        (e for e in out["expansions"] if e.get("stage") == "document_enumeration"), None
    )
    return {
        "report": report,
        "out": out,
        "enum_stage": enum_stage,
        "conn": conn,
        "terminal": term,
        "tmp": tmp,
    }


def _expected_posthoc(qid):
    q = next((x for x in GOLD["questions"] if x["query_id"] == qid), None)
    assert q, qid
    g = q["gold"]
    return sorted(g.get("expected_doc_ids") or [])


def _stored_runtime(qid, path):
    return json.loads((B / path).read_text(encoding="utf-8"))["results"][0]


def _set_search_id(fused):
    fused = json.loads(json.dumps(fused))
    fused["results"][0]["pg"]["search_id"] = ACTIVE_SEARCH
    return fused


LEG_DEFS = [
    ("file-enum-005-local", "file-enum-005", "local", dict()),
    ("file-enum-005-pg", "file-enum-005", "pg", dict()),
    ("file-enum-001-local", "file-enum-001", "local", dict()),
    ("file-enum-002-local", "file-enum-002", "local", dict()),
    (
        "file-enum-005-local-searchid-variant",
        "file-enum-005",
        "local",
        dict(
            mutate=_set_search_id,
            label="构造参数对照：与已存 local fused 逐字段相同，仅 pg.search_id 置为 active 冻结值",
        ),
    ),
    (
        "file-enum-002-local-pagesize2",
        "file-enum-002",
        "local",
        dict(page_size=2, label="构造参数对照：真实 enumerate 入口强制 page_size=2（跨页收集）"),
    ),
]


def main():
    rows = []
    for name, qid, path, kw in LEG_DEFS:
        fused_p = B / f"inputs/{path}/{qid}-fusion.json"
        rerank_p = B / f"inputs/{path}/{qid}-rerank.json"
        res = _replay_one(qid, fused_p, rerank_p, **{k: v for k, v in kw.items() if k != "label"})
        out = res["out"]
        enum = res["enum_stage"] or {}
        items = (out.get("answer") or {}).get("items") or []
        pub_ids = sorted({it.get("doc_id") for it in items})
        expected = _expected_posthoc(qid)
        stored = _stored_runtime(qid, f"legs/r1/{path}/{qid}/answer/answer-runtime-latest.json")
        stored_items = (stored.get("answer") or {}).get("items") or []
        stored_ids = sorted({it.get("doc_id") for it in stored_items})
        (OUT / "replays" / name).mkdir(parents=True, exist_ok=True)
        shutil.copy(res["terminal"], OUT / "replays" / name / "answer-runtime-latest.json")
        rows.append(
            {
                "leg": name,
                "query_id": qid,
                "path": path,
                "evidence_label": kw.get(
                    "label",
                    "存量产物读取 + 离线owning入口回放（当前源码；服务炸弹；目录行=gate-2 存量 221 行 verbatim）",
                ),
                "coverage_status": out["coverage_status"],
                "items_count": len(items),
                "published_doc_ids": pub_ids,
                "enum": {
                    "predicate": enum.get("predicate"),
                    "predicate_args": enum.get("predicate_args"),
                    "attribution_branch": enum.get("attribution_branch"),
                    "attribution_added": enum.get("attribution_added"),
                    "members_total": enum.get("members_total"),
                    "members_processed": enum.get("members_processed"),
                    "coverage_status": enum.get("coverage_status"),
                },
                "attribution_route_calls": res["conn"].attribution_calls,
                "match_vs_round1_stored": {
                    "stored_items_count": len(stored_items),
                    "stored_doc_ids": stored_ids,
                    "stored_coverage": stored["coverage_status"],
                    "reproduces_stored": (
                        pub_ids == stored_ids
                        and out["coverage_status"] == stored["coverage_status"]
                    ),
                },
                "posthoc_gold_reconciliation": {
                    "expected_doc_ids": expected,
                    "missing": sorted(set(expected) - set(pub_ids)),
                    "extra": sorted(set(pub_ids) - set(expected)),
                },
                "model_calls_used": res["report"]["model_calls_used"],
                "identity_before_matches_frozen": res["report"]["identity_before"][
                    "matches_frozen"
                ],
            }
        )
    (OUT / "diagnosis-replay.json").write_text(
        json.dumps({"legs": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    for r in rows:
        print(
            f"{r['leg']}: items {r['items_count']} cov={r['coverage_status']} "
            f"enum={r['enum']['members_processed']}/{r['enum']['members_total']} "
            f"added={r['enum']['attribution_added']} "
            f"missing={r['posthoc_gold_reconciliation']['missing'] and 'YES' or 'none'} "
            f"reproduces_stored={r['match_vs_round1_stored']['reproduces_stored']} "
            f"model={r['model_calls_used']}"
        )


if __name__ == "__main__":
    main()
