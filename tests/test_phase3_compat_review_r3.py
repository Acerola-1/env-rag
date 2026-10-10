"""5.1 third review (D1–D4): owning entry paths; no real database or model calls.

D1 cleanup order/ownership, D2 identity guards, D3 failure recovery/report,
D4 probe success contract — all through the OWNING entries (run,
cleanup_scratch, _verify_ownership), fake connections/captures only.
"""

import asyncio
import copy
import json

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


def stub_run(monkeypatch, before=None, after=None, backend_result=None, post_read_error=False):
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
        events.append("backend")
        report["probe_backend_matrix"] = copy.deepcopy(
            backend_result
            if backend_result is not None
            else {
                "PGTableGraphStorage": {
                    "status": "OK",
                    "get_node": {"entity_id": "probe-node"},
                    "tables_added": ["lightrag_graph_edges", "lightrag_graph_nodes"],
                    "repeated_initialize_same_pool": True,
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
        )

    async def cache(values, scratch, report):
        report["probe_cache_details"] = {
            "columns": ["id", "workspace", "cache_type", "chunk_id", "return_value"],
        }

    async def workspace(values, scratch, report):
        return {"failures": []}

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


# ---------------------------------------------------------------------------
# D2: identity guards on the owning run entry
# ---------------------------------------------------------------------------


def test_run_rejects_changed_env_bytes(monkeypatch, tmp_path):
    after = identity()
    after["env_sha"] = "changed-env-bytes-sha"
    events, reports = stub_run(monkeypatch, after=after)
    with pytest.raises(compat.ProbeAborted, match="post-guard failed"):
        asyncio.run(compat.run(VALUES, tmp_path))
    assert "cleanup" in events
    assert reports[-1]["guard_failure"]["stage"] == "after"


def test_run_rejects_wrong_frozen_catalog_run_before_acquire(monkeypatch, tmp_path):
    before = identity()
    before["catalog_active"]["run_id"] = "different-active-run"
    events, reports = stub_run(monkeypatch, before=before)
    with pytest.raises(compat.ProbeAborted):
        asyncio.run(compat.run(VALUES, tmp_path))
    assert "acquire" not in events
    assert reports[-1]["guard_failure"]["stage"] == "before"


def test_pre_guard_source_change_with_unchanged_counts_is_refused(monkeypatch, tmp_path):
    # r2 handoff: source content changed but counts stayed equal → refuse.
    before = identity()
    before["source_fingerprint"] = "different-content-fingerprint"
    events, reports = stub_run(monkeypatch, before=before)
    with pytest.raises(compat.ProbeAborted, match="source fingerprint"):
        asyncio.run(compat.run(VALUES, tmp_path))
    assert "acquire" not in events


def test_post_guard_catalog_switch_is_refused_by_drift(monkeypatch, tmp_path):
    # r2 handoff: search/catalog active switched DURING the run → refuse
    # even though the final value equals nothing frozen.
    after = identity()
    after["search_active"] = "brand-new-search-build"
    events, reports = stub_run(monkeypatch, after=after)
    with pytest.raises(compat.ProbeAborted, match="post-guard failed"):
        asyncio.run(compat.run(VALUES, tmp_path))
    problems = reports[-1]["guard_failure"]["problems"]
    assert any("search active changed" in p for p in problems)


def test_post_guard_read_error_still_cleans_and_records_failure(monkeypatch, tmp_path):
    events, reports = stub_run(monkeypatch, post_read_error=True)
    with pytest.raises(compat.ProbeAborted, match="post-guard capture failed"):
        asyncio.run(compat.run(VALUES, tmp_path))
    assert "cleanup" in events
    assert reports and "guard_failure" in reports[-1]


# ---------------------------------------------------------------------------
# D4: required probe contract on the owning run entry
# ---------------------------------------------------------------------------


def test_required_plain_graph_probe_failure_cannot_be_success(monkeypatch, tmp_path):
    backend = {
        "PGTableGraphStorage": {"status": "FAIL", "error": "boom"},
        "PGGraphStorage": {
            "status": "FAIL",
            "attributed_to": "Apache AGE missing (ag_catalog)",
        },
        "PGVectorStorage": {
            "status": "FAIL",
            "attributed_to": "pgvector extension missing (unknown type: public.vector)",
        },
    }
    events, reports = stub_run(monkeypatch, backend_result=backend)
    with pytest.raises(compat.ProbeAborted, match="required probe contract"):
        asyncio.run(compat.run(VALUES, tmp_path))
    # cleanup still ran (D3 independence) but the report records the failure
    assert "cleanup" in events
    assert reports[-1]["failure"]["stage"] == "probe-stage"


def test_age_success_is_also_a_contract_violation(monkeypatch, tmp_path):
    backend = {
        "PGTableGraphStorage": {
            "status": "OK",
            "get_node": {"entity_id": "probe-node"},
            "tables_added": ["lightrag_graph_edges"],
        },
        "PGGraphStorage": {"status": "OK"},  # AGE absent on this server: OK is wrong
        "PGVectorStorage": {
            "status": "FAIL",
            "attributed_to": "pgvector extension missing (unknown type: public.vector)",
        },
    }
    stub_run(monkeypatch, backend_result=backend)
    with pytest.raises(compat.ProbeAborted, match="PGGraphStorage"):
        asyncio.run(compat.run(VALUES, tmp_path))


def test_pgvector_constructor_only_failure_is_not_accepted(monkeypatch, tmp_path):
    # The D4 finding: a FAIL that never reached the extension compatibility
    # stage (attribution = constructor error type) must fail the run.
    backend = {
        "PGTableGraphStorage": {
            "status": "OK",
            "get_node": {"entity_id": "probe-node"},
            "tables_added": ["lightrag_graph_edges"],
        },
        "PGGraphStorage": {
            "status": "FAIL",
            "attributed_to": "Apache AGE missing (ag_catalog)",
        },
        "PGVectorStorage": {"status": "FAIL", "attributed_to": "ValueError"},
    }
    stub_run(monkeypatch, backend_result=backend)
    with pytest.raises(compat.ProbeAborted, match="PGVectorStorage"):
        asyncio.run(compat.run(VALUES, tmp_path))


def test_backend_probe_missing_key_fails_the_run(monkeypatch, tmp_path):
    backend = {
        "PGTableGraphStorage": {
            "status": "OK",
            "get_node": {"entity_id": "probe-node"},
            "tables_added": ["lightrag_graph_edges"],
        },
        "PGGraphStorage": {
            "status": "FAIL",
            "attributed_to": "Apache AGE missing (ag_catalog)",
        },
        # PGVectorStorage result missing entirely
    }
    stub_run(monkeypatch, backend_result=backend)
    with pytest.raises(compat.ProbeAborted, match="missing"):
        asyncio.run(compat.run(VALUES, tmp_path))


def test_unchanged_run_remains_valid(monkeypatch, tmp_path):
    events, reports = stub_run(monkeypatch)
    result = asyncio.run(compat.run(VALUES, tmp_path))
    assert "cleanup" in events and "recovery" in events
    assert "guard_failure" not in result
    assert reports and "finished_at" in reports[-1]


# ---------------------------------------------------------------------------
# D1: ownership verification and cleanup ordering on the owning entries
# ---------------------------------------------------------------------------


class MarkerConnection:
    """Fake connection for _verify_ownership / cleanup_scratch paths."""

    def __init__(self, marker_oid=42, current_oid=42, marker_secret="marker", foreign=0):
        self.marker_oid = marker_oid
        self.current_oid = current_oid
        self.marker_secret = marker_secret
        self.foreign = foreign
        self.executed = []
        self.terminated = 0

    def _log(self, sql):
        self.executed.append(" ".join(sql.split()))

    async def fetchrow(self, sql, *args):
        self._log(sql)
        if "probe_ownership" in sql:
            return {"secret": self.marker_secret, "db_oid": self.marker_oid}
        if "pg_database" in sql:
            return {"oid": self.current_oid}
        return None

    async def fetchval(self, sql, *args):
        self._log(sql)
        if "pg_database" in sql:
            return self.current_oid
        if "pg_stat_activity" in sql:
            return self.foreign
        return 0

    async def execute(self, sql, *args):
        self._log(sql)
        if "pg_terminate_backend" in sql:
            self.terminated += 1

    async def fetch(self, sql, *args):
        self._log(sql)
        return []

    async def close(self):
        pass


def install_connection(monkeypatch, connections):
    """Install a queue of fake connections (one per connect() call)."""
    queue = list(connections)

    async def connect(**kwargs):
        return queue.pop(0)

    monkeypatch.setattr(compat.asyncpg, "connect", connect)


def test_verify_ownership_requires_marker_oid_to_match_record(monkeypatch):
    # D1: marker db_oid=999 but run record/current=42 → refuse.
    conn = MarkerConnection(marker_oid=999, current_oid=42)
    install_connection(monkeypatch, [conn])
    with pytest.raises(compat.ProbeAborted):
        asyncio.run(compat._verify_ownership(VALUES, SCRATCH))
    assert not any("DROP DATABASE" in e or "pg_terminate_backend" in e for e in conn.executed)


def test_verify_ownership_requires_current_oid_to_match_record(monkeypatch):
    conn = MarkerConnection(marker_oid=42, current_oid=999)
    install_connection(monkeypatch, [conn])
    with pytest.raises(compat.ProbeAborted):
        asyncio.run(compat._verify_ownership(VALUES, SCRATCH))
    assert not any("DROP DATABASE" in e or "pg_terminate_backend" in e for e in conn.executed)


def test_verify_ownership_requires_marker_secret(monkeypatch):
    conn = MarkerConnection(marker_oid=42, current_oid=42, marker_secret="other")
    install_connection(monkeypatch, [conn])
    with pytest.raises(compat.ProbeAborted):
        asyncio.run(compat._verify_ownership(VALUES, SCRATCH))
    assert not any("DROP DATABASE" in e or "pg_terminate_backend" in e for e in conn.executed)


def test_cleanup_refuses_and_never_terminates_when_identity_changed(monkeypatch):
    # D1/E1: identity changed between verification and the destructive step —
    # the ACTUAL DROP connection must re-check and refuse before any drop.
    # Connection order: marker(scratch DB) → precheck(admin) → drop(admin,
    # sees a replaced DB and refuses BEFORE its own DROP).
    marker_conn = MarkerConnection(marker_oid=42, current_oid=42)
    precheck_conn = MarkerConnection(current_oid=42)
    drop_conn = MarkerConnection(current_oid=999)  # DB replaced after precheck
    install_connection(monkeypatch, [marker_conn, precheck_conn, drop_conn])
    with pytest.raises(compat.ProbeAborted):
        asyncio.run(compat.cleanup_scratch(VALUES, SCRATCH))
    for c in (marker_conn, precheck_conn, drop_conn):
        assert c.terminated == 0
        assert not any("DROP DATABASE" in e for e in c.executed)


def test_cleanup_refuses_on_remaining_foreign_sessions(monkeypatch):
    # D1: after our instances are finalized, an unknown session remains →
    # refuse; never terminate by database name. (Detected on the precheck
    # connection; the DROP connection is never even opened.)
    marker_conn = MarkerConnection(marker_oid=42, current_oid=42)
    precheck_conn = MarkerConnection(current_oid=42, foreign=1)
    install_connection(monkeypatch, [marker_conn, precheck_conn])
    with pytest.raises(compat.ProbeAborted, match="foreign|not belonging"):
        asyncio.run(compat.cleanup_scratch(VALUES, SCRATCH))
    assert precheck_conn.terminated == 0
    assert not any("DROP DATABASE" in e for e in precheck_conn.executed)


def test_cleanup_happy_path_drops_without_any_terminate(monkeypatch):
    # E1: the DROP-carrying connection re-reads the current OID and session
    # list ITSELF, immediately before dropping; marker/precheck connections
    # can never authorize the drop on their own.
    marker_conn = MarkerConnection(marker_oid=42, current_oid=42)
    precheck_conn = MarkerConnection(current_oid=42, foreign=0)
    drop_conn = MarkerConnection(current_oid=42, foreign=0)
    install_connection(monkeypatch, [marker_conn, precheck_conn, drop_conn])
    asyncio.run(compat.cleanup_scratch(VALUES, SCRATCH))
    for c in (marker_conn, precheck_conn, drop_conn):
        assert c.terminated == 0, "no pg_terminate_backend anywhere in the path"
    assert any("DROP DATABASE" in e for e in drop_conn.executed)
    # the drop-carrying connection itself re-read pg_database before DROP
    drop_reads = [e for e in drop_conn.executed if "pg_database" in e]
    assert drop_reads, "drop connection must re-read identity itself"
    assert drop_conn.executed.index(
        next(e for e in drop_conn.executed if "DROP DATABASE" in e)
    ) > drop_conn.executed.index(drop_reads[-1])


# ---------------------------------------------------------------------------
# D3: recovery record + cleanup_only round trip (private secret, not public)
# ---------------------------------------------------------------------------


def test_recovery_record_round_trip_drives_cleanup_only(monkeypatch, tmp_path):
    # D3: write the private record, then feed it to the public cleanup entry.
    scratch = {
        "database": "lightrag_probe_deadbeef",
        "oid": 777,
        "secret": "s3cr3t",
        "run_id": "compat-abc123",
    }
    path = compat.write_recovery_record(tmp_path, scratch)
    assert path.exists()
    body = json.loads(path.read_text())
    assert body["scratch_secret"] == "s3cr3t"  # private record carries the secret
    public_report_keys = {"run_id", "scratch", "created_at"}
    assert set(body) == public_report_keys | {"scratch_secret"}

    marker_conn = MarkerConnection(marker_oid=777, current_oid=777, marker_secret="s3cr3t")
    precheck_conn = MarkerConnection(current_oid=777)
    drop_conn = MarkerConnection(current_oid=777)
    install_connection(monkeypatch, [marker_conn, precheck_conn, drop_conn])
    asyncio.run(compat.cleanup_only(VALUES, path))
    assert any("DROP DATABASE" in e for e in drop_conn.executed)
    # the drop connection re-read identity itself before dropping (E1)
    drop_reads = [e for e in drop_conn.executed if "pg_database" in e]
    assert drop_reads
    assert drop_conn.executed.index(
        next(e for e in drop_conn.executed if "DROP DATABASE" in e)
    ) > drop_conn.executed.index(drop_reads[-1])


def test_cleanup_only_with_wrong_secret_refuses(monkeypatch, tmp_path):
    scratch = {
        "database": "lightrag_probe_deadbeef",
        "oid": 777,
        "secret": "s3cr3t",
        "run_id": "compat-abc123",
    }
    path = compat.write_recovery_record(tmp_path, scratch)
    marker_conn = MarkerConnection(marker_oid=777, current_oid=777, marker_secret="WRONG")
    precheck_conn = MarkerConnection(current_oid=777)
    drop_conn = MarkerConnection(current_oid=777)
    install_connection(monkeypatch, [marker_conn, precheck_conn, drop_conn])
    with pytest.raises(compat.ProbeAborted):
        asyncio.run(compat.cleanup_only(VALUES, path))
    for c in (marker_conn, precheck_conn, drop_conn):
        assert not any("DROP DATABASE" in e or "pg_terminate_backend" in e for e in c.executed)


def test_run_failure_writes_recovery_record_before_probe_stages(monkeypatch, tmp_path):
    # D3: the recovery record exists even when a probe stage fails later —
    # the leftover scratch DB always has a usable recovery path.
    backend = {
        "PGTableGraphStorage": {"status": "FAIL", "error": "boom"},
        "PGGraphStorage": {"status": "FAIL", "attributed_to": "Apache AGE missing (ag_catalog)"},
        "PGVectorStorage": {
            "status": "FAIL",
            "attributed_to": "pgvector extension missing (unknown type: public.vector)",
        },
    }
    events, _reports = stub_run(monkeypatch, backend_result=backend)
    with pytest.raises(compat.ProbeAborted):
        asyncio.run(compat.run(VALUES, tmp_path))
    assert events.index("recovery") < events.index("backend")
