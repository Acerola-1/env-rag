import hashlib
import json
from pathlib import Path

from env_rag_final.config import read_environment

OUT = Path(__file__).parent
preview = json.loads((OUT / "ocr-preview.json").read_text())
reviewed = {
    "pyproject.toml",
    "src/env_rag_final/cli.py",
    "src/env_rag_final/enumerate_/contract.py",
    "src/env_rag_final/enumerate_/prose_enum.py",
    "src/env_rag_final/enumerate_/table_enum.py",
    "src/env_rag_final/enumerate_/tables.py",
    "reports/pg-retrieval/phase-2/gold-candidates.json",
    "reports/pg-retrieval/phase-2/bench-r2.json",
    "reports/pg-retrieval/phase-2/explain-evidence.json",
    "tests/test_gate2_acceptance.py",
    "tests/test_gate2_rereview.py",
}
reviewed.update(str(p) for p in Path("src/env_rag_final/search").glob("*.py"))
entries = []
for classification, items in [
    ("reviewable", preview["reviewable_files"]),
    ("excluded", preview["excluded_files"]),
]:
    for item in items:
        path = item["path"]
        did = path in reviewed
        reason = (
            "Phase2 implementation/behavior/call path or submitted scoring evidence inspected"
            if did
            else (
                "Historical acceptance/runtime artifact retained; not re-audited during Phase2 incremental review"
                if path.startswith("reports/")
                else "Previously accepted Gate0/Gate1 implementation or unrelated scaffold; outside this incremental review"
            )
        )
        entries.append(
            {
                "path": path,
                "status": item["status"],
                "ocr_classification": classification,
                "review_status": "reviewed" if did else "skipped",
                "reason": reason,
                "ocr_exclusion_reason": item.get("exclude_reason"),
            }
        )
main = [e for e in entries if e["ocr_classification"] == "reviewable"]
coverage = {
    "total_files": len(main),
    "reviewed_files": sum(e["review_status"] == "reviewed" for e in main),
    "skipped_files": sum(e["review_status"] == "skipped" for e in main),
    "previewed_total_including_excluded": len(entries),
    "excluded_count": preview["excluded_count"],
    "accounted_for_rate": 1.0,
    "entries": entries,
    "extra_manual_review": [
        "README.md",
        "OpenSpec tasks/design/handoff acceptance requirements",
        "tests/test_gate2_review_r3.py",
        "current phase2 fix report/counterexample logs",
        "31 gold questions/10 negative expectations",
        "new readonly PG results and source fingerprints",
        "raw-source grid and block spans",
    ],
}
coverage["coverage_rate"] = coverage["reviewed_files"] / coverage["total_files"]
(OUT / "coverage-manifest.json").write_text(
    json.dumps(coverage, ensure_ascii=False, indent=2) + "\n"
)
final = json.loads((OUT / "files-and-final-source.json").read_text())
old = json.loads(Path("reports/pg-retrieval/gate-2/re-review/review-manifest.json").read_text())
paths = sorted(reviewed | {"tests/test_gate2_review_r3.py"})
hashes = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths if Path(p).is_file()}
values = read_environment(Path(".env"))
secrets = [
    v
    for k, v in values.items()
    if any(s in k.upper() for s in ("API_KEY", "PASSWORD", "SECRET", "TOKEN")) and len(v) >= 6
]
leaks = []
scan = list(OUT.glob("*")) + [
    Path("openspec/changes/add-pg-scoped-retrieval/handoff-phase-2-fixes-r3.md")
]
for p in scan:
    if p.is_file():
        s = p.read_text(errors="replace")
        if any(v in s for v in secrets):
            leaks.append(str(p))
manifest = {
    "review_date": "2026-10-06",
    "result": "Gate2 not passed",
    "accepted_tasks": ["4.1", "4.2", "4.3"],
    "pending_tasks": ["4.4", "4.5", "4.6"],
    "phase3_authorized": False,
    "tests": {
        "submitted_existing_passed": 152,
        "final_passed": 152,
        "final_failed": 9,
        "original13_sha_unchanged": hashes["tests/test_gate2_acceptance.py"]
        == old["source_sha256"]["tests/test_gate2_acceptance.py"],
        "second11_sha_unchanged": hashes["tests/test_gate2_rereview.py"]
        == old["source_sha256"]["tests/test_gate2_rereview.py"],
    },
    "checks": {
        "ruff_check": "passed",
        "ruff_format": "passed",
        "openspec_strict": "passed",
        "diff_check": "passed",
        "credential_scan_files": len(scan),
        "credential_leak_files": leaks,
    },
    "live_evidence": {
        "production_query_replays": 26,
        "benchmark_questions": 31,
        "file_full_enumerations": 6,
        "formal_cli_runs": 3,
        "tokenizer_cases": 25,
        "tokenizer_passed": 25,
        "table_raw_row_citations_reread": 167,
        "prose_raw_quotes_reread": 12,
        "source_reread_errors": 0,
        "readonly": True,
        "db_writes": 0,
        "model_calls": 0,
        "index_rebuilds": 0,
    },
    "final_source": {
        "public_counts": final["public_after"],
        "catalog": final["catalog_after"],
        "search": final["search_after"],
        "public_unchanged": final["public_unchanged"],
        "catalog_and_source_unchanged": final["source_and_active_unchanged"],
        "search_unchanged": final["search_before"] == final["search_after"],
    },
    "gold": {
        "questions_reexamined": 31,
        "negative_expectations_reexamined": 10,
        "frozen": False,
        "metrics_approved": False,
    },
    "coverage": {k: v for k, v in coverage.items() if k != "entries"},
    "source_sha256": hashes,
    "next": "openspec/changes/add-pg-scoped-retrieval/handoff-phase-2-fixes-r3.md",
}
(OUT / "review-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
print(
    {
        k: coverage[k]
        for k in (
            "total_files",
            "reviewed_files",
            "skipped_files",
            "coverage_rate",
            "accounted_for_rate",
        )
    }
)
print("credential_leak_files", len(leaks))
