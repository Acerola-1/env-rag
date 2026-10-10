"""Search index builder (task 4.2, corrected per Gate 2 G2-3/G2-4).

Index identity = (catalog snapshot, source fingerprint, tokenizer version,
vocab SHA, index recipe, CLEAN_VERSION). Any change produces a NEW build; the
old build's rows are pruned in the same atomic publish that flips the active
pointer, so a tokenizer/vocab/cleaning upgrade can never silently reuse the
old index.

Gate 2 corrections:
- G2-3: the COMPLETE source fingerprint is verified around the whole window —
  before the source snapshot, after derivation (before any publish), and the
  artifact/vocab/tokenizer/clean identity is re-checked at publish time. A
  change aborts the build and the previous active build stays intact.
- G2-4: table captions are attached to the chunks that actually carry the
  table fragment (via the audited ``unit_chunk_links``), never copied to every
  chunk of the document. Document-level caption/title/code signals live in the
  document row (weight A), so a chunk hit for "表 6" only comes from a chunk
  that really contains table 6 or is linked to it.
- the ledger INSERT for a same-identity retry (failed row or ``--force``) is
  conflict-safe: the old row is replaced under the same lock, so a retry can
  never crash on the primary key, and a failure never touches the old active
  build.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import asyncpg

from . import clean
from . import tokenizer as tk

INDEX_RECIPE = "phase-2-v2-local-caption-identity-guard"

WEIGHTS = {"A": {"title", "doc_name", "self_code"}, "B": {"heading", "caption"}, "C": {"body"}}


def index_identity(
    catalog_snapshot_id: str,
    source_fingerprint: str,
    tokenizer_version: str = tk.VERSION,
    vocab_sha: str | None = None,
    index_recipe: str = INDEX_RECIPE,
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "catalog": catalog_snapshot_id,
                "source": source_fingerprint,
                "tokenizer": tokenizer_version,
                "vocab": vocab_sha or tk.vocab_sha(),
                "clean": clean.CLEAN_VERSION,
                "recipe": index_recipe,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()[:16]


@dataclass
class SearchBuildResult:
    search_id: str
    workspace: str
    catalog_snapshot_id: str
    docs_indexed: int
    chunks_indexed: int
    published: bool
    warnings: list
    tokenizer_version: str
    vocab_sha: str
    elapsed_ms: int


class SearchBuildError(RuntimeError):
    pass


def _doc_search_text(doc_name: str, title: str | None, self_code: str | None) -> str:
    parts = [doc_name or "", title or "", self_code or ""]
    return "\n".join(p for p in parts if p)


async def _captions_by_chunk(
    conn: asyncpg.Connection, workspace: str, catalog_snapshot_id: str
) -> dict[str, list[str]]:
    """Chunk id → captions of the table units actually linked to that chunk.

    Uses ONLY the audited ``unit_chunk_links`` (match basis recorded at catalog
    build). A chunk with no table links gets no caption — captions are never
    copied document-wide (G2-4).
    """
    rows = await conn.fetch(
        """SELECT l.chunk_id, u.caption, u.unit_id
           FROM env_rag.unit_chunk_links l
           JOIN env_rag.source_units u
             ON u.workspace = l.workspace AND u.doc_id = l.doc_id
            AND u.snapshot_id = l.snapshot_id AND u.unit_id = l.unit_id
           WHERE l.workspace=$1 AND l.snapshot_id=$2
             AND u.unit_kind='table' AND u.caption IS NOT NULL
           ORDER BY l.chunk_id, u.unit_id""",
        workspace,
        catalog_snapshot_id,
    )
    out: dict[str, list[str]] = {}
    for r in rows:
        caps = out.setdefault(r["chunk_id"], [])
        if r["caption"] not in caps:
            caps.append(r["caption"])
    return out


async def _captions_by_doc(
    conn: asyncpg.Connection, workspace: str, catalog_snapshot_id: str
) -> dict[str, list[str]]:
    """Document-level caption signal (name/title-level discovery only)."""
    rows = await conn.fetch(
        """SELECT doc_id, caption FROM env_rag.source_units
           WHERE workspace=$1 AND snapshot_id=$2 AND unit_kind='table'
             AND caption IS NOT NULL
           ORDER BY doc_id, unit_id""",
        workspace,
        catalog_snapshot_id,
    )
    out: dict[str, list[str]] = {}
    for r in rows:
        caps = out.setdefault(r["doc_id"], [])
        if r["caption"] not in caps:
            caps.append(r["caption"])
    return out


async def build_search_index(
    conn: asyncpg.Connection,
    *,
    workspace: str = "default",
    force: bool = False,
) -> SearchBuildResult:
    """Build + atomically publish the search index for the active catalog."""
    t0 = time.monotonic()
    await conn.execute(
        "SELECT pg_advisory_lock(hashtext('env_rag_search'), hashtext($1))", workspace
    )
    try:
        return await _build_locked(conn, workspace=workspace, force=force, t0=t0)
    finally:
        await conn.execute(
            "SELECT pg_advisory_unlock(hashtext('env_rag_search'), hashtext($1))", workspace
        )


async def _build_locked(
    conn: asyncpg.Connection, *, workspace: str, force: bool, t0: float
) -> SearchBuildResult:
    from env_rag_final.catalog.builder import FROZEN_SNAPSHOT, _live_source_fingerprint, check_stale

    stale = await check_stale(conn, workspace=workspace)
    if stale.get("state") != "current":
        raise SearchBuildError(
            f"catalog state={stale.get('state')} ({stale.get('action')}); "
            "build the catalog first — search index is derived from it"
        )
    catalog_snapshot_id = stale["active_snapshot_id"]
    source_fp = stale.get("stored_fingerprint") or FROZEN_SNAPSHOT

    search_id = index_identity(catalog_snapshot_id, source_fp)
    existing = await conn.fetchrow(
        """SELECT search_id, status FROM env_rag.search_builds
           WHERE workspace=$1 AND search_id=$2""",
        workspace,
        search_id,
    )
    if existing and existing["status"] == "active" and not force:
        return SearchBuildResult(
            search_id=search_id,
            workspace=workspace,
            catalog_snapshot_id=catalog_snapshot_id,
            docs_indexed=-1,
            chunks_indexed=-1,
            published=True,
            warnings=[
                "identical (source, catalog, tokenizer, vocab, clean) already active; skipped"
            ],
            tokenizer_version=tk.VERSION,
            vocab_sha=tk.vocab_sha(),
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

    warnings: list[str] = []

    # ---- source rows under one read-only snapshot -------------------------
    async with conn.transaction(readonly=True, isolation="repeatable_read"):
        await conn.execute("SET LOCAL statement_timeout = 600000")
        docs = await conn.fetch(
            """SELECT id, doc_name, content FROM public.lightrag_doc_full
               WHERE workspace=$1 ORDER BY id""",
            workspace,
        )
        chunks = await conn.fetch(
            """SELECT id, full_doc_id, chunk_order_index, content, heading
               FROM public.lightrag_doc_chunks WHERE workspace=$1
               ORDER BY full_doc_id, chunk_order_index""",
            workspace,
        )
    # G2-3: fingerprint BEFORE derivation
    fp_before = await _live_source_fingerprint(conn, workspace)
    if fp_before != source_fp:
        raise SearchBuildError(
            f"live source fingerprint differs from the active catalog's "
            f"(live={fp_before[:16]}, catalog={source_fp[:16]}); refusing to index a stale source"
        )

    meta = await conn.fetch(
        """SELECT doc_id, title, self_code, self_code_version, doc_name, doc_type
           FROM env_rag.documents WHERE workspace=$1 AND snapshot_id=$2""",
        workspace,
        catalog_snapshot_id,
    )
    meta_by_doc = {r["doc_id"]: r for r in meta}
    if len(meta_by_doc) != len(docs):
        raise SearchBuildError(
            f"catalog documents ({len(meta_by_doc)}) do not match source docs ({len(docs)}); "
            "catalog is not a complete projection of this workspace"
        )

    caps_by_chunk = await _captions_by_chunk(conn, workspace, catalog_snapshot_id)
    caps_by_doc = await _captions_by_doc(conn, workspace, catalog_snapshot_id)

    # ---- prepare ledger row (conflict-safe for retry / --force) -----------
    # The row for one identity records that identity's CURRENT state, so a
    # rebuild of an already-active identity must NOT clobber it while the old
    # index is still serving: it keeps status='active' until the new attempt
    # publishes (and a failed attempt restores exactly the prior state).
    run_id = uuid.uuid4().hex[:16]
    prior = await conn.fetchrow(
        """SELECT search_id, status FROM env_rag.search_builds
           WHERE workspace=$1 AND search_id=$2""",
        workspace,
        search_id,
    )
    prior_status = prior["status"] if prior else None
    async with conn.transaction():
        if prior_status == "active":
            await conn.execute(
                """UPDATE env_rag.search_builds
                   SET note=$3, started_at=now(), finished_at=NULL
                   WHERE workspace=$1 AND search_id=$2""",
                workspace,
                search_id,
                json.dumps({"run_id": run_id, "attempt": "force-rebuild (old index stays active)"}),
            )
        else:
            await conn.execute(
                """INSERT INTO env_rag.search_builds
                       (search_id, workspace, catalog_snapshot_id, source_fingerprint,
                        tokenizer_version, vocab_sha, index_recipe, status, note)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,'building',$8)
                   ON CONFLICT (search_id) DO UPDATE
                       SET status='building', started_at=now(), finished_at=NULL,
                           source_fingerprint=EXCLUDED.source_fingerprint,
                           note=EXCLUDED.note""",
                search_id,
                workspace,
                catalog_snapshot_id,
                source_fp,
                tk.VERSION,
                tk.vocab_sha(),
                INDEX_RECIPE,
                json.dumps({"run_id": run_id, "attempt": "initial"}),
            )

    try:
        # ---- derive rows ---------------------------------------------------
        # Index side uses OUR tokenizer in INDEX mode (search superset:
        # jieba.cut_for_search) — every query-side maximal word assigned to a
        # phrase is present in the index, so a query term is never missing
        # merely because the index split it differently.
        doc_rows = []
        for d in docs:
            m = meta_by_doc[d["id"]]
            text = _doc_search_text(m["doc_name"], m["title"], m["self_code"])
            doc_caps = " ".join(caps_by_doc.get(d["id"], []))
            doc_rows.append(
                (
                    workspace,
                    d["id"],
                    catalog_snapshot_id,
                    search_id,
                    m["doc_name"],
                    m["title"],
                    m["self_code"],
                    m["self_code_version"],
                    m["doc_type"],
                    text,
                    tk.tokens_text(" ".join(p for p in (text, doc_caps) if p), mode="index"),
                )
            )
        chunk_rows = []
        for c in chunks:
            head = clean.heading_text(c["heading"])
            # G2-4: captions ONLY from the chunks this table is actually linked
            # to — no document-wide caption copying.
            caps = " ".join(caps_by_chunk.get(c["id"], []))
            body = clean.clean_markup(c["content"])
            hc_tokens = tk.tokens_text(" ".join(p for p in (head, caps) if p), mode="index")
            body_tokens = tk.tokens_text(body, mode="index")
            chunk_rows.append(
                (
                    workspace,
                    c["full_doc_id"],
                    catalog_snapshot_id,
                    search_id,
                    c["id"],
                    c["chunk_order_index"],
                    head,
                    caps,
                    "\n".join(p for p in (head, caps, body) if p),
                    hc_tokens,
                    body_tokens,
                )
            )

        # G2-3: fingerprint AFTER derivation, BEFORE writing/publishing
        fp_after = await _live_source_fingerprint(conn, workspace)
        if fp_after != fp_before:
            raise SearchBuildError(
                "source changed during search-index derivation "
                f"({fp_before[:12]} -> {fp_after[:12]}); build aborted, nothing published"
            )

        async with conn.transaction():
            await conn.executemany(
                """INSERT INTO env_rag.search_documents
                       (workspace, doc_id, snapshot_id, search_id, doc_name, title,
                        self_code, self_code_version, doc_type, search_text, tsv)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
                           setweight(to_tsvector('simple', $11), 'A'))
                   ON CONFLICT DO NOTHING""",
                doc_rows,
            )
            await conn.executemany(
                """INSERT INTO env_rag.search_chunks
                       (workspace, doc_id, snapshot_id, search_id, chunk_id, chunk_order,
                        heading, captions, search_text, tsv)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,
                           setweight(to_tsvector('simple', $10), 'B') ||
                           setweight(to_tsvector('simple', $11), 'C'))
                   ON CONFLICT DO NOTHING""",
                chunk_rows,
            )

        # ---- verify --------------------------------------------------------
        n_docs = await conn.fetchval(
            """SELECT count(*) FROM env_rag.search_documents
               WHERE workspace=$1 AND search_id=$2""",
            workspace,
            search_id,
        )
        n_chunks = await conn.fetchval(
            """SELECT count(*) FROM env_rag.search_chunks WHERE workspace=$1 AND search_id=$2""",
            workspace,
            search_id,
        )
        if n_docs != len(doc_rows) or n_chunks != len(chunk_rows):
            raise SearchBuildError(
                f"indexed rows mismatch: docs {n_docs}/{len(doc_rows)}, "
                f"chunks {n_chunks}/{len(chunk_rows)}"
            )
        empty_tsv = await conn.fetchval(
            """SELECT count(*) FROM env_rag.search_chunks
               WHERE workspace=$1 AND search_id=$2 AND tsv = ''::tsvector""",
            workspace,
            search_id,
        )
        if empty_tsv:
            warnings.append(f"{empty_tsv} chunk row(s) produced an empty tsvector")

        # ---- atomic publish ------------------------------------------------
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext('env_rag_search'), hashtext($1))",
                workspace,
            )
            # G2-3: the identity that was derived is re-checked at publish
            # time — the catalog must still be the one this build derives from.
            still = await check_stale(conn, workspace=workspace)
            if still.get("state") != "current" or still.get("active_snapshot_id") != (
                catalog_snapshot_id
            ):
                raise SearchBuildError(
                    "catalog changed while the search index was being built; "
                    "refusing to publish a stale index (old active build untouched)"
                )
            await conn.execute(
                """UPDATE env_rag.search_builds SET status='retired'
                   WHERE workspace=$1 AND status='active'""",
                workspace,
            )
            await conn.execute(
                """UPDATE env_rag.search_builds SET status='active', finished_at=now(),
                          note=$3
                   WHERE search_id=$1 AND workspace=$2""",
                search_id,
                workspace,
                json.dumps({"run_id": run_id, "warnings": warnings[:5]}, ensure_ascii=False),
            )
            await conn.execute(
                """DELETE FROM env_rag.search_documents
                   WHERE workspace=$1 AND search_id<>$2""",
                workspace,
                search_id,
            )
            await conn.execute(
                "DELETE FROM env_rag.search_chunks WHERE workspace=$1 AND search_id<>$2",
                workspace,
                search_id,
            )
    except BaseException as exc:
        async with conn.transaction():
            if prior_status == "active":
                # the old index is still the active one; just record the failed
                # attempt in the note — never downgrade the live row
                await conn.execute(
                    """UPDATE env_rag.search_builds
                       SET note=$3
                       WHERE search_id=$1 AND workspace=$2""",
                    search_id,
                    workspace,
                    json.dumps(
                        {"run_id": run_id, "rebuild_failed": type(exc).__name__, "prior": "active"}
                    ),
                )
            else:
                await conn.execute(
                    """UPDATE env_rag.search_builds
                       SET status='failed', finished_at=now(), note=$3
                       WHERE search_id=$1 AND workspace=$2""",
                    search_id,
                    workspace,
                    type(exc).__name__,
                )
        raise

    return SearchBuildResult(
        search_id=search_id,
        workspace=workspace,
        catalog_snapshot_id=catalog_snapshot_id,
        docs_indexed=len(doc_rows),
        chunks_indexed=len(chunk_rows),
        published=True,
        warnings=warnings,
        tokenizer_version=tk.VERSION,
        vocab_sha=tk.vocab_sha(),
        elapsed_ms=int((time.monotonic() - t0) * 1000),
    )


async def active_search_build(conn: asyncpg.Connection, workspace: str = "default") -> dict | None:
    row = await conn.fetchrow(
        """SELECT search_id, catalog_snapshot_id, source_fingerprint, tokenizer_version,
                  vocab_sha, index_recipe, finished_at
           FROM env_rag.search_builds WHERE workspace=$1 AND status='active'""",
        workspace,
    )
    return dict(row) if row else None


async def check_search_stale(
    conn: asyncpg.Connection, workspace: str = "default", parsed_root: Path | None = None
) -> dict:
    """Search index vs catalog vs live source vs tokenizer/vocab/clean identity."""
    from env_rag_final.catalog.builder import check_stale

    cat = await check_stale(conn, parsed_root=parsed_root, workspace=workspace)
    active = await active_search_build(conn, workspace)
    if active is None:
        return {"state": "no-active-search", "catalog_state": cat.get("state")}
    reasons = []
    if cat.get("state") != "current":
        reasons.append(f"catalog={cat.get('state')}")
    elif cat.get("active_snapshot_id") != active["catalog_snapshot_id"]:
        reasons.append("catalog snapshot replaced")
    if active["tokenizer_version"] != tk.VERSION:
        reasons.append(f"tokenizer changed ({active['tokenizer_version']} -> {tk.VERSION})")
    if active["vocab_sha"] != tk.vocab_sha():
        reasons.append("vocabulary changed")
    if active["index_recipe"] != INDEX_RECIPE:
        reasons.append("index recipe changed")
    # G2-3: the cleaning algorithm participates in identity — an active build
    # whose search_id does not match the CURRENT identity is stale.
    expected_id = index_identity(
        active["catalog_snapshot_id"],
        active["source_fingerprint"],
        tokenizer_version=tk.VERSION,
        vocab_sha=tk.vocab_sha(),
        index_recipe=INDEX_RECIPE,
    )
    if active["search_id"] != expected_id:
        reasons.append(
            f"index identity changed ({active['search_id']} -> {expected_id}); "
            "cleaning/tokenizer/vocab/recipe upgrade requires a rebuild"
        )
    state = "current" if not reasons else "stale"
    return {
        "state": state,
        "search_id": active["search_id"],
        "catalog_snapshot_id": active["catalog_snapshot_id"],
        "source_fingerprint": active["source_fingerprint"],
        "tokenizer_version": active["tokenizer_version"],
        "vocab_sha": active["vocab_sha"],
        "index_recipe": active["index_recipe"],
        "expected_search_id": expected_id,
        "reasons": reasons,
    }
