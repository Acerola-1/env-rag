"""Gate 2 G2-3: search build lifecycle guards (isolated fakes, no live DB).

Covers the review-identified branches:
- a same-identity retry after failure does not raise a primary-key error;
- ``--force`` re-runs the same identity without colliding;
- a failure during derivation leaves the OLD active build untouched;
- a source change during derivation aborts before publish;
- a catalog replacement during the build prevents publish.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from env_rag_final.search import index


def run(coro):
    return asyncio.run(coro)


class Ledger:
    """Tracks search_builds rows like the real table (PK on search_id)."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.statements: list[tuple[str, tuple]] = []


class BuildConn:
    def __init__(self, ledger: Ledger | None = None, fail_on_executemany: bool = False):
        self.ledger = ledger or Ledger()
        self.fail_on_executemany = fail_on_executemany
        self.wrote_chunks = False

    @asynccontextmanager
    async def transaction(self, **kw):
        yield

    async def execute(self, sql, *args):
        self.ledger.statements.append((sql, args))
        if "INSERT INTO env_rag.search_builds" in sql:
            sid = args[0]
            if sid in self.ledger.rows and "ON CONFLICT" not in sql:
                raise Exception("duplicate key value violates unique constraint")  # noqa: TRY002
            self.ledger.rows[sid] = {"status": "building", "args": args}
        if "status='failed'" in sql:
            sid = args[0]
            if sid in self.ledger.rows:
                self.ledger.rows[sid]["status"] = "failed"
        if "status='active'" in sql and "SET" in sql:
            sid = args[0]
            if sid in self.ledger.rows:
                self.ledger.rows[sid]["status"] = "active"
        if "status='retired'" in sql:
            for row in self.ledger.rows.values():
                if row["status"] == "active":
                    row["status"] = "retired"

    async def executemany(self, sql, rows):
        if self.fail_on_executemany and "search_chunks" in sql:
            raise RuntimeError("derivation exploded")
        self.ledger.statements.append((sql, ("<rows>", len(rows))))
        if "search_chunks" in sql:
            self.wrote_chunks = True

    async def fetchrow(self, sql, *args):
        if "env_rag.search_builds" in sql and "status='active'" in sql:
            return None
        if "search_id, status FROM env_rag.search_builds" in sql:
            row = self.ledger.rows.get(args[1])
            if row is None:
                return None
            return {"search_id": args[1], "status": row["status"]}
        return None

    async def fetch(self, sql, *args):
        if "public.lightrag_doc_full" in sql:
            return [{"id": "d", "doc_name": "doc.pdf", "content": "old"}]
        if "public.lightrag_doc_chunks" in sql:
            return [
                {
                    "id": "c",
                    "full_doc_id": "d",
                    "chunk_order_index": 0,
                    "content": "old",
                    "heading": None,
                }
            ]
        if "env_rag.documents" in sql:
            return [
                {
                    "doc_id": "d",
                    "doc_name": "doc.pdf",
                    "title": "T",
                    "self_code": None,
                    "self_code_version": None,
                    "doc_type": None,
                }
            ]
        return []

    async def fetchval(self, sql, *args):
        if "tsv = ''" in sql:
            return 0
        return 1


def _patch_state(monkeypatch, catalog_changes_to=None):
    import env_rag_final.catalog.builder as builder

    calls = {"n": 0}

    async def cat(*a, **kw):
        calls["n"] += 1
        snap = "catalog"
        if catalog_changes_to and calls["n"] >= 2:
            snap = catalog_changes_to
        return {"state": "current", "active_snapshot_id": snap, "stored_fingerprint": "source"}

    async def fingerprint(*a, **kw):
        return "source"

    monkeypatch.setattr(builder, "check_stale", cat)
    monkeypatch.setattr(builder, "_live_source_fingerprint", fingerprint)
    return calls


def test_retry_after_failure_reuses_identity_without_pk_error(monkeypatch):
    """A failed build's identity can be retried — no PK violation."""
    _patch_state(monkeypatch)
    ledger = Ledger()
    conn = BuildConn(ledger, fail_on_executemany=True)
    with pytest.raises(RuntimeError):
        run(index.build_search_index(conn))
    failed = [r for r in ledger.rows.values() if r["status"] == "failed"]
    assert failed

    # retry the SAME identity, this time succeeding
    conn2 = BuildConn(ledger, fail_on_executemany=False)
    result = run(index.build_search_index(conn2))
    assert result.published
    assert ledger.rows[result.search_id]["status"] == "active"


def test_force_rerun_same_identity_does_not_collide(monkeypatch):
    _patch_state(monkeypatch)
    ledger = Ledger()
    conn = BuildConn(ledger)
    first = run(index.build_search_index(conn))
    assert ledger.rows[first.search_id]["status"] == "active"

    conn2 = BuildConn(ledger)  # same identity, force=True
    second = run(index.build_search_index(conn2, force=True))
    assert second.search_id == first.search_id
    assert ledger.rows[second.search_id]["status"] == "active"


def test_failure_leaves_previous_active_untouched(monkeypatch):
    _patch_state(monkeypatch)
    ledger = Ledger()
    old = run(index.build_search_index(BuildConn(ledger)))
    old_status = ledger.rows[old.search_id]["status"]
    assert old_status == "active"

    # force a retry that fails mid-derivation: the OLD row must stay active
    conn = BuildConn(ledger, fail_on_executemany=True)
    with pytest.raises(RuntimeError):
        run(index.build_search_index(conn, force=True))
    assert ledger.rows[old.search_id]["status"] == "active"


def test_source_change_during_derivation_aborts_before_publish(monkeypatch):
    import env_rag_final.catalog.builder as builder

    calls = {"n": 0}

    async def cat(*a, **kw):
        return {"state": "current", "active_snapshot_id": "catalog", "stored_fingerprint": "source"}

    async def fingerprint(*a, **kw):
        calls["n"] += 1
        return "source" if calls["n"] == 1 else "changed"

    monkeypatch.setattr(builder, "check_stale", cat)
    monkeypatch.setattr(builder, "_live_source_fingerprint", fingerprint)
    ledger = Ledger()
    conn = BuildConn(ledger)
    with pytest.raises(index.SearchBuildError):
        run(index.build_search_index(conn))
    assert not any(r["status"] == "active" for r in ledger.rows.values())


def test_catalog_replacement_during_build_prevents_publish(monkeypatch):
    _patch_state(monkeypatch, catalog_changes_to="catalog-2")
    ledger = Ledger()
    conn = BuildConn(ledger)
    with pytest.raises(index.SearchBuildError):
        run(index.build_search_index(conn))
    assert not any(r["status"] == "active" for r in ledger.rows.values())
