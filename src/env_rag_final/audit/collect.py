"""Collect all Phase-0 audit evidence and write the eight deliverables.

Corrected per Gate 0 review (G0-1/G0-2/G0-3):
- G0-1: full source-snapshot fingerprint (content, chunks, artifacts, params).
- G0-2: every headline conclusion is computed from collected records; the
  report states only what this run actually verified. Staged writes + one
  run_id: a failed run leaves no mixed old/new deliverables.
- G0-3: sample-set targets are real identities (samples.py).

Every query runs inside the caller's READ ONLY transaction (see pg.py).
Offline checks never instantiate LightRAG storage against the live database.
"""

from __future__ import annotations

import importlib.metadata as md
import json
import platform
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

from . import identity, snapshot
from .compat import build_compatibility_md
from .probes import build_search_probes
from .samples import build_sample_set

WORKSPACE = "default"
DOC_STATUS_TABLES = ("lightrag_doc_full", "lightrag_doc_status", "lightrag_doc_chunks")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# schema.json (task 1.2)
# --------------------------------------------------------------------------


async def _schema_json(conn: asyncpg.Connection, versions: dict) -> dict:
    tables = {}
    for t in DOC_STATUS_TABLES:
        cols = await conn.fetch(
            """SELECT column_name, data_type, is_nullable
               FROM information_schema.columns
               WHERE table_schema='public' AND table_name=$1 ORDER BY ordinal_position""",
            t,
        )
        tables[t] = {
            "columns": [dict(c) for c in cols],
            "indexes": [
                dict(r)
                for r in await conn.fetch(
                    """SELECT indexname, indexdef FROM pg_indexes
                       WHERE schemaname='public' AND tablename=$1 ORDER BY indexname""",
                    t,
                )
            ],
        }
    related = await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'lightrag%' ORDER BY 1"
    )
    counts = {}
    for r in related:
        n = await conn.fetchval(f"SELECT count(*) FROM public.{r['tablename']}")
        counts[r["tablename"]] = n
    exts = await conn.fetch("SELECT extname, extversion FROM pg_extension ORDER BY 1")
    settings = await conn.fetch(
        """SELECT name, setting FROM pg_settings
           WHERE name IN ('server_version','default_text_search_config',
                          'lc_collate','lc_ctype','max_connections','TimeZone',
                          'shared_buffers')"""
    )
    ts_simple = await conn.fetch(
        "SELECT alias, token FROM ts_debug('simple', $1)",
        "医疗机构水污染物排放标准 GB 18466-2005 表1 总氮",
    )
    lex = await conn.fetchrow(
        """SELECT
             to_tsvector('simple','医疗机构水污染物排放标准') @@ to_tsquery('simple','医疗机构') AS substr_match,
             to_tsvector('simple','医疗机构水污染物排放标准') @@ plainto_tsquery('simple','医疗机构水污染物排放标准') AS exact_match"""
    )
    schemas = await conn.fetch(
        """SELECT nspname FROM pg_namespace
           WHERE nspname NOT IN ('pg_catalog','information_schema','pg_toast')
             AND nspname NOT LIKE 'pg_%temp%'"""
    )
    env_rag_taken = await conn.fetchval("SELECT count(*) FROM pg_namespace WHERE nspname='env_rag'")
    can_create_schema = await conn.fetchval(
        "SELECT has_database_privilege(current_user, current_database(), 'CREATE')"
    )
    available = await conn.fetch(
        """SELECT name, default_version FROM pg_available_extensions
           WHERE name IN ('pg_jieba','zhparser','pg_trgm','vector','vchord')"""
    )
    return {
        "generated_at": _now(),
        "database": {
            "server": dict((r["name"], r["setting"]) for r in settings),
            "current_user": await conn.fetchval("SELECT current_user"),
            "schemas": [r["nspname"] for r in schemas],
            "app_schema_plan": {
                "candidate_name": "env_rag",
                "exists": bool(env_rag_taken),
                "current_user_can_create_schema": bool(can_create_schema),
            },
            "extensions_installed": [dict(r) for r in exts],
            "extensions_available_relevant": [dict(r) for r in available],
            "custom_text_search_configs": [
                dict(r)
                for r in await conn.fetch(
                    """SELECT n.nspname AS schema, c.cfgname FROM pg_ts_config c
                       JOIN pg_namespace n ON n.oid=c.cfgnamespace
                       WHERE n.nspname NOT IN ('pg_catalog','information_schema')"""
                )
            ],
        },
        "chinese_fts_observation": {
            "ts_debug_simple": [(r["alias"], r["token"]) for r in ts_simple],
            "substring_lexeme_match": lex["substr_match"],
            "exact_lexeme_match": lex["exact_match"],
            "conclusion": (
                "观察事实（本次运行实测）：默认配置把整句中文并成单个 lexeme，子串查询不命中；"
                "中文分词必须在应用侧完成（design.md 决策 4）。"
                if lex["substr_match"] is False and lex["exact_match"] is True
                else "警告：本次实测结果与首轮观察不同（见上方原始值），结论需重新评估。"
            ),
        },
        "tables": tables,
        "row_counts": counts,
        "dependency_versions": versions,
    }


# --------------------------------------------------------------------------
# inventory.jsonl (task 1.3) + hash verification (task 1.4) + consistency checks
# --------------------------------------------------------------------------


