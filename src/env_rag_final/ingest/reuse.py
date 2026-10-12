"""Reuse of already-computed chunk-level extraction results.

The existing ``default`` workspace already holds content-addressed entity /
relationship extractions for every corpus chunk (``lightrag_llm_cache`` rows
of type ``extract``, keyed by a hash of the extraction prompt and carrying the
owning ``chunk_id``).

Because a document reproduces byte-identical chunks in a new workspace (same
document id, same text, same chunker), the extraction prompt — and therefore
the cache key — is identical too.  LightRAG's cache lookup is keyed by
``{workspace}:{cache_type}:{hash}`` and the store is partitioned by workspace,
so copying the rows with the workspace prefix rewritten makes the new
workspace's pipeline hit its own cache and issue **zero** extraction calls.

Every copied row is recorded so the run can report reuse honestly instead of
claiming a fresh extraction.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

CACHE_TABLE = "public.lightrag_llm_cache"


@dataclass
class ReuseResult:
    workspace: str
    source_workspace: str
    rows_available: int
    rows_copied: int
    chunk_ids: int

    def as_dict(self) -> dict:
        return dict(self.__dict__)


async def chunk_ids_for_doc(conn, workspace: str, doc_id: str) -> list[str]:
    rows = await conn.fetch(
        "select id from public.lightrag_doc_chunks where workspace=$1 and full_doc_id=$2",
        workspace,
        doc_id,
    )
    return [r["id"] for r in rows]


async def seed_extract_cache(
    conn,
    *,
    source_workspace: str,
    target_workspace: str,
    chunk_ids: list[str],
    cache_type: str = "extract",
    chunk_ids_for_summary: list[str] | None = None,
) -> ReuseResult:
    """Copy content-addressed cache rows into ``target_workspace``.

    ``extract`` rows are selected by ``chunk_id`` (exact per-chunk reuse).
    ``summary`` rows are workspace-merge dependent and are therefore *not*
    copied — a fresh summary is a legitimate per-workspace product, and
    copying one could misattribute another workspace's merged description.
    """
    if not chunk_ids:
        return ReuseResult(target_workspace, source_workspace, 0, 0, 0)

    available = await conn.fetchval(
        f"select count(*) from {CACHE_TABLE} "
        "where workspace=$1::varchar and cache_type=$2::varchar and chunk_id = any($3::varchar[])",
        source_workspace,
        cache_type,
        chunk_ids,
    )
    # The key is copied VERBATIM.  LightRAG's extraction cache key is
    # ``{mode}:{cache_type}:{hash}`` where ``mode`` is the constant "default"
    # for entity extraction (``handle_cache`` treats mode=="default" as the
    # extraction case), so the key does not carry the workspace; isolation
    # comes from the (workspace, id) primary key of the cache store.  The same
    # chunk therefore has the same cache key in every workspace, and copying
    # the row unchanged is what makes the new workspace's pipeline a cache hit.
    copied = await conn.execute(
        f"""
        insert into {CACHE_TABLE}
               (workspace, id, original_prompt, return_value, chunk_id, cache_type, queryparam)
        select $2::varchar,
               id, original_prompt, return_value, chunk_id, cache_type, queryparam
          from {CACHE_TABLE}
         where workspace=$1::varchar and cache_type=$3::varchar
           and chunk_id = any($4::varchar[])
        on conflict (workspace, id) do nothing
        """,
        source_workspace,
        target_workspace,
        cache_type,
        chunk_ids,
    )
    copied_n = int(str(copied).split()[-1]) if copied and str(copied).split() else 0
    return ReuseResult(
        workspace=target_workspace,
        source_workspace=source_workspace,
        rows_available=int(available or 0),
        rows_copied=copied_n,
        chunk_ids=len(chunk_ids),
    )


async def cache_rows_for_doc(conn, workspace: str, chunk_ids: list[str]) -> tuple[int, int]:
    """Return ``(extract_rows, fresh_rows)`` for the given chunks.

    ``fresh`` means rows created during this run rather than copied from the
    source workspace; the caller distinguishes them by capture time.
    """
    if not chunk_ids:
        return 0, 0
    total = await conn.fetchval(
        f"select count(*) from {CACHE_TABLE} where workspace=$1 and cache_type='extract' and chunk_id = any($2::varchar[])",
        workspace,
        chunk_ids,
    )
    return int(total or 0), 0


def reuse_note(result: ReuseResult) -> str:
    return json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True)
