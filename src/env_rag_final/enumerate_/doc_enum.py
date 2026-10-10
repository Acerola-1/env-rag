"""Document enumeration over the active catalog (task 3.4, corrected per E5).

Full paginated enumeration by an explicit match predicate. Guards:
- active snapshot is looked up per workspace and re-checked after EVERY page
  (including the last one and zero-match cases);
- the matched-set content token covers the complete match set and is
  recomputed per page (no fixed 10,000-row cap — an explicit budget bounds
  it and exceeding it degrades to partial);
- catalog_snapshot_id and source_snapshot_id are distinct: the catalog
  snapshot identifies the build; the source fingerprint comes from the
  build's recorded source fingerprint.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from .contract import EnumResult, FailStage

_TOKEN_BUDGET_ROWS = 50_000


def _set_token(rows: list) -> str:
    payload = sorted(
        json.dumps(
            {
                # G2: every field present in the returned items participates
                "doc_id": r["doc_id"],
                "doc_name": r["doc_name"],
                "title": r["title"],
                "title_confidence": r.get("title_confidence"),
                "self_code": r["self_code"],
                "self_code_version": r["self_code_version"],
                "doc_type": r.get("doc_type"),
                "unknown_fields": r.get("unknown_fields"),
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        for r in rows
    )
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


async def _active_snapshot(conn, workspace: str) -> dict | None:
    row = await conn.fetchrow(
        """SELECT snapshot_id, source_fingerprint FROM env_rag.corpus_runs
           WHERE workspace=$1 AND status='active'""",
        workspace,
    )
    return dict(row) if row else None


async def _source_fingerprint_value(raw) -> str:

    if isinstance(raw, str):
        raw = json.loads(raw) if raw else {}
    return (raw or {}).get("value", "")


async def _match_page(
    conn,
    workspace: str,
    snapshot_id: str,
    predicate_sql: str,
    args: tuple,
    limit: int,
    offset: int,
) -> list:
    # R4: the requested workspace threads through every data query
    return await conn.fetch(
        f"""SELECT doc_id, doc_name, title, title_confidence, self_code, self_code_version,
                   doc_type, unknown_fields
            FROM env_rag.documents
            WHERE workspace=$1 AND snapshot_id=$2 AND ({predicate_sql})
            ORDER BY doc_name LIMIT {limit} OFFSET {offset}""",
        workspace,
        snapshot_id,
        *args,
    )


async def _match_count(
    conn, workspace: str, snapshot_id: str, predicate_sql: str, args: tuple
) -> int:
    return await conn.fetchval(
        f"""SELECT count(*) FROM env_rag.documents
            WHERE workspace=$1 AND snapshot_id=$2 AND ({predicate_sql})""",
        workspace,
        snapshot_id,
        *args,
    )


async def enumerate_documents(
    conn,
    predicate_sql: str,
    args: tuple = (),
    predicate_text: str = "",
    page_size: int = 100,
    max_pages: int = 50,
    workspace: str = "default",
) -> EnumResult:
    """Enumerate every catalog document matching an explicit predicate."""
    if any(
        k in predicate_sql.lower() for k in (";", "--", "drop ", "insert ", "update ", "delete ")
    ):
        raise ValueError("predicate_sql must be a plain boolean expression")
    query_id = f"doc-enum-{uuid.uuid4().hex[:12]}"

    def _result(**kw) -> EnumResult:
        base = dict(
            query_id=query_id,
            kind="document",
            workspace=workspace,
            catalog_snapshot_id="",
            source_snapshot_id="",
            predicate=predicate_text or predicate_sql,
        )
        base.update(kw)
        return EnumResult(**base)

    snap_before = await _active_snapshot(conn, workspace)
    if snap_before is None:
        return _result(
            coverage_status="stale",
            fail_stage=FailStage.SNAPSHOT,
            warnings=["no active catalog build for workspace"],
        )
    snapshot_at_start = snap_before["snapshot_id"]
    source_fp = await _source_fingerprint_value(snap_before["source_fingerprint"])

    from env_rag_final.catalog.builder import _live_source_fingerprint

    live_before = await _live_source_fingerprint(conn, workspace)
    if live_before and live_before != source_fp:
        return _result(
            catalog_snapshot_id=snapshot_at_start,
            source_snapshot_id=source_fp,
            coverage_status="stale",
            fail_stage=FailStage.STALE,
            warnings=["live source fingerprint differs from the active build's; catalog is stale"],
        )

    total = await _match_count(conn, workspace, snapshot_at_start, predicate_sql, args)
    budget_rows = min(max_pages * page_size, _TOKEN_BUDGET_ROWS)
    full_at_start = await _match_page(
        conn, workspace, snapshot_at_start, predicate_sql, args, budget_rows, 0
    )
    token = _set_token(full_at_start)

    first_page = await _match_page(
        conn, workspace, snapshot_at_start, predicate_sql, args, page_size, 0
    )
    items: list[dict] = []
    for r in first_page:
        d = dict(r)
        d["citation"] = {
            "kind": "catalog_row",
            "workspace": workspace,
            "snapshot_id": snapshot_at_start,
            "doc_id": d["doc_id"],
            "doc_name": d["doc_name"],
        }
        d["citation_verified"] = True
        items.append(d)
    processed = len(items)
    pages_read = 1
    warnings: list[str] = []
    fail = FailStage.NONE
    coverage = "complete"

    offset = page_size
    while processed < total:
        if pages_read >= max_pages or offset >= budget_rows:
            coverage, fail = "partial", FailStage.BUDGET
            warnings.append(f"pagination budget reached at {processed}/{total}")
            break
        page = await _match_page(
            conn, workspace, snapshot_at_start, predicate_sql, args, page_size, offset
        )
        full_now = await _match_page(
            conn, workspace, snapshot_at_start, predicate_sql, args, budget_rows, 0
        )
        if _set_token(full_now) != token:
            coverage, fail = "stale", FailStage.STALE
            warnings.append(
                "matched doc set changed during enumeration; refusing mixed-version result"
            )
            break
        snap_now = await _active_snapshot(conn, workspace)
        if snap_now is None or snap_now["snapshot_id"] != snapshot_at_start:
            coverage, fail = "stale", FailStage.SNAPSHOT
            warnings.append("active catalog snapshot changed during enumeration")
            break
        if not page:
            break
        for r in page:
            d = dict(r)
            d["citation"] = {
                "kind": "catalog_row",
                "workspace": workspace,
                "snapshot_id": snapshot_at_start,
                "doc_id": d["doc_id"],
                "doc_name": d["doc_name"],
            }
            d["citation_verified"] = True
            items.append(d)
        processed = len(items)
        pages_read += 1
        offset += page_size

    # E5: final guard before returning — active build and match set unchanged
    live_after = await _live_source_fingerprint(conn, workspace)
    if live_after and live_after != source_fp:
        return _result(
            catalog_snapshot_id=snapshot_at_start,
            source_snapshot_id=source_fp,
            coverage_status="stale",
            fail_stage=FailStage.STALE,
            warnings=["live source changed during/after enumeration; result is stale"],
        )
    snap_final = await _active_snapshot(conn, workspace)
    if snap_final is None or snap_final["snapshot_id"] != snapshot_at_start:
        coverage, fail = "stale", FailStage.SNAPSHOT
        warnings.append("active catalog snapshot replaced before result was returned")
    else:
        full_final = await _match_page(
            conn, workspace, snapshot_at_start, predicate_sql, args, budget_rows, 0
        )
        if _set_token(full_final) != token:
            coverage, fail = "stale", FailStage.STALE
            warnings.append("matched doc set changed before result was returned")

    unknown_rows = [it for it in items if it.get("unknown_fields")]
    if unknown_rows:
        warnings.append(
            f"{len(unknown_rows)} matched docs have unknown metadata fields; "
            "they are included but flagged"
        )

    result = _result(
        catalog_snapshot_id=snapshot_at_start,
        source_snapshot_id=source_fp,
        members_total=total,
        members_processed=processed,
        items=items,
        coverage_status=coverage,
        warnings=warnings,
        fail_stage=fail,
        read_token=token,
    )
    result.validate()
    return result


# ---------------------------------------------------------------------------
# improvement-3: catalog-layer related (amended/integrated) document scan.
# ---------------------------------------------------------------------------

_META_SQL = """SELECT doc_id, doc_name, title, title_confidence, self_code, self_code_version,
               doc_type, unknown_fields
        FROM env_rag.documents
        WHERE workspace=$1 AND snapshot_id=$2
        ORDER BY doc_name LIMIT {limit} OFFSET {offset}"""


async def _meta_page(conn, workspace: str, snapshot_id: str, limit: int, offset: int) -> list:
    return await conn.fetch(_META_SQL.format(limit=limit, offset=offset), workspace, snapshot_id)


async def _meta_count(conn, workspace: str, snapshot_id: str) -> int:
    return await conn.fetchval(
        "SELECT count(*) FROM env_rag.documents WHERE workspace=$1 AND snapshot_id=$2",
        workspace,
        snapshot_id,
    )


def _attribution_rows(rows: list, query_codes: list[dict]) -> tuple[list, list]:
    """Apply the accepted name/title judgement to every scanned row.

    Returns (matches, []) where each match carries its per-branch statuses;
    rows whose judgement list is empty carry no requested code at all and are
    simply not part of the related universe (audited through the scan stats).
    """
    from env_rag_final.search.query import attribution_judgement

    matches = []
    for r in rows:
        row = dict(r)
        branches = attribution_judgement(row, query_codes)
        if not branches:
            continue
        row["attribution_branches"] = branches
        matches.append(row)
    return matches, []


def attribution_token(matches: list) -> str:
    """Content token over the related-matching set INCLUDING the per-branch
    judgement — a same-count content change (e.g. a version swap inside the
    carrying title) changes it; the base-set token alone is NOT proof for the
    related set (handoff §1)."""
    payload = sorted(
        json.dumps(
            {
                "doc_id": m["doc_id"],
                "doc_name": m["doc_name"],
                "title": m["title"],
                "self_code": m["self_code"],
                "self_code_version": m["self_code_version"],
                "branches": sorted(
                    json.dumps(b, ensure_ascii=False, sort_keys=True)
                    for b in m.get("attribution_branches", [])
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        for m in matches
    )
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


async def enumerate_attributed_documents(
    conn,
    query_codes: list[dict],
    workspace: str = "default",
    *,
    expected_snapshot_id: str,
    expected_source: str = "",
    page_size: int = 100,
    max_pages: int = 50,
) -> EnumResult:
    """Full catalog-layer scan for RELATED documents (改进组3).

    Same workspace, SAME active catalog snapshot and the same source
    fingerprint as the base enumeration — the search index and its search_id
    take NO part (an empty or foreign search_id can never disable or fake
    this step). Reads every metadata page under an explicit budget
    (``max_pages * page_size``); reaching the budget degrades to partial with
    a BUDGET fail stage — truncation is never reported as complete, and this
    internal scan is not "the whole corpus as the answer": only rows whose
    OWN name/title carry a requested code branch are collected, judged by the
    accepted per-branch attribution rule (canonical/attributed/mismatch).

    Guards: snapshot re-checked before/after and per page; the matching-set
    content token (including branch judgements) is recomputed after every
    page and finally; live source fingerprint re-checked before/after.
    """
    query_id = f"doc-attrib-{uuid.uuid4().hex[:12]}"

    def _result(**kw) -> EnumResult:
        base = dict(
            query_id=query_id,
            kind="document",
            workspace=workspace,
            catalog_snapshot_id=expected_snapshot_id,
            source_snapshot_id=expected_source,
            predicate="catalog-layer name/title attribution over the same "
            "workspace + active snapshot (no search index)",
        )
        base.update(kw)
        return EnumResult(**base)

    snap = await _active_snapshot(conn, workspace)
    if snap is None or snap["snapshot_id"] != expected_snapshot_id:
        return _result(
            coverage_status="stale",
            fail_stage=FailStage.SNAPSHOT,
            warnings=[
                "the related attribution scan must observe the SAME active catalog snapshot "
                f"as the base set (base {expected_snapshot_id!r}, "
                f"observed {snap['snapshot_id'] if snap else None!r}) — generations are never mixed"
            ],
        )
    source_fp = await _source_fingerprint_value(snap["source_fingerprint"])
    if expected_source and source_fp != expected_source:
        return _result(
            coverage_status="stale",
            fail_stage=FailStage.STALE,
            warnings=["related scan source fingerprint differs from the base enumeration's"],
        )

    from env_rag_final.catalog.builder import _live_source_fingerprint

    live_before = await _live_source_fingerprint(conn, workspace)
    if live_before and source_fp and live_before != source_fp:
        return _result(
            coverage_status="stale",
            fail_stage=FailStage.STALE,
            warnings=["live source fingerprint differs from the active build's"],
        )

    total_rows = await _meta_count(conn, workspace, expected_snapshot_id)
    budget_rows = min(max_pages * page_size, _TOKEN_BUDGET_ROWS)
    window = await _meta_page(conn, workspace, expected_snapshot_id, budget_rows, 0)
    if total_rows > budget_rows:
        return _result(
            members_total=total_rows,
            members_processed=len(window),
            coverage_status="partial",
            fail_stage=FailStage.BUDGET,
            warnings=[
                f"attribution scan budget reached before reading all {total_rows} catalog rows "
                f"(budget {budget_rows}) — a truncated related scan is never complete"
            ],
        )
    matches_start, _ = _attribution_rows(window, query_codes)
    token = attribution_token(matches_start)

    items: list[dict] = []
    scanned = 0
    offset = 0
    pages_read = 0
    warnings: list[str] = []
    fail = FailStage.NONE
    coverage = "complete"
    while offset < total_rows:
        page = await _meta_page(conn, workspace, expected_snapshot_id, page_size, offset)
        if not page:
            break
        mset, _ = _attribution_rows(page, query_codes)
        for m in mset:
            m["citation"] = {
                "kind": "catalog_row",
                "workspace": workspace,
                "snapshot_id": expected_snapshot_id,
                "doc_id": m["doc_id"],
                "doc_name": m["doc_name"],
            }
            m["citation_verified"] = True
            items.append(m)
        scanned += len(page)
        pages_read += 1
        offset += page_size
        # per-page guards (including the last page): same snapshot, same content
        full_now = await _meta_page(conn, workspace, expected_snapshot_id, budget_rows, 0)
        m_now, _ = _attribution_rows(full_now, query_codes)
        if attribution_token(m_now) != token:
            coverage, fail = "stale", FailStage.STALE
            warnings.append(
                "the related-matching set changed during the scan; refusing a mixed-version union"
            )
            items = []
            break
        snap_now = await _active_snapshot(conn, workspace)
        if snap_now is None or snap_now["snapshot_id"] != expected_snapshot_id:
            coverage, fail = "stale", FailStage.SNAPSHOT
            warnings.append("active catalog snapshot replaced during the related scan")
            break
        if scanned < total_rows and pages_read >= max_pages:
            coverage, fail = "partial", FailStage.BUDGET
            warnings.append(f"attribution scan stopped at {scanned}/{total_rows} rows (max_pages)")
            break

    # final guards: source, snapshot and the matching set after the last page
    live_after = await _live_source_fingerprint(conn, workspace)
    if live_after and source_fp and live_after != source_fp:
        coverage, fail = "stale", FailStage.STALE
        warnings.append("live source changed during/after the related scan")
    snap_final = await _active_snapshot(conn, workspace)
    if snap_final is None or snap_final["snapshot_id"] != expected_snapshot_id:
        coverage, fail = "stale", FailStage.SNAPSHOT
        warnings.append("active snapshot replaced before the related scan returned")
    if coverage == "complete":
        full_final = await _meta_page(conn, workspace, expected_snapshot_id, budget_rows, 0)
        m_final, _ = _attribution_rows(full_final, query_codes)
        if attribution_token(m_final) != token:
            coverage, fail = "stale", FailStage.STALE
            warnings.append("the related-matching set changed before the scan returned")

    result = _result(
        members_total=len(matches_start),
        members_processed=len(items),
        items=items,
        coverage_status=coverage,
        warnings=warnings,
        fail_stage=fail,
        read_token=token,
    )
    result.validate()
    return result


async def verify_publication_snapshot(
    conn, workspace: str, snapshot_id: str, source_fp: str
) -> str:
    """Post-union guard (handoff §1): after base+related were merged, the
    active catalog must STILL be the same build; returns "" when stable, else
    a human-readable reason. The union publish window is guarded as one —
    per-branch guards alone cannot cover an active swap between the reads."""
    if not snapshot_id:
        return "no snapshot identity to guard the publication window"
    snap = await _active_snapshot(conn, workspace)
    if snap is None or snap["snapshot_id"] != snapshot_id:
        return (
            "the active catalog snapshot changed before publication "
            f"(expected {snapshot_id!r}, observed {snap['snapshot_id'] if snap else None!r})"
        )
    fp = await _source_fingerprint_value(snap["source_fingerprint"])
    if source_fp and fp and fp != source_fp:
        return "the catalog source fingerprint changed before publication"
    return ""


async def verify_publication_content(
    conn,
    workspace: str,
    enum,
    related,
    predicate_args: tuple,
    query_codes: list | None = None,
    page_size: int = 100,
    max_pages: int = 50,
) -> str:
    """F1: the FINAL publication-window guard — same workspace, same snapshot,
    same source PLUS a last bounded re-read of the MATCHING SETS themselves.

    Snapshot/fingerprint equality alone cannot see a standard's version/title
    being re-registered inside the window, and hashing only the in-memory
    union (publish_token) proves nothing about the CURRENT catalog. This
    guard re-reads:

    1. the base predicate's full match window, compared against the base
       enumeration's read token (row identity fields, versions and titles
       all participate);
    2. when a related scan ran, the attribution matching set over the full
       metadata window, compared against the scan's read token — which also
       carries the per-branch attribution judgement, so a row that NO LONGER
       matches, one that NEWLY matches (a previously unrelated row becoming
       a related one) or whose judgement changed is caught; an unchanged
       total row count is not a defense.

    The reads go through the existing read-only paginated channels with the
    same budget formula as the branches — no new bypass. Returns "" when the
    publication window is content-stable; any mismatch or a failed re-read
    returns a reason: the caller publishes stale/partial, NEVER silently
    complete, and the already-read rows stay published as diagnosis (never
    quietly replaced by the new values)."""
    reason = await verify_publication_snapshot(
        conn, workspace, enum.catalog_snapshot_id, enum.source_snapshot_id
    )
    if reason:
        return reason
    budget_rows = min(max_pages * page_size, _TOKEN_BUDGET_ROWS)
    try:
        window = await _match_page(
            conn,
            workspace,
            enum.catalog_snapshot_id,
            enum.predicate,
            tuple(predicate_args),
            budget_rows,
            0,
        )
        if _set_token(list(window)) != enum.read_token:
            return (
                "the base-matched catalog content changed inside the publication window "
                "(version/title/identity re-registration under the same snapshot) — the read "
                "result is retained for diagnosis and NEVER silently re-covered or re-verified"
            )
        if related is not None and query_codes:
            mwindow = await _meta_page(conn, workspace, enum.catalog_snapshot_id, budget_rows, 0)
            matches_now, _ = _attribution_rows(list(mwindow), query_codes)
            if attribution_token(matches_now) != related.read_token:
                return (
                    "the related-matching set changed inside the publication window (a row "
                    "newly carries/stops carrying the requested code, or its attribution "
                    "judgement changed under the same snapshot and row count) — the union is "
                    "never silently published as complete"
                )
    except Exception as exc:  # an unverifiable window is never silently complete
        return (
            f"the final publication-window re-read could not be completed "
            f"({type(exc).__name__}: {exc}) — never silently complete; the reason is recorded"
        )
    return ""


def publish_token(rows: list) -> str:
    """Content token over the FINAL publish union (identity fields plus the
    source/attribution paths each row carries)."""
    payload = sorted(
        json.dumps(
            {
                "doc_id": r.get("doc_id"),
                "doc_name": r.get("doc_name"),
                "title": r.get("title"),
                "self_code": r.get("self_code"),
                "self_code_version": r.get("self_code_version"),
                "discovery": r.get("discovery"),
                "sources": sorted(r.get("sources") or [r.get("discovery") or ""]),
                "branches": sorted(
                    json.dumps(b, ensure_ascii=False, sort_keys=True)
                    for b in r.get("attribution_branches", [])
                ),
                "snapshot": (r.get("citation") or {}).get("snapshot_id"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        for r in rows
    )
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()