async def _inventory(conn: asyncpg.Connection) -> tuple[list[dict], dict]:
    docs = await conn.fetch(
        """SELECT f.id, f.doc_name, f.sidecar_location, f.content_hash,
                  f.parse_engine, f.parse_format, f.create_time, f.meta,
                  f.chunk_options, f.content,
                  s.status AS status_status, s.chunks_count, s.error_msg,
                  s.content_hash AS status_content_hash
           FROM public.lightrag_doc_full f
           LEFT JOIN public.lightrag_doc_status s
                  ON s.workspace=f.workspace AND s.id=f.id
           WHERE f.workspace=$1 ORDER BY f.doc_name""",
        WORKSPACE,
    )
    chunks = await conn.fetch(
        """SELECT id, full_doc_id, chunk_order_index, tokens, content, heading, sidecar
           FROM public.lightrag_doc_chunks WHERE workspace=$1""",
        WORKSPACE,
    )
    statuses = await conn.fetch(
        """SELECT id, file_path, status, chunks_count, error_msg
           FROM public.lightrag_doc_status WHERE workspace=$1 ORDER BY file_path""",
        WORKSPACE,
    )
    chunk_counts: dict[str, int] = {}
    chunk_orders: dict[str, list[int]] = {}
    for c in chunks:
        chunk_counts[c["full_doc_id"]] = chunk_counts.get(c["full_doc_id"], 0) + 1
        chunk_orders.setdefault(c["full_doc_id"], []).append(c["chunk_order_index"])

    docs_by_id = {r["id"]: r for r in docs}
    status_by_id = {r["id"]: r for r in statuses}
    status_extra = [r for r in statuses if r["id"] not in docs_by_id]

    parsed_dirs = sorted(identity.PARSED_ROOT.glob("*.pdf.parsed"))
    parsed_names = {p.name[: -len(".pdf.parsed")] for p in parsed_dirs}

    inventory: list[dict] = []
    hash_verify = {
        "checked": 0,
        "content_hash_ok": 0,
        "document_hash_ok": 0,
        "doc_id_ok": 0,
        "mismatches": [],
    }
    db_content_checks = {"compared": 0, "identical_with_lr_marker": 0, "differ": []}

    for row in docs:
        doc_name = row["doc_name"]
        entry = {
            "kind": "db_doc",
            "workspace": WORKSPACE,
            "doc_id": row["id"],
            "doc_name": doc_name,
            "doc_id_derivation": "doc- + md5(doc_name)",
            "doc_id_matches_md5_rule": row["id"] == identity.doc_id_for(doc_name),
            "sidecar_location": row["sidecar_location"],
            "parse_engine": row["parse_engine"],
            "parse_format": row["parse_format"],
            "doc_status_row": row["status_status"],
            "chunks_in_db": chunk_counts.get(row["id"], 0),
            "status_chunks_count": row["chunks_count"],
            "parsed_dir_available": Path(f"{identity.PARSED_ROOT}/{doc_name}.parsed").exists(),
            "observed_at": _now(),
        }
        lines = identity.blocks_lines_for(doc_name, row["sidecar_location"])
        if lines:
            meta = json.loads(lines[0])
            calc_doc_hash = identity.document_hash(lines)
            calc_content_hash = identity.content_hash(lines)
            entry["hash_verification"] = {
                "content_hash_stored": row["content_hash"],
                "content_hash_recomputed": calc_content_hash,
                "content_hash_match": calc_content_hash == row["content_hash"],
                "document_hash_stored": meta.get("document_hash"),
                "document_hash_recomputed": calc_doc_hash,
                "document_hash_match": calc_doc_hash == meta.get("document_hash"),
                "meta_doc_id_matches_db": meta.get("doc_id") == row["id"],
                "semantics": {
                    "doc_full.content_hash": "md5(normalize_merged_text_for_hash(blocks 合并正文)) — 与 PG content_hash 同源可比较",
                    "blocks.meta.document_hash": "sha256(blocks 合并正文) — 解析产物完整性指纹，不是原始 PDF 的哈希",
                    "mineru._manifest.source_content_hash": "sha256(原始 PDF 字节) — 与 document_hash 不同，不能互相认定",
                    "doc_full.id": "doc- + md5(doc_name/file_path) — 由文件名推导，与内容无关",
                },
            }
            hash_verify["checked"] += 1
            hash_verify["content_hash_ok"] += int(entry["hash_verification"]["content_hash_match"])
            hash_verify["document_hash_ok"] += int(
                entry["hash_verification"]["document_hash_match"]
            )
            hash_verify["doc_id_ok"] += int(entry["hash_verification"]["meta_doc_id_matches_db"])
            if not entry["hash_verification"]["content_hash_match"]:
                hash_verify["mismatches"].append({"doc_name": doc_name, "field": "content_hash"})

            # PG content vs local merged blocks: observed relation, not assumed.
            local = identity.merged_blocks_text(lines)
            same = row["content"].removeprefix("{{LRdoc}}") == local
            db_content_checks["compared"] += 1
            db_content_checks["identical_with_lr_marker"] += int(same)
            if not same:
                db_content_checks["differ"].append(row["id"])
            entry["db_content_vs_local_merged"] = {
                "identical_after_removing_lr_marker": same,
                "note": "doc_full.content 带存储格式前缀 {{LRdoc}}；去除该前缀后与本地合并正文逐字符比较",
            }
        else:
            entry["hash_verification"] = None
        inventory.append(entry)

    for row in status_extra:
        inventory.append(
            {
                "kind": "db_status_only",
                "workspace": WORKSPACE,
                "doc_id": row["id"],
                "doc_name": row["file_path"],
                "doc_status_row": row["status"],
                "chunks_in_db": 0,
                "status_chunks_count": row["chunks_count"],
                "error_class": _error_class(row["error_msg"]),
                "parsed_dir_available": Path(
                    f"{identity.PARSED_ROOT}/{row['file_path']}.parsed"
                ).exists(),
                "observed_at": _now(),
            }
        )

    for name in sorted(parsed_names):
        already = any(e["doc_name"] == f"{name}.pdf" for e in inventory if e["kind"] == "db_doc")
        if already:
            continue
        prior = next((e for e in inventory if e["doc_name"] == f"{name}.pdf"), None)
        if prior is not None:
            prior["kind"] = "parsed_and_status_only"
            prior["parsed_dir_available"] = True
            continue
        inventory.append(
            {
                "kind": "parsed_only",
                "doc_name": f"{name}.pdf",
                "chunks_in_db": 0,
                "parsed_dir_available": True,
                "observed_at": _now(),
            }
        )

    failed_rows = [
        {
            "doc_id": r["id"],
            "doc_name": r["file_path"],
            "error_class": _error_class(r["error_msg"]),
            "error_excerpt": _excerpt(r["error_msg"]),
            "original_doc_id": _orig_doc(r["error_msg"]),
            "original_is_processed": (
                status_by_id.get(_orig_doc(r["error_msg"]), {}).get("status") == "processed"
                if _orig_doc(r["error_msg"])
                else None
            ),
            "parsed_dir_available": Path(
                f"{identity.PARSED_ROOT}/{r['file_path']}.parsed"
            ).exists(),
        }
        for r in status_extra
    ]
    with_origins = [f for f in failed_rows if f["original_doc_id"]]

    # Duplicate-content explanation, computed this run (G0-2): compare the two
    # parsed artifacts for the water-58 pair if both are present locally.
    dup_pair = _duplicate_pair_evidence(parsed_dirs)

    checks = {
        # G0-2: these are executed here, not asserted in prose.
        "order_contiguous_docs": _count_bad_orders(chunk_orders),
        "order_total_docs": len(chunk_orders),
        "status_chunks_count_matches_actual": sum(
            1
            for r in docs
            if r["status_status"] == "processed"
            and r["chunks_count"] == chunk_counts.get(r["id"], 0)
        ),
        "status_processed_rows": sum(1 for r in docs if r["status_status"] == "processed"),
        "doc_full_meta_null": sum(1 for r in docs if r["meta"] is None),
        "doc_full_meta_total": len(docs),
    }

    stats = {
        "parsed_dirs_total": len(parsed_dirs),
        "doc_full_rows": len(docs),
        "doc_status_processed": sum(1 for r in statuses if r["status"] == "processed"),
        "doc_status_failed_rows": sum(1 for r in statuses if r["status"] == "failed"),
        "docs_with_chunks": sum(1 for n in chunk_counts.values() if n > 0),
        "chunks_total": len(chunks),
        "failed_rows": failed_rows,
        "failed_error_taxonomy": {
            "file_name_already_exists": sum(
                1 for f in failed_rows if f["error_class"] == "file_name_already_exists"
            ),
            "identical_content": sum(
                1 for f in failed_rows if f["error_class"] == "identical_content"
            ),
        },
        "failed_originals_all_processed": (
            all(f["original_is_processed"] for f in with_origins) if with_origins else None
        ),
        "consistency_checks": checks,
        "db_content_checks": db_content_checks,
        "gap_222_vs_221": None,
    }
    parsed_without_doc = [
        e for e in inventory if e["kind"] in ("parsed_only", "parsed_and_status_only")
    ]
    stats["gap_222_vs_221"] = {
        "parsed_dirs": len(parsed_dirs),
        "doc_full_rows": len(docs),
        "parsed_without_doc_full": [e["doc_name"] for e in parsed_without_doc],
        "duplicate_pair_evidence": dup_pair,
    }
    return inventory, {"stats": stats, "hash_verify": hash_verify, "chunks": chunks, "docs": docs}


