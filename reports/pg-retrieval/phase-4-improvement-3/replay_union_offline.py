"""Improvement-3 implementation replay — OFFLINE ONLY (no services).

Replays the four bounded samples (file-enum-005/local FAIL, file-enum-005/pg
CONTROL, file-enum-002/local, file-enum-001/local) and the two labeled
parameter variants through the OWNING answer entry with the catalog-layer
union NOW in place, over their OWN stored fused/rerank replay files, stored
identities and the SHA-protected gate-2 catalog row set (221 rows verbatim).

Per-leg evidence: union item-by-item (identity, basis, citation snapshot,
independent re-read), base/related/overlap/union statistics, foreign items,
post-hoc gold reconciliation vs round-1 stored terminals (labelled OFFLINE
OBSERVATION — a replay of stored inputs through the changed code, never a
live re-run or a claimed quality gain). ANY search_documents read raises:
the union must be computed entirely from the catalog layer.

Regenerate: .venv/bin/python reports/pg-retrieval/phase-4-improvement-3/replay_union_offline.py
"""

import hashlib
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

import test_phase4_improvement2_target_confirmation as tc  # noqa: E402  (VALUES/install pattern only)

from env_rag_final import answer as an  # noqa: E402

OUT = Path(__file__).resolve().parent
B = ROOT / "reports/pg-retrieval/phase-4-round-1"
DIAG = ROOT / "reports/pg-retrieval/phase-4-improvement-3-diagnosis"
GOLD = json.loads(
    (ROOT / "reports/pg-retrieval/gate-2/review-r5/gold-approved.json").read_text(encoding="utf-8")
)
ACTIVE_SEARCH = "872d689343a9cbb6"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


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


