"""Source-snapshot fingerprinting (G0-1).

The fingerprint covers *content*, not just names: PG 原文、chunks（ID／顺序／正文／
heading／sidecar）、解析 blocks／tables 字节、分块参数，以及审计代码自身的 SHA-256。
All hashing is pure functions over collected records so offline fixtures can
verify that any content / order / reference / table mutation changes the value.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _h(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


def fingerprint_docs(docs: list) -> str:
    """SHA-256 over every doc_full row's stored fields (id, name, content, hashes…)."""
    payload = [
        {
            "id": r["id"],
            "doc_name": r["doc_name"],
            "content": r["content"],
            "content_hash": r["content_hash"],
            "meta": r["meta"],
            "sidecar_location": r["sidecar_location"],
            "parse_format": r["parse_format"],
            "parse_engine": r["parse_engine"],
            "chunk_options": r["chunk_options"],
        }
        for r in sorted(docs, key=lambda r: r["id"])
    ]
    return _h(payload)


def fingerprint_chunks(chunks: list) -> str:
    """SHA-256 over every chunk row: id, order, content, tokens, heading, sidecar.

    Reordering, re-chunking, editing content, or changing any ref changes it.
    """
    payload = [
        {
            "id": r["id"],
            "full_doc_id": r["full_doc_id"],
            "chunk_order_index": r["chunk_order_index"],
            "tokens": r["tokens"],
            "content": r["content"],
            "heading": r["heading"],
            "sidecar": r["sidecar"],
        }
        for r in sorted(chunks, key=lambda r: (r["full_doc_id"], r["chunk_order_index"]))
    ]
    return _h(payload)


def fingerprint_status(statuses: list) -> str:
    payload = [
        {
            "id": r["id"],
            "status": r["status"],
            "chunks_count": r["chunks_count"],
            "error_msg": r["error_msg"],
        }
        for r in sorted(statuses, key=lambda r: r["id"])
    ]
    return _h(payload)


def fingerprint_artifacts(parsed_root: Path) -> str:
    """SHA-256 over parsed blocks/tables bytes (sorted path+size+content digest).

    Reads every ``*.blocks.jsonl`` and ``*.tables.json`` under the parsed root;
    any byte change to a product file changes the value.
    """
    files = []
    for path in sorted(parsed_root.glob("*/*.jsonl")) + sorted(parsed_root.glob("*/*.json")):
        if not (path.name.endswith(".blocks.jsonl") or path.name.endswith(".tables.json")):
            continue
        data = path.read_bytes()
        files.append(
            {
                "path": str(path.relative_to(parsed_root)),
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    return _h(files)


def chunking_params(docs: list) -> dict:
    """Distinct chunk_options values observed in doc_full (chunking-parameter snapshot)."""
    seen = {}
    for r in docs:
        opts = r["chunk_options"]
        key = json.dumps(opts, sort_keys=True, ensure_ascii=False, default=str)
        seen[key] = seen.get(key, 0) + 1
    return {"distinct_values": len(seen), "counts": seen}


def audit_code_fingerprint(audit_pkg_dir: Path) -> dict[str, str]:
    """SHA-256 per audit source file — pins the exact code that produced a run."""
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(audit_pkg_dir.glob("*.py"))
    }


def source_snapshot_fingerprint(
    docs_hash: str, chunks_hash: str, status_hash: str, artifacts_hash: str, chunk_params: dict
) -> dict:
    """Composite fingerprint binding all audited sources into one value."""
    composite = _h(
        {
            "docs": docs_hash,
            "chunks": chunks_hash,
            "status": status_hash,
            "artifacts": artifacts_hash,
            "chunk_params": chunk_params,
        }
    )
    return {
        "algorithm": "sha256 composite of per-source sha256 values",
        "value": composite,
        "components": {
            "pg_doc_full_content": docs_hash,
            "pg_doc_chunks_content_order_refs": chunks_hash,
            "pg_doc_status": status_hash,
            "parsed_blocks_tables_bytes": artifacts_hash,
            "chunking_params": chunk_params,
        },
    }