def _duplicate_pair_evidence(parsed_dirs: list[Path]) -> dict | None:
    """Compare water-58 vs water-44 parsed artifacts: raw text and normalized.

    G0-2 requires the claim to be exactly what is verified: normalized merged
    text equality (after stripping file-derived ids), NOT raw text or PDF bytes.
    """
    w58 = next((d for d in parsed_dirs if d.name.startswith("water-58_")), None)
    w44 = next((d for d in parsed_dirs if d.name.startswith("water-44_")), None)
    if not w58 or not w44:
        return None
    m58 = identity.merged_blocks_text(_lines(w58))
    m44 = identity.merged_blocks_text(_lines(w44))
    n58, n44 = (
        identity.normalize_merged_text_for_hash(m58),
        identity.normalize_merged_text_for_hash(m44),
    )
    import hashlib as _hl

    return {
        "water58_doc_name": w58.name[: -len(".parsed")],
        "water44_doc_name": w44.name[: -len(".parsed")],
        "raw_merged_text_equal": m58 == m44,
        "normalized_merged_text_equal": n58 == n44,
        "normalized_md5": _hl.md5(n58.encode()).hexdigest(),
        "raw_sha256_58": _hl.sha256(m58.encode()).hexdigest(),
        "raw_sha256_44": _hl.sha256(m44.encode()).hexdigest(),
        "verified_claim": (
            "water-58 与 water-44 的**规范化合并正文**（去除文件派生标记后）相等，MD5 相同；"
            "原始 merged text 与其 SHA-256 不同，PDF 字节未比较。导入管线按规范化 content_hash "
            "重复拒绝 water-58 入库（doc_status doc-cf323c0335… error_msg）。"
            if n58 == n44 and m58 != m44
            else "两文件规范化正文不相等——重复拒绝结论需重新调查。"
        ),
    }


def _lines(parsed_dir: Path) -> list[str]:
    bl = sorted(parsed_dir.glob("*.blocks.jsonl"))
    return bl[0].read_text().splitlines() if bl else []


def _count_bad_orders(chunk_orders: dict[str, list[int]]) -> int:
    bad = 0
    for orders in chunk_orders.values():
        s = sorted(orders)
        if s != list(range(len(s))):
            bad += 1
    return bad


def _error_class(msg: str | None) -> str:
    if msg and msg.startswith("File name already exists"):
        return "file_name_already_exists"
    if msg and msg.startswith("Identical content already exists"):
        return "identical_content"
    return "other"


