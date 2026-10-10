"""Bounded four-local follow-up; --dry-run makes ZERO backend requests.

Use the new approved anchor explicitly, then the unchanged owning evaluation
entry. The default CLI anchor and all historical anchor files stay untouched.
"""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from env_rag_final.config import read_environment
from env_rag_final.evaluation import run_evaluation, validate_phase4_anchor

ROOT = Path(__file__).resolve().parents[3]
ANCHOR = ROOT / "reports/pg-retrieval/phase-4/phase-4-config-anchor-improvements123-local-r1.json"
BUDGET = ROOT / "reports/pg-retrieval/phase-4/improvements123-local-validation-budget.json"
QUERIES = [
    "file-enum-005",
    "prose-enum-001",
    "neg-004",
    "prose-enum-006",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    anchor = json.loads(ANCHOR.read_text())
    for name, expected in anchor["evaluation_code_anchors"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"additional approved code anchor drift: {name}")
    values = read_environment(ROOT / ".env")
    expected = validate_phase4_anchor(anchor_path=ANCHOR, values=values)
    report = asyncio.run(
        run_evaluation(
            args.report_dir,
            round_no=1,
            rounds=[1] if args.dry_run else None,
            paths=["local"],
            query_ids=QUERIES,
            dry_run=args.dry_run,
            budgets=json.loads(BUDGET.read_text()),
            values=values,
            expected_identity=expected,
            user_allows_answer_model=False,
        )
    )
    print("Local-only dry-run" if args.dry_run else "Local-only bounded validation completed")
    print(f"artifacts: {args.report_dir.resolve()}")
    if args.dry_run:
        print(f"backend_fetches: {report.get('backend_fetches')}")


if __name__ == "__main__":
    main()
