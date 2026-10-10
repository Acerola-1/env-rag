"""Improvement-2 offline diagnosis driver: local-path scope contamination.

Diagnosis ONLY — this script changes no production code. It re-drives the
four bounded samples (prose-enum-001/local, prose-enum-006/local,
neg-004/local + the correct control table-enum-001/local) through the OWNING
answer entry (answer.run_answer) over:

  * the path's OWN stored fused-replay artifacts
    (reports/pg-retrieval/phase-4-round-1/inputs/local/<qid>-{fusion,rerank}.json),
  * stored identity material (each fused report's own identity_before),
  * the ORIGINAL parsed sidecars (read-only via the frozen PARSED_ROOT),
  * an explicit FAKE READ-ONLY catalog connection: prose rows come from the
    stored local runtime's expansions (scope id + member unit ids); table
    unit rows are DERIVED from the original tables.json sidecars (the same
    artifacts the accepted catalog was built from) and the rebuild is
    cross-checked against the stored run's expansion item counts — any
    mismatch is reported, never adjusted away.

Service boundary: real asyncpg.connect, httpx posting and any non-SELECT
statement blow up; allow_model=False, transport=None; zero network/DB/model.
gold (expected_items / target membership) is consulted ONLY post-hoc for the
reconciliation table — no input target/child list is derived from it. The
goal-document derivation uses ONLY this path's own artifacts: the question
text (its 标准号+年号) matched against each candidate document's
``file_path`` recorded in the local fused usable entries.

Regenerate:  .venv/bin/python reports/pg-retrieval/phase-4-improvement-2-diagnosis/replay_local_scope_offline.py
"""

from __future__ import annotations

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

import test_answer as fx  # noqa: E402  (accepted offline harness: FakeAdapter)

from env_rag_final import answer as an  # noqa: E402
from env_rag_final import evaluation as ev  # noqa: E402
from env_rag_final.audit import identity as aid  # noqa: E402
from env_rag_final.enumerate_.prose_enum import _unit_text_from_blocks  # noqa: E402

DIAG = Path(__file__).resolve().parent
B = ROOT / "reports/pg-retrieval/phase-4-round-1"
GOLD = json.loads(
    (ROOT / "reports/pg-retrieval/gate-2/review-r5/gold-approved.json").read_text(encoding="utf-8")
)

_SAMPLES = ("prose-enum-001", "prose-enum-006", "neg-004", "table-enum-001")


def _doc_codes(file_path: str) -> tuple[str, str | None]:
    m = re.search(r"GB\s?(\d{4,5})[-—–]?(\d{0,4})", file_path)
    return (m.group(1), m.group(2) or None) if m else ("", None)


def _question_codes(question: str) -> list[tuple[str, str | None]]:
    return [
        (m.group(1), m.group(2) or None)
        for m in re.finditer(r"GB\s*(\d{4,5})(?:\s*[-—–]\s*(\d{4}))?", question)
    ]