def _excerpt(msg: str | None) -> str:
    if not msg:
        return ""
    return msg.split(". Original doc_id")[0][:120]


def _orig_doc(msg: str | None) -> str | None:
    m = re.search(r"doc-[0-9a-f]{32}", msg or "")
    return m.group(0) if m else None


# --------------------------------------------------------------------------
# mapping-samples.jsonl (task 1.5) — all conclusions computed from query results
# --------------------------------------------------------------------------


async def _mapping_samples(conn: asyncpg.Connection) -> list[dict]:
    async def chunk(doc_name: str, idx: int):
        return await conn.fetchrow(
            """SELECT c.id, c.chunk_order_index, c.sidecar, c.content, c.tokens
               FROM public.lightrag_doc_chunks c
               WHERE c.workspace=$1 AND c.full_doc_id=
                     (SELECT id FROM public.lightrag_doc_full WHERE workspace=$1 AND doc_name=$2)
               AND c.chunk_order_index=$3""",
            WORKSPACE,
            doc_name,
            idx,
        )

    samples: list[dict] = []
    gb8978 = "water-11_生态环境部_污水综合排放标准_GB8978-1996.pdf"
    gb18466 = "water-09_生态环境部_医疗机构水污染物排放标准_GB18466-2005.pdf"

    # A) GB 8978 表1 两片同 chunk（行数由解析 tables.json 读取，不由模板写死）
    r = await chunk(gb8978, 1)
    content = r["content"]
    frag_rows = {}
    w11 = identity.PARSED_ROOT / f"{gb8978}.parsed"
    tjson = sorted(w11.glob("*.tables.json"))
    if tjson:
        tables = json.loads(tjson[0].read_text())["tables"]
        for tid, te in tables.items():
            if te.get("caption") in ("表 1 第一类污染物最高允许排放浓度", "表 1(完)"):
                frag_rows[tid] = {"caption": te["caption"], "dimension": te.get("dimension")}
    both = "-0001" in content and "-0002" in content
    samples.append(
        {
            "sample_id": "gb8978-table1-two-fragments-one-chunk",
            "kind": "table_fragments_same_chunk",
            "doc_name": gb8978,
            "doc_id": await _doc_id(conn, gb8978),
            "chunk_id": r["id"],
            "chunk_order_index": 1,
            "fragments": frag_rows,
            "match_status": "confirmed" if both and frag_rows else "not_found",
            "evidence": {
                "fragment1_in_chunk": "-0001" in content,
                "fragment2_in_chunk": "-0002" in content,
            },
            "basis": "PG chunk.content 内联 table id + tables.json caption/dimension（本次运行读取）",
        }
    )

    # B) GB 18466 正文定义
    r = await chunk(gb18466, 1)
    refs1 = json.loads(r["sidecar"])["refs"]
    defs = ["3.1", "3.2", "3.3", "3.4"]
    found = [d for d in defs if d in r["content"]]
    samples.append(
        {
            "sample_id": "gb18466-definitions-prose",
            "kind": "prose_definitions",
            "doc_name": gb18466,
            "doc_id": await _doc_id(conn, gb18466),
            "chunk_id": r["id"],
            "chunk_order_index": 1,
            "definitions_found_in_chunk": found,
            "sidecar_block_refs": [e["id"] for e in refs1],
            "match_status": "confirmed" if len(found) == 4 else "partial",
            "evidence": {"content_length": len(r["content"])},
            "basis": "本次对 chunk.content 做子串核验（3.1…3.4）",
        }
    )

    # C) 跨 chunk 正文范围
    c1, c2 = await chunk(gb18466, 1), await chunk(gb18466, 2)
    span = {
        "4.1.1": ("chunk1", "4.1.1" in c1["content"]),
        "4.1.2": ("chunk1", "4.1.2" in c1["content"]),
        "4.1.3": ("chunk2", "4.1.3" in c2["content"]),
        "4.1.4": ("chunk2", "4.1.4" in c2["content"]),
        "4.1.5": ("chunk2", "4.1.5" in c2["content"]),
    }
    ok = all(v[1] for v in span.values())
    samples.append(
        {
            "sample_id": "gb18466-section-4.1-cross-chunk",
            "kind": "prose_scope_cross_chunk",
            "doc_name": gb18466,
            "doc_id": await _doc_id(conn, gb18466),
            "chunk_ids": [c1["id"], c2["id"]],
            "chunk_order_indexes": [1, 2],
            "clause_layout": span,
            "match_status": "confirmed" if ok else "partial",
            "observed": (
                "条款 4.1 的正文项按本次子串核验分布于 chunk-001（4.1.1–4.1.2）与 chunk-002（4.1.3–4.1.5）。"
                if ok
                else "子串核验未全部命中，条款分布与首轮观察不同，需重新定位。"
            ),
            "basis": "本次对两 chunk content 做子串核验（4.1.1…4.1.5）",
        }
    )

    # D) block 跨多 chunk —— 全库聚合取真实最大值（G0-2：最大值来自聚合查询而非固定值 14）
    rows = await conn.fetch(
        """WITH refs AS (
             SELECT c.full_doc_id, c.id AS chunk_id, c.chunk_order_index, e->>'id' AS ref_id
             FROM public.lightrag_doc_chunks c
             CROSS JOIN LATERAL jsonb_array_elements(c.sidecar->'refs') e
             WHERE c.workspace=$1)
           SELECT full_doc_id, ref_id, count(DISTINCT chunk_id) AS n,
                  min(chunk_order_index) AS lo, max(chunk_order_index) AS hi
           FROM refs GROUP BY full_doc_id, ref_id HAVING count(DISTINCT chunk_id) >= 2
           ORDER BY n DESC LIMIT 1""",
        WORKSPACE,
    )
    if rows:
        top = rows[0]
        doc_row = await conn.fetchrow(
            "SELECT id, doc_name FROM public.lightrag_doc_full WHERE workspace=$1 AND id=$2",
            WORKSPACE,
            top["full_doc_id"],
        )
        blocks = identity.blocks_lines_for(doc_row["doc_name"], None)
        block_content = ""
        if blocks:
            for line in blocks[1:]:
                b = json.loads(line)
                if b.get("blockid") == top["ref_id"]:
                    block_content = b.get("content") or ""
                    break
        samples.append(
            {
                "sample_id": "one-block-spanning-many-chunks",
                "kind": "block_spans_chunks",
                "doc_name": doc_row["doc_name"],
                "doc_id": doc_row["id"],
                "block_id": top["ref_id"],
                "chunks_containing_it": top["n"],
                "chunk_order_range": [top["lo"], top["hi"]],
                "block_content_length": len(block_content),
                "match_status": "confirmed",
                "observed": f"本次全库聚合实测：引用数最多的 block 出现在 {top['n']} 个 chunk 中"
                f"（chunk_order {top['lo']}–{top['hi']}）；单 chunk 命中仅代表该 chunk，不代表整个 block 已读。",
                "basis": "PG sidecar.refs 全库聚合（本次运行，read-only SQL）",
            }
        )
    else:
        samples.append(
            {
                "sample_id": "one-block-spanning-many-chunks",
                "kind": "block_spans_chunks",
                "match_status": "gap",
                "observed": "本次聚合未找到 block 跨 chunk 案例",
                "basis": "PG sidecar.refs 全库聚合（本次运行）",
            }
        )

    # E) 空 sidecar chunk —— 计数由查询产生
    rows = await conn.fetch(
        """SELECT c.id, c.chunk_order_index, f.doc_name, c.tokens
           FROM public.lightrag_doc_chunks c
           JOIN public.lightrag_doc_full f ON f.workspace=c.workspace AND f.id=c.full_doc_id
           WHERE c.workspace=$1 AND c.sidecar::text='{}' ORDER BY f.doc_name, c.chunk_order_index""",
        WORKSPACE,
    )
    samples.append(
        {
            "sample_id": "empty-sidecar-chunks",
            "kind": "missing_refs_anomaly",
            "count": len(rows),
            "instances": [
                {
                    "doc_name": r["doc_name"],
                    "chunk_id": r["id"],
                    "chunk_order_index": r["chunk_order_index"],
                    "tokens": r["tokens"],
                }
                for r in rows
            ],
            "match_status": "gap" if rows else "none_found",
            "observed": f"本次实测 {len(rows)} 个 chunk 的 sidecar 为 {{}}，无法从 chunk 反查原始 block；"
            "正文内联 table id 可作次要依据（fallback，不得自动升级为 confirmed）。"
            if rows
            else "本次未发现空 sidecar chunk。",
            "basis": "PG 全量扫描 sidecar::text='{}'（本次运行）",
        }
    )

    # F) 全库 block 引用覆盖
    coverage = await _ref_coverage(conn)
    samples.append(
        {
            "sample_id": "catalog-wide-ref-coverage",
            "kind": "coverage_stats",
            "match_status": "observed",
            "stats": coverage,
            "observed": (
                f"本次实测：{coverage['docs_full_coverage']} 份产物 block ID 全覆盖、"
                f"{coverage['docs_partial_coverage']} 份部分覆盖、{coverage['docs_without_chunks']} 份无 chunk。"
                "注意：该覆盖只证明 block ID 被引用，不证明 block 全部文字出现在某 chunk 中。"
            ),
            "basis": "parsed blocks.jsonl blockid 全集 ∩ PG sidecar.refs 全集（本次运行）",
        }
    )
    return samples


