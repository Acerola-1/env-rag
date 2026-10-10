"""Table enumeration orchestration (tasks 3.2, corrected per E2/E3/E4/E5).

Entry ``enumerate_table``: chapter-scoped linking, HTML header evidence
always provided, row citations bound to physical fragment + row coordinates,
identity/version guards around the whole read, and strict contract validation.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from env_rag_final.audit import identity as sid
from env_rag_final.catalog.builder import check_stale

from .contract import EnumResult, FailStage
from .tables import enumerate_logical_table, link_logical_tables


async def enumerate_table(
    conn,
    workspace: str,
    doc_id: str,
    table_number: str,
    parsed_root: Path | None = None,
    chapter_scope: str | None = None,
    allow_partial: bool = False,
) -> EnumResult:
    """Enumerate one logical table by base number.

    E2: when several same-number logical tables exist (cross-chapter), a
    ``chapter_scope`` must disambiguate; without it the result is ambiguous
    listing the candidates — never "pick the first".
    """
    parsed_root = parsed_root or sid.PARSED_ROOT
    query_id = f"table-{uuid.uuid4().hex[:12]}"

    def _result(**kw) -> EnumResult:
        base = dict(
            query_id=query_id,
            kind="table",
            workspace=workspace,
            catalog_snapshot_id="",
            source_snapshot_id="",
            scope_ids=[],
        )
        base.update(kw)
        return EnumResult(**base)

    stale_before = await check_stale(conn)
    snapshot_id = stale_before.get("active_snapshot_id")
    if stale_before.get("state") != "current" or snapshot_id is None:
        return _result(
            coverage_status="stale",
            fail_stage=FailStage.STALE,
            warnings=[f"catalog state={stale_before.get('state')}: {stale_before.get('action')}"],
        )

    doc_name = await conn.fetchval(
        "SELECT doc_name FROM env_rag.documents WHERE workspace=$1 AND snapshot_id=$2 AND doc_id=$3",
        workspace,
        snapshot_id,
        doc_id,
    )
    if doc_name is None:
        return _result(
            catalog_snapshot_id=snapshot_id,
            source_snapshot_id=stale_before.get("stored_fingerprint") or "",
            coverage_status="stale",
            fail_stage=FailStage.SNAPSHOT,
            warnings=[f"doc {doc_id} not found in catalog snapshot {snapshot_id}"],
        )

    units = await conn.fetch(
        """SELECT unit_id, unit_order, table_seq, caption, heading, locator
           FROM env_rag.source_units
           WHERE workspace=$1 AND snapshot_id=$2 AND doc_id=$3 AND unit_kind='table'
           ORDER BY unit_order, table_seq""",
        workspace,
        snapshot_id,
        doc_id,
    )

    # E2: the formal entry ALWAYS supplies header evidence for grouping
    pdir = sid.PARSED_ROOT / f"{doc_name}.parsed"
    tj = sorted(pdir.glob("*.tables.json"))
    tables = json.loads(tj[0].read_text())["tables"] if tj else {}
    provider = lambda tid: (tables.get(tid) or {}).get("content", "")  # noqa: E731
    logical = link_logical_tables([dict(u) for u in units], html_provider=provider)

    candidates = [lt for lt in logical if lt.number == table_number]
    if chapter_scope is not None:
        candidates = [lt for lt in candidates if lt.scope_key == chapter_scope]
    if not candidates:
        return _result(
            catalog_snapshot_id=snapshot_id,
            source_snapshot_id=stale_before["stored_fingerprint"],
            members_total=0,
            members_processed=0,
            coverage_status="ambiguous",
            fail_stage=FailStage.AMBIGUOUS,
            warnings=[f"no logical table 表{table_number} in {doc_name[:40]}"],
        )
    if len(candidates) > 1:
        return _result(
            catalog_snapshot_id=snapshot_id,
            source_snapshot_id=stale_before["stored_fingerprint"],
            coverage_status="ambiguous",
            fail_stage=FailStage.AMBIGUOUS,
            warnings=[
                f"{len(candidates)} logical tables share 表{table_number} "
                f"(chapters: {[c.scope_key for c in candidates]}); supply chapter_scope"
            ],
        )
    target = candidates[0]

    # G3: metadata is keyed by the fragment's stable identity (table_id), so a
    # missing first fragment can never shift the coordinates of the rest.
    warnings: list[str] = []
    unreadable = 0
    frag_meta: dict[str, dict] = {}
    for frag in target.fragments:
        entry = tables.get(frag.table_id)
        chunk_ids = await conn.fetch(
            """SELECT chunk_id FROM env_rag.unit_chunk_links
               WHERE workspace=$1 AND snapshot_id=$2 AND doc_id=$3 AND unit_id=$4
               ORDER BY chunk_order""",
            workspace,
            snapshot_id,
            doc_id,
            frag.table_id,
        )
        frag_meta[frag.table_id] = {
            "table_id": frag.table_id,
            "caption": frag.caption,
            "blockid": frag.blockid,
            "locator": frag.table_id,
            "chunk_ids": [c["chunk_id"] for c in chunk_ids],
            "order": frag.order,
            "heading_scope": frag.heading,
            "readable": not (entry is None or not (entry.get("content") or "").strip()),
        }
        if not frag_meta[frag.table_id]["readable"]:
            unreadable += 1
            warnings.append(f"fragment {frag.table_id} unreadable (missing/empty tables.json)")
    fragments_html = [
        (tables.get(f.table_id) or {}).get("content", "")
        for f in target.fragments
        if frag_meta[f.table_id]["readable"]
    ]

    total_frags = len(target.fragments)
    if unreadable == total_frags:
        return _result(
            catalog_snapshot_id=snapshot_id,
            source_snapshot_id=stale_before["stored_fingerprint"],
            scope_ids=[target.table_id],
            members_total=total_frags,
            members_processed=0,
            coverage_status="ambiguous",
            fail_stage=FailStage.AMBIGUOUS,
            warnings=["no fragment of the logical table is readable"],
        )
    if unreadable and not allow_partial:
        return _result(
            catalog_snapshot_id=snapshot_id,
            source_snapshot_id=stale_before["stored_fingerprint"],
            scope_ids=[target.table_id],
            members_total=total_frags,
            members_processed=total_frags - unreadable,
            coverage_status="partial",
            fail_stage=FailStage.MISSING_FRAGMENT,
            warnings=warnings,
        )

    # E4: Fragments carry html — enumerate with physical row coordinates
    rows = enumerate_logical_table(target.fragments)
    coverage = "complete"
    fail = FailStage.NONE
    if rows.structure_status != "confirmed":
        coverage = "ambiguous"
        fail = FailStage.AMBIGUOUS
        warnings.append(f"structure_status={rows.structure_status}（列/数据行无法可靠识别）")
    elif target.status != "confirmed":
        coverage = "partial" if target.status == "partial" else "ambiguous"
        fail = FailStage.AMBIGUOUS if target.status == "ambiguous" else FailStage.NONE
        warnings.append(f"logical table status={target.status}（续表关联不完整/歧义）")
    if rows.sequence_ok is False:
        coverage = "partial"
        warnings.append("序号不连续：缺片或解析缺行，不能宣称 complete")
    if unreadable:
        coverage = "partial"
        fail = FailStage.MISSING_FRAGMENT
    if not rows.rows:
        coverage = "ambiguous"
        fail = FailStage.AMBIGUOUS
        warnings.append("no data rows could be extracted")

    # G2: re-check the source before claiming a final coverage
    stale_final = await check_stale(conn)
    if (
        stale_final.get("state") != "current"
        or stale_final.get("active_snapshot_id") != snapshot_id
    ):
        return _result(
            catalog_snapshot_id=snapshot_id,
            source_snapshot_id=stale_before.get("stored_fingerprint") or "",
            scope_ids=[target.table_id],
            members_total=total_frags,
            members_processed=len(fragments_html),
            coverage_status="stale",
            fail_stage=FailStage.STALE,
            warnings=["catalog/source changed during table enumeration; result is stale"],
        )

    # E4: row citations bound to (fragment_index, row_in_fragment)
    items = []
    for i, row in enumerate(rows.rows):
        fi, ri = rows.row_origins[i]
        meta = frag_meta[target.fragments[fi].table_id]
        items.append(
            {
                "seq": (row[0] or "").strip() if row else "",
                "cells": row,
                "citation": {
                    "kind": "table_row",
                    "workspace": workspace,
                    "doc_id": doc_id,
                    "snapshot_id": snapshot_id,
                    "fragment_index": fi,
                    "row_in_fragment": ri,
                    "table_id": meta["table_id"],
                    "blockid": meta["blockid"],
                    "locator": meta["locator"],
                    "chunk_ids": meta["chunk_ids"],
                },
                "citation_verified": True,  # row coordinates come from parsing the bound fragment
            }
        )

    result = _result(
        catalog_snapshot_id=snapshot_id,
        source_snapshot_id=stale_before["stored_fingerprint"],
        scope_ids=[target.table_id],
        members_total=total_frags,
        members_processed=len(fragments_html),
        items=items,
        coverage_status=coverage,
        warnings=warnings,
        fail_stage=fail,
    )
    # E3/R2: header, units and footnotes are part of the delivered result
    result.warnings.append(
        "table_structure: header="
        + json.dumps(rows.header, ensure_ascii=False)
        + "; units="
        + json.dumps(rows.units, ensure_ascii=False)
        + "; footnotes="
        + json.dumps(rows.footnotes, ensure_ascii=False)
    )
    result.validate()
    return result
