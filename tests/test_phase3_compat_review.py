"""5.1 safety acceptance: fake connections only; never create/drop a real DB."""

import asyncio

import pytest

from env_rag_final import compat_runtime as compat

VALUES = {
    "POSTGRES_HOST": "test.invalid",
    "POSTGRES_PORT": "5432",
    "POSTGRES_USER": "fixture",
    "POSTGRES_PASSWORD": "fixture",
    "POSTGRES_DATABASE": "rag",
}


class UnownedDatabase:
    def __init__(self):
        self.mutations = []
        self.closed = False

    async def fetchval(self, sql, *args):
        if "pg_database" in sql:
            return 1  # An existing database, with no task ownership evidence.
        if "shobj_description" in sql:
            return None
        return 0

    async def fetch(self, sql, *args):
        return []

    async def fetchrow(self, sql, *args):
        return {"oid": 1, "datname": compat.SCRATCH_DB, "ownership_marker": None}

    async def execute(self, sql, *args):
        self.mutations.append(sql)

    async def close(self):
        self.closed = True


def install_connection(monkeypatch, connection):
    async def connect(**kwargs):
        return connection

    monkeypatch.setattr(compat.asyncpg, "connect", connect)


def test_existing_unowned_database_cannot_be_reused(monkeypatch):
    connection = UnownedDatabase()
    install_connection(monkeypatch, connection)
    # Refusal must happen before handing the database to LightRAG initialization.
    with pytest.raises(Exception):
        asyncio.run(compat._ensure_scratch(VALUES))
    assert connection.mutations == []
    assert connection.closed


def test_cleanup_cannot_terminate_or_drop_unowned_database(monkeypatch):
    connection = UnownedDatabase()
    install_connection(monkeypatch, connection)
    with pytest.raises(Exception):
        asyncio.run(compat.cleanup(VALUES))
    assert connection.mutations == []
    assert connection.closed


def test_production_count_change_aborts_probe(monkeypatch):
    class ChangedProduction(UnownedDatabase):
        async def fetchval(self, sql, *args):
            counts = {
                "lightrag_doc_full": 222,  # Frozen count is 221.
                "lightrag_doc_chunks": 5709,
                "lightrag_doc_status": 279,
                "lightrag_llm_cache": 16514,
                "lightrag_entity_chunks": 65527,
                "lightrag_full_entities": 221,
                "lightrag_full_relations": 221,
                "lightrag_relation_chunks": 119575,
            }
            return counts[sql.split("public.", 1)[1]]

    connection = ChangedProduction()
    install_connection(monkeypatch, connection)
    report = {}
    with pytest.raises(Exception):
        asyncio.run(compat.verify_production_untouched(VALUES, report))
    assert connection.mutations == []
    assert connection.closed