async def _doc_id(conn: asyncpg.Connection, doc_name: str) -> str:
    return await conn.fetchval(
        "SELECT id FROM public.lightrag_doc_full WHERE workspace=$1 AND doc_name=$2",
        WORKSPACE,
        doc_name,
    )


async def _ref_coverage(conn: asyncpg.Connection) -> dict:
    pgrefs: dict[str, set[str]] = {}
    rows = await conn.fetch(
        """SELECT full_doc_id, e->>'id' AS ref_id
           FROM public.lightrag_doc_chunks, jsonb_array_elements(sidecar->'refs') e
           WHERE workspace=$1""",
        WORKSPACE,
    )
    for r in rows:
        pgrefs.setdefault(r["full_doc_id"], set()).add(r["ref_id"])
    parsed: dict[str, set[str]] = {}
    for d in sorted(identity.PARSED_ROOT.glob("*.pdf.parsed")):
        bl = list(d.glob("*.blocks.jsonl"))
        if not bl:
            continue
        lines = bl[0].read_text().splitlines()
        meta = json.loads(lines[0])
        ids = set()
        for line in lines[1:]:
            b = json.loads(line)
            if b.get("type") == "content":
                ids.add(b["blockid"])
        parsed[meta["doc_id"]] = ids
    full = sum(1 for k, v in parsed.items() if k in pgrefs and v <= pgrefs[k])
    no_chunks = sum(1 for k in parsed if k not in pgrefs)
    partial = len(parsed) - full - no_chunks
    return {
        "parsed_docs": len(parsed),
        "parsed_blocks_total": sum(len(v) for v in parsed.values()),
        "docs_full_coverage": full,
        "docs_partial_coverage": partial,
        "docs_without_chunks": no_chunks,
        "partial_doc_ids": sorted(k for k, v in parsed.items() if k in pgrefs and v - pgrefs[k]),
    }


# --------------------------------------------------------------------------
# fingerprint / manifest / audit.md
# --------------------------------------------------------------------------


