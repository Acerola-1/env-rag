"""Explicit migrations for the application-owned catalog schema (task 2.1, S1).

Ownership rules (enforced, test-verified):
- Exactly ONE application schema name is supported: ``env_rag``. Any other
  value — public, system schemas, quoted/injected identifiers — is rejected
  *before any SQL is executed*.
- The migration ledger lives in the application schema; every DDL statement is
  written against that schema (no string rewriting of a fixed target).
- ``teardown`` verifies ownership first: the schema must exist, must be the
  application schema, and must contain only application-owned tables. Anything
  else aborts before dropping.
- ``public.lightrag_*`` is never touched: this module emits no statement that
  references it.

Object list (design.md decision 2; search_documents/search_chunks added in
Phase 2 tasks 4.2 with their own build ledger ``search_builds``):
    corpus_runs       — build ledger: version, source+recipe fingerprint, snapshot_id
    documents         — per-document catalog with provenance-tracked metadata
    source_units      — ordered raw block/table locators (定位信息 only)
    unit_chunk_links  — many-to-many units ↔ chunks with match basis
    scopes            — hierarchical chapter/clause/logical-table ranges
    scope_units       — ordered membership of scopes
    search_builds     — search index ledger (tokenizer/vocab/index recipe identity)
    search_documents  — document-level weighted tsvector
    search_chunks     — chunk-level weighted tsvector (cleaned text)
"""

from __future__ import annotations

import re

import asyncpg

SCHEMA = "env_rag"

_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

_APP_TABLES = (
    "corpus_runs",
    "documents",
    "source_units",
    "unit_chunk_links",
    "scopes",
    "scope_units",
    "schema_migrations",
    "search_builds",
    "search_documents",
    "search_chunks",
)


class MigrationError(RuntimeError):
    """Raised before any SQL executes when ownership cannot be proven."""


def validate_schema_name(schema_name: str) -> str:
    """Accept only the exact supported application schema.

    public, system schemas, quoted/injected identifiers all fail here — before
    any SQL runs.
    """
    if schema_name != SCHEMA:
        raise MigrationError(
            f"unsupported schema {schema_name!r}: this build supports only "
            f"'{SCHEMA}' (ownership cannot be proven for any other name); "
            "no SQL was executed"
        )
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", schema_name):
        raise MigrationError(f"invalid identifier {schema_name!r}")
    return schema_name


