"""Read-only classification of submitted enrichment paths, zero model calls."""

import asyncio
import collections
import json
from pathlib import Path

import asyncpg
from dotenv import dotenv_values


async def main():
    values = dotenv_values(".env")
    runtime = json.loads(
        Path("reports/pg-retrieval/phase-3-rerank-r2/rerank-runtime-latest.json").read_text()
    )
    result = runtime["results"][0]
    snapshot = runtime["identity_after"]["catalog_active"]["snapshot_id"]
    paths = [p for c in result["ordered"] for p in c["paths"] if p.get("enrichment_basis")]
    ids = sorted({p["unit_id"] for p in paths})
    conn = await asyncpg.connect(
        host=values["POSTGRES_HOST"],
        port=int(values["POSTGRES_PORT"]),
        user=values["POSTGRES_USER"],
        password=values["POSTGRES_PASSWORD"],
        database=values["POSTGRES_DATABASE"],
        timeout=15,
        server_settings={"default_transaction_read_only": "on"},
    )
    try:
        async with conn.transaction(readonly=True):
            rows = await conn.fetch(
                "SELECT unit_id, unit_kind, doc_id FROM env_rag.source_units "
                "WHERE workspace=$1 AND snapshot_id=$2 AND unit_id=ANY($3::text[])",
                result["workspace"],
                snapshot,
                ids,
            )
    finally:
        await conn.close()
    by_id = {r["unit_id"]: dict(r) for r in rows}
    entries = [
        {
            "unit_id": p["unit_id"],
            "claimed_kind": p["citation"]["kind"],
            "actual_kind": by_id.get(p["unit_id"], {}).get("unit_kind"),
            "doc_id": by_id.get(p["unit_id"], {}).get("doc_id"),
        }
        for p in paths
    ]
    report = {
        "snapshot": snapshot,
        "enriched_paths": len(entries),
        "actual_kinds": dict(collections.Counter(p["actual_kind"] for p in entries)),
        "wrong_table_claims": sum(
            p["claimed_kind"] == "table_unit" and p["actual_kind"] != "table" for p in entries
        ),
        "paths": entries,
        "model_calls": 0,
        "writes": 0,
    }
    Path("reports/pg-retrieval/phase-3-rerank-review-r2/unit-type-probe.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps({k: v for k, v in report.items() if k != "paths"}))


asyncio.run(main())
