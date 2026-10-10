"""Read-only PG access helpers: single connection, read-only transaction, timeouts."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import uuid
from pathlib import Path

import asyncpg

STATEMENT_TIMEOUT_MS = 30_000


def redact_exception(exc: BaseException) -> dict[str, str]:
    """Keep only the exception type; messages may embed DSNs or credentials."""
    return {"error_type": type(exc).__name__}


async def _audit(dsn_kwargs: dict, out_dir: Path) -> dict:
    from .collect import collect_everything

    conn = await asyncpg.connect(statement_cache_size=0, timeout=10, **dsn_kwargs)
    try:
        async with conn.transaction(readonly=True, isolation="repeatable_read"):
            await conn.execute(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
            # G0-2: collect into a staging dir first; commit atomically. A failed
            # run never mixes partial files with published ones; retain its
            # diagnostic generation separately if collection or publication fails.
            staging = out_dir.parent / f".{out_dir.name}.staging-{uuid.uuid4().hex[:8]}"
            staging.mkdir(parents=True, exist_ok=True)
            phase = "collect"
            try:
                result = await collect_everything(conn, staging)
                phase = "publish"
                _commit(staging, out_dir)
                return result
            except Exception as exc:
                failure_path, failed_stage = _retain_failure(staging, out_dir, exc, phase)
                raise AuditError(
                    f"Phase-0 audit failed at stage '{failed_stage}': "
                    f"{type(exc).__name__}; evidence: {failure_path}"
                ) from None
            finally:
                shutil.rmtree(staging, ignore_errors=True)
    finally:
        await conn.close()


def _commit(staging: Path, out_dir: Path) -> None:
    """Publish an immutable generation through an atomic symlink replacement."""
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    runs = out_dir.parent / f".{out_dir.name}.runs"
    runs.mkdir(exist_ok=True)
    generation = runs / uuid.uuid4().hex
    os.replace(staging, generation)
    pointer = out_dir.parent / f".{out_dir.name}.pointer-{uuid.uuid4().hex}"
    legacy = None
    try:
        pointer.symlink_to(generation.relative_to(out_dir.parent), target_is_directory=True)
        # Existing ordinary directories require a one-time conversion; retain
        # and restore the whole directory if installing the pointer fails.
        if out_dir.exists() and not out_dir.is_symlink():
            legacy = runs / f"legacy-{uuid.uuid4().hex}"
            os.replace(out_dir, legacy)
        try:
            os.replace(pointer, out_dir)
        except Exception:
            if legacy is not None:
                os.replace(legacy, out_dir)
            raise
    except Exception:
        # Keep the un-published generation available for failure evidence.
        os.replace(generation, staging)
        raise
    finally:
        pointer.unlink(missing_ok=True)


def _retain_failure(staging: Path, out_dir: Path, exc: Exception, phase: str) -> tuple[Path, str]:
    staging.mkdir(parents=True, exist_ok=True)
    manifest_path = staging / "run-manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    status = manifest.get("status", "")
    failed_stage = status.removeprefix("failed_at:") if status.startswith("failed_at:") else phase
    manifest.update(
        status=f"failed_at:{failed_stage}",
        error_type=type(exc).__name__,
        run_id=manifest.get("run_id") or uuid.uuid4().hex[:16],
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    failures = out_dir.parent / f".{out_dir.name}.failures"
    failures.mkdir(parents=True, exist_ok=True)
    destination = failures / uuid.uuid4().hex
    os.replace(staging, destination)
    return destination, failed_stage


def run_audit(env_values: dict[str, str], out_dir: Path) -> dict:
    """Run the full audit. Errors are credential-free and locate the stage.

    Per-step failures are already recorded in run-manifest.json by
    collect_everything (with the failing step name); this wrapper only adds
    the connection/transport stage for errors raised outside that flow.
    """
    dsn_kwargs = {
        "host": env_values["POSTGRES_HOST"],
        "port": int(env_values["POSTGRES_PORT"]),
        "user": env_values["POSTGRES_USER"],
        "password": env_values["POSTGRES_PASSWORD"],
        "database": env_values["POSTGRES_DATABASE"],
    }
    try:
        return asyncio.run(_audit(dsn_kwargs, out_dir))
    except AuditError:
        raise
    except BaseException as exc:  # noqa: BLE001 - redacted re-raise
        failure = redact_exception(exc)
        stage = "connect" if isinstance(exc, (OSError, asyncpg.PostgresError)) else "audit-run"
        raise AuditError(
            f"Phase-0 audit failed at stage '{stage}': {failure['error_type']} "
            f"(details suppressed; step-level status is in run-manifest.json)"
        ) from None


class AuditError(RuntimeError):
    """Raised when the audit cannot complete; message is credential-free."""


# Backwards-compatible alias.
AuditConnectionError = AuditError