def _migration_ddl(schema: str) -> list[tuple[str, str]]:
    """All DDL written against the app schema (single source, no rewriting)."""
    s = schema
    return [
        (
            "0001_corpus_runs",
            f"""
            CREATE TABLE IF NOT EXISTS {s}.corpus_runs (
                run_id             TEXT PRIMARY KEY,
                recipe_id          TEXT NOT NULL,
                source_fingerprint JSONB NOT NULL,
                snapshot_id        TEXT NOT NULL,
                workspace          TEXT NOT NULL,
                status             TEXT NOT NULL CHECK (status IN ('building', 'active', 'failed', 'retired')),
                started_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
                finished_at        TIMESTAMPTZ,
                note               TEXT
            )
            """,
        ),
        (
            "0002_documents",
            f"""
            CREATE TABLE IF NOT EXISTS {s}.documents (
                workspace         TEXT NOT NULL,
                doc_id            TEXT NOT NULL,
                snapshot_id       TEXT NOT NULL,
                doc_name          TEXT,
                title             TEXT,
                title_confidence  TEXT NOT NULL DEFAULT 'unknown'
                                  CHECK (title_confidence IN ('extracted', 'inferred', 'unknown')),
                self_code         TEXT,
                self_code_version TEXT,
                referenced_codes  JSONB NOT NULL DEFAULT '[]'::jsonb,
                doc_type          TEXT,
                publish_date      TEXT,
                implement_date    TEXT,
                stats_period      TEXT,
                unknown_fields    JSONB NOT NULL DEFAULT '[]'::jsonb,
                field_provenance  JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                source_fingerprint TEXT,
                PRIMARY KEY (workspace, doc_id, snapshot_id)
            )
            """,
        ),
        (
            "0003_source_units",
            f"""
            CREATE TABLE IF NOT EXISTS {s}.source_units (
                workspace      TEXT NOT NULL,
                doc_id         TEXT NOT NULL,
                snapshot_id    TEXT NOT NULL,
                unit_id        TEXT NOT NULL,
                unit_kind      TEXT NOT NULL CHECK (unit_kind IN ('block', 'table')),
                unit_order     INTEGER NOT NULL,
                heading        TEXT,
                parent_headings JSONB NOT NULL DEFAULT '[]'::jsonb,
                level          INTEGER,
                caption        TEXT,
                table_seq      INTEGER,
                dimension      JSONB,
                content_length INTEGER,
                requires_span  BOOLEAN NOT NULL DEFAULT FALSE,
                locator        JSONB NOT NULL,
                PRIMARY KEY (workspace, doc_id, snapshot_id, unit_id)
            )
            """,
        ),
        (
            "0004_unit_chunk_links",
            f"""
            CREATE TABLE IF NOT EXISTS {s}.unit_chunk_links (
                workspace      TEXT NOT NULL,
                doc_id         TEXT NOT NULL,
                snapshot_id    TEXT NOT NULL,
                unit_id        TEXT NOT NULL,
                chunk_id       TEXT NOT NULL,
                chunk_order    INTEGER NOT NULL,
                match_basis    TEXT NOT NULL CHECK (match_basis IN ('sidecar_ref', 'inline_table_id')),
                coverage_status TEXT NOT NULL DEFAULT 'partial'
                                CHECK (coverage_status IN ('full', 'partial')),
                PRIMARY KEY (workspace, doc_id, snapshot_id, unit_id, chunk_id)
            )
            """,
        ),
        (
            "0005_scopes",
            f"""
            CREATE TABLE IF NOT EXISTS {s}.scopes (
                workspace      TEXT NOT NULL,
                doc_id         TEXT NOT NULL,
                snapshot_id    TEXT NOT NULL,
                scope_id       TEXT NOT NULL,
                scope_kind     TEXT NOT NULL CHECK (scope_kind IN ('chapter', 'clause', 'logical_table')),
                parent_scope_id TEXT,
                title          TEXT,
                number         TEXT,
                confirm_status TEXT NOT NULL DEFAULT 'ambiguous'
                                CHECK (confirm_status IN ('confirmed', 'partial', 'ambiguous', 'requires_span')),
                note           TEXT,
                PRIMARY KEY (workspace, doc_id, snapshot_id, scope_id)
            )
            """,
        ),
        (
            "0006_scope_units",
            f"""
            CREATE TABLE IF NOT EXISTS {s}.scope_units (
                workspace   TEXT NOT NULL,
                doc_id      TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                scope_id    TEXT NOT NULL,
                unit_id     TEXT NOT NULL,
                seq         INTEGER NOT NULL,
                PRIMARY KEY (workspace, doc_id, snapshot_id, scope_id, seq),
                FOREIGN KEY (workspace, doc_id, snapshot_id, unit_id)
                    REFERENCES {s}.source_units (workspace, doc_id, snapshot_id, unit_id) ON DELETE CASCADE,
                FOREIGN KEY (workspace, doc_id, snapshot_id, scope_id)
                    REFERENCES {s}.scopes (workspace, doc_id, snapshot_id, scope_id) ON DELETE CASCADE
            )
            """,
        ),
        (
            "0007_indexes",
            f"""
            CREATE INDEX IF NOT EXISTS idx_cat_units_doc
                ON {s}.source_units (workspace, doc_id, snapshot_id, unit_order);
            CREATE INDEX IF NOT EXISTS idx_cat_links_chunk
                ON {s}.unit_chunk_links (workspace, chunk_id);
            CREATE INDEX IF NOT EXISTS idx_cat_scopes_doc
                ON {s}.scopes (workspace, doc_id, snapshot_id, scope_kind);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_cat_runs_active
                ON {s}.corpus_runs (workspace) WHERE status = 'active';
            CREATE INDEX IF NOT EXISTS idx_cat_runs_snapshot
                ON {s}.corpus_runs (workspace, snapshot_id, status);
            """,
        ),
        (
            "0008_search_builds",
            f"""
            CREATE TABLE IF NOT EXISTS {s}.search_builds (
                search_id           TEXT PRIMARY KEY,
                workspace           TEXT NOT NULL,
                catalog_snapshot_id TEXT NOT NULL,
                source_fingerprint  TEXT NOT NULL,
                tokenizer_version   TEXT NOT NULL,
                vocab_sha           TEXT NOT NULL,
                index_recipe        TEXT NOT NULL,
                status              TEXT NOT NULL CHECK (status IN ('building', 'active', 'failed', 'retired')),
                started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
                finished_at         TIMESTAMPTZ,
                note                TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS uq_search_active
                ON {s}.search_builds (workspace) WHERE status = 'active';
            """,
        ),
        (
            "0009_search_objects",
            f"""
            CREATE TABLE IF NOT EXISTS {s}.search_documents (
                workspace   TEXT NOT NULL,
                doc_id      TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                search_id   TEXT NOT NULL,
                doc_name    TEXT,
                title       TEXT,
                self_code   TEXT,
                self_code_version TEXT,
                doc_type    TEXT,
                search_text TEXT NOT NULL DEFAULT '',
                tsv         tsvector NOT NULL,
                PRIMARY KEY (workspace, doc_id, snapshot_id, search_id)
            );
            CREATE INDEX IF NOT EXISTS idx_sdoc_gin ON {s}.search_documents USING GIN (tsv);
            CREATE INDEX IF NOT EXISTS idx_sdoc_identity
                ON {s}.search_documents (workspace, search_id, doc_id);

            CREATE TABLE IF NOT EXISTS {s}.search_chunks (
                workspace   TEXT NOT NULL,
                doc_id      TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                search_id   TEXT NOT NULL,
                chunk_id    TEXT NOT NULL,
                chunk_order INTEGER NOT NULL,
                heading     TEXT,
                captions    TEXT,
                search_text TEXT NOT NULL,
                tsv         tsvector NOT NULL,
                PRIMARY KEY (workspace, doc_id, snapshot_id, chunk_id, search_id)
            );
            CREATE INDEX IF NOT EXISTS idx_schunk_gin ON {s}.search_chunks USING GIN (tsv);
            CREATE INDEX IF NOT EXISTS idx_schunk_identity
                ON {s}.search_chunks (workspace, search_id, doc_id, chunk_order);
            """,
        ),
    ]


