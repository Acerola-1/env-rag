"""Explicit fixed-code rounds; dry-run is zero backend, live needs user consent."""

import argparse
import asyncio
import json

from prepared_common import (
    HERE,
    ROOT,
    check_terminal,
    round_path,
    validate_bundle,
    verify_artifact_manifest,
)

from env_rag_final.evaluation import run_evaluation


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--round", type=int, choices=(1, 2))
    parser.add_argument(
        "--authorized", action="store_true", help="use ONLY after human approves this batch"
    )
    args = parser.parse_args(argv)
    if not args.dry_run and (args.round is None or not args.authorized):
        raise SystemExit("live mode requires a selected round and explicit user-authorized batch")
    anchor, values, expected = validate_bundle()
    if args.dry_run:
        destination = HERE / "dry-run"
        budgets = json.loads((HERE / "two-round-budget.json").read_text())
    else:
        destination = round_path(args.round)
        if destination.exists():
            raise SystemExit("round destination already exists: no retry or historical overwrite")
        budgets = json.loads((HERE / f"round-{args.round}-budget.json").read_text())
        mapping_dir = ROOT / "reports/pg-retrieval/phase-4-formal-mapping-r2"
        verify_artifact_manifest(
            mapping_dir / "capture-manifest.json", [mapping_dir / "mapping.json"]
        )
        mapping = json.loads((mapping_dir / "mapping.json").read_text())
        if (
            mapping["source_fingerprint"] != expected["source_fingerprint"]
            or mapping["catalog_snapshot_id"]
            != anchor["frozen_identity"]["catalog_run_snapshot"].split("/")[1]
        ):
            raise SystemExit("mapping identity differs from this approved generation")
        if args.round == 2:
            first = round_path(1)
            terminal = json.loads((first / "eval-runtime-latest.json").read_text())
            check_terminal(terminal, budgets["total_caps"])
            if not (first / "pilot-manifest.json").exists():
                raise SystemExit("round 1 evidence manifest required before round 2")
            verify_artifact_manifest(
                first / "pilot-manifest.json",
                [first / "eval-runtime-latest.json", first / "prepared-binding.json"],
            )
            binding = json.loads((first / "prepared-binding.json").read_text())
            if binding["generation"] != anchor["generation"]["id"] or binding["round"] != 1:
                raise SystemExit("first-round generation binding differs from this approved batch")
        destination.mkdir(parents=True)
        (destination / "prepared-binding.json").write_text(
            json.dumps(
                {
                    "generation": anchor["generation"]["id"],
                    "round": args.round,
                    "budget_file": f"round-{args.round}-budget.json",
                    "consent_flag": True,
                    "no_retry": True,
                },
                indent=2,
            )
            + "\n"
        )
    report = asyncio.run(
        run_evaluation(
            destination,
            round_no=args.round or 1,
            rounds=[1, 2] if args.dry_run else None,
            paths=["pg", "local", "fusion"],
            query_ids=None,
            dry_run=args.dry_run,
            budgets=budgets,
            values=values,
            expected_identity=expected,
            user_allows_answer_model=not args.dry_run,
        )
    )
    if not args.dry_run:
        check_terminal(report, budgets["total_caps"])
    print(
        json.dumps(
            {
                "mode": "dry-run" if args.dry_run else "live",
                "round": args.round,
                "report_dir": str(destination),
                "backend_fetches": report.get("backend_fetches"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
