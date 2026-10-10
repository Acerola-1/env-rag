"""Independent source reread and explicit amendment routing; zero model calls."""

import asyncio
import hashlib
import json
from pathlib import Path

import asyncpg
from dotenv import dotenv_values

from env_rag_final import fusion as fu
from env_rag_final.compat_runtime import _identity_drift
from env_rag_final.search.query import run_query

ROOT = Path("reports/pg-retrieval/phase-3-fusion-review")


async def main():
    values = dict(dotenv_values(".env"))
    before = await fu._capture_identity(values)
    submitted = json.loads(
        Path("reports/pg-retrieval/phase-3-fusion/fusion-runtime-latest.json").read_text()
    )
    conn = await asyncpg.connect(**fu._pg_dsn(values))
    reread = []
    try:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            for result in submitted["results"]:
                for entry in result["usable"]:
                    row = await conn.fetchrow(
                        "SELECT id,workspace,full_doc_id,content FROM public.lightrag_doc_chunks "
                        "WHERE workspace=$1 AND id=$2",
                        entry["workspace"],
                        entry["chunk_id"],
                    )
                    valid = bool(row) and (
                        row["full_doc_id"] == entry["doc_id"]
                        and row["content"] == entry["content"]
                        and hashlib.sha256(row["content"].encode()).hexdigest()
                        == entry["content_sha256"]
                    )
                    reread.append(
                        {
                            "query_id": result["query_id"],
                            "chunk_id": entry["chunk_id"],
                            "verified": valid,
                        }
                    )
            related = await run_query(
                conn,
                "GB 18466-2005 含修改单的相关文件有哪些？",
                workspace="default",
                expand=False,
            )
            requested, resolved = fu._pg_targets(related)
            _, targets, _ = fu._normalize_pg(related)
            allowed = fu._allowed_docs(resolved)
            amendments = [t for t in targets if t.get("discovery") == "doc_attribution"]
            constraint_probe = fu._apply_doc_constraint(
                [{"doc_id": t["doc_id"], "discovery": t["discovery"]} for t in amendments], allowed
            )
    finally:
        await conn.close()
    after = await fu._capture_identity(values)
    report = {
        "submitted_source_reread": reread,
        "verified_count": sum(e["verified"] for e in reread),
        "related_request": {
            "status": related.status,
            "requested": requested,
            "resolved": resolved,
            "pg_proven_related_targets": amendments,
            "fusion_constraint_decisions": constraint_probe,
        },
        "identity_before": before,
        "identity_after": after,
        "identity_drift": _identity_drift(before["identity"], after["identity"]),
        "model_calls": 0,
        "writes": 0,
    }
    (ROOT / "read-only-probes.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "reread": len(reread),
                "verified": report["verified_count"],
                "pg_related_targets": len(amendments),
                "related_targets_wrongly_rejected": sum(
                    bool(e.get("constraint_rejected")) for e in constraint_probe
                ),
                "drift": report["identity_drift"],
                "model_calls": 0,
            }
        )
    )


asyncio.run(main())
