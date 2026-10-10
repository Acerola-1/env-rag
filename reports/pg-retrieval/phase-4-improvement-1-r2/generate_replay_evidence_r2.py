"""R2 function-level replay evidence — OFFLINE ONLY (no network/DB/model).

Re-runs the five prose questions through the FORMAL expansion entry + the
answer-side independent reader exactly as
tests/test_phase4_improvement1_prose_integrity.py does, and records per
question: the INPUT requested_clauses derived from the original question
text (F4-a — never from gold), the stored trace's recorded input for
contrast, the delivered item set, and the one-to-one (编号+全文+来源)
missing/extra sets against gold (post-hoc only).

Regenerate:  .venv/bin/python reports/pg-retrieval/phase-4-improvement-1-r2/generate_replay_evidence_r2.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import test_phase4_improvement1_prose_integrity as t  # noqa: E402

R1 = ROOT / "reports/pg-retrieval/phase-4-round-1"


def case(qid: str) -> dict:
    d = json.loads((R1 / f"legs/r1/pg/{qid}/answer/answer-runtime-latest.json").read_text())
    exp = next(e for e in d["results"][0]["expansions"] if e.get("selected") and e.get("kind") == "prose")
    result, items, probs, q = t._replay(qid)
    require_clause = qid != "prose-enum-004"
    missing, extra = t._set_match(
        q["gold"]["expected_items"], items, result["doc_id"], result["unit_ids"], require_clause
    )
    return {
        "query_id": qid,
        "evidence_label": "原始产物离线读取 + 离线正式入口回放（fake 只读连接、已存 trace 身份）",
        "question": q["question"],
        "input_requested_clauses_from_question": t._request_from_question(
            q["question"], exp["scope_id"].rsplit(":", 1)[-1]
        ),
        "stored_trace_recorded_input": exp.get("requested_clauses"),
        "coverage_status": result["coverage_status"],
        "independent_reread_problems": probs,
        "one_to_one": {"missing": missing, "extra": extra},
        "items": [
            {
                "clause": it.get("clause"),
                "len": len(it.get("text") or ""),
                "verified": it.get("citation_verified"),
                "reverified": it.get("citation_reverified"),
            }
            for it in items
        ],
    }


def main() -> None:
    cases = [case(q) for q in ("prose-enum-003", "prose-enum-001", "prose-enum-002", "prose-enum-004", "prose-enum-006")]
    for c in cases:
        assert c["one_to_one"] == {"missing": [], "extra": []}, c
        assert c["independent_reread_problems"] == [], c
        assert c["coverage_status"] == "complete", c
    out = Path(__file__).resolve().parent / "replay-evidence-r2.json"
    out.write_text(json.dumps(cases, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out} (5 questions, all one-to-one exact, 0 problems, complete)")


if __name__ == "__main__":
    main()