class LocalCatalogConn:
    """Explicit FAKE read-only catalog. Rows come ONLY from stored artifacts:
    prose scope members / units from the local runtime's recorded expansions;
    table units derived from the original tables.json sidecars; doc names /
    codes from the local fused usable file_path."""

    def __init__(self, fused: dict, runtime: dict):
        ib = fused["identity_before"]
        self.snap = ib["catalog_active"]["snapshot_id"]
        self.doc_names: dict[str, str] = {}
        for r in fused["results"]:
            for u in r.get("usable") or []:
                if u.get("doc_id") and u.get("file_path"):
                    self.doc_names[u["doc_id"]] = u["file_path"]
        # prose seam: {scope_id: unit_ids} + per-doc scopes by number
        self.scope_units: dict[str, list[str]] = {}
        self.scopes: dict[tuple[str, str], dict] = {}
        self.unit_rows: dict[tuple[str, str], dict] = {}
        for e in runtime["results"][0]["expansions"]:
            sid_, doc_id = e.get("scope_id"), e.get("doc_id")
            if not sid_ or not doc_id:
                continue
            uids = e.get("unit_ids") or []
            self.scope_units[sid_] = list(uids)
            num = sid_.rsplit(":", 1)[-1]
            self.scopes[(doc_id, num)] = {
                "scope_id": sid_,
                "scope_kind": "chapter" if "." not in num else "clause",
                "title": None,
                "number": num,
                "confirm_status": "confirmed",
            }
            pdir = aid.PARSED_ROOT / f"{self.doc_names.get(doc_id, '?')}.parsed"
            for uid in uids:
                text = _unit_text_from_blocks(pdir, uid) or ""
                self.unit_rows[(doc_id, uid)] = {
                    "unit_id": uid,
                    "unit_kind": "block",
                    "heading": "",
                    "requires_span": False,
                    "content_length": len(text),
                    "locator": json.dumps({"blockid": uid}),
                }
        self.queries: list[tuple[str, tuple]] = []

    def _table_rows(self, doc_id: str) -> list[dict]:
        name = self.doc_names.get(doc_id) or ""
        tj = sorted((aid.PARSED_ROOT / f"{name}.parsed").glob("*.tables.json"))
        if not tj:
            return []
        tables = json.loads(tj[0].read_text(encoding="utf-8")).get("tables") or {}
        rows = []
        for order, (tid, entry) in enumerate(
            sorted(tables.items(), key=lambda kv: int(str(kv[0]).rsplit("-", 1)[-1])), start=1
        ):
            cap = (entry or {}).get("caption") or ""
            m = re.search(r"[表图]\s*[0-9０-９]+", cap)
            seq = int(re.sub(r"\D", "", m.group(0))) if m else None
            rows.append(
                {
                    "unit_id": tid,
                    "unit_order": order,
                    "table_seq": seq,
                    "caption": cap or None,
                    "heading": (entry or {}).get("heading") or None,
                    "locator": json.dumps({"blockid": (entry or {}).get("blockid") or tid}),
                }
            )
        return rows

    async def fetch(self, sql: str, *args):
        self.queries.append(("fetch", sql))
        u = sql.upper()
        assert "INSERT" not in u and "UPDATE" not in u and "DELETE" not in u and "CREATE" not in u
        if "scope_units su" in sql:
            return [{"unit_id": uid} for uid in self.scope_units.get(args[2], [])]
        if "FROM env_rag.scopes" in sql and "number=$4" in sql:
            row = self.scopes.get((args[2], args[3]))
            return [dict(row)] if row else []
        if "unit_kind='table'" in sql:
            return self._table_rows(args[2])
        if "unit_chunk_links" in sql:
            return []
        raise AssertionError(f"unexpected SQL (fake catalog): {sql!r} args={args!r}")

    async def fetchrow(self, sql: str, *args):
        self.queries.append(("fetchrow", sql))
        u = sql.upper()
        assert "INSERT" not in u and "UPDATE" not in u and "DELETE" not in u
        if "requires_span" in sql:
            return self.unit_rows.get((args[2], args[3]))
        if "self_code_version FROM env_rag.documents" in sql:
            name = self.doc_names.get(args[2])
            if not name:
                return None
            code, ver = _doc_codes(name)
            return {"doc_name": name, "self_code": code, "self_code_version": ver}
        raise AssertionError(f"unexpected SQL (fake catalog): {sql!r}")

    async def fetchval(self, sql: str, *args):
        self.queries.append(("fetchval", sql))
        if "doc_name FROM env_rag.documents" in sql:
            return self.doc_names.get(args[2])
        raise AssertionError(f"unexpected SQL (fake catalog): {sql!r}")

    async def close(self):
        pass


def _install(mp_list: list, conn, ident: dict):
    def _do(target, name, value):
        p = patch.object(target, name, value)
        p.start()
        mp_list.append(p)

    async def capture(_values):
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

    _do(an, "_capture_identity", capture)
    snap, fp = ident["catalog_active"]["snapshot_id"], ident["source_fingerprint"]

    async def current(_conn, **_kw):
        return {"state": "current", "active_snapshot_id": snap, "stored_fingerprint": fp}

    import env_rag_final.catalog.builder as builder
    import env_rag_final.catalog.source as source_mod
    import env_rag_final.enumerate_.table_enum as table_enum_mod
    import env_rag_final.search.expand as expand_mod

    _do(builder, "check_stale", current)
    _do(table_enum_mod, "check_stale", current)

    async def no_live_fp(_c, _w):
        return ""

    _do(builder, "_live_source_fingerprint", no_live_fp)

    async def fresh(_conn, _ws, parsed_root=None):
        return {
            "state": "current",
            "catalog_snapshot_id": snap,
            "search_id": ident["search_active"],
        }

    _do(expand_mod, "check_search_stale", fresh)
    _do(source_mod, "SourceAdapter", fx.FakeAdapter)
    # 本诊断必须走已验收改进组1的生产边界逻辑：不替换任何 expand/verify 函数。
    _do(
        ev,
        "LocalCandidateAdapter",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no local service")),
    )

    def boom(**_kw):
        raise AssertionError("diagnosis must never open a real DB connection")

    _do(an.asyncpg, "connect", boom)

    def http_boom(*_a, **_k):
        raise AssertionError("diagnosis must never make an HTTP call")

    _do(an.httpx.AsyncClient, "post", http_boom)
    return conn


from env_rag_final.local_adapter import EMBEDDING_DIM, EMBEDDING_MODEL  # noqa: E402

# the REAL verify_config_guard runs (only the production embedding identity
# passes it): the values dict carries the frozen constants, no secrets.
VALUES = dict(fx.VALUES)
VALUES["EMBEDDING_MODEL"] = EMBEDDING_MODEL
VALUES["EMBEDDING_DIM"] = str(EMBEDDING_DIM)


