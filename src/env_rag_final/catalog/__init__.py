"""Structure catalog for the env_rag application schema (Phase 1, corrected)."""

from . import builder, metadata, schema, scopes, units
from .builder import (
    RECIPE_ID,
    BuildResult,
    BuildVerificationError,
    SourceChangedError,
    build_catalog,
    build_identity,
    check_stale,
)
from .schema import (
    SCHEMA,
    MigrationError,
    applied_names,
    migrate,
    teardown,
    validate_schema_name,
)

__all__ = [
    "SCHEMA",
    "RECIPE_ID",
    "MigrationError",
    "applied_names",
    "migrate",
    "teardown",
    "validate_schema_name",
    "builder",
    "metadata",
    "schema",
    "scopes",
    "units",
    "BuildResult",
    "BuildVerificationError",
    "SourceChangedError",
    "build_catalog",
    "build_identity",
    "check_stale",
]