def catalog_rows():
    """221 rows VERBATIM from the SHA-protected gate-2 replay (存量产物读取).
    68a0's unknown_fields flag existence is backed by stored round-1 expansion
    warnings on both legs (field names never published — flagged 离线重建)."""
    data = json.loads((ROOT / "reports/pg-retrieval/gate-2/replay.json").read_text())
    found = {}

    def walk(o):
        if isinstance(o, dict):
            if o.get("discovery") == "document_enumeration" and o.get("doc_id"):
                found[o["doc_id"]] = {
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
    found["doc-68a03b50e1ba1ffc6a0116529f694fe1"]["unknown_fields"] = [
        "<存量 warning 证实存在；字段名未入历史工件>"
    ]
    return found


ALL_ROWS = catalog_rows()


class UnionCatalogConn:
    """Fake read-only catalog: evaluates the REAL predicate shapes, serves the
    full metadata scan for the attribution branch, answers corpus_runs /
    documents identity re-reads — and RAISES on any search-layer SQL."""

    def __init__(self, snapshot_id):
        self.snapshot_id = snapshot_id
        self.queries = []

    def _matching(self, pred, pargs):
        cb = re.findall(
            r"\(self_code = \$(\d+)(?: AND self_code_version IN \(([^)]*)\))?\)", pred or ""
        )
        lk = re.search(r"doc_name LIKE '%' \|\| \$(\d+) \|\| '%'", pred or "")
        out = []
        for d, row in ALL_ROWS.items():
            hit = False
            if cb:
                for n, vers in cb:
                    if row.get("self_code") != pargs[int(n) - 3]:
                        continue
                    if vers:
                        wanted = [pargs[int(v) - 3] for v in re.findall(r"\$(\d+)", vers)]
                        if (row.get("self_code_version") or "") not in wanted:
                            continue
                    hit = True
                    break
            elif lk:
                hit = pargs[int(lk.group(1)) - 3] in (row.get("doc_name") or "")
            if hit:
                out.append((d, row))
        out.sort(key=lambda kv: kv[1]["doc_name"] or "")
        return out

    def _all_sorted(self):
        return sorted(ALL_ROWS.items(), key=lambda kv: kv[1]["doc_name"] or "")

    def _meta(self, d, row, *, unknown=False):
        r = {
            "doc_id": d,
            "doc_name": row["doc_name"],
            "title": row["title"],
            "self_code": row["self_code"],
            "self_code_version": row["self_code_version"],
            "doc_type": row.get("doc_type"),
        }
        if unknown:
            r["title_confidence"] = 1.0
            r["unknown_fields"] = list(row.get("unknown_fields") or [])
        return r

    async def fetch(self, sql, *args):
        self.queries.append(("fetch", sql, list(map(str, args))))
        u = sql.upper()
        assert not any(w in u for w in ("INSERT", "UPDATE", "DELETE", "CREATE"))
        if "SEARCH_DOCUMENTS" in u or "SEARCH_CHUNKS" in u:
            raise AssertionError(
                "the union must be computed from the catalog layer — the search "
                "index was touched, which is the improvement-3 root cause"
            )
        if "FROM ENV_RAG.DOCUMENTS" in u and "UNKNOWN_FIELDS" in u:
            m = re.search(r"AND \((.*)\)\s+ORDER BY", sql)
            if m:
                rows = self._matching(m.group(1), tuple(args[2:]))
            else:
                rows = self._all_sorted()
            lim = re.search(r"LIMIT (\d+) OFFSET (\d+)", sql)
            metas = [self._meta(d, r, unknown=True) for d, r in rows]
            if lim:
                a, b = int(lim.group(1)), int(lim.group(2))
                metas = metas[b : b + a]
            return metas
        raise AssertionError(f"unexpected SQL: {sql[:120]!r}")

    async def fetchval(self, sql, *args):
        self.queries.append(("fetchval", sql, list(map(str, args))))
        u = sql.upper()
        if "COUNT(*)" in u and "ENV_RAG.DOCUMENTS" in u:
            m = re.search(r"AND \((.*)\)", sql)
            if m:
                return len(self._matching(m.group(1), tuple(args[2:])))
            return len(ALL_ROWS)
        if "DOC_NAME FROM ENV_RAG.DOCUMENTS" in u:
            row = ALL_ROWS.get(args[2])
            return row["doc_name"] if row else None
        raise AssertionError(f"unexpected SQL: {sql[:120]!r}")

    async def fetchrow(self, sql, *args):
        self.queries.append(("fetchrow", sql, list(map(str, args))))
        u = sql.upper()
        if "CORPUS_RUNS" in u:
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
        if "REQUIRES_SPAN" in u:
            return None
        raise AssertionError(f"unexpected SQL: {sql[:120]!r}")

    async def close(self):
        pass

    def search_reads(self):
        return [q for q in self.queries if "SEARCH_" in q[1].upper()]


def _install(mp, conn, ident):
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
    mp.setattr(an, "verify_gold_guard", lambda p: ib["gold_sha"])
    mp.setattr(an, "GOLD_PATH", Path("reports/pg-retrieval/gate-2/review-r5/gold-approved.json"))

    async def current(_c, **_kw):
        return {
            "state": "current",
            "active_snapshot_id": ib["catalog_active"]["snapshot_id"],
            "stored_fingerprint": ib["source_fingerprint"],
        }

    import env_rag_final.catalog.builder as builder
    import env_rag_final.catalog.source as source_mod
    import env_rag_final.search.expand as expand_mod

    mp.setattr(builder, "check_stale", current)
    mp.setattr(expand_mod, "check_search_stale", current)

    async def no_fp(_c, _w):
        return ""

    mp.setattr(builder, "_live_source_fingerprint", no_fp)
    mp.setattr(source_mod, "SourceAdapter", tc.fx.FakeAdapter)

    def boom(**_kw):
        raise AssertionError("no real DB connection in the offline replay")

    mp.setattr(an.asyncpg, "connect", boom)

    def http_boom(*_a, **_k):
        raise AssertionError("no HTTP in the offline replay")

    mp.setattr(an.httpx.AsyncClient, "post", http_boom)


def replay(qid, path, mutate=None, page_size=None):
    fused_p = B / f"inputs/{path}/{qid}-fusion.json"
    rerank_p = B / f"inputs/{path}/{qid}-rerank.json"
    fused = json.loads(fused_p.read_text(encoding="utf-8"))
    ident = fused["identity_before"]
    if mutate:
        fused = mutate(fused)
    tmp = Path(tempfile.mkdtemp())
    fp = tmp / "fusion-runtime-latest.json"
    rp = tmp / "rerank-runtime-latest.json"
    fp.write_text(json.dumps(fused, ensure_ascii=False), encoding="utf-8")
    shutil.copy(rerank_p, rp)
    conn = UnionCatalogConn(ident["catalog_active"]["snapshot_id"])
    mp = MP()
    try:
        _install(mp, conn, ident)
        if page_size is not None:
            import env_rag_final.enumerate_.doc_enum as de

            real = de.enumerate_documents

            async def sized(*a, **kw):
                kw["page_size"] = page_size
                return await real(*a, **kw)

            mp.setattr(de, "enumerate_documents", sized)
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
    (OUT / "replays" / _leg_name(qid, path, mutate, page_size)).mkdir(parents=True, exist_ok=True)
    shutil.copy(
        term, OUT / f"replays/{_leg_name(qid, path, mutate, page_size)}/answer-runtime-latest.json"
    )
    return report, conn


def _leg_name(qid, path, mutate, page_size):
    if mutate:
        return f"{qid}-{path}-searchid-variant"
    if page_size:
        return f"{qid}-{path}-pagesize{page_size}"
    return f"{qid}-{path}"


def _set_search_id(fused):
    fused = json.loads(json.dumps(fused))
    fused["results"][0]["pg"]["search_id"] = ACTIVE_SEARCH
    return fused


def reconcile(qid, out, enum, conn, expected_ids):
    items = (out.get("answer") or {}).get("items") or []
    pub = sorted({it["doc_id"] for it in items})
    foreign = [
        it
        for it in items
        if (it.get("citation") or {}).get("snapshot_id") != enum.get("catalog_snapshot_id")
    ]
    return {
        "query_id": qid,
        "coverage_status": out["coverage_status"],
        "model_calls_used": None,
        "items_count": len(items),
        "published_doc_ids": pub,
        "posthoc_gold": {
            "expected": sorted(expected_ids),
            "missing": sorted(set(expected_ids) - set(pub)),
            "extra": sorted(set(pub) - set(expected_ids)),
        },
        "enum_stats": {
            k: enum.get(k)
            for k in (
                "base_total",
                "base_processed",
                "base_coverage",
                "related_total",
                "related_processed",
                "related_matches",
                "related_evidence",
                "related_coverage",
                "attribution_branch",
                "attribution_added",
                "overlap_evidence",
                "overlap_canonical",
                "union_total",
                "members_total",
                "members_processed",
                "coverage_status",
                "publication_guard",
                "catalog_snapshot_id",
            )
        },
        "items_detail": [
            {
                "doc_id": it["doc_id"],
                "self_code": it.get("self_code"),
                "self_code_version": it.get("self_code_version"),
                "attribution": it.get("attribution"),
                "citation_snapshot": (it.get("citation") or {}).get("snapshot_id"),
                "citation_workspace": (it.get("citation") or {}).get("workspace"),
                "citation_verified": it.get("citation_verified"),
                "citation_reverified": it.get("citation_reverified"),
            }
            for it in items
        ],
        "citations_with_foreign_or_empty_snapshot": len(foreign),
        "search_layer_reads": len(conn.search_reads()),
    }


def main():
    rows = []
    gold_ids = {
        q["query_id"]: sorted((q.get("gold") or {}).get("expected_doc_ids") or [])
        for q in GOLD["questions"]
    }
    legs = [
        ("file-enum-005", "local", None, None),
        ("file-enum-005", "pg", None, None),
        ("file-enum-005", "local", _set_search_id, None),
        ("file-enum-001", "local", None, None),
        ("file-enum-002", "local", None, None),
        ("file-enum-002", "local", None, 2),
    ]
    for qid, path, mutate, ps in legs:
        report, conn = replay(qid, path, mutate, ps)
        out = report["results"][0]
        enum = next((e for e in out["expansions"] if e.get("stage") == "document_enumeration"), {})
        rec = reconcile(qid, out, enum, conn, gold_ids[qid])
        rec["leg"] = _leg_name(qid, path, mutate, ps)
        rec["model_calls_used"] = report["model_calls_used"]
        rec["evidence_label"] = (
            "构造参数对照（存储输入逐字段复制仅改 pg.search_id / 强制 page_size）"
            + " + 存量产物读取 + 离线owning入口回放（当前源码）"
            if (mutate or ps)
            else "存量产物读取 + 离线owning入口回放（当前源码；服务炸弹）"
        )
        # hard gates for the failing leg only; controls keep their shape
        assert rec["search_layer_reads"] == 0, rec["leg"]
        assert rec["model_calls_used"] == 0
        if rec["enum_stats"]["attribution_branch"]:
            assert rec["posthoc_gold"]["missing"] == [], rec["leg"]
        rows.append(rec)
    (OUT / "union-reconcile.json").write_text(
        json.dumps({"legs": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    for r in rows:
        print(
            f"{r['leg']}: items={r['items_count']} cov={r['coverage_status']} "
            f"missing={len(r['posthoc_gold']['missing'])} extra={len(r['posthoc_gold']['extra'])} "
            f"added={r['enum_stats']['attribution_added']} search_reads={r['search_layer_reads']}"
        )
    print("wrote union-reconcile.json + 6 terminal reports")


if __name__ == "__main__":
    main()