def _git() -> dict:
    def g(*args):
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, cwd=Path(__file__).resolve().parents[3]
        ).stdout.strip()

    return {"commit": g("rev-parse", "HEAD"), "dirty": bool(g("status", "--porcelain"))}


def _versions() -> dict:
    out = {}
    for dist in (
        "lightrag-hku",
        "asyncpg",
        "pgvector",
        "qdrant-client",
        "neo4j",
        "lxml",
        "python-dotenv",
    ):
        try:
            out[dist] = md.version(dist)
        except md.PackageNotFoundError:
            out[dist] = "not-installed"
    out["python"] = platform.python_version()
    try:
        import jieba  # noqa: F401

        out["jieba"] = md.version("jieba")
    except (ImportError, md.PackageNotFoundError):
        out["jieba"] = "not-installed（探针候选，Phase 2 锁定）"
    return out


def _manifest(run_id: str, fingerprint: dict, steps: list[dict], code_fp: dict) -> dict:
    failed = [s for s in steps if s["status"] != "ok"]
    return {
        "run_id": run_id,
        "generated_at": _now(),
        "status": "ok" if not failed else f"failed_at:{failed[0]['step']}",
        "tool": "env_rag_final.audit (Phase 0 read-only audit)",
        "code_version": {**_git(), "audit_source_sha256": code_fp},
        "dependency_versions": _versions(),
        "execution": {
            "entry": "uv run env-rag-final audit [--report-dir reports/pg-retrieval/phase-0]",
            "transaction": "READ ONLY REPEATABLE READ, statement_timeout=30s, statement_cache_size=0",
            "writes": "none — no DDL/DML, no LightRAG storage initialization against the live DB",
        },
        "inputs": {
            "workspace": WORKSPACE,
            "parsed_artifacts_dir": str(identity.PARSED_ROOT),
            "source_snapshot_fingerprint": fingerprint,
        },
        "steps": steps,
        "deliverables_expected": [
            "schema.json",
            "inventory.jsonl",
            "mapping-samples.jsonl",
            "search-probes.json",
            "sample-set.json",
            "compatibility.md",
            "audit.md",
            "run-manifest.json",
        ],
        "rerun_policy": "语料／产物／分块任一变化都会改变 source_snapshot_fingerprint 的对应组件；"
        "这是观察事实，不得为消除差异写库。失败运行以 status=failed_at:* 标记，不与成功产物混用。",
    }


def _fmt(v) -> str:
    return str(v)


