"""Catalog builder (tasks 2.6, S4/S5): fingerprint, recipe-bound builds, atomic publish.

Flow (design.md decision 2, corrected per review):
  1. REPEATABLE READ snapshot of source rows; artifact fingerprint taken BEFORE
     the snapshot.
  2. Derivation (metadata/units/scopes — reads local artifacts) happens INSIDE
     the guard: the artifact fingerprint is re-checked AFTER _derive and the
     publish only proceeds if both reads match the snapshot value (S4).
  3. Build identity = sha256(source fingerprint + recipe_id) → snapshot_id.
     The recipe version participates, so fixing scopes/metadata algorithms
     produces a NEW build — the "source unchanged ⇒ skip" path can never reuse
     a stale catalog (S5).
  4. corpus_runs stores snapshot_id and recipe_id; publish is serialized with
     pg_advisory_xact_lock and protected by a partial unique index (one active
     per workspace). Failures record status=failed and never touch the old
     active build.
  5. Verification covers unit/link/scope integrity AND link→chunk ownership:
     every linked chunk_id must exist in the source snapshot for the same
     doc/workspace (S4).

Historical original text is NOT promised: only locators and chunk ids are
stored; a changed source makes the catalog stale.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

import asyncpg

from env_rag_final.audit import identity as sid
from env_rag_final.audit import snapshot as snap

from . import scopes as scopes_mod
from . import units as units_mod
from .metadata import extract_document_metadata

# Gate 0 frozen source fingerprint.
FROZEN_SNAPSHOT = "95f7791fd84171ab727870fc5810d79b4327b0c4fa547d432951e0499a3808f8"

# S5: the catalog recipe participates in build identity. Bump on any change to
# metadata / scopes / units algorithms that should invalidate existing builds.
RECIPE_ID = "phase-1-v4-single-active-snapshot-prune"


class SourceChangedError(RuntimeError):
    """Raised when the live source fingerprint differs from the expected one."""


class BuildVerificationError(RuntimeError):
    """Raised when reference-integrity verification fails before publish."""


@dataclass
class BuildResult:
    snapshot_id: str
    fingerprint: str
    recipe_id: str
    published: bool
    docs: int
    units: int
    links: int
    scopes: int
    unlinked_block_refs: int
    warnings: list


def build_identity(source_fingerprint_value: str, recipe_id: str = RECIPE_ID) -> str:
    """snapshot_id binds BOTH the source snapshot and the catalog recipe."""
    return hashlib.sha256(
        json.dumps(
            {"source": source_fingerprint_value, "recipe": recipe_id}, sort_keys=True
        ).encode()
    ).hexdigest()[:16]


async def _live_source_fingerprint(conn: asyncpg.Connection, workspace: str = "default") -> str:
    """R4: recompute the composite source fingerprint from live rows — used by
    enumeration entries to verify the source still matches the active build."""
    from env_rag_final.audit import identity as _sid
    from env_rag_final.audit import snapshot as _snap

    rows = await _collect_rows(conn, workspace)
    return snap.source_snapshot_fingerprint(
        _snap.fingerprint_docs(rows["docs"]),
        _snap.fingerprint_chunks(rows["chunks"]),
        _snap.fingerprint_status(rows["statuses"]),
        _snap.fingerprint_artifacts(_sid.PARSED_ROOT),
        _snap.chunking_params(rows["docs"]),
    )["value"]


async def _collect_rows(conn: asyncpg.Connection, workspace: str = "default") -> dict:
    return {
        "docs": await conn.fetch(
            """SELECT id, doc_name, content, content_hash, meta, sidecar_location,
                      parse_format, parse_engine, chunk_options
               FROM public.lightrag_doc_full WHERE workspace=$1 ORDER BY id""",
            workspace,
        ),
        "chunks": await conn.fetch(
            """SELECT id, full_doc_id, chunk_order_index, tokens, content, heading, sidecar
               FROM public.lightrag_doc_chunks WHERE workspace=$1
               ORDER BY full_doc_id, chunk_order_index""",
            workspace,
        ),
        "statuses": await conn.fetch(
            """SELECT id, status, chunks_count, error_msg FROM public.lightrag_doc_status
               WHERE workspace=$1""",
            workspace,
        ),
    }


async def _source_fingerprint(rows: dict, parsed_root: Path) -> str:
    return snap.source_snapshot_fingerprint(
        snap.fingerprint_docs(rows["docs"]),
        snap.fingerprint_chunks(rows["chunks"]),
        snap.fingerprint_status(rows["statuses"]),
        snap.fingerprint_artifacts(parsed_root),
        snap.chunking_params(rows["docs"]),
    )["value"]


async def build_catalog(
    conn: asyncpg.Connection,
    *,
    expected_fingerprint: str = FROZEN_SNAPSHOT,
    parsed_root: Path | None = None,
    workspace: str = "default",
    force: bool = False,
) -> BuildResult:
    """Serialize the whole build, including staging writes and pruning."""
    await conn.execute(
        "SELECT pg_advisory_lock(hashtext('env_rag_publish'), hashtext($1))", workspace
    )
    try:
        return await _build_catalog_locked(
            conn,
            expected_fingerprint=expected_fingerprint,
            parsed_root=parsed_root,
            workspace=workspace,
            force=force,
        )
    finally:
        await conn.execute(
            "SELECT pg_advisory_unlock(hashtext('env_rag_publish'), hashtext($1))", workspace
        )


async def _build_catalog_locked(
    conn: asyncpg.Connection,
    *,
    expected_fingerprint: str,
    parsed_root: Path | None,
    workspace: str,
    force: bool,
) -> BuildResult:
    """Build and publish the catalog from a guarded source snapshot."""
    parsed_root = parsed_root or sid.PARSED_ROOT
    warnings: list = []

    # ---- 1. guard BEFORE snapshot ----------------------------------------
    fp_before = snap.fingerprint_artifacts(parsed_root)

    # ---- 2. one REPEATABLE READ source snapshot ---------------------------
    async with conn.transaction(readonly=True, isolation="repeatable_read"):
        await conn.execute("SET LOCAL statement_timeout = 60000")
        rows = await _collect_rows(conn, workspace)
    live_fp = await _source_fingerprint(rows, parsed_root)
    if live_fp != expected_fingerprint:
        raise SourceChangedError(
            "live source fingerprint differs from expected; refusing to build a stale catalog "
            f"(expected={expected_fingerprint[:16]}, live={live_fp[:16]})"
        )

    snap_id = build_identity(live_fp)

    # ---- 3. derive INSIDE the artifact guard (S4) -------------------------
    # _derive reads local parsed artifacts; after it returns the fingerprint is
    # re-checked. Publishing only proceeds when the artifacts consumed are the
    # same bytes that were fingerprinted into the snapshot.
    try:
        doc_rows, unit_rows, link_rows, scope_rows, warnings = _derive(
            rows, snap_id, parsed_root, workspace
        )
    finally:
        pass
    fp_after = snap.fingerprint_artifacts(parsed_root)
    if fp_after != fp_before:
        raise SourceChangedError(
            "parsed artifacts changed during derivation "
            f"(before={fp_before[:12]}, after={fp_after[:12]}); build aborted, nothing published"
        )

    # ---- 4. idempotency on (source, recipe) — and only when published ------
    existing = await conn.fetchrow(
        """SELECT run_id, status FROM env_rag.corpus_runs
           WHERE snapshot_id=$1 AND workspace=$2 ORDER BY started_at DESC LIMIT 1""",
        snap_id,
        workspace,
    )
    if existing and existing["status"] == "active" and not force:
        return BuildResult(
            snapshot_id=snap_id,
            fingerprint=live_fp,
            recipe_id=RECIPE_ID,
            published=True,
            docs=-1,
            units=-1,
            links=-1,
            scopes=-1,
            unlinked_block_refs=0,
            warnings=["identical (source, recipe) already active; build skipped (idempotent)"],
        )

    run_id = uuid.uuid4().hex[:16]
    async with conn.transaction():
        await conn.execute(
            """INSERT INTO env_rag.corpus_runs
                   (run_id, recipe_id, source_fingerprint, snapshot_id, workspace, status)
               VALUES ($1, $2, $3, $4, $5, 'building')""",
            run_id,
            RECIPE_ID,
            json.dumps({"value": live_fp}, ensure_ascii=False),
            snap_id,
            workspace,
        )

    try:
        # ---- 5. write catalog rows ----------------------------------------
        async with conn.transaction():
            await conn.executemany(
                """INSERT INTO env_rag.documents (workspace, doc_id, snapshot_id, doc_name, title,
                       title_confidence, self_code, self_code_version, referenced_codes, doc_type,
                       publish_date, implement_date, stats_period, unknown_fields, field_provenance,
                       source_fingerprint)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11,$12,$13,$14::jsonb,$15::jsonb,$16)
                   ON CONFLICT (workspace, doc_id, snapshot_id) DO NOTHING""",
                [
                    (
                        d["workspace"],
                        d["doc_id"],
                        d["snapshot_id"],
                        d["doc_name"],
                        d["title"],
                        d["title_confidence"],
                        d["self_code"],
                        d["self_code_version"],
                        json.dumps(d["referenced_codes"], ensure_ascii=False),
                        d["doc_type"],
                        d["publish_date"],
                        d["implement_date"],
                        d["stats_period"],
                        json.dumps(d["unknown_fields"], ensure_ascii=False),
                        json.dumps(d["field_provenance"], ensure_ascii=False),
                        live_fp,
                    )
                    for d in doc_rows
                ],
            )
            await conn.executemany(
                """INSERT INTO env_rag.source_units (workspace, doc_id, snapshot_id, unit_id,
                       unit_kind, unit_order, heading, parent_headings, level, caption, table_seq,
                       dimension, content_length, requires_span, locator)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,$10,$11,$12::jsonb,$13,$14,$15::jsonb)
                   ON CONFLICT DO NOTHING""",
                [
                    (
                        u["workspace"],
                        u["doc_id"],
                        u["snapshot_id"],
                        u["unit_id"],
                        u["unit_kind"],
                        u["unit_order"],
                        u["heading"],
                        u["parent_headings"]
                        if isinstance(u["parent_headings"], str)
                        else json.dumps(u["parent_headings"], ensure_ascii=False),
                        u["level"],
                        u["caption"],
                        u["table_seq"],
                        u["dimension"],
                        u["content_length"],
                        u["requires_span"],
                        u["locator"]
                        if isinstance(u["locator"], str)
                        else json.dumps(u["locator"], ensure_ascii=False),
                    )
                    for u in unit_rows
                ],
            )
            await conn.executemany(
                """INSERT INTO env_rag.unit_chunk_links (workspace, doc_id, snapshot_id, unit_id,
                       chunk_id, chunk_order, match_basis, coverage_status)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT DO NOTHING""",
                [
                    (
                        lk["workspace"],
                        lk["doc_id"],
                        lk["snapshot_id"],
                        lk["unit_id"],
                        lk["chunk_id"],
                        lk["chunk_order"],
                        lk["match_basis"],
                        lk["coverage_status"],
                    )
                    for lk in link_rows
                ],
            )
            await conn.executemany(
                """INSERT INTO env_rag.scopes (workspace, doc_id, snapshot_id, scope_id, scope_kind,
                       parent_scope_id, title, number, confirm_status, note)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT DO NOTHING""",
                [
                    (
                        s["workspace"],
                        s["doc_id"],
                        s["snapshot_id"],
                        s["scope_id"],
                        s["scope_kind"],
                        s["parent_scope_id"],
                        s["title"],
                        s["number"],
                        s["confirm_status"],
                        s["note"],
                    )
                    for s in scope_rows
                ],
            )
            await conn.executemany(
                """INSERT INTO env_rag.scope_units (workspace, doc_id, snapshot_id, scope_id, unit_id, seq)
                   VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT DO NOTHING""",
                [
                    (s["workspace"], s["doc_id"], s["snapshot_id"], s["scope_id"], uid, i)
                    for s in scope_rows
                    for i, uid in enumerate(s["_members"])
                ],
            )

        # ---- 6. verify integrity incl. link→chunk ownership (S4) -----------
        await _verify(conn, snap_id, workspace, rows)

        # ---- 7. serialized atomic publish ----------------------------------
        await _publish(conn, run_id, snap_id, workspace)
    except BaseException as exc:
        async with conn.transaction():
            await conn.execute(
                """UPDATE env_rag.corpus_runs SET status='failed', finished_at=now(), note=$2
                   WHERE run_id=$1""",
                run_id,
                f"{type(exc).__name__}",
            )
        raise

    return BuildResult(
        snapshot_id=snap_id,
        fingerprint=live_fp,
        recipe_id=RECIPE_ID,
        published=True,
        docs=len(doc_rows),
        units=len(unit_rows),
        links=len(link_rows),
        scopes=len(scope_rows),
        unlinked_block_refs=0,
        warnings=warnings,
    )


async def _publish(conn, run_id: str, snapshot_id: str, workspace: str) -> None:
    """Serialize activation and pruning in one rollback-safe transaction."""
    async with conn.transaction():
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext('env_rag_publish'), hashtext($1))",
            workspace,
        )
        await conn.execute(
            "UPDATE env_rag.corpus_runs SET status='retired' WHERE workspace=$1 AND status='active'",
            workspace,
        )
        await conn.execute(
            """UPDATE env_rag.corpus_runs SET status='active', finished_at=now()
               WHERE run_id=$1""",
            run_id,
        )
        # Every deletion is under the same publisher lock and transaction.
        # A failure restores both the old active pointer and its directory.
        for table in ("unit_chunk_links", "scope_units", "source_units", "scopes", "documents"):
            await conn.execute(
                f"DELETE FROM env_rag.{table} WHERE workspace=$1 AND snapshot_id<>$2",
                workspace,
                snapshot_id,
            )


def _derive(
    rows: dict, snap_id: str, parsed_root: Path, workspace: str
) -> tuple[list, list, list, list, list]:
    doc_rows: list = []
    unit_rows: list = []
    link_rows: list = []
    scope_rows: list = []
    warnings: list = []
    chunks_by_doc: dict[str, list] = {}
    for c in rows["chunks"]:
        chunks_by_doc.setdefault(c["full_doc_id"], []).append(c)
    known_chunk_ids = {c["id"] for c in rows["chunks"]}

    missing_sources = 0
    for d in rows["docs"]:
        doc_id, doc_name = d["id"], d["doc_name"]
        meta_rec = extract_document_metadata(doc_name, d["content"])
        doc_rows.append(
            {
                "workspace": workspace,
                "doc_id": doc_id,
                "snapshot_id": snap_id,
                "doc_name": doc_name,
                **meta_rec,
            }
        )
        pdir = units_mod.sidecar_dir_for(d["sidecar_location"], doc_name)
        if not pdir.exists():
            # S4: missing source is recorded and later blocks publication — a
            # catalog claiming full coverage with silent skips is not allowed.
            missing_sources += 1
            warnings.append({"doc_id": doc_id, "warning": "parsed dir missing; units skipped"})
            continue
        try:
            _meta, blocks = units_mod.parse_blocks(pdir)
        except FileNotFoundError:
            missing_sources += 1
            warnings.append({"doc_id": doc_id, "warning": "no blocks.jsonl; units skipped"})
            continue
        us, ls = units_mod.build_units_and_links(
            doc_id, doc_name, snap_id, chunks_by_doc.get(doc_id, []), pdir
        )
        # S4: only links whose chunk actually exists in this source snapshot
        ls = [lk for lk in ls if lk["chunk_id"] in known_chunk_ids]
        unit_rows.extend(us)
        link_rows.extend(ls)

        chunk_link_counts: dict[str, int] = {}
        for lk in ls:
            chunk_link_counts[lk["unit_id"]] = chunk_link_counts.get(lk["unit_id"], 0) + 1

        scopes = scopes_mod.build_scopes(doc_id, snap_id, blocks)
        # S2: persist span requirements (requires_span) instead of warnings only
        for sc in scopes_mod.persist_span_requirements(
            doc_id, snap_id, blocks, scopes, chunk_link_counts
        ):
            warnings.append(
                {
                    "doc_id": doc_id,
                    "scope_id": sc["scope_id"],
                    "status": sc["confirm_status"],
                    "note": sc["note"],
                }
            )
        scope_rows.extend(scopes)
        # mark units that belong to requires_span scopes
        span_scope_units = {
            uid
            for sc in scopes
            if sc["confirm_status"] == "requires_span"
            for uid in sc["_members"]
        }
        for u in unit_rows:
            if u["unit_id"] in span_scope_units:
                u["requires_span"] = True

    if missing_sources:
        raise BuildVerificationError(
            f"{missing_sources} document(s) have no readable parsed source; refusing to publish "
            "a 'complete' catalog with silent gaps (drop the docs or fix sources first)"
        )
    return doc_rows, unit_rows, link_rows, scope_rows, warnings


async def _verify(conn: asyncpg.Connection, snap_id: str, workspace: str, rows: dict) -> None:
    """Integrity: unit/scope references resolve; every linked chunk exists in
    the source snapshot for the same doc and workspace (S4)."""
    orphan_links = await conn.fetchval(
        """SELECT count(*) FROM env_rag.unit_chunk_links l
           WHERE l.snapshot_id=$1 AND NOT EXISTS (
             SELECT 1 FROM env_rag.source_units u
             WHERE u.workspace=l.workspace AND u.doc_id=l.doc_id
               AND u.snapshot_id=l.snapshot_id AND u.unit_id=l.unit_id)""",
        snap_id,
    )
    orphan_members = await conn.fetchval(
        """SELECT count(*) FROM env_rag.scope_units su
           WHERE su.snapshot_id=$1 AND NOT EXISTS (
             SELECT 1 FROM env_rag.source_units u
             WHERE u.workspace=su.workspace AND u.doc_id=su.doc_id
               AND u.snapshot_id=su.snapshot_id AND u.unit_id=su.unit_id)""",
        snap_id,
    )
    dangling_scope = await conn.fetchval(
        """SELECT count(*) FROM env_rag.scope_units su
           WHERE su.snapshot_id=$1 AND NOT EXISTS (
             SELECT 1 FROM env_rag.scopes s
             WHERE s.workspace=su.workspace AND s.doc_id=su.doc_id
               AND s.snapshot_id=su.snapshot_id AND s.scope_id=su.scope_id)""",
        snap_id,
    )
    # link→chunk ownership: chunk must exist in the snapshot under the same doc
    known = {(c["id"], c["full_doc_id"]) for c in rows["chunks"]}
    bad_chunk = 0
    for lk in await conn.fetch(
        """SELECT unit_id, chunk_id, doc_id FROM env_rag.unit_chunk_links
           WHERE snapshot_id=$1""",
        snap_id,
    ):
        if (lk["chunk_id"], lk["doc_id"]) not in known:
            bad_chunk += 1
    if orphan_links or orphan_members or dangling_scope or bad_chunk:
        raise BuildVerificationError(
            f"reference integrity failed: orphan_links={orphan_links}, "
            f"orphan_scope_members={orphan_members}, dangling_scope_rows={dangling_scope}, "
            f"links_to_unknown_chunks={bad_chunk}"
        )


async def active_snapshot(conn: asyncpg.Connection, workspace: str = "default") -> dict | None:
    row = await conn.fetchrow(
        """SELECT run_id, recipe_id, snapshot_id, source_fingerprint, finished_at
           FROM env_rag.corpus_runs WHERE workspace=$1 AND status='active'""",
        workspace,
    )
    return dict(row) if row else None


async def check_stale(
    conn: asyncpg.Connection, parsed_root: Path | None = None, workspace: str = "default"
) -> dict:
    """Compare live source fingerprint AND recipe against the active build."""
    parsed_root = parsed_root or sid.PARSED_ROOT
    active = await active_snapshot(conn, workspace)
    if active is None:
        return {"state": "no-active-build"}
    async with conn.transaction(readonly=True):
        rows = await _collect_rows(conn, workspace)
    live_fp = await _source_fingerprint(rows, parsed_root)
    raw_fp = active["source_fingerprint"]
    if isinstance(raw_fp, str):
        raw_fp = json.loads(raw_fp) if raw_fp else {}
    stored = (raw_fp or {}).get("value")
    recipe_current = active["recipe_id"] == RECIPE_ID
    if live_fp == stored and recipe_current:
        state, action = "current", ""
    elif live_fp != stored and not recipe_current:
        state = "stale"
        action = "source changed AND recipe outdated; rebuild required"
    elif not recipe_current:
        state = "recipe-outdated"
        action = "catalog recipe changed; rebuild required (old build must not be reused)"
    else:
        state = "stale"
        action = "source changed; rebuild required; old locators must not be used"
    return {
        "state": state,
        "active_run_id": active["run_id"],
        "active_snapshot_id": active["snapshot_id"],
        "recipe_id": active["recipe_id"],
        "expected_recipe_id": RECIPE_ID,
        "live_fingerprint": live_fp,
        "stored_fingerprint": stored,
        "action": action,
    }