def _assert_no_foreign_targets(sql: str) -> None:
    """Defense in depth: DDL must not mention public or lightrag objects."""
    lowered = sql.lower()
    if "public." in lowered or "lightrag" in lowered:
        raise MigrationError(f"DDL references foreign objects: {sql[:80]}")


async def _verify_ownership(conn: asyncpg.Connection, schema_name: str) -> None:
    """Ownership proof before teardown: only known application tables inside."""
    exists = await conn.fetchval(
        "SELECT count(*) FROM information_schema.schemata WHERE schema_name=$1", schema_name
    )
    if not exists:
        raise MigrationError(f"schema '{schema_name}' does not exist; nothing to tear down")
    placeholders = ", ".join(f"'{t}'" for t in _APP_TABLES)
    foreign = await conn.fetchval(
        f"""SELECT count(*) FROM information_schema.tables
            WHERE table_schema=$1 AND table_name NOT IN ({placeholders})""",
        schema_name,
    )
    if foreign:
        raise MigrationError(
            f"schema '{schema_name}' contains {foreign} non-application table(s); "
            "ownership cannot be proven — aborting teardown"
        )


async def migrate(conn: asyncpg.Connection) -> list[str]:
    """Apply pending migrations into the application schema (idempotent)."""
    applied: list[str] = []
    async with conn.transaction():
        await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        await conn.execute(
            f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.schema_migrations (
                   name TEXT PRIMARY KEY,
                   applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
               )"""
        )
    done = {r["name"] for r in await conn.fetch(f"SELECT name FROM {SCHEMA}.schema_migrations")}
    for name, sql in _migration_ddl(SCHEMA):
        if name in done:
            continue
        _assert_no_foreign_targets(sql)
        async with conn.transaction():
            await conn.execute(sql)
            await conn.execute(f"INSERT INTO {SCHEMA}.schema_migrations (name) VALUES ($1)", name)
        applied.append(name)
    return applied


async def applied_names(conn: asyncpg.Connection) -> list[str]:
    return [
        r["name"]
        for r in await conn.fetch(f"SELECT name FROM {SCHEMA}.schema_migrations ORDER BY name")
    ]


async def teardown(conn: asyncpg.Connection) -> None:
    """Drop the application schema after proving it contains only our objects.

    Refuses at two gates, both before any DROP runs: the schema-name check
    (public/system/injection) and the ownership check (foreign tables inside).
    """
    validate_schema_name(SCHEMA)
    await _verify_ownership(conn, SCHEMA)
    await conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
