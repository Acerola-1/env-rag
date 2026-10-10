"""Own one unique probe DB; inject an OID read failure; preserve strict cleanup."""

import asyncio
import json
import uuid
from pathlib import Path

import asyncpg
from dotenv import dotenv_values

from env_rag_final import compat_runtime as compat

OUT = Path(__file__).parent


async def main():
    values = dict(dotenv_values(".env"))
    original_connect = asyncpg.connect
    ownership_comment = "codex-review-owned-" + uuid.uuid4().hex
    owned = {}
    injected = False
    result = {"actual_model_calls": 0, "actual_embedding_calls": 0}

    def options(database):
        return {
            "host": values["POSTGRES_HOST"],
            "port": int(values["POSTGRES_PORT"]),
            "user": values["POSTGRES_USER"],
            "password": values["POSTGRES_PASSWORD"],
            "database": database,
            "timeout": 15,
        }

    class Proxy:
        def __init__(self, connection, database):
            self.connection = connection
            self.database = database

        def __getattr__(self, name):
            return getattr(self.connection, name)

        async def execute(self, sql, *args):
            answer = await self.connection.execute(sql, *args)
            if self.database == "postgres" and sql.startswith('CREATE DATABASE "lightrag_probe_'):
                db = sql.split('"')[1]
                oid = await self.connection.fetchval(
                    "SELECT oid FROM pg_database WHERE datname=$1", db
                )
                owned.update(database=db, oid=oid)
                # Separate reviewer proof of creation, before intentionally failing
                # the application marker setup. Only this newly created DB is marked.
                await self.connection.execute(
                    f"COMMENT ON DATABASE \"{db}\" IS '{ownership_comment}'"
                )
            return answer

        async def fetchrow(self, sql, *args):
            nonlocal injected
            if (
                self.database == owned.get("database")
                and sql.startswith("SELECT oid FROM pg_database")
                and not injected
            ):
                injected = True
                raise OSError("review-injected OID read failure")
            return await self.connection.fetchrow(sql, *args)

    async def wrapped_connect(**kwargs):
        return Proxy(await original_connect(**kwargs), kwargs.get("database"))

    directory = OUT / "partial-live"
    before = await compat.capture_production_identity(values, "review-before")
    try:
        asyncpg.connect = wrapped_connect
        try:
            await compat.run(values, directory)
        except compat.ProbeAborted:
            result["run_refused"] = True
        else:
            raise AssertionError("partial acquisition unexpectedly succeeded")
        finally:
            asyncpg.connect = original_connect

        report = json.loads((directory / "compat-runtime-probes-latest.json").read_text())
        assert injected and report["scratch"]["database"] == owned["database"]
        assert report["scratch"]["oid"] is None
        assert report["scratch"]["oid_known"] is False
        assert report["failure"]["stage"] == "acquire-partial"
        assert report["guard_failure"]["stage"] == "cleanup-error"
        assert report["cleanup"]["dropped"] is False
        assert "identity_after" in report and "finished_at" not in report
        result.update(
            oid_unknown_preserved=True,
            partial_failure_stage_preserved=True,
            strict_cleanup_refused_incomplete_marker=True,
            terminal_report_contains_post_guard=True,
            recovery_record_mode=oct(Path(report["recovery_record"]).stat().st_mode & 0o777),
        )
        # Controlled reviewer recovery: first verify the independent CREATE ledger
        # and database comment; never infer ownership just from the retained name.
        admin = await original_connect(**options("postgres"))
        try:
            row = await admin.fetchrow(
                "SELECT oid, shobj_description(oid,'pg_database') AS marker "
                "FROM pg_database WHERE datname=$1",
                owned["database"],
            )
            assert row and row["oid"] == owned["oid"] and row["marker"] == ownership_comment
        finally:
            await admin.close()
        private = json.loads(Path(report["recovery_record"]).read_text())
        connection = await original_connect(**options(owned["database"]))
        try:
            await connection.execute(
                "CREATE TABLE probe_ownership "
                "(run_id TEXT PRIMARY KEY,secret TEXT NOT NULL,db_oid BIGINT NOT NULL)"
            )
            await connection.execute(
                "INSERT INTO probe_ownership VALUES ($1,$2,$3)",
                private["run_id"],
                private["scratch_secret"],
                owned["oid"],
            )
        finally:
            await connection.close()
        await compat.cleanup_scratch(
            values,
            {**owned, "run_id": private["run_id"], "secret": private["scratch_secret"]},
        )
        result["verified_manual_marker_recovery_then_formal_cleanup"] = True
    finally:
        asyncpg.connect = original_connect
        admin = await original_connect(**options("postgres"))
        try:
            row = await admin.fetchrow(
                "SELECT oid, shobj_description(oid,'pg_database') AS marker "
                "FROM pg_database WHERE datname=$1",
                owned.get("database", "__none__"),
            )
            if row is not None:
                # Fallback is limited to the reviewer's creation ledger + nonce.
                # Never terminate sessions, never clean an unrecognized database.
                assert row["oid"] == owned["oid"] and row["marker"] == ownership_comment
                attached = await admin.fetchval(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname=$1", owned["database"]
                )
                assert attached == 0
                await admin.execute(f'DROP DATABASE "{owned["database"]}"')
                result["reviewer_owned_fallback_cleanup"] = True
            else:
                result["reviewer_owned_fallback_cleanup"] = False
            result["owned_database_absent"] = (
                await admin.fetchval(
                    "SELECT 1 FROM pg_database WHERE datname=$1", owned.get("database", "__none__")
                )
                is None
            )
            result["remaining_probe_database_names"] = [
                r["datname"]
                for r in await admin.fetch(
                    "SELECT datname FROM pg_database WHERE datname LIKE 'lightrag_probe_%'"
                )
            ]
        finally:
            await admin.close()
        after = await compat.capture_production_identity(values, "review-after")
        result["production_identity_unchanged"] = {
            k: v for k, v in before.items() if k != "when"
        } == {k: v for k, v in after.items() if k != "when"}
        (OUT / "partial-live-verification.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )


asyncio.run(main())