def replay(qid: str) -> dict:
    fused_path = B / f"inputs/local/{qid}-fusion.json"
    rerank_path = B / f"inputs/local/{qid}-rerank.json"
    fused = json.loads(fused_path.read_text(encoding="utf-8"))
    runtime = json.loads((B / f"legs/r1/local/{qid}/answer/answer-runtime-latest.json").read_text())
    conn = LocalCatalogConn(fused, runtime)
    ps: list = []
    tmp = Path(tempfile.mkdtemp())
    _install(ps, conn, fused["identity_before"])
    # the stored run routed counters through the harness's own production
    # category map (evaluation.COUNTER_CATEGORIES — a runner parameter, not
    # answer/gold data); replay with the identical seam value.
    cat_over = {qid: ev.COUNTER_CATEGORIES[qid]} if qid in ev.COUNTER_CATEGORIES else None
    try:
        report = __import__("asyncio").run(
            an.run_answer(
                tmp / "run",
                [qid],
                rerank_report_path=rerank_path,
                fused_report_path=fused_path,
                conn=conn,
                values=VALUES,
                allow_model=False,
                transport=None,
                category_overrides=cat_over,
            )
        )
    finally:
        while ps:
            ps.pop().stop()
    term = tmp / "run" / "answer-runtime-latest.json"
    case_dir = DIAG / "replays" / qid
    case_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(term, case_dir / "answer-runtime-latest.json")
    out = report["results"][0]
    old = runtime["results"][0]
    return {
        "qid": qid,
        "report": report,
        "out": out,
        "old": old,
        "conn": conn,
        "fused": fused,
    }


def _prose_clauses(items_of) -> list:
    return sorted((it.get("clause") or it.get("seq") or "?") for it in items_of)


def reconcile(res: dict) -> dict:
    qid, out, old, fused = res["qid"], res["out"], res["old"], res["fused"]
    question = fused["results"][0]["query"]
    goal_codes = _question_codes(question)
    doc_names = res["conn"].doc_names
    goal_docs = sorted(
        d for d, name in doc_names.items() if (_doc_codes(name)) in [(c, v) for c, v in goal_codes]
    )
    sel = (out.get("scope_selection") or {}).get("selected_docs") or []
    per_doc = {
        e.get("doc_id"): {
            "kind": e.get("kind"),
            "items_count": e.get("items_count"),
            "selected": e.get("selected"),
        }
        for e in out.get("expansions") or []
        if e.get("kind") in ("prose", "table")
    }
    old_per_doc = {
        e.get("doc_id"): e.get("items_count")
        for e in old.get("expansions") or []
        if e.get("kind") in ("prose", "table")
    }
    contam_docs = [d for d in sel if d not in goal_docs]
    published = out.get("answer") or {}
    pub_items = published.get("items") or []
    goal_items = [it for it in pub_items if it.get("doc_id") in goal_docs]
    foreign_items = [
        it for it in pub_items if it.get("doc_id") and it.get("doc_id") not in goal_docs
    ]
    return {
        "qid": qid,
        "question": question,
        "stage_provenance": {
            "local_discovery_docs": sorted({u["doc_id"] for u in fused["results"][0]["usable"]}),
            "targets_resolved_in_replay": fused["results"][0].get("targets_resolved"),
            "typed_targets_in_replay": [
                (t.get("target_type"), t.get("doc_id"), t.get("discovery"))
                for t in fused["results"][0].get("typed_targets") or []
            ],
            "answer_selected_docs": sel,
            "scope_basis_text": (out.get("scope_selection") or {}).get("basis"),
        },
        "goal_docs_from_path_artifacts": goal_docs,
        "contaminating_docs": contam_docs,
        "per_doc_expansions_new": per_doc,
        "per_doc_expansions_stored_run": old_per_doc,
        "coverage_new": out.get("coverage_status"),
        "coverage_stored": old.get("coverage_status"),
        "published_item_counts": {
            "total": len(pub_items),
            "in_goal_docs": len(goal_items),
            "foreign_docs": len(foreign_items),
        },
        "published_clause_sets": {
            "goal": _prose_clauses(goal_items),
            "foreign": _prose_clauses(foreign_items),
        },
        "identity_before_matches_frozen": res["report"]["identity_before"]["matches_frozen"],
        "model_calls_used": res["report"]["model_calls_used"],
        "fake_conn_statements": len(res["conn"].queries),
        "fake_conn_read_only_enforced": True,
        # sidecar-derived table rows / stored-trace prose rows consistency:
        # a rebuild that no longer matches the stored run is FLAGGED, never
        # adjusted to fit.
        "rebuild_matches_stored_expansions": per_doc_counts(per_doc) == dict(old_per_doc)
        if per_doc and old_per_doc
        else None,
    }


def per_doc_counts(per_doc: dict) -> dict:
    return {d: v["items_count"] for d, v in per_doc.items()}


def main() -> None:
    results = []
    for qid in _SAMPLES:
        res = replay(qid)
        rec = reconcile(res)
        results.append(rec)
        print(
            f"{qid}: goal={rec['goal_docs_from_path_artifacts']} "
            f"selected={rec['stage_provenance']['answer_selected_docs']} "
            f"cov new={rec['coverage_new']} vs stored={rec['coverage_stored']} "
            f"published={rec['published_item_counts']}"
        )
    (DIAG / "local-scope-reconcile.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print("wrote local-scope-reconcile.json")


if __name__ == "__main__":
    main()
