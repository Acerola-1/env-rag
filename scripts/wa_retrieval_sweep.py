#!/usr/bin/env python
"""Retrieval sweep: PG, all five LightRAG modes and the PG+mode combinations.

Runs against the live gateway for both libraries and records, per case, the
real dispatch, the owning instance, the evidence counts and the failure
visibility.  No canned answers are used.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local/workspace-access"

CASES = [
    ("air", "air-reader", "臭氧污染防治攻坚行动方案要求什么"),
    ("water", "water-reader", "地表水环境质量标准的分类"),
]

MODES = ["naive", "local", "global", "hybrid", "mix"]


def call(
    client: httpx.Client,
    base: str,
    user: str,
    creds: dict,
    workspace,
    question: str,
    route: str,
    mode: str | None,
) -> dict:
    login = client.post(
        f"{base}/api/login", json={"user_id": user, "password": creds[user]["password"]}
    ).json()
    body = {"workspace": workspace, "question": question, "route": route, "no_record": True}
    if mode:
        body["mode"] = mode
    started = time.time()
    res = client.post(
        f"{base}/api/query", json=body, headers={"X-RAG-Token": login["csrf"]}, timeout=900
    )
    elapsed = round(time.time() - started, 2)
    if res.status_code != 200:
        return {"http": res.status_code, "elapsed_s": elapsed}
    result = res.json()["result"]
    blocks = result["per_workspace"]
    return {
        "http": 200,
        "elapsed_s": elapsed,
        "status": result["status"],
        "workspaces": result["workspaces"],
        "evidence": len(result["evidence"]),
        "failures": result["failures"],
        "stale": result.get("stale"),
        "per_workspace": [
            {
                "workspace": b["workspace"],
                "status": b["status"],
                "mode": b.get("mode"),
                "items": len(b.get("items") or []),
                "entities": len(b.get("entities") or []),
                "relationships": len(b.get("relationships") or []),
                "search_id": b.get("search_id"),
                "catalog_snapshot_id": b.get("catalog_snapshot_id"),
                "error": b.get("error"),
            }
            for b in blocks
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8099")
    parser.add_argument(
        "--out", default=str(ROOT / "reports/workspace-access/wa-20261012-r1/retrieval-sweep.json")
    )
    args = parser.parse_args()
    creds = json.loads((LOCAL / "credentials.json").read_text(encoding="utf-8"))
    client = httpx.Client(timeout=900)
    rows: list[dict] = []

    for workspace, user, question in CASES:
        rows.append(
            {
                "case": f"{workspace}:pg",
                "route": "pg",
                "mode": None,
                **call(client, args.base, user, creds, workspace, question, "pg", None),
            }
        )
        for mode in MODES:
            rows.append(
                {
                    "case": f"{workspace}:lightrag:{mode}",
                    "route": "lightrag",
                    "mode": mode,
                    **call(client, args.base, user, creds, workspace, question, "lightrag", mode),
                }
            )
            rows.append(
                {
                    "case": f"{workspace}:pg+lightrag:{mode}",
                    "route": "pg+lightrag",
                    "mode": mode,
                    **call(
                        client, args.base, user, creds, workspace, question, "pg+lightrag", mode
                    ),
                }
            )

    # dual-library combined question, one generation over both libraries
    rows.append(
        {
            "case": "dual:pg+lightrag:hybrid",
            "route": "pg+lightrag",
            "mode": "hybrid",
            **call(
                client,
                args.base,
                "dual-reader",
                creds,
                ["air", "water"],
                "空气质量标准与地表水环境质量标准的适用范围",
                "pg+lightrag",
                "hybrid",
            ),
        }
    )

    out = Path(args.out)
    out.write_text(json.dumps({"cases": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = [r for r in rows if r.get("http") == 200 and r.get("evidence")]
    print(json.dumps({"cases": len(rows), "with_evidence": len(ok)}, ensure_ascii=False))
    for r in rows:
        print(
            f"  {r['case']:34s} http={r.get('http')} status={r.get('status')} "
            f"ev={r.get('evidence')} {r.get('elapsed_s')}s "
            + (
                "FAIL " + json.dumps(r.get("failures"), ensure_ascii=False)
                if r.get("failures")
                else ""
            )
        )
    return 0 if len(ok) == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
