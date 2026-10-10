"""Freeze reviewer-owned source gold; never changes the agent's submission."""

import copy
import hashlib
import json
import re
from pathlib import Path

OUT = Path(__file__).parent
submitted = Path("reports/pg-retrieval/phase-2/gold-candidates.json")
payload = json.loads(submitted.read_text())
materials = json.loads(Path("reports/pg-retrieval/gate-2/raw-gold-materials.json").read_text())
by_name = {d["doc_name"]: d for d in materials.values()}
review = json.loads((OUT / "gold-review-v5.json").read_text())
counters = json.loads((OUT / "counterexamples-full.json").read_text())
assert len(payload["questions"]) == len(review["questions"]) == 31
assert len(payload["counter_examples"]) >= 8
assert len(counters["runs"]) == 8 and all(r["behavior_assertion_passed"] for r in counters["runs"])
assert counters["public_unchanged"] and counters["source_and_active_unchanged"]
assert counters["search_before"] == counters["search_after"]


def norm(value):
    return re.sub(r"\s+", "", str(value or "")).lower()


checks = []
for q in payload["questions"]:
    names = {t["doc_id"]: t["doc_name"] for t in q["target_docs"]}
    raw_blocks = []
    raw_rows = []
    for target in q["gold"].get("target_evidence", []):
        uid = target.get("unit_id")
        if not uid:
            continue
        doc = by_name[names[target["doc_id"]]]
        if uid in doc["tables"]:
            raw_rows.extend(doc["tables"][uid]["grid"])
        else:
            raw_blocks.append(next(b["content"] for b in doc["blocks"] if b["blockid"] == uid))
    for expected in q["gold"].get("expected_items") or []:
        if q["category"] == "table_enum":
            if expected.get("cells"):
                ok = any(
                    tuple(map(norm, expected["cells"])) == tuple(map(norm, row)) for row in raw_rows
                )
            elif "seq" in expected:
                ok = any(
                    norm(row[0]) == norm(expected["seq"]) and norm(row[1]) == norm(expected["name"])
                    for row in raw_rows
                    if len(row) > 1
                )
            else:
                ok = any(norm(row[1]) == norm(expected["name"]) for row in raw_rows if len(row) > 1)
        elif q["category"] == "prose_enum":
            text = expected.get("text") if isinstance(expected, dict) else expected
            ok = any(norm(text) in norm(block) for block in raw_blocks)
        else:
            continue
        checks.append({"query_id": q["query_id"], "expected": expected, "source_supported": ok})
        assert ok, q["query_id"]

frozen = copy.deepcopy(payload)
frozen["version"] = "gate2-source-gold-reviewed-2026-10-06-v1"
frozen["reviewer"] = "main agent"
frozen["reviewed_at"] = "2026-10-06"
frozen["submitted_sha256"] = hashlib.sha256(submitted.read_bytes()).hexdigest()
frozen["review_policy"] = {
    "source_gold_approved": True,
    "runtime_metrics_approved": False,
    "projection": "declared item content; source OCR labels preserved, canonical reference mapping separately reviewed",
    "citation_requirement": "all claimed quotations must re-read at their declared raw unit/grid position; citation_verified alone is not proof",
    "failed_questions": "retain fixed denominators and public failures; do not substitute versions or discard ambiguous answers",
    "discovery_requirement": "an explicitly empty discovery snapshot is authoritative; enumeration never rescues discovery recall",
}
frozen["reviewed_runtime_reference"] = {
    "catalog_snapshot_id": counters["catalog_after"]["active_snapshot_id"],
    "source_fingerprint": counters["catalog_after"]["stored_fingerprint"],
    "search_id": counters["search_after"]["search_id"],
    "tokenizer_version": counters["search_after"]["tokenizer_version"],
    "vocab_sha": counters["search_after"]["vocab_sha"],
    "top_k": 20,
}
for q in frozen["questions"]:
    q["gold_review_status"] = "approved"
    q["review_note"] = next(
        r["review_note"] for r in review["questions"] if r["query_id"] == q["query_id"]
    )
    if q["query_id"] == "prose-enum-004":
        q["gold"]["reviewed_class_mapping"] = [
            {"source_item_position": i + 1, "raw_source_label": raw, "canonical_class": canon}
            for i, (raw, canon) in enumerate(
                zip(["I类", "Ⅰ类", "Ⅰ类", "N类", "V类"], ["I类", "II类", "III类", "IV类", "V类"])
            )
        ]
for c in frozen["counter_examples"]:
    c["review_status"] = "expectation_reviewed"
(OUT / "gold-approved.json").write_text(json.dumps(frozen, ensure_ascii=False, indent=2) + "\n")
result = {
    "review_date": "2026-10-06",
    "source_gold_frozen": True,
    "runtime_metrics_approved": False,
    "positive_questions": 31,
    "negative_expectations": len(frozen["counter_examples"]),
    "real_counter_runs": 8,
    "real_counter_assertions_passed": 8,
    "submitted_sha256": frozen["submitted_sha256"],
    "approved_sha256": hashlib.sha256((OUT / "gold-approved.json").read_bytes()).hexdigest(),
    "expected_item_source_checks": checks,
    "note": "Gold data correctness is approved independently of the still failing implementation; submitted labels remain unchanged.",
}
(OUT / "gold-freeze-manifest.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2) + "\n"
)
print(
    "frozen",
    len(frozen["questions"]),
    len(frozen["counter_examples"]),
    "expected source checks",
    len(checks),
)
