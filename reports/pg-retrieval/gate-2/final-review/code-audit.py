"""Check every explicit code/version route against the frozen target documents."""

import json
from pathlib import Path

OUT = Path(__file__).parent
gold = json.loads(Path("reports/pg-retrieval/gate-2/review-r5/gold-approved.json").read_text())
by_id = {q["query_id"]: q for q in gold["questions"]}
checks = []
questions = set()
for line in (OUT / "benchmark-runs.jsonl").read_text().splitlines():
    run = json.loads(line)
    expected = {d["doc_id"] for d in by_id[run["gold_query_id"]]["target_docs"]}
    for code in run["parsed_codes"]:
        stages = [
            s
            for s in run["trace"]
            if s.get("stage") == "code_exact"
            and s.get("code") == code["code"]
            and s.get("version_requested") == code["version"]
        ]
        selected = {d for s in stages for d in s.get("selected_docs", [])}
        versions = {v for s in stages for v in s.get("selected_versions", [])}
        passed = bool(stages) and bool(selected) and selected <= expected
        if code["version"]:
            passed = passed and versions == {code["version"]}
        checks.append(
            {
                "query_id": run["gold_query_id"],
                "requested": code,
                "selected_docs": sorted(selected),
                "expected_docs": sorted(expected),
                "selected_versions": sorted(versions),
                "passed": passed,
            }
        )
        questions.add(run["gold_query_id"])
assert checks and all(c["passed"] for c in checks), [c for c in checks if not c["passed"]]
out = {
    "positive_questions_with_explicit_codes": len(questions),
    "code_version_route_checks": len(checks),
    "passed": sum(c["passed"] for c in checks),
    "accuracy": 1.0,
    "checks": checks,
}
(OUT / "code-audit.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
print({k: v for k, v in out.items() if k != "checks"})
