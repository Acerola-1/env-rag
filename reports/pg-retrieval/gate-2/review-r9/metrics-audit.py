"""Independent discovery-only recall calculation using frozen raw runs and SELECTs."""

import asyncio
import json
from pathlib import Path

import asyncpg

from env_rag_final.config import read_environment

OUT = Path(__file__).parent


async def main():
    gold = json.loads(Path("reports/pg-retrieval/gate-2/review-r5/gold-approved.json").read_text())
    runs = {
        r["gold_query_id"]: r
        for r in map(json.loads, (OUT / "benchmark-runs.jsonl").read_text().splitlines())
    }
    values = read_environment(Path(".env"))
    conn = await asyncpg.connect(
        host=values["POSTGRES_HOST"],
        port=int(values["POSTGRES_PORT"]),
        user=values["POSTGRES_USER"],
        password=values["POSTGRES_PASSWORD"],
        database=values["POSTGRES_DATABASE"],
        server_settings={"default_transaction_read_only": "on", "statement_timeout": "30000"},
        statement_cache_size=0,
    )
    try:
        snap = gold["frozen_inputs"]["catalog_snapshot_id"]
        links = await conn.fetch(
            "SELECT workspace,doc_id,unit_id,chunk_id FROM env_rag.unit_chunk_links WHERE workspace=$1 AND snapshot_id=$2",
            "default",
            snap,
        )
        members = await conn.fetch(
            "SELECT workspace,doc_id,scope_id,unit_id FROM env_rag.scope_units WHERE workspace=$1 AND snapshot_id=$2",
            "default",
            snap,
        )
        unit_links = {}
        for r in links:
            unit_links.setdefault((r["workspace"], r["doc_id"], r["unit_id"]), set()).add(
                r["chunk_id"]
            )
        scope_units = {}
        for r in members:
            scope_units.setdefault((r["workspace"], r["doc_id"], r["scope_id"]), set()).add(
                r["unit_id"]
            )

        def match(t, candidates):
            ws, doc = t.get("workspace", "default"), t["doc_id"]
            cs = [
                c
                for c in candidates
                if c.get("workspace", "default") == ws and c.get("doc_id") == doc
            ]
            if t.get("chunk_id"):
                chunks = {t["chunk_id"]}
            elif t.get("unit_id") or t.get("table_id"):
                uid = t.get("unit_id") or t.get("table_id")
                chunks = unit_links.get((ws, doc, uid), set())
                if not chunks:
                    return any(c.get("unit_id") == uid or c.get("table_id") == uid for c in cs)
            elif t.get("scope_id"):
                chunks = set().union(
                    *(
                        unit_links.get((ws, doc, u), set())
                        for u in scope_units.get((ws, doc, t["scope_id"]), set())
                    )
                )
            else:
                return bool(cs)
            observed = {
                cid for c in cs for cid in [c.get("chunk_id"), *(c.get("chunk_ids") or [])] if cid
            }
            return bool(chunks & observed)

        rows = []
        for q in gold["questions"]:
            run = runs[q["query_id"]]
            assert run["discovery_candidates"] is not None
            assert (
                run["catalog_snapshot_id"] == snap
                and run["source_snapshot_id"] == gold["frozen_inputs"]["source_fingerprint"]
            )
            candidates = run["discovery_candidates"][:20]
            groups = q["gold"]["target_evidence"]
            hits = [
                any(match(t, candidates) for t in [g, *(g.get("alternatives") or [])])
                for g in groups
            ]
            docs = {c["doc_id"] for c in candidates}
            expected_docs = (
                {d["doc_id"] for d in q["target_docs"]} if q["category"] == "file_enum" else set()
            )
            rows.append(
                {
                    "query_id": q["query_id"],
                    "groups": len(groups),
                    "hits": sum(hits),
                    "file_docs": len(expected_docs),
                    "file_hits": len(expected_docs & docs),
                    "snapshot_captured": True,
                    "candidate_limit": 20,
                    "discovery_total": len(run["discovery_candidates"]),
                }
            )
        totals = {k: sum(r[k] for r in rows) for k in ("groups", "hits", "file_docs", "file_hits")}
        totals["evidence_recall_at_20"] = totals["hits"] / totals["groups"]
        totals["file_doc_recall_at_20"] = totals["file_hits"] / totals["file_docs"]
        bench = json.loads((OUT / "benchmark.json").read_text())
        assert totals["evidence_recall_at_20"] == bench["evidence_recall_at_k_reviewed"]
        assert totals["file_doc_recall_at_20"] == bench["list_doc_recall_at_k_reviewed"]
        (OUT / "metrics-audit.json").write_text(
            json.dumps(
                {"readonly": True, "agrees_with_benchmark": True, "totals": totals, "rows": rows},
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        print(totals)
    finally:
        await conn.close()


asyncio.run(main())
