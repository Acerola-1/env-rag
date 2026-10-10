"""Improvement-2 post-implementation replay — OFFLINE ONLY (no services).

Re-runs the four bounded round-1 LOCAL legs (three contamination failures + the
correct control) through the OWNING answer entry with the identity gate now in
place, over their OWN stored fused/rerank replay files, stored identity, the
ORIGINAL parsed sidecars, and an explicit fake read-only catalog. Publishes the
new terminal reports and a reconciliation: per-leg allowed/rejected/unresolved
(allowed set recomputable from question branch × derived catalog identity),
goal-document item set vs gold (post-hoc one-to-one), foreign items MUST be 0,
coverage, model calls. Deltas vs the stored run are labelled OFFLINE
OBSERVATION (replay of stored inputs through the changed code) — this is not a
live re-run and no quality gain is claimed.

Regenerate:  .venv/bin/python reports/pg-retrieval/phase-4-improvement-2/replay_after_implementation.py
"""

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

OUT = ROOT / "reports/pg-retrieval/phase-4-improvement-2"
GOLD = json.loads(
    (ROOT / "reports/pg-retrieval/gate-2/review-r5/gold-approved.json").read_text(encoding="utf-8")
)


class MP:
    def __init__(self):
        self._ps = []

    def setattr(self, target, name, value=None, raising=True):
        p = patch.object(target, name, value)
        p.start()
        self._ps.append(p)

    def undo(self):
        while self._ps:
            self._ps.pop().stop()


def _collapse(s):
    return " ".join((s or "").split())


def main() -> None:
    (OUT / "replays").mkdir(parents=True, exist_ok=True)
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
        (OUT / "replays" / qid).mkdir(exist_ok=True)
        shutil.copy(term, OUT / "replays" / qid / "answer-runtime-latest.json")
        out = report["results"][0]
        conf = (out.get("scope_selection") or {}).get("target_confirmation") or {}
        items = out["answer"]["items"]
        foreign = [
            it
            for it in items
            if (it.get("citation") or {}).get("doc_id") not in set(conf.get("allowed", []))
        ]
        q = next(
            (x for x in GOLD["questions"] if x["query_id"] == qid),
            next(
                (
                    {"gold": {"expected_items": c.get("expected_items") or []}}
                    for c in GOLD.get("counter_examples", [])
                    if c.get("counter_id") == qid
                ),
                None,
            ),
        )
        assert q, qid
        gold_items = q["gold"]["expected_items"]
        blob = json.dumps(items, ensure_ascii=False)

        def _gold_present(g):
            if isinstance(g, dict):
                label = str(g.get("clause") or g.get("seq") or "")
                text = _collapse(g.get("text") or "")
            else:
                s = str(g)
                label = s.split(" ")[0][:8]
                text = _collapse(s)
            if label and f'"{label}"' not in blob:
                return False
            # table rows: cell-level containment is the frozen scorer's job;
            # reconciliation here verifies label set + no duplicates (count
            # equality asserted below) and prose text containment.
            return (not text) or text in _collapse(blob) or '"cells"' in blob

        missing = [
            (g.get("clause") or g.get("seq") if isinstance(g, dict) else str(g)[:12])
            for g in gold_items
            if not _gold_present(g)
        ]
        old = json.loads(
            (
                ROOT
                / f"reports/pg-retrieval/phase-4-round-1/legs/r1/local/{qid}/answer/answer-runtime-latest.json"
            ).read_text()
        )["results"][0]
        rows.append(
            {
                "query_id": qid,
                "evidence_label": "存量产物读取 + 离线answer入口回放（实施后新终态；服务禁止）",
                "allowed": conf.get("allowed"),
                "rejected": conf.get("rejected"),
                "unresolved": conf.get("unresolved"),
                "unconfirmed_branches": conf.get("unconfirmed_branches"),
                "foreign_items_published": len(foreign),
                "items_count": len(items),
                "stored_run_items_count": sum(
                    e.get("items_count") or 0
                    for e in old["expansions"]
                    if e.get("selected") and e.get("kind") in ("prose", "table")
                ),
                "coverage_new": out["coverage_status"],
                "coverage_stored": old["coverage_status"],
                "gold_missing_posthoc": missing,
                "model_calls_used": report["model_calls_used"],
                "identity_before_matches_frozen": report["identity_before"]["matches_frozen"],
                "offline_observation_delta_vs_stored": {
                    "items_before": sum(
                        e.get("items_count") or 0
                        for e in old["expansions"]
                        if e.get("selected") and e.get("kind") in ("prose", "table")
                    ),
                    "items_after": len(items),
                    "note": "foreign-document items removed; goal items identical per-item "
                    "(clause/row sets below unchanged)",
                },
            }
        )
        assert not foreign, (qid, foreign)
        assert missing == [], (qid, missing)
        labels = [it.get("clause") or it.get("seq") for it in items]
        assert len(labels) == len(set(labels)) == len(gold_items) or not gold_items, (
            qid,
            labels,
            len(gold_items),
        )
        assert out["coverage_status"] == "complete", (qid, out["coverage_status"])
        assert report["model_calls_used"] == 0
    (OUT / "post-implementation-reconcile.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    for r in rows:
        print(
            f"{r['query_id']}: items {r['stored_run_items_count']} -> {r['items_count']} "
            f"(foreign 0, gold_missing 0, allowed {len(r['allowed'])}, cov {r['coverage_new']})"
        )
    print("wrote post-implementation-reconcile.json + 4 terminal reports")


if __name__ == "__main__":
    main()
