"""Record incremental review coverage and final unchanged-source evidence."""

import hashlib
import json
from pathlib import Path

from env_rag_final.config import read_environment

OUT = Path(__file__).parent
preview = json.loads((OUT / "ocr-preview.json").read_text())
reviewed = {
    "src/env_rag_final/search/eval.py",
    "src/env_rag_final/search/expand.py",
    "src/env_rag_final/search/gold.py",
    "src/env_rag_final/search/query.py",
    "reports/pg-retrieval/phase-2/gold-candidates.json",
    "reports/pg-retrieval/phase-2/bench-r3.json",
    "tests/test_gate2_acceptance.py",
    "tests/test_gate2_rereview.py",
    "tests/test_gate2_review_r3.py",
}
entries = []
for kind, items in [
    ("reviewable", preview["reviewable_files"]),
    ("excluded", preview["excluded_files"]),
]:
    for item in items:
        done = item["path"] in reviewed
        reason = (
            "Phase2 changed implementation/owning call path, submitted gold/score or unchanged acceptance assertions examined"
            if done
            else (
                "Historical runtime/review artifact retained; not re-audited in this Phase2 incremental review"
                if item["path"].startswith("reports/")
                else "Previously accepted implementation/dependency/scaffold outside the present Phase2 change; earlier review retained"
            )
        )
        entries.append(
            {
                "path": item["path"],
                "status": item["status"],
                "ocr_classification": kind,
                "review_status": "reviewed" if done else "skipped",
                "reason": reason,
                "ocr_exclusion_reason": item.get("exclude_reason"),
            }
        )
selected = [e for e in entries if e["ocr_classification"] == "reviewable"]
coverage = {
    "total_files": len(selected),
    "reviewed_files": sum(e["review_status"] == "reviewed" for e in selected),
    "skipped_files": sum(e["review_status"] == "skipped" for e in selected),
    "excluded_count": preview["excluded_count"],
    "previewed_total_including_excluded": len(entries),
    "entries": entries,
    "accounted_for_rate": 1.0,
    "extra_manual_review": [
        "tests/test_gate2_review_r4.py",
        "README and OpenSpec tasks/design/handoffs",
        "current fix report and 31-question/10-expectation gold review",
        "new readonly production/benchmark/scope/CLI/source outputs",
        "167 raw grid rows and11 raw prose citation checks",
    ],
}
coverage["coverage_rate"] = coverage["reviewed_files"] / coverage["total_files"]
(OUT / "coverage-manifest.json").write_text(
    json.dumps(coverage, ensure_ascii=False, indent=2) + "\n"
)
old = json.loads(Path("reports/pg-retrieval/gate-2/review-r3/review-manifest.json").read_text())
tests = (
    "tests/test_gate2_acceptance.py",
    "tests/test_gate2_rereview.py",
    "tests/test_gate2_review_r3.py",
)
files = reviewed | set(tests) | {"tests/test_gate2_review_r4.py"}
hashes = {
    p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in sorted(files) if Path(p).is_file()
}
unchanged = {p: hashes[p] == old["source_sha256"][p] for p in tests}
source = json.loads((OUT / "final-source.json").read_text())
bench = json.loads((OUT / "benchmark.json").read_text())
raw_checks = {
    category: {
        "questions": sum(r["category"] == category for r in bench["rows"]),
        "current_program_exact": sum(
            r["category"] == category and bool(r.get("enum_set_check", {}).get("exact_match"))
            for r in bench["rows"]
        ),
    }
    for category in ("prose_enum", "table_enum", "file_enum")
}
scan = list(OUT.glob("*")) + [
    Path("openspec/changes/add-pg-scoped-retrieval/handoff-phase-2-fixes-r4.md")
]
v = read_environment(Path(".env"))
secrets = [
    value
    for key, value in v.items()
    if any(k in key.upper() for k in ("API_KEY", "PASSWORD", "TOKEN", "SECRET")) and len(value) >= 6
]
leaks = []
for p in scan:
    if p.is_file() and any(value in p.read_text(errors="replace") for value in secrets):
        leaks.append(str(p))
manifest = {
    "review_date": "2026-10-06",
    "result": "Gate2 not passed",
    "accepted_tasks": ["4.1", "4.2", "4.3"],
    "pending_tasks": ["4.4", "4.5", "4.6"],
    "phase3_authorized": False,
    "tests": {
        "existing_passed": 161,
        "new_counterexamples_failed": 7,
        "old33_assertion_files_unchanged": unchanged,
    },
    "checks": {
        "ruff_check": "passed",
        "ruff_format": "passed",
        "openspec_strict": "passed",
        "diff_check": "passed",
        "credential_scan_files": len(scan),
        "credential_leak_files": leaks,
    },
    "live": {
        "readonly": True,
        "production_queries": 26,
        "benchmark_questions": 31,
        "tokenizer_cases": 25,
        "tokenizer_passed": 25,
        "direct_scope_reads": 2,
        "explicit_scope_queries": 2,
        "formal_cli_runs": 2,
        "db_writes": 0,
        "index_rebuilds": 0,
        "model_calls": 0,
        "raw_table_row_citations_checked": 167,
        "raw_prose_citations_checked": 11,
        "unbound_prose_citations": 1,
    },
    "source_final": {
        "public_counts": source["public_after"],
        "catalog": source["catalog_after"],
        "search": source["search_after"],
        "public_unchanged": source["matches_initial_public"],
        "catalog_and_source_unchanged": source["matches_initial_catalog"],
        "search_unchanged": source["matches_initial_search"],
    },
    "gold": {
        "positives_reexamined": 31,
        "counter_expectations_reexamined": 10,
        "formal_frozen": False,
        "metrics_approved": False,
    },
    "current_program_checks_unapproved": raw_checks,
    "coverage": {k: value for k, value in coverage.items() if k != "entries"},
    "source_sha256": hashes,
    "next": "openspec/changes/add-pg-scoped-retrieval/handoff-phase-2-fixes-r4.md",
}
(OUT / "review-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
summary = {
    k: coverage[k] for k in ("total_files", "reviewed_files", "skipped_files", "coverage_rate")
}
review = OUT / "review.md"
text = review.read_text().split("\n审查覆盖统计：")[0]
review.write_text(
    text
    + "\n审查覆盖统计："
    + json.dumps(summary, ensure_ascii=False)
    + "；全部preview条目均有review/skip及理由，额外人工审查另记于账本。\n"
)
print(summary, "credential leak files", len(leaks))