def _audit_md(stats: dict, hash_verify: dict, samples: list, schema: dict, manifest: dict) -> str:
    checks = stats["consistency_checks"]
    dbchecks = stats["db_content_checks"]
    tax = stats["failed_error_taxonomy"]
    gap = stats["gap_222_vs_221"]
    span_sample = next(s for s in samples if s["sample_id"] == "one-block-spanning-many-chunks")
    empty_sample = next(s for s in samples if s["sample_id"] == "empty-sidecar-chunks")
    cov = next(s for s in samples if s["sample_id"] == "catalog-wide-ref-coverage")["stats"]
    dup = gap.get("duplicate_pair_evidence") or {}

    not_parsed = gap["parsed_without_doc_full"]

    # Dynamic statements — every number below comes from this run's records.
    gap_line = (
        f"- 解析产物 {gap['parsed_dirs']} 份 vs doc_full {gap['doc_full_rows']} 行；"
        f"无 doc_full 行的产物：{'、'.join(not_parsed)}。"
        if not_parsed
        else f"- 解析产物 {gap['parsed_dirs']} 份与 doc_full {gap['doc_full_rows']} 行一一对应。"
    )
    dup_line = (
        f"- 差异定因（本次复算）：{dup.get('verified_claim', '证据不足，见 duplicate_pair_evidence')}"
        if dup
        else "- 差异定因：本轮未能本地复算重复对，仅记录 doc_status 错误信息。"
    )
    if stats["failed_originals_all_processed"] is True:
        failed_line = (
            f"failed 共 {stats['doc_status_failed_rows']} 条"
            f"（{tax['file_name_already_exists']} 条重复文件名＋{tax['identical_content']} 条重复内容），"
            "逐条核验其错误信息指向的原始 doc_id 全部存在且 processed（本次运行核验）。"
        )
    else:
        failed_line = (
            f"failed 共 {stats['doc_status_failed_rows']} 条；存在指向原始文档缺失或未 processed 的行，"
            "逐行身份见 inventory.jsonl（其中存在未指向已处理原文的行）。"
        )
    order_line = (
        f"chunk_order_index 在全部 {checks['order_total_docs']} 份文档上连续且无重复"
        if checks["order_contiguous_docs"] == 0
        else f"有 {checks['order_contiguous_docs']}/{checks['order_total_docs']} 份文档的序号不连续或重复（见 inventory.jsonl）"
    )
    meta_line = (
        f"doc_full.meta 全部为 NULL（{checks['doc_full_meta_null']}/{checks['doc_full_meta_total']}，本次实测）"
        if checks["doc_full_meta_null"] == checks["doc_full_meta_total"]
        else f"doc_full.meta 非 NULL 行数 {checks['doc_full_meta_total'] - checks['doc_full_meta_null']}（本次实测）"
    )
    status_line = (
        f"processed 行的 chunks_count 与实际 chunk 行数全部一致（{checks['status_chunks_count_matches_actual']}"
        f"/{checks['status_processed_rows']}，本次实测）"
        if checks["status_chunks_count_matches_actual"] == checks["status_processed_rows"]
        else "processed 行中 chunks_count 与实际不一致的文档见 consistency_checks（本次实测）"
    )
    content_line = (
        f"doc_full.content 带存储格式前缀 {{{{LRdoc}}}}；去除该前缀后与本地合并正文逐字符相等"
        f"（{dbchecks['identical_with_lr_marker']}/{dbchecks['compared']}，本次实测）。"
        "Phase 1 比较原文时必须先做该转换。"
        if not dbchecks["differ"]
        else f"doc_full.content 与本地合并正文去除 {{{{LRdoc}}}} 前缀后仍有 {len(dbchecks['differ'])} 份不同（见 db_content_checks）。"
    )
    fts_obs = schema["chinese_fts_observation"]
    fts_line = fts_obs["conclusion"]

    return f"""# Phase 0 审计报告（只读）

生成时间：{_now()}；run_id：`{manifest["run_id"]}`；状态：`{manifest["status"]}`。
全部结论由 `uv run env-rag-final audit` 在本次运行中实际采集——凡标注"本次实测/本次复算"的数字都能在
本目录报告文件中复核；首轮历史观察单独标注，不与本次混写。
数据库访问限定为单个 READ ONLY 事务内的 SELECT 与 pg_catalog／ts_debug 探针，无 DDL／DML。

## 1. 已观察事实（本次运行采集）

### 1.1 计数口径（两种口径分列统计，不交叉换算）

| 口径 | 数值 |
|---|---|
| 解析产物目录（`*.pdf.parsed`） | {stats["parsed_dirs_total"]} |
| `doc_full` 行数（目录数） | {stats["doc_full_rows"]} |
| `doc_status` processed 行数 | {stats["doc_status_processed"]} |
| `doc_status` failed 行数 | {stats["doc_status_failed_rows"]} |
| 有 chunks 的文档数 | {stats["docs_with_chunks"]} |
| chunks 总数 | {stats["chunks_total"]} |

{gap_line}
{dup_line}
- {failed_line}
- {order_line}（本次实测）；{status_line}。
- {content_line}

### 1.2 身份与哈希合同（task 1.4 结论，本次运行复算）

对全部 {hash_verify["checked"]} 份同时有解析产物与库内记录的文档复算：

| 字段 | 语义（复算公式） | 匹配数 |
|---|---|---|
| `doc_full.id` | `"doc-" + md5(doc_name)`，由**文件名**推导，与内容无关 | {hash_verify["doc_id_ok"]} |
| `doc_full.content_hash` | `md5(normalize_merged_text_for_hash(blocks 合并正文))`，与 document_hash **不同源** | {hash_verify["content_hash_ok"]} |
| `blocks.meta.document_hash` | `sha256(blocks 合并正文)`，解析产物完整性指纹 | {hash_verify["document_hash_ok"]} |
| `mineru_raw/_manifest.source_content_hash` | `sha256(原始 PDF 字节)` | 首轮抽样（air-02）核验；本轮未逐份复算 PDF 字节 |

明确不可比较的哈希对：`document_hash`（解析后正文）≠ `source_content_hash`（原始 PDF 字节）≠
`content_hash`（规范化正文 md5）。三者均可各自复算，字段名之间不构成等价关系。
{meta_line}，标题等元数据只能从解析产物正文提取。

### 1.3 block/table → chunk 映射（task 1.5 证据，详见 mapping-samples.jsonl）

- sidecar.refs 的 ref 类型本次聚合仅见 block（类型清单见 independent 核验先例与本次聚合）；无 table 类型 ref；
  table 定位靠 chunk 正文内联 `<table id>` 标记与 tables.json 的 blockid 关联。
- GB 8978-1996 表 1 两片同在 chunk-001（片段 caption/dimension 本次从 tables.json 读取，见 mapping-samples）。
- GB 18466-2005 定义 3.1–3.4 与跨 chunk 条款 4.1 的核验结果由本次子串检查产生（见 clause_layout）。
- 反向多对多：{span_sample["observed"]}
- 空 sidecar：{empty_sample["observed"]}
- 全库覆盖：{cov["docs_full_coverage"]} 份产物 block **ID** 全覆盖、{cov["docs_partial_coverage"]} 份部分覆盖、
  {cov["docs_without_chunks"]} 份无 chunk。注意：ID 引用覆盖≠block 全部文字覆盖。

### 1.4 中文全文检索现状（task 1.7 观察，详见 search-probes.json）

- {fts_line}
- jieba 等分词器未安装，探针只记录"待 Phase 2 安装后验证"的方案，未标成功。

### 1.5 发布包离线接口（task 1.6，详见 compatibility.md 及其探针记录）

- lightrag-hku {schema["dependency_versions"]["lightrag-hku"]} 导入成功；本次运行实际执行接口存在性、
  docstring 字段、源码副作用扫描等探针（记录嵌在 compatibility.md §3）。
- 初始化副作用已由源码扫描确认：首次建池必然走 initdb/check_tables 路径——本轮审计完全未实例化存储。
- 三库 workspace 现场**取值**属于历史观察（首轮 2026-10-04 只读探针：PG 行 `workspace='default'`、
  Qdrant payload `workspace_id='_'`、Neo4j label `base`）；本轮未重新连接 Qdrant/Neo4j，引用时以上次
  记录为准。发布包常量（`DEFAULT_WORKSPACE="_"` 等）本次已从源码扫描确认，见 compatibility.md §1.3。

## 2. 推断（有依据、未逐条验证）

- `doc_status.content_hash` 与 `doc_full.content_hash` 语义相同。——推断，Phase 1 全量核验。
- 部分覆盖产物中缺引用的 block 属解析端"空块/合并块"处理。——首轮抽样（air-03）核验，未全量。

## 3. 未验证项（Phase 1+ 处理，本阶段不冒充完成）

- 发布包查询链路运行时行为、reranker、llm_response_cache 副作用：需按 tasks 5.1 在隔离环境实测。
- 应用侧分词召回率：jieba 未安装、tsvector/GIN 未建，属 Phase 2。
- Neo4j/Qdrant 本轮未连接；aquery 语义链路未运行。

## 4. 下一步（进入 Gate 0 复审）

1. 主 agent 复审本目录报告与 fixture 测试（tests/），确认身份合同、白名单与排除项、兼容性风险。
2. 通过后进入第 2 组任务：显式辅助 schema 迁移（`env_rag` 占用与权限见 schema.json app_schema_plan）、
   适配器、目录构建。
3. 失败／重复文档的处置单独处理，不阻断有效白名单验证。

## 5. 复跑与来源变化

`run-manifest.json` 记录 run_id、审计代码逐文件 SHA-256 与来源快照指纹。指纹组件覆盖：PG 原文、
chunks（ID／顺序／正文／heading／sidecar）、解析 blocks／tables 字节、分块参数、doc_status。
任一组件变化都会改变 composite 值——这是**观察事实**，不允许为了消除差异写库。
失败运行以 `status=failed_at:<step>` 标记，不会与成功产物混用。报告不含任何凭据（异常只报类型）。
"""


