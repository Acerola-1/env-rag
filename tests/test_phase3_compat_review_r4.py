"""Independent rev 3 acceptance at failure boundaries; fake I/O only."""

import asyncio
import copy
import importlib.util
from pathlib import Path

import pytest

from env_rag_final import compat_runtime as compat

_spec = importlib.util.spec_from_file_location(
    "compat_review_rev3_fixtures", Path(__file__).with_name("test_phase3_compat_review_r3.py")
)
fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixtures)


def test_identity_change_on_actual_drop_connection_is_refused(monkeypatch):
    verify = fixtures.MarkerConnection(current_oid=42)
    precheck = fixtures.MarkerConnection(current_oid=42)
    actual_drop = fixtures.MarkerConnection(current_oid=999)
    fixtures.install_connection(monkeypatch, [verify, precheck, actual_drop])
    with pytest.raises(compat.ProbeAborted):
        asyncio.run(compat.cleanup_scratch(fixtures.VALUES, fixtures.SCRATCH))
    assert not any("DROP DATABASE" in s for s in actual_drop.executed)


def test_recovery_record_write_error_still_cleans_and_records_failure(monkeypatch, tmp_path):
    events, reports = fixtures.stub_run(monkeypatch)

    def failed_record(report_dir, scratch):
        raise OSError("record filesystem unavailable")

    monkeypatch.setattr(compat, "write_recovery_record", failed_record)
    with pytest.raises((compat.ProbeAborted, OSError)):
        asyncio.run(compat.run(fixtures.VALUES, tmp_path))
    assert "cleanup" in events
    assert reports and ("failure" in reports[-1] or "guard_failure" in reports[-1])


def test_cleanup_error_alone_is_persisted_in_failed_report(monkeypatch, tmp_path):
    events, reports = fixtures.stub_run(monkeypatch)

    async def failed_cleanup(values, scratch):
        events.append("cleanup")
        raise compat.ProbeAborted("foreign session refuses cleanup")

    monkeypatch.setattr(compat, "cleanup_scratch", failed_cleanup)
    with pytest.raises(compat.ProbeAborted):
        asyncio.run(compat.run(fixtures.VALUES, tmp_path))
    assert reports and reports[-1]["cleanup"]["dropped"] is False
    assert "finished_at" not in reports[-1]


def test_workspace_initialize_failure_finalizes_constructed_instance(monkeypatch):
    import lightrag

    instances = []

    class FailingRAG:
        def __init__(self, **kwargs):
            self.workspace = kwargs["workspace"]
            self.finalized = False
            instances.append(self)

        async def initialize_storages(self):
            # Represents a partially initialized instance holding acquired resources.
            raise RuntimeError("initialization failed after acquisition")

        async def finalize_storages(self):
            self.finalized = True

    monkeypatch.setattr(lightrag, "LightRAG", FailingRAG)
    with pytest.raises((compat.ProbeAborted, RuntimeError)):
        asyncio.run(compat.probe_workspace_identity(fixtures.VALUES, fixtures.SCRATCH, {}))
    assert instances and all(r.finalized for r in instances)


def test_created_database_connection_failure_retains_cleanup_or_recovery_identity(
    monkeypatch, tmp_path
):
    original_acquire = compat._acquire_scratch
    events, reports = fixtures.stub_run(monkeypatch)
    monkeypatch.setattr(compat, "_acquire_scratch", original_acquire)
    created = []

    class Admin:
        async def fetchval(self, sql, *args):
            return 0  # Generated database name is available.

        async def execute(self, sql, *args):
            if sql.startswith("CREATE DATABASE"):
                created.append(sql.split('"')[1])

        async def close(self):
            pass

    async def connect(**kwargs):
        if kwargs["database"] == "postgres":
            return Admin()
        raise OSError("new database connection unavailable after CREATE")

    monkeypatch.setattr(compat.asyncpg, "connect", connect)
    with pytest.raises((compat.ProbeAborted, OSError)):
        asyncio.run(compat.run(fixtures.VALUES, tmp_path))
    assert created
    assert "cleanup" in events or any(
        r.get("scratch", {}).get("database") == created[0] for r in reports
    )


def test_wrong_repeated_initialize_result_fails_required_contract(monkeypatch, tmp_path):
    events, reports = fixtures.stub_run(monkeypatch)
    original = compat.probe_backend_matrix

    async def wrong_repeated(values, scratch, report):
        await original(values, scratch, report)
        report["probe_backend_matrix"]["PGTableGraphStorage"]["repeated_initialize_same_pool"] = (
            False
        )

    monkeypatch.setattr(compat, "probe_backend_matrix", wrong_repeated)
    with pytest.raises(compat.ProbeAborted):
        asyncio.run(compat.run(fixtures.VALUES, tmp_path))
    assert "cleanup" in events
    assert reports and "finished_at" not in reports[-1]


def test_post_guard_error_refuses_and_preserves_cleanup_evidence(monkeypatch, tmp_path):
    events, reports = fixtures.stub_run(monkeypatch, post_read_error=True)
    with pytest.raises(compat.ProbeAborted, match="post-guard capture failed"):
        asyncio.run(compat.run(fixtures.VALUES, tmp_path))
    assert "cleanup" in events
    assert reports[-1]["cleanup"]["ownership_verified"] is True
    assert "finished_at" not in reports[-1]


def test_frozen_counts_content_and_catalog_changes_reject_before_acquire(monkeypatch, tmp_path):
    before = copy.deepcopy(fixtures.identity())
    before["source_fingerprint"] = "changed-content-with-identical-counts"
    events, reports = fixtures.stub_run(monkeypatch, before=before)
    with pytest.raises(compat.ProbeAborted):
        asyncio.run(compat.run(fixtures.VALUES, tmp_path))
    assert "acquire" not in events
    assert reports[-1]["guard_failure"]["stage"] == "before"
