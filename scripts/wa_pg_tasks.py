#!/usr/bin/env python
"""Three real PG task types per library: file list, prose clause, confirmed table.

Runs the workspace-aware enumeration entry points against the live catalog for
``air`` and ``water`` and records the coverage, citations and snapshot identity
of each result.  No model is involved; these are deterministic complete-range
reads.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = str(ROOT / ".venv/bin/env-rag-final")

TARGETS = {
    "air": {
        "files_query": "臭氧污染防治攻坚行动方案 涉及哪些文件",
        "prose_doc": "doc-00645c1f4da31db8df7673ca9d0dd052",
        "prose_scope": "doc-00645c1f4da31db8df7673ca9d0dd052:scope:01.1",
        "table_doc": "doc-e48b9ef7fd5c2049d28342dec28aecfb",
        "table_number": "1",
    },
    "water": {
        "files_query": "地表水环境质量标准 涉及哪些文件",
        "prose_doc": "doc-22aae4e69fd62630943d8d2de1dc3255",
        "prose_scope": "doc-22aae4e69fd62630943d8d2de1dc3255:scope:1",
        "table_doc": "doc-9bb11e5d3809e590259aef28fb61062b",
        "table_number": "1",
    },
}


def run(args: list[str]) -> dict:
    res = subprocess.run([CLI, *args], cwd=ROOT, text=True, capture_output=True, timeout=900)
    text = res.stdout
    start = text.find("{")
    payload = json.loads(text[start:]) if start >= 0 else None
    if payload is None:
        return {"exit": res.returncode, "error": (res.stdout + res.stderr)[-300:]}
    payload["exit"] = res.returncode
    return payload


def slim(payload: dict) -> dict:
    if "error" in payload:
        return payload
    items = (
        payload.get("answer", {}).get("items")
        if isinstance(payload.get("answer"), dict)
        else payload.get("items")
    )
    items = items or []
    return {
        "exit": payload.get("exit"),
        "workspace": payload.get("workspace"),
        "catalog_snapshot_id": payload.get("catalog_snapshot_id"),
        "source_snapshot_id": payload.get("source_snapshot_id"),
        "coverage_status": payload.get("coverage_status"),
        "fail_stage": payload.get("fail_stage"),
        "items": len(items),
        "items_verified": sum(1 for i in items if (i.get("citation") or {}).get("verified", True)),
        "first_citation": (items[0].get("citation") if items else None),
        "members_total": payload.get("members_total"),
        "members_processed": payload.get("members_processed"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out", default=str(ROOT / "reports/workspace-access/wa-20261012-r1/pg-tasks.json")
    )
    args = parser.parse_args()
    rows: list[dict] = []
    for workspace, target in TARGETS.items():
        cases = [
            (
                "files",
                [
                    "ask",
                    "--workspace",
                    workspace,
                    "--query",
                    target["files_query"],
                    "--kind",
                    "files",
                    "--format",
                    "json",
                ],
            ),
            (
                "prose",
                [
                    "enum-prose",
                    "--workspace",
                    workspace,
                    "--doc-id",
                    target["prose_doc"],
                    "--scope-id",
                    target["prose_scope"],
                ],
            ),
            (
                "table",
                [
                    "enum-table",
                    "--workspace",
                    workspace,
                    "--doc-id",
                    target["table_doc"],
                    "--table-number",
                    target["table_number"],
                ],
            ),
        ]
        for kind, argv in cases:
            started = time.time()
            result = run(argv)
            rows.append(
                {
                    "workspace": workspace,
                    "task": kind,
                    "argv": argv[1:],
                    "elapsed_s": round(time.time() - started, 2),
                    **slim(result),
                }
            )
    out = Path(args.out)
    out.write_text(json.dumps({"tasks": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    for row in rows:
        print(
            f"  {row['workspace']:6s} {row['task']:6s} status={row.get('coverage_status')} "
            f"items={row.get('items')} snapshot={str(row.get('catalog_snapshot_id'))[:12]} "
            f"exit={row.get('exit')} {row.get('elapsed_s')}s"
        )
    bad = [
        r
        for r in rows
        if r.get("coverage_status") not in ("complete", "partial", "ambiguous", "missing")
    ]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
