import asyncio
import hashlib
import inspect
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
from dotenv import dotenv_values
from lxml import html

from env_rag_final.audit import identity


async def main():
    v = dotenv_values("/Users/acerola/Dev/Python/RAG/env-rag-final/.env")
    conn = await asyncpg.connect(
        host=v["POSTGRES_HOST"],
        port=int(v["POSTGRES_PORT"]),
        user=v["POSTGRES_USER"],
        password=v["POSTGRES_PASSWORD"],
        database=v["POSTGRES_DATABASE"],
        timeout=10,
    )
    result = {}
    try:
        async with conn.transaction(readonly=True, isolation="repeatable_read"):
            await conn.execute("SET LOCAL statement_timeout='30s'")
            docs = await conn.fetch(
                "SELECT id,doc_name,content,content_hash,sidecar_location,meta FROM public.lightrag_doc_full WHERE workspace=$1 ORDER BY id",
                "default",
            )
            chunks = await conn.fetch(
                "SELECT id,full_doc_id,chunk_order_index,content,heading,sidecar FROM public.lightrag_doc_chunks WHERE workspace=$1 ORDER BY full_doc_id,chunk_order_index",
                "default",
            )
            statuses = await conn.fetch(
                "SELECT id,status,chunks_count,error_msg FROM public.lightrag_doc_status WHERE workspace=$1",
                "default",
            )
            result["counts"] = {
                "doc_full": len(docs),
                "chunks": len(chunks),
                "status": dict(Counter(r["status"] for r in statuses)),
                "env_rag_exists": await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='env_rag')"
                ),
            }
            known = {r["id"]: r for r in docs}
            status_map = {r["id"]: r for r in statuses}
            import re

            missing_originals = []
            for r in statuses:
                if r["status"] != "failed":
                    continue
                m = re.search(r"doc-[0-9a-f]{32}", r["error_msg"] or "")
                original = m.group(0) if m else None
                if (
                    original not in known
                    or status_map.get(original, {}).get("status") != "processed"
                ):
                    missing_originals.append(r["id"])
            result["failed_original_errors"] = missing_originals
            refs = {}
            chunk_by_doc = {}
            ref_types = Counter()
            for r in chunks:
                sc = (
                    json.loads(r["sidecar"])
                    if isinstance(r["sidecar"], str)
                    else r["sidecar"] or {}
                )
                chunk_by_doc.setdefault(r["full_doc_id"], []).append(r)
                refs.setdefault(r["full_doc_id"], set()).update(
                    x["id"] for x in sc.get("refs", []) if x.get("type") == "block"
                )
                ref_types.update(x.get("type") for x in sc.get("refs", []))
            order_errors = []
            for did, rs in chunk_by_doc.items():
                if [r["chunk_order_index"] for r in rs] != list(range(len(rs))):
                    order_errors.append(did)
                if status_map.get(did, {}).get("chunks_count") != len(rs):
                    order_errors.append(did)
            result["order_or_count_errors"] = order_errors
            result["ref_types"] = dict(ref_types)
            hash_errors = []
            db_text_errors = []
            db_marker_errors = []
            db_content_samples = []
            for r in docs:
                lines = identity.blocks_lines_for(r["doc_name"], r["sidecar_location"])
                meta = json.loads(lines[0])
                if (
                    identity.doc_id_for(r["doc_name"]) != r["id"]
                    or identity.content_hash(lines) != r["content_hash"]
                    or identity.document_hash(lines) != meta["document_hash"]
                ):
                    hash_errors.append(r["id"])
                local = identity.merged_blocks_text(lines)
                if r["content"].removeprefix("{{LRdoc}}") != local:
                    db_marker_errors.append(r["id"])
                if local != r["content"]:
                    db_text_errors.append(r["id"])
                    if len(db_content_samples) < 2:
                        db_content_samples.append(
                            {
                                "doc_id": r["id"],
                                "db_length": len(r["content"]),
                                "local_length": len(local),
                                "db_prefix": r["content"][:200],
                                "local_prefix": local[:200],
                                "stripped_equal": r["content"].strip() == local.strip(),
                            }
                        )
            result["hash_errors"] = hash_errors
            result["db_full_content_vs_local_errors"] = db_text_errors
            result["db_content_after_removing_lr_marker_errors"] = db_marker_errors
            result["db_full_content_vs_local_samples"] = db_content_samples
            block_members = {}
            for r in chunks:
                sc = (
                    json.loads(r["sidecar"])
                    if isinstance(r["sidecar"], str)
                    else r["sidecar"] or {}
                )
                for ref in sc.get("refs", []):
                    if ref.get("type") == "block":
                        block_members.setdefault((r["full_doc_id"], ref["id"]), set()).add(r["id"])
            key = max(block_members, key=lambda k: len(block_members[k]))
            result["largest_block_reference_span"] = {
                "doc_id": key[0],
                "doc_name": known[key[0]]["doc_name"],
                "block_id": key[1],
                "chunks": len(block_members[key]),
            }
            coverage = Counter()
            partial = []
            for p in sorted(identity.PARSED_ROOT.glob("*.pdf.parsed/*.blocks.jsonl")):
                lines = p.read_text().splitlines()
                meta = json.loads(lines[0])
                did = meta["doc_id"]
                units = {
                    b["blockid"] for b in map(json.loads, lines[1:]) if b.get("type") == "content"
                }
                if did not in chunk_by_doc:
                    coverage["no_chunks"] += 1
                    continue
                missing = sorted(units - refs.get(did, set()))
                if missing:
                    coverage["partial"] += 1
                    partial.append({"doc_id": did, "missing_block_ids": missing})
                else:
                    coverage["all_ids_referenced"] += 1
            result["coverage"] = dict(coverage)
            result["partial_documents"] = partial
            result["table_8978"] = []
            for r in chunks:
                if r["full_doc_id"] != "doc-b45c510232ed4d2452b0f5b2a13434e4":
                    continue
                root = html.fragment_fromstring(r["content"], create_parent="div")
                for t in root.xpath(".//table[@id]"):
                    if t.get("id").endswith(("-0001", "-0002")):
                        result["table_8978"].append(
                            {
                                "chunk_id": r["id"],
                                "table_id": t.get("id"),
                                "rows": len(t.xpath(".//tr")),
                                "items": [
                                    " ".join(td.itertext()).strip()
                                    for td in t.xpath("./tr[position()>1]/td[2]")
                                ],
                            }
                        )
            result["full_doc_meta_null_count"] = sum(r["meta"] is None for r in docs)
    finally:
        await conn.close()
    from lightrag import LightRAG
    from lightrag.kg.postgres_impl import ClientManager

    source = inspect.getsource(ClientManager.get_client)
    result["offline_interfaces"] = {
        "aquery_data_exists": hasattr(LightRAG, "aquery_data"),
        "docstring_chunk_id": "chunk_id" in (LightRAG.aquery_data.__doc__ or ""),
        "pg_get_client_calls_check_tables": "await db.check_tables()" in source,
    }
    result["verification_provenance"] = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "transaction": "READ ONLY REPEATABLE READ",
        "workspace": "default",
        "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "audit_source_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(identity.__file__).parent.glob("*.py"))
        },
    }
    out = Path(sys.argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    summary = {
        k: v
        for k, v in result.items()
        if k not in ("partial_documents", "db_full_content_vs_local_errors")
    }
    summary["db_full_content_vs_local_mismatch_count"] = len(db_text_errors)
    print(json.dumps(summary, ensure_ascii=False))


try:
    asyncio.run(main())
except Exception as exc:
    print("VERIFY_FAIL", type(exc).__name__)
    raise SystemExit(1)
