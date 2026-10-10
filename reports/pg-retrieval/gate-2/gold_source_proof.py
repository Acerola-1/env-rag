"""Read-only identity/link cross-check for the main agent's gold review."""

import asyncio
import hashlib
import json
from pathlib import Path

import asyncpg

from env_rag_final.catalog.builder import check_stale
from env_rag_final.config import read_environment

OUT = Path(__file__).parent


async def main():
    values = read_environment(Path(".env"))
    conn = await asyncpg.connect(
        host=values["POSTGRES_HOST"],
        port=int(values["POSTGRES_PORT"]),
        user=values["POSTGRES_USER"],
        password=values["POSTGRES_PASSWORD"],
        database=values["POSTGRES_DATABASE"],
        statement_cache_size=0,
        server_settings={"default_transaction_read_only": "on", "statement_timeout": "30000"},
    )
    try:
        state = await check_stale(conn)
        docs = [
            dict(r)
            for r in await conn.fetch(
                "SELECT doc_id,doc_name,self_code,self_code_version,title FROM env_rag.documents WHERE workspace='default' AND snapshot_id=$1 ORDER BY doc_name",
                state["active_snapshot_id"],
            )
        ]
        ids = {d["doc_id"] for d in docs}
        gold = json.loads((OUT / "gold-review.json").read_text())
        submitted = json.loads(
            Path("reports/pg-retrieval/phase-2/gold-candidates.json").read_text()
        )
        file_checks = []
        for q in submitted["questions"]:
            if q["category"] != "file_enum":
                continue
            expected = q["gold"]["expected_doc_ids"]
            assert set(expected) <= ids
            match = {
                "file-enum-001": lambda d: d["self_code"] == "GB3095",
                "file-enum-002": lambda d: "中国移动源环境管理年报" in d["doc_name"],
                "file-enum-003": lambda d: (
                    "水利部_" in d["doc_name"] and "年中国水资源公报" in d["doc_name"]
                ),
                "file-enum-004": lambda d: "修改单" in d["doc_name"],
                "file-enum-005": lambda d: (
                    d["self_code"] == "GB18466" or "GB18466" in d["doc_name"]
                ),
                "file-enum-006": lambda d: d["self_code"] == "GB3838",
            }[q["query_id"]]
            matched = [d for d in docs if match(d)]
            file_checks.append(
                {
                    "query_id": q["query_id"],
                    "predicate_matches_submitted_set": set(expected)
                    == {d["doc_id"] for d in matched},
                    "matched_catalog_rows": matched,
                    "question_semantics_accepted": q["query_id"] != "file-enum-005",
                }
            )
        links = []
        for q in gold["questions"]:
            for material in q["reference_material"]:
                uid = material.get("table_id") or material.get("blockid")
                if not uid:
                    continue
                doc_id = "doc-" + hashlib.md5(material["doc_name"].encode()).hexdigest()
                rows = [
                    dict(r)
                    for r in await conn.fetch(
                        "SELECT unit_id,chunk_id,match_basis,coverage_status FROM env_rag.unit_chunk_links WHERE workspace='default' AND snapshot_id=$1 AND doc_id=$2 AND unit_id=$3 ORDER BY chunk_id",
                        state["active_snapshot_id"],
                        doc_id,
                        uid,
                    )
                ]
                links.append(
                    {
                        "query_id": q["query_id"],
                        "doc_id": doc_id,
                        "unit_id": uid,
                        "links": rows,
                        "note": "Link coverage status retained; this is not a frozen recall group",
                    }
                )
        runs = [
            json.loads(line)
            for line in Path("reports/pg-retrieval/phase-2/search-runs.jsonl")
            .read_text()
            .splitlines()
        ]
        diagnostics = []
        for record in runs:
            qid = record["gold_query_id"]
            groups = [x for x in links if x["query_id"] == qid]
            found = {c["chunk_id"] for c in record["candidates"] if c.get("chunk_id")}
            diagnostics.append(
                {
                    "query_id": qid,
                    "candidate_chunks": sorted(found),
                    "provisional_groups": [
                        {
                            "unit_id": g["unit_id"],
                            "chunk_ids": [r["chunk_id"] for r in g["links"]],
                            "any_mapped_chunk_in_discovery": bool(
                                found & {r["chunk_id"] for r in g["links"]}
                            ),
                        }
                        for g in groups
                    ],
                    "not_a_gate_metric": True,
                }
            )
        result = {
            "readonly": True,
            "model_calls": 0,
            "state_before": state,
            "file_identity_checks": file_checks,
            "raw_units_to_source_chunks": links,
            "submitted_run_diagnostics": diagnostics,
            "medical_related_documents": [
                d for d in docs if "医疗机构水污染物排放标准" in d["doc_name"]
            ],
            "state_after": await check_stale(conn),
            "metrics_frozen": False,
        }
        (OUT / "gold-source-proof.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
        print("file sets cross-checked:", len(file_checks), "source units checked:", len(links))
        print("fact006 diagnostic:", next(d for d in diagnostics if d["query_id"] == "fact-006"))
    finally:
        await conn.close()


asyncio.run(main())
