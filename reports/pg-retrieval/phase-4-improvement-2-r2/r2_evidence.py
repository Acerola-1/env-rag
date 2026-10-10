"""Improvement-2 r2 evidence driver — OFFLINE ONLY (no services).

Two things, both through the OWNING answer entry (answer.run_answer) over fake
read-only catalogs and stored artifacts; zero network/DB/model calls:

1. four-leg preservation: the four bounded round-1 LOCAL legs are replayed on
   their OWN stored inputs and the published item lists are compared, item by
   item, against the accepted generation (phase-4-improvement-2/replays/).
   Results MUST be identical (17->4, 13->1, 44->13, control 13).
2. attribution & scope traces (r2 A/B): the evidence trajectory from the
   5.3-published typed doc_attribution target + allowed_set_basis through the
   catalog re-read into the FINAL items — including the upstream-confirmed
   attribution target WITHOUT any usable chunk (full scope read), the bare
   candidate-label refusal, and the trusted/untrusted code-less scope pair.

Evidence labels: 存量产物读取 (stored artifacts) / 构造 (explicit synthetic
fixtures shaped field-for-field after neg-010's stored pg fusion input) /
离线owning入口回放 (offline replay through the owning entry). Nothing here is
a live database re-run or a cold generation.

Regenerate:  .venv/bin/python reports/pg-retrieval/phase-4-improvement-2-r2/r2_evidence.py
"""

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import test_phase4_improvement2_target_confirmation as tc  # noqa: E402

OUT = Path(__file__).resolve().parent
PREV = ROOT / "reports/pg-retrieval/phase-4-improvement-2"
GOLD_SHA = "1bf130077c21583a89c5ca14695694d9552c558a7d8dc5d45ff0d9f72cfd7a5e"


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


def _meta_reads(conn):
    """Every documents-row identity read the gate made through the OWNING
    guarded connection (workspace, snapshot, doc_id)."""
    return [
        {
            "sql": "SELECT doc_name, self_code, self_code_version FROM env_rag.documents ...",
            "workspace": list(a)[0],
            "catalog_snapshot_id": list(a)[1],
            "doc_id": list(a)[2],
        }
        for (_kind, sql, a) in conn.queries
        if "self_code_version FROM env_rag.documents" in sql
    ]


