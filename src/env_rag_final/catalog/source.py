"""Read-only adapter over ``public.lightrag_*`` (task 2.2, corrected per S6).

Corrected behaviors:
- Identity is always the composite key (workspace, id). Lookup first filters by
  the requested workspace; cross-workspace diagnosis happens ONLY after the
  target composite is absent. Two workspaces holding the same doc_id both
  resolve correctly.
- One method call = one connection + one READ ONLY REPEATABLE READ snapshot:
  total, order validation and page rows all come from the same snapshot, and a
  ``snapshot_epoch`` is returned so callers can detect a source change between
  pages (epoch differs → stale, refuse to continue).
- Order validation covers NULL/negative, duplicates AND gaps in 0..n-1.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import asyncpg


class SourceNotFoundError(LookupError):
    pass


class CrossWorkspaceError(ValueError):
    """The id exists but only under a different workspace."""


class OrderAnomalyError(ValueError):
    """NULL/negative order, duplicates, or gaps in 0..n-1."""


class SourceChangedError(RuntimeError):
    """The source epoch changed between/within a paginated read."""


@dataclass(frozen=True)
class ChunkPage:
    workspace: str
    doc_id: str
    chunks: list
    total: int
    offset: int
    limit: int
    snapshot_epoch: str  # snapshot id of this page; differing across pages ⇒ stale


class SourceAdapter:
    """Read-only access to existing LightRAG tables with snapshot-bound reads."""

    def __init__(self, dsn_kwargs: dict):
        self._dsn = dict(dsn_kwargs, statement_cache_size=0, timeout=15)

    async def _session(self):
        return await asyncpg.connect(**self._dsn)

    async def _read_one(self, stmt: str, *args, fetch="val"):
        """Single-statement helper for simple checks (own connection)."""
        conn = await self._session()
        try:
            async with conn.transaction(readonly=True, isolation="repeatable_read"):
                await conn.execute("SET LOCAL statement_timeout = 30000")
                if fetch == "val":
                    return await conn.fetchval(stmt, *args)
                if fetch == "row":
                    return await conn.fetchrow(stmt, *args)
                return await conn.fetch(stmt, *args)
        finally:
            await conn.close()

    @staticmethod
    async def _content_epoch(conn, workspace: str, doc_id: str) -> str:
        """A document source version, independent of the reading transaction."""
        doc = await conn.fetchrow(
            """SELECT id, doc_name, content, content_hash, chunk_options
               FROM public.lightrag_doc_full WHERE workspace=$1 AND id=$2""",
            workspace,
            doc_id,
        )
        chunks = await conn.fetch(
            """SELECT id, full_doc_id, chunk_order_index, tokens, content, heading, sidecar
               FROM public.lightrag_doc_chunks WHERE workspace=$1 AND full_doc_id=$2
               ORDER BY chunk_order_index, id""",
            workspace,
            doc_id,
        )
        payload = {
            "workspace": workspace,
            "doc_id": doc_id,
            "document": dict(doc) if doc is not None else None,
            "chunks": [dict(row) for row in chunks],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()
        ).hexdigest()

    # -- document level ------------------------------------------------------

    async def doc_exists(self, workspace: str, doc_id: str) -> bool:
        """Composite-key lookup (workspace, doc_id). Cross-workspace is only
        diagnosed when the composite is absent but the id exists elsewhere."""
        hit = await self._read_one(
            "SELECT count(*) FROM public.lightrag_doc_full WHERE workspace=$1 AND id=$2",
            workspace,
            doc_id,
        )
        if hit:
            return True
        elsewhere = await self._read_one(
            """SELECT DISTINCT workspace FROM public.lightrag_doc_full
               WHERE id=$1 AND workspace<>$2 LIMIT 1""",
            doc_id,
            workspace,
        )
        if elsewhere:
            raise CrossWorkspaceError(
                f"doc {doc_id} exists only in workspace '{elsewhere}', not '{workspace}'"
            )
        return False

    async def get_doc(self, workspace: str, doc_id: str):
        row = await self._read_one(
            """SELECT id, workspace, doc_name, content, meta, sidecar_location, parse_format,
                      parse_engine, content_hash, chunk_options
               FROM public.lightrag_doc_full WHERE workspace=$1 AND id=$2""",
            workspace,
            doc_id,
            fetch="row",
        )
        if row is None:
            await self.doc_exists(workspace, doc_id)  # raises CrossWorkspaceError if elsewhere
            raise SourceNotFoundError(f"doc {doc_id!r} not found in workspace {workspace!r}")
        return row

    async def list_docs(
        self, workspace: str, limit: int = 100, offset: int = 0
    ) -> tuple[list, int]:
        conn = await self._session()
        try:
            async with conn.transaction(readonly=True, isolation="repeatable_read"):
                await conn.execute("SET LOCAL statement_timeout = 30000")
                rows = await conn.fetch(
                    """SELECT id, doc_name, parse_engine, content_hash
                       FROM public.lightrag_doc_full WHERE workspace=$1
                       ORDER BY doc_name LIMIT $2 OFFSET $3""",
                    workspace,
                    limit,
                    offset,
                )
                total = await conn.fetchval(
                    "SELECT count(*) FROM public.lightrag_doc_full WHERE workspace=$1", workspace
                )
            return rows, total
        finally:
            await conn.close()

    # -- chunk level -----------------------------------------------------------

    @staticmethod
    def check_orders(orders: list) -> None:
        """NULL/negative, duplicates and gaps in 0..n-1 all fail."""
        nulls = sum(1 for o in orders if o is None or o < 0)
        if nulls:
            raise OrderAnomalyError(f"{nulls} chunk(s) with NULL/negative order index")
        seen: dict = {}
        for o in orders:
            seen[o] = seen.get(o, 0) + 1
        dups = sorted(o for o, n in seen.items() if n > 1)
        if dups:
            raise OrderAnomalyError(f"duplicate chunk order indices: {dups[:5]}")
        missing = sorted(set(range(len(orders))) - set(orders))
        if missing:
            raise OrderAnomalyError(
                f"order indices not contiguous 0..n-1; first gaps: {missing[:5]}"
            )

    # backwards-compatible alias
    _check_orders = check_orders

    async def doc_chunk_total(self, workspace: str, doc_id: str) -> int:
        await self.get_doc(workspace, doc_id)  # composite-key existence check
        conn = await self._session()
        try:
            async with conn.transaction(readonly=True, isolation="repeatable_read"):
                await conn.execute("SET LOCAL statement_timeout = 30000")
                orders = [
                    r["chunk_order_index"]
                    for r in await conn.fetch(
                        """SELECT chunk_order_index FROM public.lightrag_doc_chunks
                           WHERE workspace=$1 AND full_doc_id=$2""",
                        workspace,
                        doc_id,
                    )
                ]
                self.check_orders(orders)
                return await conn.fetchval(
                    """SELECT count(*) FROM public.lightrag_doc_chunks
                       WHERE workspace=$1 AND full_doc_id=$2""",
                    workspace,
                    doc_id,
                )
        finally:
            await conn.close()

    async def read_chunks_ordered(
        self,
        workspace: str,
        doc_id: str,
        limit: int = 200,
        offset: int = 0,
        expected_epoch: str | None = None,
    ) -> ChunkPage:
        """Stable ordered pagination bound to one snapshot.

        Pass ``expected_epoch`` (the previous page's) to enforce that the source
        did not change between pages; a changed epoch raises SourceChangedError.
        """
        if limit < 1 or offset < 0:
            raise ValueError("limit must be >=1 and offset >=0")
        conn = await self._session()
        try:
            async with conn.transaction(readonly=True, isolation="repeatable_read"):
                await conn.execute("SET LOCAL statement_timeout = 30000")
                epoch = await self._content_epoch(conn, workspace, doc_id)
                if expected_epoch is not None and epoch != expected_epoch:
                    raise SourceChangedError(
                        f"source snapshot changed between pages "
                        f"({expected_epoch} -> {epoch}); refuse to continue pagination"
                    )
                doc_row = await conn.fetchrow(
                    """SELECT count(*) AS n FROM public.lightrag_doc_full
                       WHERE workspace=$1 AND id=$2""",
                    workspace,
                    doc_id,
                )
                if not doc_row["n"]:
                    elsewhere = await conn.fetchval(
                        """SELECT DISTINCT workspace FROM public.lightrag_doc_full
                           WHERE id=$1 AND workspace<>$2 LIMIT 1""",
                        doc_id,
                        workspace,
                    )
                    if elsewhere:
                        raise CrossWorkspaceError(
                            f"doc {doc_id} exists only in workspace '{elsewhere}', not '{workspace}'"
                        )
                    raise SourceNotFoundError(
                        f"doc {doc_id!r} not found in workspace {workspace!r}"
                    )
                orders = [
                    r["chunk_order_index"]
                    for r in await conn.fetch(
                        """SELECT chunk_order_index FROM public.lightrag_doc_chunks
                           WHERE workspace=$1 AND full_doc_id=$2""",
                        workspace,
                        doc_id,
                    )
                ]
                self.check_orders(orders)
                total = await conn.fetchval(
                    """SELECT count(*) FROM public.lightrag_doc_chunks
                       WHERE workspace=$1 AND full_doc_id=$2""",
                    workspace,
                    doc_id,
                )
                rows = await conn.fetch(
                    """SELECT id, full_doc_id, chunk_order_index, tokens, content, file_path,
                              heading, sidecar
                       FROM public.lightrag_doc_chunks
                       WHERE workspace=$1 AND full_doc_id=$2
                       ORDER BY chunk_order_index LIMIT $3 OFFSET $4""",
                    workspace,
                    doc_id,
                    limit,
                    offset,
                )
                return ChunkPage(
                    workspace=workspace,
                    doc_id=doc_id,
                    chunks=rows,
                    total=total,
                    offset=offset,
                    limit=limit,
                    snapshot_epoch=epoch,
                )
        finally:
            await conn.close()

    async def get_chunk(self, workspace: str, chunk_id: str):
        """Composite lookup on the chunk's own (workspace, id) pair."""
        row = await self._read_one(
            """SELECT id, workspace, full_doc_id, chunk_order_index, tokens, content,
                      file_path, heading, sidecar
               FROM public.lightrag_doc_chunks WHERE workspace=$1 AND id=$2""",
            workspace,
            chunk_id,
            fetch="row",
        )
        if row is None:
            elsewhere = await self._read_one(
                """SELECT DISTINCT workspace FROM public.lightrag_doc_chunks
                   WHERE id=$1 AND workspace<>$2 LIMIT 1""",
                chunk_id,
                workspace,
            )
            if elsewhere:
                raise CrossWorkspaceError(
                    f"chunk {chunk_id} exists only in workspace '{elsewhere}', not '{workspace}'"
                )
            raise SourceNotFoundError(f"chunk {chunk_id!r} not found in workspace {workspace!r}")
        return row
