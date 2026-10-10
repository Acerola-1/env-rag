"""5.1 second review: owning entry paths; no real database or model calls."""

import asyncio
import copy

import pytest

from env_rag_final import compat_runtime as compat

VALUES = {
    "POSTGRES_HOST": "test.invalid",
    "POSTGRES_PORT": "5432",
    "POSTGRES_USER": "fixture",
    "POSTGRES_PASSWORD": "fixture",
    "POSTGRES_DATABASE": "rag",
}
SCRATCH = {"database": "lightrag_probe_fixture", "oid": 42, "secret": "marker", "run_id": "r"}


def identity():
    return {
        "public_counts": dict(compat.FROZEN["public_counts"]),
        "catalog_active": {
            "run_id": compat.FROZEN["catalog_run_id"],
            "snapshot_id": compat.FROZEN["catalog_snapshot_id"],
        },
        "source_fingerprint": compat.FROZEN["source_fingerprint"],
        "search_active": compat.FROZEN["search_active"],
        "gold_sha": compat.FROZEN["gold_sha"],
        "env_sha": "original-env-bytes-sha",
    }


def stub_run(monkeypatch, before=None, after=None, backend_fail=False, post_read_error=False):
    events = []
    reports = []

    async def capture(values, when):
        events.append("capture:" + when)
        if when == "after" and post_read_error:
            raise OSError("post-read unavailable")
        return copy.deepcopy((before or identity()) if when == "before" else (after or identity()))

    async def acquire(values):
        events.append("acquire")
        return dict(SCRATCH)

    async def pool(values, scratch, report):
        report["probe_pool_lifecycle"] = {
            "initdb_check_tables_per_stage": {
                "first_acquire": {"initdb": 1, "check_tables": 1},
                "second_acquire_holding_ref": {"initdb": 1, "check_tables": 1},
                "reacquire_after_full_release": {"initdb": 2, "check_tables": 2},
            }
        }

    async def backend(values, scratch, report):
        report["probe_backend_matrix"] = {
            "PGTableGraphStorage": {
                "status": "FAIL" if backend_fail else "OK",
                **(
                    {}
                    if backend_fail
                    else {
                        "get_node": {"entity_id": "probe-node"},
                        "tables_added": ["lightrag_graph_edges", "lightrag_graph_nodes"],
                        "repeated_initialize_same_pool": True,
                    }
                ),
            },
            "PGGraphStorage": {
                "status": "FAIL",
                "attributed_to": "Apache AGE missing (ag_catalog)",
            },
            "PGVectorStorage": {
                "status": "FAIL",
                "attributed_to": "pgvector extension missing (unknown type: public.vector)",
            },
        }

    async def workspace(values, scratch, report):
        return {"failures": []}

    async def cache(values, scratch, report):
        report["probe_cache_details"] = {
            "columns": ["id", "workspace", "cache_type", "chunk_id", "return_value"],
        }

    async def cleanup(values, scratch):
        events.append("cleanup")

    async def write(report_dir, report):
        reports.append(copy.deepcopy(report))

    def recovery(report_dir, scratch):
        events.append("recovery")
        return report_dir / f"record-{scratch['run_id']}.json"

    for name, fn in {
        "capture_production_identity": capture,
        "_acquire_scratch": acquire,
        "probe_pool_lifecycle": pool,
        "probe_backend_matrix": backend,
        "probe_workspace_identity": workspace,
        "probe_cache_details": cache,
        "cleanup_scratch": cleanup,
        "_write_report": write,
        "write_recovery_record": recovery,
    }.items():
        monkeypatch.setattr(compat, name, fn)
    monkeypatch.setattr(compat, "_set_scratch_env_for", lambda *args: None)
    return events, reports


def test_run_rejects_changed_env_bytes(monkeypatch, tmp_path):
    after = identity()
    after["env_sha"] = "changed-env-bytes-sha"
    events, reports = stub_run(monkeypatch, after=after)
    with pytest.raises(compat.ProbeAborted):
        asyncio.run(compat.run(VALUES, tmp_path))
    assert "cleanup" in events
    assert reports[-1]["guard_failure"]


