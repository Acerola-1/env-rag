"""Fourth independent review: partial creation must retain auditable identity."""

import asyncio
import importlib.util
from pathlib import Path

import pytest

from env_rag_final import compat_runtime as compat

_spec = importlib.util.spec_from_file_location(
    "compat_review_r3_stubs", Path(__file__).with_name("test_phase3_compat_review_r3.py")
)
fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixtures)


def test_oid_lookup_error_does_not_mask_partial_creation_identity(monkeypatch):
    created = []

    class Admin:
        async def fetchval(self, sql, *args):
            return 0

        async def execute(self, sql, *args):
            if sql.startswith("CREATE DATABASE"):
                created.append(sql.split('"')[1])

        async def close(self):
            pass

    class ScratchConnection:
        async def fetchrow(self, sql, *args):
            raise OSError("OID metadata read failed after creation")

        async def close(self):
            pass

    async def connect(**kwargs):
        return Admin() if kwargs["database"] == "postgres" else ScratchConnection()

    monkeypatch.setattr(compat.asyncpg, "connect", connect)
    with pytest.raises(compat.ProbeAborted) as caught:
        asyncio.run(compat._acquire_scratch(fixtures.VALUES))
    assert created
    assert caught.value.partial_scratch["database"] == created[0]


def partial_run(monkeypatch):
    events, reports = fixtures.stub_run(monkeypatch)
    partial = {**fixtures.SCRATCH, "partial": True}

    async def acquire(values):
        error = compat.ProbeAborted("marker setup unavailable after CREATE")
        error.partial_scratch = dict(partial)
        raise error

    monkeypatch.setattr(compat, "_acquire_scratch", acquire)
    return events, reports, partial


def test_partial_acquire_persists_terminal_identity_and_cleanup_result(monkeypatch, tmp_path):
    events, reports, partial = partial_run(monkeypatch)
    with pytest.raises(compat.ProbeAborted):
        asyncio.run(compat.run(fixtures.VALUES, tmp_path))
    assert "cleanup" in events
    assert reports[-1].get("scratch", {}).get("database") == partial["database"]
    assert reports[-1].get("cleanup", {}).get("ownership_verified") is True
    assert "finished_at" not in reports[-1]


def test_partial_acquire_still_performs_post_guard_capture(monkeypatch, tmp_path):
    events, reports, _partial = partial_run(monkeypatch)
    with pytest.raises(compat.ProbeAborted):
        asyncio.run(compat.run(fixtures.VALUES, tmp_path))
    assert "capture:after" in events
    assert "identity_after" in reports[-1] or "identity_after_error" in reports[-1]


def test_partial_acquire_cleanup_refusal_remains_visible(monkeypatch, tmp_path):
    events, reports, partial = partial_run(monkeypatch)

    async def refuse_cleanup(values, scratch):
        events.append("cleanup")
        raise compat.ProbeAborted("marker incomplete; cannot prove destructive cleanup ownership")

    monkeypatch.setattr(compat, "cleanup_scratch", refuse_cleanup)
    with pytest.raises(compat.ProbeAborted):
        asyncio.run(compat.run(fixtures.VALUES, tmp_path))
    assert reports[-1]["scratch"]["database"] == partial["database"]
    assert reports[-1]["cleanup"]["dropped"] is False
    assert reports[-1]["guard_failure"]["stage"] == "cleanup-error"
