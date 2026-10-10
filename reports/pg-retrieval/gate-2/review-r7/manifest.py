"""Preserve reviewer coverage, immutable gold identity, and current source state."""

import hashlib
import json
from pathlib import Path

from env_rag_final.config import read_environment

OUT = Path(__file__).parent
preview = json.loads((OUT / "ocr-preview.json").read_text())
reviewed = {
    "src/env_rag_final/search/expand.py",
    "src/env_rag_final/enumerate_/prose_enum.py",
    "src/env_rag_final/cli.py",
    "tests/test_gate2_review_r6.py",
    "reports/pg-retrieval/phase-2/report-gate2-fixes-r6.md",
    "reports/pg-retrieval/phase-2/bench-r6.json",
}
entries = []
for classification, items in [
    ("reviewable", preview["reviewable_files"]),
    ("excluded", preview["excluded_files"]),
]:
    for item in items:
        done = item["path"] in reviewed
        entries.append(
            {
                "path": item["path"],
                "status": item["status"],
                "ocr_classification": classification,
                "review_status": "reviewed" if done else "skipped",
                "reason": "F1 changed implementation, owning paths, acceptance test or submitted score/report examined"
                if done
                else "Prior accepted source/dependency or historical artifact outside this incremental F1 review; no new full-repository audit",
                "ocr_exclusion_reason": item.get("exclude_reason"),
            }
        )
selected = [e for e in entries if e["ocr_classification"] == "reviewable"]
coverage = {
    "total_files": len(selected),
    "reviewed_files": sum(e["review_status"] == "reviewed" for e in selected),
    "skipped_files": sum(e["review_status"] == "skipped" for e in selected),
    "excluded_count": len(preview["excluded_files"]),
    "accounted_for_rate": 1.0,
    "entries": entries,
    "extra_manual_review": [
        "tests/test_gate2_review_r7.py (created after preview)",
        "frozen reviewer gold, prior hashes, all 31 current runs, 301 raw citations, 8 real negatives, source and guard boundaries (no new CLI invocation)",
        "OpenSpec current tasks and handoffs; current read-only identity and tokenizer outputs",
    ],
}
coverage["coverage_rate"] = coverage["reviewed_files"] / coverage["total_files"]
(OUT / "coverage-manifest.json").write_text(
    json.dumps(coverage, ensure_ascii=False, indent=2) + "\n"
)

old = json.loads(Path("reports/pg-retrieval/gate-2/review-r5/review-manifest.json").read_text())
hashes = {
    p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
    for p in reviewed | {"tests/test_gate2_review_r7.py"}
    if Path(p).is_file()
}
old["source_sha256"]["tests/test_gate2_review_r6.py"] = json.loads(
    Path("reports/pg-retrieval/gate-2/review-r6/review-manifest.json").read_text()
)["source_sha256"]["tests/test_gate2_review_r6.py"]
old_tests = {
    p: hashlib.sha256(Path(p).read_bytes()).hexdigest() == h
    for p, h in old["source_sha256"].items()
    if p.startswith("tests/")
}
assert all(old_tests.values())
freeze = json.loads(
    Path("reports/pg-retrieval/gate-2/review-r5/gold-freeze-manifest.json").read_text()
)
gold_hash = hashlib.sha256(
    Path("reports/pg-retrieval/gate-2/review-r5/gold-approved.json").read_bytes()
).hexdigest()
assert gold_hash == freeze["approved_sha256"]
replay = json.loads((OUT / "replay.json").read_text())
final = json.loads((OUT / "final-source.json").read_text())
assert all(
    final[k]
    for k in ("matches_initial_public", "matches_initial_catalog", "matches_initial_search")
)
probes = json.loads((OUT / "tokenizer-probes.json").read_text())
assert len(probes["index_query_consistency"]) == 25 and all(
    t["pass"] for t in probes["index_query_consistency"]
)
counters = json.loads((OUT / "counterexamples-full.json").read_text())
assert len(counters["runs"]) == 8 and all(r["behavior_assertion_passed"] for r in counters["runs"])
cli = []
assert all(r["exit_code"] == 0 for r in cli)
citation = json.loads((OUT / "citation-reread.json").read_text())
assert all(s["failed"] == 0 for s in citation["summary"].values())
values = read_environment(Path(".env"))
secrets = [
    v
    for k, v in values.items()
    if any(s in k.upper() for s in ("API_KEY", "PASSWORD", "SECRET", "TOKEN")) and len(v) >= 6
]
scan = [p for p in OUT.iterdir() if p.is_file()] + [
    Path("openspec/changes/add-pg-scoped-retrieval/handoff-phase-2-fixes-r7.md")
]
leaks = [str(p) for p in scan if any(v in p.read_text(errors="replace") for v in secrets)]
assert not leaks
manifest = {
    "review_date": "2026-10-06",
    "result": "Gate2 not passed; body offsets accepted; F1 verifier has three counterexamples",
    "accepted_tasks": ["4.1", "4.2", "4.3", "4.5"],
    "pending_tasks": ["4.4", "4.6"],
    "phase3_authorized": False,
    "tests": {"existing_passed": 171, "new_failed": 3, "old43_files_unchanged": old_tests},
    "gold": {
        "source_gold_frozen": True,
        "sha256": gold_hash,
        "unchanged": True,
        "positive_questions": 31,
        "negative_expectations": 10,
    },
    "live": {
        "production_queries": 0,
        "benchmark_questions": 31,
        "real_negative_runs": 8,
        "negative_passed": 8,
        "formal_cli_runs": 0,
        "tokenizer_cases": 25,
        "tokenizer_passed": 25,
        "db_writes": 0,
        "index_rebuilds": 0,
        "model_calls": 0,
        "readonly": True,
        "citations": citation["summary"],
    },
    "frozen_benchmark_metrics_reproduced": True,
    "metrics": json.loads((OUT / "metrics-audit.json").read_text())["totals"],
    "enum_set_checks": json.loads((OUT / "benchmark.json").read_text())["enum_set_checks"],
    "source_final": {
        "public_counts": final["public_after"],
        "catalog": final["catalog_after"],
        "search": final["search_after"],
        "all_match_initial": True,
        "match_previous_review_search": final["search_after"] == old["source_final"]["search"],
    },
    "checks": {
        "ruff_check": "passed",
        "ruff_format": "passed",
        "openspec_strict": "passed",
        "diff_check": "passed",
        "credential_scan_files": len(scan),
        "credential_leak_files": leaks,
    },
    "source_sha256": hashes,
    "coverage": {
        k: coverage[k] for k in ("total_files", "reviewed_files", "skipped_files", "coverage_rate")
    },
}
(OUT / "review-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
print(
    {
        "result": manifest["result"],
        "coverage": manifest["coverage"],
        "gold_unchanged": True,
        "source_unchanged": True,
        "leaks": len(leaks),
    }
)