def test_run_rejects_wrong_frozen_catalog_run_before_acquire(monkeypatch, tmp_path):
    before = identity()
    before["catalog_active"]["run_id"] = "different-active-run"
    events, reports = stub_run(monkeypatch, before=before)
    with pytest.raises(compat.ProbeAborted):
        asyncio.run(compat.run(VALUES, tmp_path))
    assert "acquire" not in events
    assert reports[-1]["guard_failure"]["stage"] == "before"


def test_post_guard_read_error_still_cleans_owned_resources_and_records_failure(
    monkeypatch, tmp_path
):
    events, reports = stub_run(monkeypatch, post_read_error=True)
    with pytest.raises((compat.ProbeAborted, OSError)):
        asyncio.run(compat.run(VALUES, tmp_path))
    assert "cleanup" in events
    assert reports and "guard_failure" in reports[-1]


def test_required_plain_graph_probe_failure_cannot_be_success(monkeypatch, tmp_path):
    stub_run(monkeypatch, backend_fail=True)
    with pytest.raises(compat.ProbeAborted):
        asyncio.run(compat.run(VALUES, tmp_path))


class MarkerConnection:
    def __init__(self, marker_oid=42, current_oid=42):
        self.marker_oid = marker_oid
        self.current_oid = current_oid
        self.executed = []
        self.terminated = 0

    async def fetchrow(self, sql, *args):
        if "probe_ownership" in sql:
            return {"secret": "marker", "db_oid": self.marker_oid}
        if "pg_database" in sql:
            return {"oid": self.current_oid}
        return {"secret": "marker", "db_oid": self.marker_oid}

    async def fetchval(self, sql, *args):
        if "pg_database" in sql:
            return self.current_oid
        if "pg_stat_activity" in sql:
            return 0
        return 0

    async def execute(self, sql, *args):
        self.executed.append(" ".join(sql.split()))
        if "pg_terminate_backend" in sql:
            self.terminated += 1

    async def close(self):
        pass


def install_connection(monkeypatch, connection):
    async def connect(**kwargs):
        return connection

    monkeypatch.setattr(compat.asyncpg, "connect", connect)


def test_stored_ownership_oid_must_match_not_only_current_oid(monkeypatch):
    conn = MarkerConnection(marker_oid=999, current_oid=42)
    install_connection(monkeypatch, conn)
    with pytest.raises(compat.ProbeAborted):
        asyncio.run(compat._verify_ownership(VALUES, SCRATCH))
    assert conn.executed == []


def test_cleanup_changed_oid_cannot_terminate_sessions_first(monkeypatch):
    conn = MarkerConnection(current_oid=999)
    install_connection(monkeypatch, conn)

    async def previously_verified(values, scratch):
        pass  # Identity changed after the earlier verification connection closed.

    monkeypatch.setattr(compat, "_verify_ownership", previously_verified)
    with pytest.raises(compat.ProbeAborted):
        asyncio.run(compat.cleanup_scratch(VALUES, SCRATCH))
    assert conn.executed == []


def test_changed_count_rejected_by_named_guard_not_fixture_exception(monkeypatch):
    changed = identity()
    changed["public_counts"]["lightrag_doc_full"] = 222

    async def capture(values, when):
        return changed

    monkeypatch.setattr(compat, "capture_production_identity", capture)
    report = {}
    with pytest.raises(compat.ProbeAborted, match="production identity mismatch"):
        asyncio.run(compat.verify_production_untouched(VALUES, report))
    assert report["production_untouched"]["matches_frozen"] is False


def test_unchanged_run_remains_valid(monkeypatch, tmp_path):
    events, reports = stub_run(monkeypatch)
    result = asyncio.run(compat.run(VALUES, tmp_path))
    assert "cleanup" in events
    assert "guard_failure" not in result
    assert reports and "finished_at" in reports[-1]