def four_legs():
    rows = []
    for qid in ("prose-enum-001", "prose-enum-006", "neg-004", "table-enum-001"):
        mp = MP()
        tmp = Path(tempfile.mkdtemp())
        try:
            report, _q = tc._run_stored(mp, tmp, qid)
        finally:
            mp.undo()
        term = tmp / "run" / "answer-runtime-latest.json"
        assert term.exists(), term
        (OUT / "replays" / qid).mkdir(parents=True, exist_ok=True)
        shutil.copy(term, OUT / "replays" / qid / "answer-runtime-latest.json")
        out = report["results"][0]
        conf = (out.get("scope_selection") or {}).get("target_confirmation") or {}
        items = out["answer"]["items"]
        prev = json.loads(
            (PREV / f"replays/{qid}/answer-runtime-latest.json").read_text(encoding="utf-8")
        )["results"][0]
        identical_items = json.dumps(items, ensure_ascii=False, sort_keys=True) == json.dumps(
            prev["answer"]["items"], ensure_ascii=False, sort_keys=True
        )
        assert identical_items, qid  # preservation: item lists byte-equal
        assert prev["coverage_status"] == out["coverage_status"] == "complete", qid
        assert report["model_calls_used"] == 0
        rows.append(
            {
                "query_id": qid,
                "evidence_label": "存量产物读取 + 离线answer入口回放（r2 代码下的保持性核对）",
                "items_count": len(items),
                "allowed": conf.get("allowed"),
                "foreign_items_published": len(
                    [
                        it
                        for it in items
                        if (it.get("citation") or {}).get("doc_id")
                        not in set(conf.get("allowed", []))
                    ]
                ),
                "coverage_status": out["coverage_status"],
                "model_calls_used": report["model_calls_used"],
                "items_identical_to_accepted_generation": identical_items,
                "accepted_generation_sha_of_compared_report": hashlib.sha256(
                    (PREV / f"replays/{qid}/answer-runtime-latest.json").read_bytes()
                ).hexdigest(),
            }
        )
    (OUT / "four-leg-preservation.json").write_text(
        json.dumps({"legs": rows, "gold_sha": GOLD_SHA}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    print(
        "four-leg preservation:",
        *[f"\n  {r['query_id']}: {r['items_count']} items, identical" for r in rows],
    )
    return rows


def trace_typed_full_read():
    """A3: upstream-confirmed attribution target, NO usable chunk, still fully
    registered and read; trajectory published typed/basis -> catalog re-reads
    -> confirmation -> final items."""
    mp = MP()
    tmp = Path(tempfile.mkdtemp())

    def upstream(row):
        row["usable"] = [u for u in row["usable"] if u["doc_id"] != tc._M]
        row["typed_targets"] = [tc._typed_attribution(tc._M, tc._M_NAME)]
        row["allowed_set_basis"] = tc._allowed_set_basis([tc._G], [tc._M])
        row["targets_resolved"] = [
            {"code": "GB9001", "version": "2020", "docs": [tc._G], "versions": ["2020"]}
        ]
        row["path_provenance"] = {"path": "fusion", "discovery_only": False}
        return row

    try:
        report, fused, conn = tc._synth_leg(
            tmp,
            mp,
            "GB 9001-2020 的 4 章规定了哪些要求？含修改单和相关文件。",
            {
                tc._G: tc._goal_doc(),
                tc._M: tc._goal_doc(self_code=None, self_code_version=None, file_path=tc._M_NAME),
            },
            upstream=upstream,
            return_conn=True,
        )
    finally:
        mp.undo()
    out = report["results"][0]
    conf = (out.get("scope_selection") or {}).get("target_confirmation") or {}
    assert set(conf["allowed"]) == {tc._G, tc._M}, conf
    assert {it["doc_id"] for it in out["answer"]["items"]} == {tc._G, tc._M}
    assert out["coverage_status"] == "complete", out
    assert report["model_calls_used"] == 0
    assert any(tc._M in f and "FULL scope read" in f for f in out["flags"]), out["flags"]
    return {
        "evidence_label": "构造（5.3 真实发布形状：字段逐一同 neg-010 存量 pg fused 输入）+ 离线owning入口回放",
        "question": "GB 9001-2020 的 4 章规定了哪些要求？含修改单和相关文件。",
        "step1_upstream_published_evidence": {
            "typed_targets": fused["typed_targets"],
            "allowed_set_basis": fused["allowed_set_basis"],
            "targets_resolved": fused["targets_resolved"],
            "usable_docs": sorted({u["doc_id"] for u in fused["usable"]}),
            "note": "doc-synth-modify carries NO usable chunk — evidence lives "
            "only in the published typed target + allowed-set basis",
        },
        "step2_catalog_rereads_via_owning_connection": _meta_reads(conn),
        "step3_confirmation": {
            "request_branches": conf.get("request_branches"),
            "branch_source": conf.get("branch_source"),
            "allowed": conf.get("allowed"),
            "allowed_basis": conf.get("allowed_basis"),
            "rejected": conf.get("rejected"),
            "unresolved": conf.get("unresolved"),
            "identity_source": conf.get("identity_source"),
        },
        "step4_final_items": {
            "items": [
                {
                    "doc_id": it.get("doc_id"),
                    "clause": it.get("clause"),
                    "citation_verified": it.get("citation_verified"),
                    "citation_reverified": it.get("citation_reverified"),
                }
                for it in out["answer"]["items"]
            ],
            "coverage_status": out["coverage_status"],
            "model_calls_used": report["model_calls_used"],
            "registration_flags": [f for f in out["flags"] if "FULL scope read" in f],
        },
    }


def trace_bare_label_refusal():
    """A1: a candidate that labels ITSELF doc_attribution / membership_basis
    (and a self_code-unknown catalog row) must never join the allowed set."""
    mp = MP()
    tmp = Path(tempfile.mkdtemp())
    try:
        report, fused, conn = tc._synth_leg(
            tmp,
            mp,
            "GB 9001-2020 的 4 章规定了哪些要求？含修改单和相关文件。",
            {
                tc._G: tc._goal_doc(),
                tc._X: tc._foreign_doc(
                    self_code=None,
                    self_code_version=None,
                    file_path="synth-自称修改单但只是候选自报.pdf",
                    membership=True,
                ),
            },
            return_conn=True,
        )
    finally:
        mp.undo()
    out = report["results"][0]
    conf = (out.get("scope_selection") or {}).get("target_confirmation") or {}
    assert conf["allowed"] == [tc._G], conf
    assert {it["doc_id"] for it in out["answer"]["items"]} == {tc._G}
    assert tc._X not in conf["allowed_basis"], conf["allowed_basis"]
    assert any(
        tc._X == u["doc_id"] and "upstream-published" in u["reason"] for u in conf["unresolved"]
    ), conf["unresolved"]
    return {
        "evidence_label": "构造 + 离线owning入口回放（伪标记安全拒绝）",
        "candidate_self_labels": {
            "paths0_discovery": fused["usable"][1]["paths"][0]["discovery"],
            "paths0_membership_basis": fused["usable"][1]["paths"][0]["membership_basis"],
        },
        "upstream_published_evidence": {
            "typed_targets": fused["typed_targets"],
            "allowed_set_basis": fused.get("allowed_set_basis"),
        },
        "confirmation": {
            "allowed": conf["allowed"],
            "allowed_basis": conf["allowed_basis"],
            "unresolved": conf["unresolved"],
        },
        "published_docs": sorted({it["doc_id"] for it in out["answer"]["items"]}),
        "coverage_status": out["coverage_status"],
    }


def trace_codeless_pair():
    """B3/B1: trusted upstream code_exact resolution confirms a code-less
    scope (documents still re-gated by catalog identity); a discovery-only
    local path self-reporting the SAME resolution confirms nothing."""

    def pos_upstream(row):
        row["targets_resolved"] = [
            {"code": "GB9001", "version": "2020", "docs": [tc._G], "versions": ["2020"]}
        ]
        row["path_provenance"] = {"path": "fusion", "discovery_only": False}
        row.pop("targets_confirmed", None)
        row.pop("discovery_docs", None)
        return row

    def neg_upstream(row):
        row["targets_resolved"] = [
            {"code": "GB9001", "version": "2020", "docs": [tc._G], "versions": ["2020"]}
        ]
        return row

    q = "第 4 章规定了哪些要求？逐项列出。"
    docs = {tc._G: tc._goal_doc(), tc._X: tc._foreign_doc()}
    mp = MP()
    tmp = Path(tempfile.mkdtemp())
    try:
        pos, pos_fused, _ = tc._synth_leg(tmp, mp, q, docs, upstream=pos_upstream, return_conn=True)
    finally:
        mp.undo()
    mp = MP()
    tmp = Path(tempfile.mkdtemp())
    try:
        neg, neg_fused, _ = tc._synth_leg(tmp, mp, q, docs, upstream=neg_upstream, return_conn=True)
    finally:
        mp.undo()
    p_out, n_out = pos["results"][0], neg["results"][0]
    p_conf = p_out["scope_selection"]["target_confirmation"]
    n_conf = n_out["scope_selection"]["target_confirmation"]
    assert p_conf["allowed"] == [tc._G] and p_out["coverage_status"] == "complete"
    assert _rejected_by_gate(p_conf)  # noise doc rejected by canonical identity
    assert n_out["coverage_status"] == "ambiguous"
    assert not (n_out.get("answer") or {}).get("items")
    assert not n_out["scope_selection"]["selected_docs"]
    return {
        "evidence_label": "构造 + 离线owning入口回放（可信/不可信无编号范围成对）",
        "question": q,
        "trusted_positive": {
            "upstream_targets_resolved": pos_fused["targets_resolved"],
            "path_provenance": pos_fused["path_provenance"],
            "branch_source": p_conf["branch_source"],
            "allowed": p_conf["allowed"],
            "rejected": p_conf["rejected"],
            "coverage_status": p_out["coverage_status"],
            "published_docs": sorted({it["doc_id"] for it in p_out["answer"]["items"]}),
        },
        "discovery_only_negative": {
            "upstream_targets_resolved": neg_fused["targets_resolved"],
            "path_provenance": neg_fused["path_provenance"],
            "targets_confirmed": neg_fused.get("targets_confirmed"),
            "verdict": n_conf["verdict"],
            "discovery_proposals_kept_for_audit": n_conf["discovery_proposals_kept_for_audit"],
            "refusal_basis": n_conf["refusal_basis"],
            "coverage_status": n_out["coverage_status"],
            "items": (n_out.get("answer") or {}).get("items", []),
            "selected_docs": n_out["scope_selection"]["selected_docs"],
        },
    }


def _rejected_by_gate(conf):
    return any("matches no requested branch" in str(x.get("reason", "")) for x in conf["rejected"])


def main() -> None:
    four_legs()
    trace = {
        "typed_attribution_full_read_no_chunks": trace_typed_full_read(),
        "bare_candidate_label_refusal": trace_bare_label_refusal(),
        "codeless_trusted_vs_selfreported_pair": trace_codeless_pair(),
    }
    (OUT / "attribution-and-scope-trace.json").write_text(
        json.dumps(trace, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print("wrote attribution-and-scope-trace.json")


if __name__ == "__main__":
    main()
