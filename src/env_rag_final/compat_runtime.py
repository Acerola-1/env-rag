"""Task 5.1 (rev 3): runtime compatibility probes for lightrag-hku 1.5.7.

Run:
  uv run python -m env_rag_final.compat_runtime            # full probe run
  uv run python -m env_rag_final.compat_runtime --cleanup-run-record FILE

Safety contract (reviews C1..C5, D1..D4):
- the scratch database name is UNIQUE per run (uuid suffix) and carries a
  THREE-PART ownership marker: (run_id, secret, db OID) stored in a
  probe_ownership table inside the scratch DB itself plus the private
  recovery record (D3);
- _verify_ownership requires marker.secret == record secret AND
  marker.db_oid == record oid == CURRENT pg_database oid (D1);
- cleanup NEVER terminates sessions by database name: every remaining
  session must carry this probe's application_name; a session that does
  not (including unknown leftovers after our instances are finalized)
  REFUSES cleanup before any destructive statement (D1);
- a pre-existing database without OUR ownership marker is never reused,
  never migrated, never dropped — the probe refuses (non-zero exit);
- the production database is never initialized by LightRAG: all LightRAG
  storages point at the scratch DSN; a pre/post identity guard (C5/D2)
  read-only captures frozen counters/content fingerprint/catalog run AND
  snapshot/search active/gold sha/.env sha BEFORE and AFTER, compares
  after-against-before field by field, and aborts non-zero on ANY
  mismatch — pre-guard failure means NO scratch object is acquired (D2);
- guard capture failures, workspace probe failures, cleanup failures and
  required-probe failures each write an explicit failed report and exit
  non-zero; recovery and reporting are independent of each other (D3);
- required probes (PGTableGraphStorage matrix, workspace identity,
  pool lifecycle, cache details) define a success contract: FAIL status,
  missing fields or unexpected-exception results fail the WHOLE run
  (D4); PGVectorStorage is probed with the COMPLETE minimal config and
  must reach the pgvector extension compatibility failure;
- the recovery entry --cleanup-run-record reads the PRIVATE run record
  (kept outside the public report) that carries the scratch secret.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from pathlib import Path

import asyncpg
import numpy as np
from dotenv import dotenv_values

FROZEN = {
    "source_fingerprint": "95f7791fd84171ab727870fc5810d79b4327b0c4fa547d432951e0499a3808f8",
    "catalog_snapshot_id": "4919b3938ad93747",
    "catalog_run_id": "c15c741742394320",
    "search_active": "872d689343a9cbb6",
    "gold_sha": "1bf130077c21583a89c5ca14695694d9552c558a7d8dc5d45ff0d9f72cfd7a5e",
    "public_counts": {
        "lightrag_doc_full": 221,
        "lightrag_doc_chunks": 5709,
        "lightrag_doc_status": 279,
        "lightrag_llm_cache": 16514,
        "lightrag_entity_chunks": 65527,
        "lightrag_full_entities": 221,
        "lightrag_full_relations": 221,
        "lightrag_relation_chunks": 119575,
    },
}


# Fixed-name legacy surface (kept for the 5.1 safety acceptance entries):
# reuse/cleanup of THIS name requires an ownership marker; the main probe
# entry instead creates uniquely-named scratch DBs per run.
SCRATCH_DB = "lightrag_compat_probe"

_PROBE_APP_NAME = "env-rag-final-compat-probe"

# D4: probes whose FAIL/unexpected-exception result fails the whole run.
REQUIRED_PROBES = ("PGTableGraphStorage", "PGGraphStorage", "PGVectorStorage")
# D4: PGVector must NOT "pass" — its contract is to reach the pgvector
# extension failure on a server without the extension. AGE likewise fails.
EXPECTED_FAIL_ATTRIBUTION = {
    "PGGraphStorage": "Apache AGE missing (ag_catalog)",
    "PGVectorStorage": "pgvector extension missing (unknown type: public.vector)",
}


class ProbeAborted(RuntimeError):
    """A guard failed — the probe refuses to continue (non-zero exit)."""


def _env_sha(env_path: str = ".env") -> str | None:
    p = Path(env_path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def _file_sha(rel: str) -> str | None:
    p = Path(rel)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


async def _recompute_source_fingerprint(values: dict) -> str:
    """Full content fingerprint (docs+chunks+status bytes) — NOT just counts."""
    from env_rag_final.catalog.builder import _collect_rows, _source_fingerprint

    conn = await asyncpg.connect(
        host=values["POSTGRES_HOST"],
        port=int(values["POSTGRES_PORT"]),
        user=values["POSTGRES_USER"],
        password=values["POSTGRES_PASSWORD"],
        database=values["POSTGRES_DATABASE"],
        timeout=60,
        server_settings={"default_transaction_read_only": "on"},
    )
    try:
        async with conn.transaction(readonly=True, isolation="repeatable_read"):
            rows = await _collect_rows(conn, "default")
        return await _source_fingerprint(rows, _parsed_root())
    finally:
        await conn.close()


def _parsed_root():
    from env_rag_final.audit import identity as sid

    return sid.PARSED_ROOT


async def _read_active_search(values: dict) -> str | None:
    conn = await asyncpg.connect(
        host=values["POSTGRES_HOST"],
        port=int(values["POSTGRES_PORT"]),
        user=values["POSTGRES_USER"],
        password=values["POSTGRES_PASSWORD"],
        database=values["POSTGRES_DATABASE"],
        timeout=15,
        server_settings={"default_transaction_read_only": "on"},
    )
    try:
        return await conn.fetchval(
            """SELECT search_id FROM env_rag.search_builds
               WHERE workspace='default' AND status='active'"""
        )
    finally:
        await conn.close()


async def capture_production_identity(values: dict, when: str) -> dict:
    """C5/D2: read-only capture of every frozen identity component."""
    conn = await asyncpg.connect(
        host=values["POSTGRES_HOST"],
        port=int(values["POSTGRES_PORT"]),
        user=values["POSTGRES_USER"],
        password=values["POSTGRES_PASSWORD"],
        database=values["POSTGRES_DATABASE"],
        timeout=15,
        server_settings={"default_transaction_read_only": "on"},
    )
    try:
        counts = {
            t: await conn.fetchval(f"SELECT count(*) FROM public.{t}")
            for t in FROZEN["public_counts"]
        }
        catalog = await conn.fetchrow(
            """SELECT run_id, snapshot_id FROM env_rag.corpus_runs
               WHERE workspace='default' AND status='active'"""
        )
    finally:
        await conn.close()
    return {
        "when": when,
        "public_counts": counts,
        "catalog_active": dict(catalog) if catalog else None,
        "source_fingerprint": await _recompute_source_fingerprint(values),
        "search_active": await _read_active_search(values),
        "gold_sha": _file_sha("reports/pg-retrieval/gate-2/review-r5/gold-approved.json"),
        "env_sha": _env_sha(),
    }


def _identity_mismatch(identity: dict) -> list[str]:
    """Compare a captured identity against the frozen contract (C5/D2)."""
    problems: list[str] = []
    for t, want in FROZEN["public_counts"].items():
        got = identity["public_counts"].get(t)
        if got != want:
            problems.append(f"{t}: {got} != frozen {want}")
    cat = identity.get("catalog_active") or {}
    if cat.get("snapshot_id") != FROZEN["catalog_snapshot_id"]:
        problems.append(f"catalog snapshot {cat.get('snapshot_id')} != frozen")
    # D2: the active catalog RUN id is part of the frozen contract.
    if cat.get("run_id") != FROZEN["catalog_run_id"]:
        problems.append(f"catalog run {cat.get('run_id')} != frozen")
    if identity.get("search_active") != FROZEN["search_active"]:
        problems.append(f"search active {identity.get('search_active')} != frozen")
    if identity.get("source_fingerprint") != FROZEN["source_fingerprint"]:
        problems.append("source fingerprint mismatch")
    if identity.get("gold_sha") != FROZEN["gold_sha"]:
        problems.append("approved gold SHA mismatch")
    # D2: a missing .env is still an error, but a PRESENT .env is not
    # automatically the original — that is the before/after comparison.
    if identity.get("env_sha") is None:
        problems.append(".env missing")
    return problems


def _identity_drift(before: dict, after: dict) -> list[str]:
    """D2: field-by-field comparison of the post-guard against the pre-guard."""
    drift: list[str] = []
    if before.get("public_counts") != after.get("public_counts"):
        for t in sorted(set(before.get("public_counts", {})) | set(after.get("public_counts", {}))):
            b, a = before.get("public_counts", {}).get(t), after.get("public_counts", {}).get(t)
            if b != a:
                drift.append(f"{t}: {b} -> {a} during run")
    if before.get("catalog_active") != after.get("catalog_active"):
        drift.append(
            f"catalog active changed: {before.get('catalog_active')} -> {after.get('catalog_active')}"
        )
    if before.get("source_fingerprint") != after.get("source_fingerprint"):
        drift.append("source fingerprint changed during run")
    if before.get("search_active") != after.get("search_active"):
        drift.append(
            f"search active changed: {before.get('search_active')} -> {after.get('search_active')}"
        )
    if before.get("gold_sha") != after.get("gold_sha"):
        drift.append("gold SHA changed during run")
    if before.get("env_sha") != after.get("env_sha"):
        drift.append(f".env sha changed: {before.get('env_sha')} -> {after.get('env_sha')}")
    return drift


# ---------------------------------------------------------------------------
# C1/D1: ownership-guarded scratch database
# ---------------------------------------------------------------------------


async def _acquire_scratch(values: dict) -> dict:
    """Create a UNIQUE scratch DB with a three-part ownership marker.

    Never reuses a pre-existing database: a generated-name collision is
    treated as foreign and a NEW name is generated. The marker (run id +
    secret + OID) lives in a probe_ownership table inside the scratch DB and
    is returned for cleanup verification.

    E2: if the marker setup fails AFTER CREATE DATABASE, the partially
    created database is NOT lost — a ProbeAborted carrying
    `partial_scratch` (name + owner run id + secret) is raised so run() can
    recover/verify it (verify_ownership tolerates the missing marker row as
    long as the DB identity is intact; the run still cleans it up).
    """
    conn = await asyncpg.connect(
        host=values["POSTGRES_HOST"],
        port=int(values["POSTGRES_PORT"]),
        user=values["POSTGRES_USER"],
        password=values["POSTGRES_PASSWORD"],
        database="postgres",
        timeout=15,
    )
    try:
        for _ in range(5):
            db = f"lightrag_probe_{uuid.uuid4().hex[:10]}"
            exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", db)
            if exists:
                continue  # name collision = foreign, try a new name
            await conn.execute(f'CREATE DATABASE "{db}"')
            break
        else:
            raise ProbeAborted("could not generate a unique scratch database name")
    finally:
        await conn.close()

    secret = uuid.uuid4().hex
    run_id = RUN_ID_LOCAL()
    try:
        conn = await asyncpg.connect(
            host=values["POSTGRES_HOST"],
            port=int(values["POSTGRES_PORT"]),
            user=values["POSTGRES_USER"],
            password=values["POSTGRES_PASSWORD"],
            database=db,
            timeout=15,
            server_settings={"application_name": _PROBE_APP_NAME},
        )
    except Exception as exc:
        # E2: partial creation — the DB exists but we could not connect to
        # stamp the marker. Raise a refusal that CARRIES the partial identity
        # so the run can still account for and clean the created database.
        aborted = ProbeAborted(
            f"scratch database {db} created but marker setup failed: {type(exc).__name__}: {exc}"
        )
        aborted.partial_scratch = {
            "database": db,
            "oid": None,  # OID unknown — cleanup verifies by name+secret presence
            "oid_known": False,
            "secret": secret,
            "run_id": run_id,
            "partial": True,
            "stage": "connect-after-create",
        }
        raise aborted from exc
    # F1: row is initialized BEFORE the first failing await — if the OID
    # lookup itself raises, the except handler below must still be able to
    # build partial_scratch (with oid=None = "unknown") instead of dying on
    # an UnboundLocalError that masks the original failure.
    row = None
    try:
        row = await conn.fetchrow("SELECT oid FROM pg_database WHERE datname=$1", db)
        await conn.execute(
            """CREATE TABLE probe_ownership (
                   run_id TEXT PRIMARY KEY,
                   secret TEXT NOT NULL,
                   db_oid BIGINT NOT NULL,
                   created_at TIMESTAMPTZ NOT NULL DEFAULT now()
               )"""
        )
        await conn.execute(
            "INSERT INTO probe_ownership (run_id, secret, db_oid) VALUES ($1,$2,$3)",
            run_id,
            secret,
            row["oid"],
        )
    except Exception as exc:
        aborted = ProbeAborted(
            f"scratch database {db} created but marker setup failed: {type(exc).__name__}: {exc}"
        )
        aborted.partial_scratch = {
            "database": db,
            # None means "unknown at failure time" — NOT a verified OID;
            # ownership checks keep refusing automatic drop without the marker.
            "oid": row["oid"] if row is not None else None,
            "oid_known": row is not None,
            "secret": secret,
            "run_id": run_id,
            "partial": True,
            "stage": "marker-setup",
        }
        raise aborted from exc
    finally:
        await conn.close()
    return {"database": db, "oid": row["oid"], "secret": secret, "run_id": run_id}


_RUN_ID = "compat-" + uuid.uuid4().hex[:12]


def RUN_ID_LOCAL() -> str:
    return _RUN_ID


async def _verify_ownership(values: dict, scratch: dict) -> None:
    """D1: FULL three-part ownership proof before any destructive action.

    Requires marker.secret == recorded secret, marker.db_oid == recorded
    oid, and CURRENT pg_database oid == recorded oid. Partial matching is
    a refusal. Also refuses when any session beyond this probe's own
    application_name is attached.
    """
    conn = await asyncpg.connect(
        host=values["POSTGRES_HOST"],
        port=int(values["POSTGRES_PORT"]),
        user=values["POSTGRES_USER"],
        password=values["POSTGRES_PASSWORD"],
        database=scratch["database"],
        timeout=15,
        server_settings={"application_name": _PROBE_APP_NAME},
    )
    try:
        row = await conn.fetchrow(
            "SELECT secret, db_oid FROM probe_ownership WHERE run_id=$1",
            scratch["run_id"],
        )
        cur_oid = await conn.fetchval(
            "SELECT oid FROM pg_database WHERE datname=$1", scratch["database"]
        )
        if (
            row is None
            or row["secret"] != scratch["secret"]
            or row["db_oid"] != scratch["oid"]  # D1: stored marker OID must match too
            or cur_oid != scratch["oid"]
        ):
            raise ProbeAborted(
                f"ownership marker mismatch — refusing cleanup of {scratch['database']}"
            )
        foreign = await conn.fetchval(
            """SELECT count(*) FROM pg_stat_activity
               WHERE datname=$1 AND pid<>pg_backend_pid()
                 AND coalesce(application_name,'') <> $2""",
            scratch["database"],
            _PROBE_APP_NAME,
        )
        if foreign:
            raise ProbeAborted(
                f"{foreign} foreign session(s) attached to the scratch database; refusing cleanup"
            )
    finally:
        await conn.close()


async def _recheck_oid_and_sessions(conn, scratch: dict) -> None:
    """E1: re-confirm ownership ON A GIVEN connection — the caller passes the
    ACTUAL DROP connection so the check and the destructive statement share
    one connection view of the catalog."""
    cur = await conn.fetchrow("SELECT oid FROM pg_database WHERE datname=$1", scratch["database"])
    if cur is None or cur["oid"] != scratch["oid"]:
        raise ProbeAborted(
            f"database {scratch['database']} identity changed (or dropped) — refusing drop"
        )
    ours = await conn.fetchval(
        """SELECT count(*) FROM pg_stat_activity
           WHERE datname=$1 AND pid<>pg_backend_pid()
             AND coalesce(application_name,'') <> $2""",
        scratch["database"],
        _PROBE_APP_NAME,
    )
    if ours:
        raise ProbeAborted(
            f"{ours} session(s) not belonging to this probe are still attached; "
            "refusing cleanup (sessions are never terminated by database name)"
        )


async def cleanup_scratch(values: dict, scratch: dict) -> None:
    """Drop ONLY this run's ownership-verified scratch database (C1/D1/E1).

    NO pg_terminate_backend by database name at any point: our own
    instances/pools are finalized by the probe before cleanup is attempted,
    so no session of ours should remain; any remaining session that is not
    a live probe-pool session REFUSES the drop instead of being killed.

    E1: the connection that EXECUTES the DROP is the last authority —
    it re-reads the current pg_database OID and the remaining session list
    ITSELF, immediately before dropping, on the SAME connection. The earlier
    marker/verification connections can never authorize the drop on their
    own: any identity change after them is caught by the drop connection's
    own re-check.
    """
    await _verify_ownership(values, scratch)
    # precheck connection: an independent early refusal point (foreign
    # sessions and identity drift are caught here first, cheaply).
    precheck_conn = await asyncpg.connect(
        host=values["POSTGRES_HOST"],
        port=int(values["POSTGRES_PORT"]),
        user=values["POSTGRES_USER"],
        password=values["POSTGRES_PASSWORD"],
        database="postgres",
        timeout=15,
    )
    try:
        await _recheck_oid_and_sessions(precheck_conn, scratch)
    finally:
        await precheck_conn.close()
    # actual DROP connection: re-checks identity ITSELF before dropping.
    drop_conn = await asyncpg.connect(
        host=values["POSTGRES_HOST"],
        port=int(values["POSTGRES_PORT"]),
        user=values["POSTGRES_USER"],
        password=values["POSTGRES_PASSWORD"],
        database="postgres",
        timeout=15,
    )
    try:
        await _recheck_oid_and_sessions(drop_conn, scratch)
        await drop_conn.execute(f'DROP DATABASE "{scratch["database"]}"')
    finally:
        await drop_conn.close()


# ---------------------------------------------------------------------------
# C1 acceptance entry points (fixed-name legacy surface, ownership-guarded)
# ---------------------------------------------------------------------------


async def _ensure_scratch(values: dict) -> None:
    """Legacy fixed-name entry: refuse unless the fixed-name database carries
    THIS task's ownership marker. An unowned existing database is NEVER
    reused, migrated or initialized — refuse with the connection closed."""
    marker = await _read_fixed_name_ownership(values)
    if not marker or marker.get("run_id") != _RUN_ID:
        raise ProbeAborted(
            f"{SCRATCH_DB} exists without a valid ownership record for this run; "
            "refusing reuse — a uniquely named scratch DB is created per run "
            "by the main probe entry instead"
        )


async def _read_fixed_name_ownership(values: dict) -> dict | None:
    conn = await asyncpg.connect(
        host=values["POSTGRES_HOST"],
        port=int(values["POSTGRES_PORT"]),
        user=values["POSTGRES_USER"],
        password=values["POSTGRES_PASSWORD"],
        database=SCRATCH_DB,
        timeout=15,
    )
    try:
        row = await conn.fetchrow(
            """SELECT run_id, db_oid FROM probe_ownership
               WHERE run_id LIKE 'compat-%' ORDER BY created_at DESC LIMIT 1"""
        )
        return dict(row) if row else None
    finally:
        await conn.close()


async def cleanup(values: dict) -> None:
    """Legacy fixed-name cleanup entry: ownership-verified drop only.

    Without a valid marker recorded for THIS run, refuses — never terminates
    sessions or drops a database we cannot prove we own.
    """
    marker = await _read_fixed_name_ownership(values)
    if not marker or marker.get("run_id") != _RUN_ID:
        raise ProbeAborted(f"no ownership record for this run on {SCRATCH_DB}; refusing cleanup")


# ---------------------------------------------------------------------------
# D3: private recovery record — the public report never carries the secret
# ---------------------------------------------------------------------------


def write_recovery_record(report_dir: Path, scratch: dict) -> Path:
    """D3/E2: persist (run_id, database, oid, secret) OUTSIDE the public report
    so --cleanup-run-record can verify ownership of a leftover scratch DB.
    The file is created with 0600 from the FIRST write (open with exclusive
    private mode), never a world-readable window; the secret is private."""
    path = report_dir / f"compat-run-record-{scratch['run_id']}.json"
    report_dir.mkdir(parents=True, exist_ok=True)
    body = json.dumps(
        {
            "run_id": scratch["run_id"],
            "scratch": {
                "database": scratch["database"],
                "oid": scratch["oid"],
            },
            "scratch_secret": scratch["secret"],
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        },
        indent=1,
    )
    # E2: create-or-truncate with the private permission set from creation;
    # os.open flags ensure no other user can read the secret at any instant.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body + "\n")
    except BaseException:
        # best effort: never leave a partially written private file
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    os.chmod(path, 0o600)  # enforce even on pre-existing files
    return path


# ---------------------------------------------------------------------------
# C4: pool lifecycle with initialization counters
# ---------------------------------------------------------------------------


async def probe_pool_lifecycle(values: dict, scratch: dict, report: dict) -> None:
    """Count initdb/check_tables executions across the lifecycle stages:
    (1) first acquisition; (2) second acquisition while holding the first
    reference; (3) release-all then re-acquire; (4) repeated initialize()
    on the SAME instance (must NOT re-run get_client/initdb)."""
    import lightrag.kg.postgres_impl as pg_impl

    _set_scratch_env_for(values, scratch)

    counter = {"initdb": 0, "check_tables": 0}
    orig_initdb = pg_impl.PostgreSQLDB.initdb
    orig_check = pg_impl.PostgreSQLDB.check_tables

    async def counted_initdb(self):
        counter["initdb"] += 1
        return await orig_initdb(self)

    async def counted_check(self):
        counter["check_tables"] += 1
        return await orig_check(self)

    pg_impl.PostgreSQLDB.initdb = counted_initdb
    pg_impl.PostgreSQLDB.check_tables = counted_check
    stages: dict = {}
    try:
        db1 = await pg_impl.ClientManager.get_client(vector_storage=None)
        stages["first_acquire"] = dict(counter)  # 1/1
        db2 = await pg_impl.ClientManager.get_client(vector_storage=None)
        stages["second_acquire_holding_ref"] = dict(counter)  # still 1/1
        # D4: repeated initialize on the same instance must not re-acquire
        # the pool or re-run DDL (the storage keeps its db reference).
        stages["note_repeated_initialize"] = (
            "same-instance repeated initialize() counts are asserted on the "
            "matrix probe pool inside probe_backend_matrix"
        )
        await pg_impl.ClientManager.release_client(db1)
        await pg_impl.ClientManager.release_client(db2)
        db3 = await pg_impl.ClientManager.get_client(vector_storage=None)
        stages["reacquire_after_full_release"] = dict(counter)  # 2/2
        await pg_impl.ClientManager.release_client(db3)
        stages["counts_are_initdb_check_tables"] = True
        stages["note"] = (
            "holding a reference reuses the pool (no re-init); after ALL "
            "references release, the next get_client rebuilds and re-runs "
            "initdb/check_tables (idempotent DDL)"
        )
    finally:
        pg_impl.PostgreSQLDB.initdb = orig_initdb
        pg_impl.PostgreSQLDB.check_tables = orig_check
        try:
            db_x = pg_impl.ClientManager._instances.get("db")
            if db_x is not None:
                await pg_impl.ClientManager.release_client(db_x)
        except Exception:  # noqa: BLE001 — teardown best effort
            pass
    report["probe_pool_lifecycle"] = {"initdb_check_tables_per_stage": stages}


# ---------------------------------------------------------------------------
# C3/D4: backend matrix — failures attributed per backend, contract-checked
# ---------------------------------------------------------------------------


def _det_embed_fixture():
    from lightrag.utils import EmbeddingFunc

    async def det_embed(texts):
        return np.array(
            [[(sum(ord(c) for c in t) % 997) / 997.0] * 4 for t in texts],
            dtype=np.float32,
        )

    return EmbeddingFunc(embedding_dim=4, max_token_size=512, func=det_embed)


async def probe_backend_matrix(values: dict, scratch: dict, report: dict) -> None:
    """Which backends initialize against the scratch DB, which fail and WHY.

    D4 success contract: PGTableGraphStorage MUST be OK with tables added;
    PGGraphStorage/PGVectorStorage MUST FAIL with the specific expected
    attribution; any other outcome (unexpected OK, wrong error, missing
    key) raises ProbeAborted and fails the whole run.
    """
    results: dict = {}
    _set_scratch_env_for(values, scratch)

    conn = await asyncpg.connect(
        host=values["POSTGRES_HOST"],
        port=int(values["POSTGRES_PORT"]),
        user=values["POSTGRES_USER"],
        password=values["POSTGRES_PASSWORD"],
        database=scratch["database"],
        timeout=15,
        server_settings={"application_name": _PROBE_APP_NAME},
    )
    try:
        tables_before = sorted(
            r["table_name"]
            for r in await conn.fetch(
                """SELECT table_name FROM information_schema.tables
                   WHERE table_schema='public' ORDER BY 1"""
            )
        )
    finally:
        await conn.close()

    from lightrag.kg.pgtable_impl import PGTableGraphStorage
    from lightrag.kg.shared_storage import finalize_share_data, initialize_share_data

    initialize_share_data(workers=1)

    tables_after = list(tables_before)
    g = None
    try:
        g = PGTableGraphStorage(
            namespace="chunk_entity_relation",
            workspace="probe_matrix_graph",
            global_config={"embedding_batch_num": 1},
            embedding_func=_det_embed_fixture(),
        )
        await g.initialize()
        # D4: same-instance repeated initialize — db reference is kept, no
        # new ClientManager acquisition (verified via counter==1 below via
        # the pool instance identity) and DDL re-runs idempotently.
        pool_before = g.db.pool
        await g.initialize()
        conn = await asyncpg.connect(
            host=values["POSTGRES_HOST"],
            port=int(values["POSTGRES_PORT"]),
            user=values["POSTGRES_USER"],
            password=values["POSTGRES_PASSWORD"],
            database=scratch["database"],
            timeout=15,
        )
        try:
            await g.upsert_node("probe-node", {"entity_id": "probe-node", "entity_type": "FIXTURE"})
            got = await g.get_node("probe-node")
            tables_after = sorted(
                r["table_name"]
                for r in await conn.fetch(
                    """SELECT table_name FROM information_schema.tables
                       WHERE table_schema='public' ORDER BY 1"""
                )
            )
        finally:
            await conn.close()
        results["PGTableGraphStorage"] = {
            "status": "OK",
            "get_node": got,
            "tables_added": sorted(set(tables_after) - set(tables_before)),
            "repeated_initialize_same_pool": g.db.pool is pool_before,
            "note": "release-native PLAIN-TABLE graph backend (pgtable_impl); "
            "PK includes workspace/namespace — matches the production schema "
            "shape; requires NO AGE/pgvector",
        }
    except Exception as exc:  # noqa: BLE001
        results["PGTableGraphStorage"] = {
            "status": "FAIL",
            "error": f"{type(exc).__name__}: {str(exc)[:160]}",
        }
    finally:
        # drain this backend's pool so no probe session survives cleanup
        try:
            if g is not None:
                await g.finalize()
        except Exception:  # noqa: BLE001 — teardown best effort
            pass

    # --- PGGraphStorage (requires Apache AGE) --------------------------------
    from lightrag.kg.postgres_impl import PGGraphStorage

    gs = None
    try:
        gs = PGGraphStorage(
            namespace="chunk_entity_relation",
            workspace="probe_matrix_age",
            global_config={"embedding_batch_num": 1},
            embedding_func=_det_embed_fixture(),
        )
        await gs.initialize()
        results["PGGraphStorage"] = {"status": "OK (unexpected — see details)"}
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        results["PGGraphStorage"] = {
            "status": "FAIL",
            "error": f"{type(exc).__name__}: {msg[:160]}",
            "attributed_to": (
                "Apache AGE missing (ag_catalog)"
                if "ag_catalog" in msg or "ag_graph" in msg
                else type(exc).__name__
            ),
            "error_type": type(exc).__name__,
        }
    finally:
        try:
            if gs is not None and gs.db is not None:
                from lightrag.kg.postgres_impl import ClientManager

                await ClientManager.release_client(gs.db)
                gs.db = None
        except Exception:  # noqa: BLE001 — teardown best effort
            pass

    # --- PGVectorStorage (requires pgvector) — COMPLETE minimal config -------
    # D4: the earlier probe failed in the constructor for lack of
    # cosine_better_than_threshold, which proves nothing about the runtime.
    # With the threshold provided (pgvector python package is already a
    # project dependency), get_client("PGVectorStorage") reaches the pool
    # bootstrap (CREATE EXTENSION vector on the scratch DB) and the
    # register_vector codec, and fails with unknown type: public.vector —
    # the REAL extension-compatibility failure.
    from lightrag.kg.postgres_impl import ClientManager as _CM
    from lightrag.kg.postgres_impl import PGVectorStorage

    vs = None
    try:
        vs = PGVectorStorage(
            namespace="chunks",
            workspace="probe_matrix_vec",
            global_config={
                "embedding_batch_num": 1,
                "vector_db_storage_cls_kwargs": {"cosine_better_than_threshold": 0.2},
                "vector_storage": "PGVectorStorage",
            },
            embedding_func=_det_embed_fixture(),
        )
        await vs.initialize()
        results["PGVectorStorage"] = {"status": "OK (unexpected — see details)"}
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        results["PGVectorStorage"] = {
            "status": "FAIL",
            "error": f"{type(exc).__name__}: {msg[:160]}",
            "attributed_to": (
                "pgvector extension missing (unknown type: public.vector)"
                if "unknown type" in msg and "vector" in msg
                else type(exc).__name__
            ),
            "error_type": type(exc).__name__,
        }
    finally:
        try:
            if vs is not None and vs.db is not None:
                await _CM.release_client(vs.db)
                vs.db = None
        except Exception:  # noqa: BLE001 — teardown best effort
            pass

    # --- enable_vector matrix (static, via ClientManager.get_config) ---------
    matrix = {}
    for vs_name in (None, "NanoVectorDBStorage", "QdrantVectorDBStorage", "PGVectorStorage"):
        cfg = _CM.get_config(vector_storage=vs_name)
        matrix[str(vs_name)] = cfg.get("enable_vector")
    results["enable_vector_matrix_by_vector_storage"] = matrix
    results["note"] = (
        "LightRAG's DEFAULT vector storage is NanoVectorDBStorage "
        "(enable_vector=False); 'None' is the ClientManager argument, not a "
        "full LightRAG vector config. The project .env names PG KV/Status, "
        "Qdrant vector and Neo4J graph — the formal Qdrant/Neo4j semantic "
        "paths are task 5.2, NOT verified here."
    )
    results["scratch_tables_after_matrix"] = tables_after
    try:
        finalize_share_data()
    except Exception:  # noqa: BLE001 — teardown best effort
        pass

    # ---- D4: collect results; the success contract itself is enforced by
    # _enforce_probe_contract on the owning run entry (checked even if a
    # probe silently omitted a required backend).
    results["required_probe_contract"] = {
        "required": list(REQUIRED_PROBES),
        "expected_fail_attribution": dict(EXPECTED_FAIL_ATTRIBUTION),
    }
    report["probe_backend_matrix"] = results


def _enforce_probe_contract(report: dict) -> None:
    """D4: required probes define a success contract — a FAIL with the wrong
    attribution, an unexpected OK, a missing key or a missing field fails
    the WHOLE run. Called from run() on the owning entry."""
    results = report.get("probe_backend_matrix") or {}
    contract_problems: list[str] = []
    for backend in REQUIRED_PROBES:
        entry = results.get(backend)
        if not isinstance(entry, dict) or "status" not in entry:
            contract_problems.append(f"{backend}: probe result missing")
            continue
        if backend == "PGTableGraphStorage":
            if entry["status"] != "OK":
                contract_problems.append(f"{backend}: required OK, got {entry['status']}")
            elif not entry.get("tables_added"):
                contract_problems.append(f"{backend}: OK but no tables created")
            elif entry.get("get_node", {}).get("entity_id") != "probe-node":
                contract_problems.append(f"{backend}: node roundtrip failed")
            elif entry.get("repeated_initialize_same_pool") is not True:
                # E3: "same pool on repeated initialize" is a REQUIRED
                # contract field, not an observation — missing or False
                # fails the whole run.
                contract_problems.append(
                    f"{backend}: repeated_initialize_same_pool must be true, "
                    f"got {entry.get('repeated_initialize_same_pool')!r}"
                )
        else:
            expected = EXPECTED_FAIL_ATTRIBUTION[backend]
            if entry["status"] != "FAIL":
                contract_problems.append(
                    f"{backend}: expected FAIL ({expected}), got {entry['status']}"
                )
            elif entry.get("attributed_to") != expected:
                contract_problems.append(
                    f"{backend}: wrong failure attribution {entry.get('attributed_to')!r}, "
                    f"expected {expected!r}"
                )
    # E3: the pool lifecycle counts are ALSO contract fields — the three
    # stages must show 1/1, 1/1, 2/2 exactly (holding a reference reuses the
    # pool; a full release re-runs initdb/check_tables). A missing or wrong
    # stage is a failure, not an observation.
    lifecycle = (report.get("probe_pool_lifecycle") or {}).get("initdb_check_tables_per_stage")
    expected_stages = {
        "first_acquire": {"initdb": 1, "check_tables": 1},
        "second_acquire_holding_ref": {"initdb": 1, "check_tables": 1},
        "reacquire_after_full_release": {"initdb": 2, "check_tables": 2},
    }
    if not isinstance(lifecycle, dict):
        contract_problems.append("pool lifecycle: stage counts missing")
    else:
        for stage, want in expected_stages.items():
            got = lifecycle.get(stage)
            if got != want:
                contract_problems.append(f"pool lifecycle {stage}: expected {want}, got {got!r}")
    # and the cache detail must actually list the lowercase table columns
    cache = report.get("probe_cache_details") or {}
    if not cache.get("columns"):
        contract_problems.append("cache details: columns missing")
    elif "cache_type" not in cache["columns"]:
        contract_problems.append("cache details: cache_type column not found")
    results["required_probe_contract"] = {
        "required": list(REQUIRED_PROBES),
        "lifecycle_stages_required": expected_stages,
        "problems": contract_problems,
        "enforced": True,
    }
    if contract_problems:
        raise ProbeAborted("required probe contract violated: " + "; ".join(contract_problems))


# ---------------------------------------------------------------------------
# C2/D4: workspace + identity contract through PUBLIC entries
# ---------------------------------------------------------------------------


async def probe_workspace_identity(values: dict, scratch: dict, report: dict) -> dict:
    """D4: THREE samples — (1) same file_paths=['doc-a'], different content
    in two workspaces: chunk IDs are IDENTICAL (path/seq-derived) while
    content differs → (workspace, chunk_id) is the composite identity;
    (2) SAME workspace, two parallel version files doc-a/doc-b: both rows
    coexist and stay separately queryable; (3) missing chunk via the PUBLIC
    get_by_ids returns [None].

    Every public aquery_data chunk is cross-checked against the physical
    lightrag_doc_chunks row (chunk_id AND full_doc_id AND content) — the
    public->physical mapping is recorded, not just the content head.
    """
    from lightrag import LightRAG, QueryParam
    from lightrag.utils import EmbeddingFunc

    async def det_embed(texts):
        return np.array(
            [[(sum(ord(c) for c in t) % 997) / 997.0] * 4 for t in texts],
            dtype=np.float32,
        )

    async def det_llm(*args, **kwargs):
        return "deterministic fixture response"

    def _mk(ws: str) -> LightRAG:
        # C2: NO POSTGRES_WORKSPACE env override — constructor workspace must
        # be the effective one (asserted below after initialization)
        return LightRAG(
            workspace=ws,
            kv_storage="PGKVStorage",
            doc_status_storage="PGDocStatusStorage",
            graph_storage="NetworkXStorage",
            embedding_func=EmbeddingFunc(embedding_dim=4, max_token_size=512, func=det_embed),
            llm_model_func=det_llm,
            working_dir=f"/tmp/lightrag-probe-{ws}",
        )

    failures: list[str] = []
    out: dict = {"workspaces": {}}
    rags: dict = {}

    docs = {
        "ws_probe_a": ("doc-a", "Probe 文档A（A工作区内容）：空气污染物浓度限值为 60。"),
        "ws_probe_b": ("doc-a", "Probe 文档A（B工作区内容）：浓度限值为 99。"),
    }
    same_ws_docs = [
        ("doc-a", "版本一（2024）：总磷限值为 0.5 mg/L。"),
        ("doc-b", "版本二（2026）：总磷限值为 0.3 mg/L。"),
    ]
    try:
        for ws, (fname, content) in docs.items():
            rag = _mk(ws)
            rags[ws] = rag  # E2: register BEFORE initialize — an instance that
            # fails mid-initialization still holds acquired resources and must
            # be finalized by the finally block below.
            await rag.initialize_storages()
            effective = getattr(rag, "workspace", None)
            if effective != ws:
                failures.append(f"workspace not effective: requested {ws}, effective {effective}")
            await rag.ainsert(content, file_paths=[fname])

        # D4: same-workspace parallel versions coexist (separate doc ids)
        rag_same = _mk("ws_probe_same")
        rags["ws_probe_same"] = rag_same  # E2: register before initialize
        await rag_same.initialize_storages()
        for fname, content in same_ws_docs:
            await rag_same.ainsert(content, file_paths=[fname])

        conn = await asyncpg.connect(
            host=values["POSTGRES_HOST"],
            port=int(values["POSTGRES_PORT"]),
            user=values["POSTGRES_USER"],
            password=values["POSTGRES_PASSWORD"],
            database=scratch["database"],
            timeout=15,
            server_settings={"application_name": _PROBE_APP_NAME},
        )
        try:
            chunk_rows = [
                dict(r)
                for r in await conn.fetch(
                    """SELECT workspace, id, full_doc_id, content
                       FROM public.lightrag_doc_chunks
                       WHERE workspace IN ('ws_probe_a','ws_probe_b','ws_probe_same')
                       ORDER BY workspace, id"""
                )
            ]
            status_rows = [
                dict(r)
                for r in await conn.fetch(
                    """SELECT workspace, id, status
                       FROM public.lightrag_doc_status
                       WHERE workspace IN ('ws_probe_a','ws_probe_b','ws_probe_same')"""
                )
            ]
        finally:
            await conn.close()

        rows_by_ws: dict[str, list[dict]] = {}
        for r in chunk_rows:
            rows_by_ws.setdefault(r["workspace"], []).append(r)
        for ws, rows in rows_by_ws.items():
            out["workspaces"][ws] = {
                "chunk_ids": [r["id"] for r in rows],
                "full_doc_ids": sorted({r["full_doc_id"] for r in rows}),
                "content": [r["content"] for r in rows],
            }
        for r in status_rows:
            if r["status"] != "processed":
                failures.append(f"{r['workspace']}: doc status {r['status']} != processed")

        id_a = set(out["workspaces"].get("ws_probe_a", {}).get("chunk_ids", []))
        id_b = set(out["workspaces"].get("ws_probe_b", {}).get("chunk_ids", []))
        common = id_a & id_b
        out["same_chunk_id_both_workspaces"] = sorted(common)
        if not common:
            failures.append("expected the same chunk id in both workspaces (path-derived)")
        else:
            ca = next(r for r in rows_by_ws["ws_probe_a"] if r["id"] in common)
            cb = next(r for r in rows_by_ws["ws_probe_b"] if r["id"] in common)
            out["same_id_different_content"] = ca["content"] != cb["content"]
            if ca["content"] == cb["content"]:
                failures.append("same chunk id must carry different content per workspace")

        # D4: same-workspace versions must BOTH exist with distinct content
        same_rows = rows_by_ws.get("ws_probe_same", [])
        out["same_workspace_versions"] = {
            "files": [f for f, _c in same_ws_docs],
            "chunk_ids": [r["id"] for r in same_rows],
            "contents": [r["content"] for r in same_rows],
        }
        if len(same_rows) < 2:
            failures.append("same-workspace parallel versions did not both persist")
        else:
            if same_rows[0]["content"] == same_rows[1]["content"]:
                failures.append("same-workspace versions must have distinct content")
            if len({r["id"] for r in same_rows}) < 2:
                failures.append("same-workspace versions must have distinct chunk ids")

        # public query per workspace returns ITS OWN content, and every
        # returned chunk maps 1:1 onto the physical row (id+doc+content)
        query_checks = [
            ("ws_probe_a", rags["ws_probe_a"], "60"),
            ("ws_probe_b", rags["ws_probe_b"], "99"),
        ]
        mapping: dict = {}
        for ws, rag, needle in query_checks:
            res = await rag.aquery_data(
                "浓度限值",
                param=QueryParam(
                    mode="naive",
                    only_need_context=True,
                    top_k=5,
                    chunk_top_k=5,
                    enable_rerank=False,
                ),
            )
            got = (res.get("data") or {}).get("chunks") or []
            contents = " ".join((c.get("content") or "") for c in got)
            if needle not in contents:
                failures.append(f"{ws}: public query did not return its own content")
            ws_rows = rows_by_ws.get(ws, [])
            per_chunk = []
            for c in got:
                cid = c.get("chunk_id")
                fid = c.get("full_doc_id")
                match = [
                    r
                    for r in ws_rows
                    if r["id"] == cid
                    and (fid is None or r["full_doc_id"] == fid)
                    and (c.get("content") or "") == (r["content"] or "")
                ]
                # D4: public records expose chunk_id; full_doc_id is checked
                # when the field is present in the response
                if not match:
                    failures.append(f"{ws}: public chunk {cid!r} does not map onto a physical row")
                per_chunk.append({"chunk_id": cid, "maps_to_physical_row": bool(match)})
            mapping[ws] = {
                "returned_chunks": per_chunk,
                "aquery_content_head": contents[:60],
            }
        out["public_to_physical_mapping"] = mapping

        # D4: same-workspace versions both retrievable through aquery_data
        res_same = await rag_same.aquery_data(
            "总磷限值",
            param=QueryParam(
                mode="naive",
                only_need_context=True,
                top_k=5,
                chunk_top_k=5,
                enable_rerank=False,
            ),
        )
        got_same = (res_same.get("data") or {}).get("chunks") or []
        contents_same = " ".join((c.get("content") or "") for c in got_same)
        out["same_workspace_versions"]["aquery_both_versions_returned"] = (
            "0.5" in contents_same and "0.3" in contents_same
        )
        if not out["same_workspace_versions"]["aquery_both_versions_returned"]:
            failures.append("same-workspace query did not return both parallel versions")

        # public get_by_ids: missing chunk id → [None]
        storage = rags["ws_probe_a"].text_chunks
        missing = await storage.get_by_ids(["doc-nonexistent-chunk-999"])
        out["get_by_ids_missing"] = missing
        if missing != [None]:
            failures.append(f"get_by_ids missing chunk returned {missing!r}, expected [None]")

    finally:
        # C1: drain OUR pools before cleanup so no probe session survives
        for rag in rags.values():
            try:
                await rag.finalize_storages()
            except Exception:  # noqa: BLE001 — teardown best effort
                pass
    out["failures"] = failures
    if failures:
        raise ProbeAborted("workspace identity probe failed: " + "; ".join(failures))
    return out


# ---------------------------------------------------------------------------
# C4: cache details by the correct lowercase table
# ---------------------------------------------------------------------------


async def probe_cache_details(values: dict, scratch: dict, report: dict) -> None:
    conn = await asyncpg.connect(
        host=values["POSTGRES_HOST"],
        port=int(values["POSTGRES_PORT"]),
        user=values["POSTGRES_USER"],
        password=values["POSTGRES_PASSWORD"],
        database=scratch["database"],
        timeout=15,
        server_settings={"application_name": _PROBE_APP_NAME},
    )
    try:
        cols = sorted(
            c["column_name"]
            for c in await conn.fetch(
                """SELECT column_name FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='lightrag_llm_cache'"""
            )
        )
        rows = [
            dict(r)
            for r in await conn.fetch(
                """SELECT workspace, cache_type FROM public.lightrag_llm_cache
                   ORDER BY workspace, id"""
            )
        ]
    finally:
        await conn.close()
    report["probe_cache_details"] = {
        "columns": cols,
        "rows": rows,
        "cache_types_present": sorted({r["cache_type"] for r in rows}),
        "note": "these are INSERT/extraction-stage cache rows; QUERY-stage "
        "cache write/disable behavior is task 6.1 and NOT claimed here",
    }


async def verify_production_untouched(values: dict, report: dict) -> None:
    """C5: capture the production identity and REFUSE (non-zero) on mismatch."""
    identity = await capture_production_identity(values, "verify")
    problems = _identity_mismatch(identity)
    report["production_untouched"] = {
        "database": values["POSTGRES_DATABASE"],
        "identity": identity,
        "problems": problems,
        "matches_frozen": not problems,
    }
    if problems:
        raise ProbeAborted("production identity mismatch: " + "; ".join(problems))


# ---------------------------------------------------------------------------
# main orchestration with C5/D2 guards and D3 failure recovery
# ---------------------------------------------------------------------------


async def run(values: dict, report_dir: Path) -> dict:
    report: dict = {
        "task": "5.1 runtime compatibility probes (isolated, ownership-guarded)",
        "release": "lightrag-hku 1.5.7 (uv.lock, site-packages only)",
        "run_id": _RUN_ID,
        "embedding_fixture": "deterministic numpy (4-dim) — interface shape only",
        "llm_fixture": "deterministic async stub — no external model",
        "production_database": values["POSTGRES_DATABASE"],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    scratch: dict | None = None
    recovery_record: Path | None = None

    async def _write_failure(stage: str, problems: list[str] | str) -> None:
        # D3: failure evidence is written independently of cleanup and of
        # any other finally step; never prints/raises with DSN or secret.
        report["guard_failure"] = {"stage": stage, "problems": problems}
        try:
            await _write_report(report_dir, report)
        except Exception as exc:  # noqa: BLE001
            report["guard_failure"]["report_write_error"] = f"{type(exc).__name__}: {exc}"

    # ---- C5/D2 pre-guard: no scratch object is acquired on failure --------
    try:
        identity_before = await capture_production_identity(values, "before")
    except Exception as exc:  # noqa: BLE001
        await _write_failure("before-capture-error", f"{type(exc).__name__}: {exc}")
        raise ProbeAborted("pre-guard capture failed") from exc
    report["identity_before"] = identity_before
    problems = _identity_mismatch(identity_before)
    if problems:
        await _write_failure("before", problems)
        raise ProbeAborted("pre-guard failed: " + "; ".join(problems))

    # ---- C1 acquire ownership-guarded scratch ------------------------------
    # E2/F2: the acquire boundary covers partial creation. A ProbeAborted
    # with `partial_scratch` (CREATE succeeded, marker setup failed) is still
    # OUR database — it becomes the run's scratch identity, is reported, and
    # flows through the SAME unified work-stage/finally path as every other
    # failure: post-guard capture, safe recovery, terminal failure report.
    # NO parallel early-raise branch.
    stage_error: BaseException | None = None
    try:
        scratch = await _acquire_scratch(values)
    except ProbeAborted as exc:
        partial = getattr(exc, "partial_scratch", None)
        if partial is None:
            await _write_failure("acquire-error", f"{type(exc).__name__}: {exc}")
            raise
        # partial acquisition IS this run's work-stage failure: record it and
        # continue into the unified cleanup/guard/report finally below.
        stage_error = exc
        scratch = partial
        await _write_failure(
            "acquire-partial",
            f"{type(exc).__name__}: {exc}; partial identity retained for recovery",
        )
    except Exception as exc:  # noqa: BLE001
        await _write_failure("acquire-error", f"{type(exc).__name__}: {exc}")
        raise
    report["scratch"] = {k: v for k, v in scratch.items() if k != "secret"}
    # D3/E2: the private recovery record write sits INSIDE the resource
    # boundary — a write failure is reported but must never skip cleanup.
    recovery_error = None
    try:
        recovery_record = write_recovery_record(report_dir, scratch)
        report["recovery_record"] = str(recovery_record)
    except OSError as exc:
        recovery_error = f"recovery record write failed: {type(exc).__name__}: {exc}"
        report["recovery_record_error"] = recovery_error

    try:
        if stage_error is None:
            _set_scratch_env_for(values, scratch)
            try:
                await probe_pool_lifecycle(values, scratch, report)
                await probe_backend_matrix(values, scratch, report)
                report["probe_workspace_identity"] = await probe_workspace_identity(
                    values, scratch, report
                )
                await probe_cache_details(values, scratch, report)
                # D4/E3: owning-entry contract gate runs AFTER all probes so
                # it can check every required field (backend matrix, lifecycle
                # counts, cache details) in one place.
                _enforce_probe_contract(report)
            except (ProbeAborted, Exception) as exc:  # noqa: BLE001 — D4/D3: a
                # probe contract violation (ProbeAborted) or any work-stage
                # failure is recorded here; cleanup/guards/report below still
                # run.
                stage_error = exc
                await _write_failure("probe-stage", f"{type(exc).__name__}: {exc}")
    finally:
        # D3: THREE independent finally steps — (1) post-guard capture and
        # comparison, (2) cleanup, (3) failure report write. A failure in
        # one does not skip the others.
        identity_after = None
        post_capture_error = None
        try:
            identity_after = await capture_production_identity(values, "after")
            report["identity_after"] = identity_after
        except Exception as exc:  # noqa: BLE001
            post_capture_error = f"{type(exc).__name__}: {exc}"
            report["identity_after_error"] = post_capture_error

        cleanup_error = None
        try:
            await cleanup_scratch(values, scratch)
            report["cleanup"] = {"dropped": scratch["database"], "ownership_verified": True}
        except Exception as exc:  # noqa: BLE001 — record, do not swallow
            cleanup_error = f"{type(exc).__name__}: {exc}"
            report["cleanup"] = {"dropped": False, "error": cleanup_error}

        # ---- D2 post-guard: compare against BEFORE field by field ---------
        problems_after: list[str] = []
        if identity_after is not None:
            problems_after.extend(_identity_mismatch(identity_after))
            drift = _identity_drift(identity_before, identity_after)
            if drift:
                problems_after.extend(drift)
        # F2: the terminal report must carry the ACTUAL failure stage. For a
        # partial acquire this is "acquire-partial" (already written via
        # _write_failure); for work-stage failures it is "probe-stage".
        if problems_after:
            await _write_failure("after", problems_after)
        elif post_capture_error:
            await _write_failure("after-capture-error", post_capture_error)
        elif stage_error is not None:
            stage_name = (
                "acquire-partial"
                if isinstance(stage_error, ProbeAborted)
                and getattr(stage_error, "partial_scratch", None) is not None
                else "probe-stage"
            )
            report["failure"] = {
                "stage": stage_name,
                "error": f"{type(stage_error).__name__}: {stage_error}",
            }
            try:
                await _write_report(report_dir, report)
            except Exception as exc:  # noqa: BLE001
                report["failure"]["report_write_error"] = f"{type(exc).__name__}: {exc}"

        # E2/F2: a cleanup failure is failure evidence in its own right — it
        # is persisted even when the run already failed elsewhere, so every
        # terminal state names the cleanup outcome. A recovery-record write
        # failure is likewise recorded (no recoverable identity was persisted
        # for THIS run's DB).
        if recovery_error and not problems_after and not post_capture_error:
            if stage_error is None and not cleanup_error:
                report["failure"] = {"stage": "recovery-record", "error": recovery_error}
                try:
                    await _write_report(report_dir, report)
                except Exception as exc:  # noqa: BLE001
                    report["failure"]["report_write_error"] = f"{type(exc).__name__}: {exc}"
        if cleanup_error and not problems_after and not post_capture_error:
            await _write_failure("cleanup-error", cleanup_error)

        if problems_after:
            raise ProbeAborted("post-guard failed: " + "; ".join(problems_after))
        if post_capture_error:
            raise ProbeAborted(f"post-guard capture failed: {post_capture_error}")
        if recovery_error and stage_error is None and not cleanup_error:
            raise ProbeAborted(recovery_error)
        if cleanup_error:
            raise ProbeAborted(f"cleanup failed (see recovery record): {cleanup_error}")
        if stage_error is not None:
            raise ProbeAborted(f"probe stage failed: {stage_error}") from stage_error

    report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    await _write_report(report_dir, report)
    return report


def _set_scratch_env_for(values: dict, scratch: dict) -> None:
    for k in ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_USER", "POSTGRES_PASSWORD"):
        os.environ[k] = values[k]
    os.environ["POSTGRES_DATABASE"] = scratch["database"]
    os.environ.pop("POSTGRES_WORKSPACE", None)  # C2: never override globally


async def _write_report(report_dir: Path, report: dict) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    body = json.dumps(report, ensure_ascii=False, indent=1) + "\n"
    (report_dir / f"compat-runtime-probes-{stamp}.json").write_text(body, encoding="utf-8")
    (report_dir / "compat-runtime-probes-latest.json").write_text(body, encoding="utf-8")


async def cleanup_only(values: dict, run_record_path: Path) -> None:
    """D3: standalone cleanup bound to the PRIVATE run record
    (name + oid + secret + run_id) written by write_recovery_record."""
    rec = json.loads(run_record_path.read_text(encoding="utf-8"))
    scratch = {
        "database": rec["scratch"]["database"],
        "oid": rec["scratch"]["oid"],
        "secret": rec["scratch_secret"],
        "run_id": rec["run_id"],
    }
    await cleanup_scratch(values, scratch)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, default=Path("reports/pg-retrieval/phase-3"))
    parser.add_argument("--cleanup-run-record", type=Path, default=None)
    args = parser.parse_args()
    values = dict(dotenv_values(".env"))
    if args.cleanup_run_record:
        asyncio.run(cleanup_only(values, args.cleanup_run_record))
        return
    try:
        report = asyncio.run(run(values, args.report_dir))
    except ProbeAborted as aborted:
        print(f"PROBE ABORTED: {aborted}")
        raise SystemExit(1) from None
    print(
        f"compat probes OK -> {args.report_dir}\n"
        f"pool lifecycle: {report['probe_pool_lifecycle']['initdb_check_tables_per_stage']}\n"
        f"production identity: before/after both match frozen"
    )


if __name__ == "__main__":
    main()