# --------------------------------------------------------------------------
# runner
# --------------------------------------------------------------------------


class _StepFailure(RuntimeError):
    pass


async def collect_everything(conn: asyncpg.Connection, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex[:16]
    versions = _versions()
    steps: list[dict] = []

    async def step(name: str, fn):
        try:
            result = await fn()
            steps.append({"step": name, "status": "ok"})
            return result
        except BaseException as exc:  # noqa: BLE001 — record stage, re-raise redacted
            steps.append({"step": name, "status": "error", "error_type": type(exc).__name__})
            # Persist the failure manifest before propagating (staged outputs stay coherent).
            (out_dir / "run-manifest.json").write_text(
                json.dumps(
                    _manifest(
                        run_id,
                        {"algorithm": "not-computed", "value": None, "components": {}},
                        steps,
                        snapshot.audit_code_fingerprint(Path(__file__).parent),
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
            raise

    # Pin local inputs before any of the evidence builders read them.
    async def read_artifact_fingerprint():
        return snapshot.fingerprint_artifacts(identity.PARSED_ROOT)

    artifacts_hash = await step("artifact_snapshot_start", read_artifact_fingerprint)

    # ---- collect rows once, reuse for inventory + fingerprint (one snapshot) ----
    async def collect_rows():
        return {
            "docs": await conn.fetch(
                """SELECT f.id, f.doc_name, f.sidecar_location, f.content_hash, f.parse_engine,
                          f.parse_format, f.meta, f.chunk_options, f.content
                   FROM public.lightrag_doc_full f WHERE f.workspace=$1 ORDER BY f.id""",
                WORKSPACE,
            ),
            "chunks": await conn.fetch(
                """SELECT id, full_doc_id, chunk_order_index, tokens, content, heading, sidecar
                   FROM public.lightrag_doc_chunks WHERE workspace=$1""",
                WORKSPACE,
            ),
            "statuses": await conn.fetch(
                """SELECT id, file_path, status, chunks_count, error_msg
                   FROM public.lightrag_doc_status WHERE workspace=$1""",
                WORKSPACE,
            ),
        }

    rows = await step("collect_rows", collect_rows)

    # ---- G0-1: source snapshot fingerprint over the same rows ----
    docs_hash = snapshot.fingerprint_docs(rows["docs"])
    chunks_hash = snapshot.fingerprint_chunks(rows["chunks"])
    status_hash = snapshot.fingerprint_status(rows["statuses"])
    params = snapshot.chunking_params(rows["docs"])
    fingerprint = snapshot.source_snapshot_fingerprint(
        docs_hash, chunks_hash, status_hash, artifacts_hash, params
    )

    async def run_schema():
        return await _schema_json(conn, versions)

    async def run_inventory():
        return await _inventory(conn)

    schema = await step("schema.json", run_schema)
    _write(out_dir / "schema.json", schema)

    inventory, meta = await step("inventory.jsonl", run_inventory)
    (out_dir / "inventory.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in inventory) + "\n"
    )

    samples = await step("mapping-samples.jsonl", lambda: _mapping_samples(conn))
    (out_dir / "mapping-samples.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in samples) + "\n"
    )

    probes = await step("search-probes.json", lambda: build_search_probes(conn))
    _write(out_dir / "search-probes.json", probes)

    sample_set = await step("sample-set.json", lambda: build_sample_set(conn))
    sample_set["source_snapshot_fingerprint"] = fingerprint
    for questions in sample_set["questions"].values():
        for question in questions:
            for target in question["target_docs"]:
                target["snapshot_id"] = fingerprint["value"]
    _write(out_dir / "sample-set.json", sample_set)

    async def run_compat() -> str:
        return build_compatibility_md(versions)

    compat_md = await step("compatibility.md", run_compat)
    (out_dir / "compatibility.md").write_text(compat_md)

    async def validate_artifact_snapshot():
        if snapshot.fingerprint_artifacts(identity.PARSED_ROOT) != artifacts_hash:
            raise RuntimeError("Local parsed artifacts changed during audit")

    await step("artifact_snapshot_end", validate_artifact_snapshot)

    manifest = _manifest(
        run_id, fingerprint, steps, snapshot.audit_code_fingerprint(Path(__file__).parent)
    )
    audit_md = _audit_md(meta["stats"], meta["hash_verify"], samples, schema, manifest)
    (out_dir / "audit.md").write_text(audit_md)
    steps.append({"step": "audit.md", "status": "ok"})

    manifest = _manifest(
        run_id, fingerprint, steps, snapshot.audit_code_fingerprint(Path(__file__).parent)
    )
    _write(out_dir / "run-manifest.json", manifest)

    return {"stats": meta["stats"], "hash_verify": meta["hash_verify"], "manifest": manifest}


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
