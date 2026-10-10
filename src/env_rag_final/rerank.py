"""Task 5.4: one joint rerank over the fused candidate set (task 5.3 output).

Contracts (handoff-phase-3-5.4.md):
- The WHOLE usable merged set from 5.3 is sent to ONE rerank request — never
  PG and local scored separately and stitched, never local-only, never the
  display head instead of the full read-back text.
- Every input keeps a stable input index and its (workspace, chunk_id)
  identity, full text, doc attribution, content SHA, both paths and the
  typed doc/scope/table targets (targets stay out of the scored text).
- The verified service contract (SiliconFlow /v1/rerank, Cohere-style):
  POST {model, query, documents, top_n, return_documents} ->
  {id, results: [{index, relevance_score}], meta}. rerank_score is set ONLY
  from a real response — never fabricated. Ordering maps back through the
  response index (never through text equality); same text in two versions
  stays two sources.
- Response validation: coverage of ALL input indices exactly once, no
  out-of-range/missing/duplicates; scores must be finite numbers (bool /
  str / NaN / Inf rejected). Ties keep the original input order. A
  missing/invalid response never claims rerank success.
- Failures (timeout / 401/403 / non-2xx / JSON or structure errors) record
  real status, elapsed, error type and safe response evidence (never
  headers/keys); fallback to the original fusion order is an EXPLICIT
  degraded result with no fabricated scores. No borrowing a previous
  query's response.
- Empty input / missing / stale / constraint-rejected candidates record the
  skip reason and ZERO calls; identity drift stops trusted publication with
  the unified 5.3 terminal contract (per-query ledger, original error).
- The full retained set (≤40) is sent; if the service input budget is
  exceeded the character budget and unsent set are recorded and the run
  degrades explicitly — never a silent truncation claimed as full.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import asyncpg
import httpx
from dotenv import dotenv_values

from env_rag_final.fusion import (
    GOLD_PATH,
    AdapterError,
    _capture_identity,
    _identity_drift,
    verify_config_guard,
    verify_gold_guard,
)

RERANK_INPUT_BUDGET = 40  # the 5.4 handoff: send the FULL retained set (≤40)

_SCORE_FIELDS_CONTRACT = {
    "endpoint": "{host}/v1/rerank (POST)",
    "request": ["model", "query", "documents", "top_n", "return_documents=false"],
    "response": ["id", "results[{index, relevance_score}]", "meta.tokens"],
    "errors": {"401/403": "auth", "429": "rate limit", "5xx": "service"},
}

# credentials that must NEVER appear in persisted evidence (R4)
_SENSITIVE_KEYS = ("api_key", "authorization", "password", "token", "secret")


def _sanitize_evidence(value, values: dict):
    """R4/C3: recursively scrub configured secrets / sensitive fields from any
    evidence before it is persisted. Failure evidence stays (status, error
    type, non-sensitive reason) — only credential material is removed.

    Secrets are applied LONGEST-FIRST: a short credential value (e.g. a
    single-character fixture placeholder) that also occurs inside a longer
    secret must not be replaced first, or it corrupts the longer secret and
    the leak survives."""
    secrets = sorted(
        {
            v
            for k, v in (values or {}).items()
            if isinstance(v, str)
            and v
            and any(s in k.lower() for s in ("key", "password", "secret", "token"))
        },
        key=len,
        reverse=True,
    )
    if isinstance(value, str):
        red = value
        for s in secrets:
            red = red.replace(s, "<redacted>")
        return red
    if isinstance(value, dict):
        return {
            k: (
                "<redacted>"
                if any(s in str(k).lower() for s in _SENSITIVE_KEYS)
                else _sanitize_evidence(v, values)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_evidence(v, values) for v in value]
    return value


class _PreflightRejection(Exception):
    """R3: a refusal inside the unified zero-contact pre-flight boundary;
    carries the terminal stage and detail for the failure report."""

    def __init__(self, stage: str, detail):
        super().__init__(f"{stage}: {detail}")
        self.stage = stage
        self.detail = detail


# ---------------------------------------------------------------------------
# R1: replay input binding — identity, content and source verification
# ---------------------------------------------------------------------------


def _verify_replay_binding(replay_body: dict, identity_before: dict) -> list[str]:
    """The replayed fusion report must carry the SAME production identity as
    the live capture; a mismatched/missing fingerprint refuses the replay —
    an arbitrary file is never trusted just because the live DB is frozen."""
    problems: list[str] = []
    replay_after = replay_body.get("identity_after") or {}
    if not replay_after:
        problems.append("replay report has no identity_after; provenance unknown")
        return problems
    checks = {
        "source_fingerprint": identity_before.get("source_fingerprint"),
        "search_active": identity_before.get("search_active"),
        "gold_sha": identity_before.get("gold_sha"),
    }
    for field, live_value in checks.items():
        if replay_after.get(field) != live_value:
            problems.append(f"replay {field} {replay_after.get(field)!r} != live {live_value!r}")
    replay_cat = replay_after.get("catalog_active") or {}
    live_cat = identity_before.get("catalog_active") or {}
    if replay_cat.get("snapshot_id") != live_cat.get("snapshot_id"):
        problems.append(
            f"replay catalog snapshot {replay_cat.get('snapshot_id')!r} != live "
            f"{live_cat.get('snapshot_id')!r}"
        )
    return problems


async def _verify_candidates_against_source(
    values: dict, workspace: str, candidates: list[dict]
) -> tuple[list[dict], list[str]]:
    """R1/C1: read the CURRENT production PG rows for every replayed candidate.

    Verifies per candidate: (workspace, chunk_id) exists in the CURRENT
    source, verified flag, and that the replayed text is byte-identical to
    the current production content (a re-computed SHA over tampered text is
    not proof — the production row is). C1: the PUBLISHED metadata is
    CANONICALIZED from the real production row — content_sha256/length are
    recomputed over the verified row content and doc_id is backfilled from
    full_doc_id (the replay's original values are kept under ``replayed_*``
    with the repair basis recorded); stale/empty doc_id and wrong SHAs can
    never be published as verified metadata unchanged."""
    import hashlib

    problems: list[str] = []
    ids = sorted({c.get("chunk_id") for c in candidates if c.get("chunk_id")})
    rows: dict = {}
    if ids:
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
            pg_rows = await conn.fetch(
                """SELECT id, workspace, full_doc_id, content, file_path
                   FROM public.lightrag_doc_chunks
                   WHERE workspace = $1 AND id = ANY($2)""",
                workspace,
                ids,
            )
        finally:
            await conn.close()
        rows = {r["id"]: r for r in pg_rows}
    verified: list[dict] = []
    for c in candidates:
        cid = c.get("chunk_id")
        row = rows.get(cid)
        if row is None:
            problems.append(f"{cid}: not found in current production PG (workspace={workspace})")
            continue
        if c.get("workspace") != workspace:
            problems.append(
                f"{cid}: replay workspace {c.get('workspace')!r} != request {workspace!r}"
            )
            continue
        if c.get("verified") is not True:
            problems.append(f"{cid}: replay marks the candidate unverified")
            continue
        content = row["content"] or ""
        if c.get("content") != content:
            problems.append(
                f"{cid}: replayed text differs from the CURRENT production content "
                "(a recomputed SHA over tampered text is not source proof)"
            )
            continue
        # C1/D2: canonicalize the published metadata from the CURRENT row —
        # doc/SHA/length are ALWAYS the row's values; every actual change is
        # recorded (a wrong length counts even when doc/SHA already matched).
        row_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        row_len = len(content)
        replayed_doc = c.get("doc_id")
        if replayed_doc and row["full_doc_id"] != replayed_doc:
            problems.append(
                f"{cid}: replay doc {replayed_doc} != production full_doc_id {row['full_doc_id']}"
            )
            continue
        replayed_sha = c.get("content_sha256")
        replayed_len = c.get("content_len")
        if replayed_doc != row["full_doc_id"] or replayed_sha != row_sha or replayed_len != row_len:
            c = dict(c)
            c["replayed_doc_id"] = replayed_doc
            c["replayed_content_sha256"] = replayed_sha
            c["replayed_content_len"] = replayed_len
            c["canonicalization_basis"] = (
                "metadata repaired from the CURRENT production row after the replay "
                "text was verified byte-identical; original replay values kept in "
                "replayed_* fields"
            )
            c["repair_fields"] = [
                name
                for name, old, new in (
                    ("doc_id", replayed_doc, row["full_doc_id"]),
                    ("content_sha256", replayed_sha, row_sha),
                    ("content_len", replayed_len, row_len),
                )
                if old != new
            ]
        c["doc_id"] = row["full_doc_id"]
        c["content_sha256"] = row_sha
        c["content_len"] = row_len
        verified.append(c)
    return verified, problems


async def _enrich_table_paths(
    values: dict, workspace: str, snapshot_id: str | None, candidates: list[dict]
) -> tuple[list[dict], list[str]]:
    """R2/C2: replayed candidates may predate the 5.3-F2 table-fragment path
    fix — their paths lack unit_id/table_id. Enrich them from the REAL
    catalog mapping, joined with source_units to get each unit's ACTUAL
    kind: only real tables create table_unit/table_id citations; block (and
    other non-table) links keep block/source_unit semantics — a body block
    is never dressed up as a table fragment. The active snapshot id is
    REQUIRED (no scanning across generations when it is missing); the
    enrichment is additive (original paths kept verbatim) and always marked
    as association completion, never as a new PG retrieval hit."""
    notes: list[str] = []
    if not snapshot_id:
        notes.append(
            "path enrichment skipped: no verified active catalog snapshot on the "
            "replay; cross-generation scans are forbidden"
        )
        return candidates, notes
    ids = sorted({c.get("chunk_id") for c in candidates if c.get("chunk_id")})
    if not ids:
        return candidates, notes
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
        links = await conn.fetch(
            """SELECT l.unit_id, l.doc_id, l.chunk_id, u.unit_kind
               FROM env_rag.unit_chunk_links l
               JOIN env_rag.source_units u
                 ON u.workspace = l.workspace AND u.snapshot_id = l.snapshot_id
                AND u.doc_id = l.doc_id AND u.unit_id = l.unit_id
               WHERE l.workspace=$1 AND l.snapshot_id=$2 AND l.chunk_id = ANY($3::text[])
               ORDER BY l.doc_id, l.unit_id, l.chunk_order""",
            workspace,
            snapshot_id,
            ids,
        )
    finally:
        await conn.close()
    links_by_chunk: dict = {}
    for link in links:
        links_by_chunk.setdefault(link["chunk_id"], []).append(link)
    enriched_tables = 0
    enriched_blocks = 0
    for c in candidates:
        for link in links_by_chunk.get(c.get("chunk_id")) or []:
            uid = link["unit_id"]
            kind = link.get("unit_kind")
            existing_units = {p.get("unit_id") for p in c.get("paths", []) if p.get("unit_id")}
            if uid in existing_units:
                continue
            if kind == "table":
                enriched_tables += 1
                c.setdefault("paths", []).append(
                    {
                        "path": "pg",
                        "unit_id": uid,
                        "table_id": uid,
                        "citation": {
                            "kind": "table_unit",
                            "workspace": workspace,
                            "snapshot_id": snapshot_id,
                            "doc_id": link["doc_id"],
                            "table_id": uid,
                            "chunk_ids": [c.get("chunk_id")],
                        },
                        "enrichment_basis": (
                            "association completion from env_rag.unit_chunk_links + "
                            "source_units (unit_kind=table); replay predates the "
                            "5.3-F2 path fix — NOT a new retrieval hit or a "
                            "requested-range confirmation"
                        ),
                        "score": {"kind": "none", "value": None},
                    }
                )
            else:
                # block / other non-table unit: keep its real semantics
                enriched_blocks += 1
                c.setdefault("paths", []).append(
                    {
                        "path": "pg",
                        "unit_id": uid,
                        "unit_kind": kind or "unknown",
                        "citation": {
                            "kind": "source_unit",
                            "workspace": workspace,
                            "snapshot_id": snapshot_id,
                            "doc_id": link["doc_id"],
                            "unit_id": uid,
                            "unit_kind": kind or "unknown",
                            "chunk_ids": [c.get("chunk_id")],
                        },
                        "enrichment_basis": (
                            "association completion from env_rag.unit_chunk_links + "
                            "source_units (unit_kind="
                            f"{kind or 'unknown'}); body-block association, never a "
                            "table fragment"
                        ),
                        "score": {"kind": "none", "value": None},
                    }
                )
    if enriched_tables or enriched_blocks:
        notes.append(
            f"association completion: {enriched_tables} table fragment path(s) and "
            f"{enriched_blocks} non-table (block/source_unit) path(s) from "
            "unit_chunk_links JOIN source_units by actual unit_kind (replay paths "
            "predate the 5.3-F2 fix); no id/locator/kind guessed"
        )
    return candidates, notes


# ---------------------------------------------------------------------------
# Input preparation: identity + full text, never display summaries
# ---------------------------------------------------------------------------


def _rerank_inputs(fused_result: dict) -> tuple[list[dict], list[str]]:
    """Build the scored input list from a 5.3 fused result.

    Only USABLE merged chunk candidates with read-back full text enter the
    scored set; typed doc/scope/table targets are returned separately and
    never dressed up as chunk text. Each input keeps its stable index,
    identity, paths and content SHA."""
    inputs: list[dict] = []
    skipped: list[str] = []
    for c in fused_result.get("usable", []):
        text = c.get("content")
        if not text:
            skipped.append(
                f"{c.get('chunk_id')}: no read-back full text; display heads are "
                "never sent instead of the text"
            )
            continue
        record = {
            "input_index": len(inputs),
            "workspace": c.get("workspace"),
            "chunk_id": c.get("chunk_id"),
            "doc_id": c.get("doc_id"),
            "content_sha256": c.get("content_sha256"),
            "content_len": c.get("content_len"),
            "paths": c.get("paths", []),
            "text": text,
        }
        # D2: canonical-repair provenance is PUBLISHED (not kept only in the
        # local verified dict): original replay values, the repair basis and
        # which fields actually changed travel into the final report. Key
        # presence marks "was repaired" — a repaired-to value (e.g. an empty
        # replayed doc_id) is itself the evidence, so it must survive even
        # when its original is None.
        for repair_field in (
            "replayed_doc_id",
            "replayed_content_sha256",
            "replayed_content_len",
            "canonicalization_basis",
            "repair_fields",
        ):
            if repair_field in c:
                record[repair_field] = c[repair_field]
        inputs.append(record)
    return inputs, skipped


# ---------------------------------------------------------------------------
# Response validation (real contract, no fabrication)
# ---------------------------------------------------------------------------


def _finite_score(value) -> bool:
    """R3: overflow-safe finiteness — an absurd JSON integer (10**400) makes
    math.isfinite itself raise OverflowError; such a value is simply not a
    usable finite score, never an uncaught crash."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def _validate_response(payload, expected_count: int) -> tuple[list[dict] | None, str | None]:
    """Validate the rerank response against the verified contract.

    Returns (validated results sorted by (−score, input_index), error)."""
    if not isinstance(payload, dict):
        return None, f"response is not a JSON object ({type(payload).__name__})"
    results = payload.get("results")
    if not isinstance(results, list):
        return None, "response has no results array"
    seen: set = set()
    validated: list[dict] = []
    for r in results:
        if not isinstance(r, dict):
            return None, "results entry is not an object"
        idx = r.get("index")
        if isinstance(idx, bool) or not isinstance(idx, int):
            return None, f"result index is not an integer ({idx!r})"
        if idx < 0 or idx >= expected_count:
            return None, f"result index {idx} out of range [0, {expected_count})"
        if idx in seen:
            return None, f"duplicate result index {idx}"
        seen.add(idx)
        score = r.get("relevance_score")
        if not _finite_score(score):
            return None, f"relevance_score for index {idx} is not a finite number ({score!r})"
        try:
            score_f = float(score)
        except (OverflowError, ValueError):
            return None, f"relevance_score for index {idx} cannot be represented as float"
        validated.append({"index": idx, "relevance_score": score_f})
    missing = sorted(set(range(expected_count)) - seen)
    if missing:
        return None, f"response missing indices {missing[:8]} ({len(missing)} of {expected_count})"
    validated.sort(key=lambda r: (-r["relevance_score"], r["index"]))
    return validated, None


def _validate_response_safe(payload, expected_count: int) -> tuple[list[dict] | None, str | None]:
    """R3: the response validation itself can never escape with an unhandled
    exception (malformed nesting, absurd values, exotic types) — any internal
    error becomes an explicit rejection with its reason."""
    try:
        return _validate_response(payload, expected_count)
    except Exception as exc:  # noqa: BLE001 — any validation crash is a rejection
        return None, f"response validation failed ({type(exc).__name__}: {exc})"


# ---------------------------------------------------------------------------
# The one real rerank call (bounded, recorded, never fabricated)
# ---------------------------------------------------------------------------


async def _call_rerank(values: dict, query: str, documents: list[str], transport=None) -> dict:
    """One bounded rerank HTTP call; records real status/elapsed/error."""
    host = (values.get("RERANK_BINDING_HOST") or "").rstrip("/")
    # the configured host may already carry the endpoint path (…/v1/rerank);
    # only append the contract path when the host is a bare origin.
    url = host if host.endswith("/rerank") else f"{host}/v1/rerank"
    started = time.monotonic()
    record: dict = {
        "service": "rerank",
        "operation": "rerank",
        "endpoint": "/v1/rerank",
        "url_path_used": "configured-endpoint" if host.endswith("/rerank") else "host+/v1/rerank",
        "model": values.get("RERANK_MODEL"),
        "documents_sent": len(documents),
        "chars_sent": sum(len(d) for d in documents),
    }
    try:
        if transport is not None:
            # test/fixed-replay transport: the request body is passed through
            # so the recorded receipt still reflects the real payload shape.
            resp = await transport(query, documents)
        else:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {values.get('RERANK_BINDING_API_KEY')}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": values.get("RERANK_MODEL"),
                        "query": query,
                        "documents": documents,
                        "return_documents": False,
                    },
                )
        record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        record["status_code"] = resp.status_code
        if resp.status_code != 200:
            record["status"] = "failure"
            record["error"] = f"HTTP {resp.status_code}"
            # C3: sanitize FIRST, then bound the length — truncating before
            # sanitizing can cut a secret across the boundary and leave its
            # unredacted prefix in the report.
            record["response_evidence"] = _sanitize_evidence(resp.text, values)[:300]
            return record
        try:
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001 — recorded, then explicit failure
            record["status"] = "failure"
            record["error"] = f"non-JSON response ({type(exc).__name__})"
            record["response_evidence"] = _sanitize_evidence(resp.text, values)[:300]
            return record
        record["status"] = "success"
        # shape/size summary for the call record; the RAW response (index/
        # score/meta) is retained separately by _rerank_one for independent
        # re-verification (R4).
        record["response_evidence"] = {
            "id": payload.get("id") if isinstance(payload, dict) else None,
            "results_len": len(payload.get("results") or []) if isinstance(payload, dict) else 0,
        }
        record["payload"] = payload
        return record
    except Exception as exc:  # noqa: BLE001 — real failure receipt, then degrade
        record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        record["status"] = "failure"
        record["error"] = _sanitize_evidence(f"{type(exc).__name__}: {exc}", values)[:200]
        return record


# ---------------------------------------------------------------------------
# Owning orchestration entry
# ---------------------------------------------------------------------------


async def run_rerank(
    report_dir: Path,
    query_ids: list[str] | None = None,
    fused_report_path: Path | None = None,
    transport=None,
) -> dict:
    """Joint rerank over the 5.3 fused usable sets (replay inputs, one real
    call per query, no retrieval round-trip). ``transport`` injects a fixed
    replay/fake transport (tests); production passes None for real HTTP."""
    report: dict = {
        "task": "5.4 joint rerank over fused candidates (bounded, recorded)",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "service_contract": _SCORE_FIELDS_CONTRACT,
        "input_budget": RERANK_INPUT_BUDGET,
    }
    report_dir.mkdir(parents=True, exist_ok=True)

    def _write_terminal() -> None:
        # C3: the WHOLE report passes sanitization at the single write point —
        # pre-flight/identity/failure details and any other embedded evidence
        # can never leak configured secrets, whatever path produced them.
        safe_report = _sanitize_evidence(report, values_ref["v"])
        stamp = time.strftime("%Y%m%dT%H%M%S")
        body = json.dumps(safe_report, ensure_ascii=False, indent=1) + "\n"
        (report_dir / f"rerank-runtime-{stamp}.json").write_text(body, encoding="utf-8")
        (report_dir / "rerank-runtime-latest.json").write_text(body, encoding="utf-8")

    async def _write_failure(stage: str, detail) -> None:
        report["failure"] = {"stage": stage, "detail": detail}
        _write_terminal()

    values_ref = {"v": None}
    values_ref["v"] = dict(dotenv_values(".env"))
    values = values_ref["v"]
    fused_path = fused_report_path or Path(
        "reports/pg-retrieval/phase-3-fusion/fusion-runtime-latest.json"
    )
    wanted = query_ids or ["fact-002"]

    # ---- R3: the WHOLE pre-flight (gold read/parse/structure, unknown ids,
    # config+key checks, SHA, fused-report read/parse) sits inside ONE
    # zero-backend-contact failure boundary — every ordinary rejection writes
    # the zero-call failure terminal with the real error type/reason before
    # re-raising. BaseException is never caught; nothing is swallowed.
    zero_call_ledger = {
        "query_id": None,
        "call_records": [],
        "group_records": [],
        "by_service": {},
        "groups": {},
        "note": "pre-flight rejection before any backend read or service call",
    }
    try:
        gold_text = GOLD_PATH.read_text(encoding="utf-8")
        gold = json.loads(gold_text)
        by_id = {q["query_id"]: q for q in gold["questions"]}
        for c in gold.get("counter_examples", []):
            cid = c.get("counter_id")
            if cid and cid not in by_id:
                by_id[cid] = {
                    "query_id": cid,
                    "question": c.get("question") or "",
                    "workspace": "default",
                }
        unknown = [q for q in wanted if q not in by_id]
        if unknown:
            raise _PreflightRejection("unknown-query-id", unknown)
        for qid in wanted:
            verify_config_guard(values, by_id[qid].get("workspace") or "default")
            if not (values.get("RERANK_BINDING_HOST") and values.get("RERANK_MODEL")):
                raise AdapterError("RERANK_BINDING_HOST / RERANK_MODEL missing in .env")
            # R3: a missing API key must never become "Bearer None" on the wire
            if not (values.get("RERANK_BINDING_API_KEY") or "").strip():
                raise AdapterError("RERANK_BINDING_API_KEY missing in .env")
        gold_sha = verify_gold_guard(GOLD_PATH)
        fused = json.loads(fused_path.read_text(encoding="utf-8"))
        fused_by_id = {r["query_id"]: r for r in fused.get("results", [])}
        fused_identity_after = fused.get("identity_after")
    except _PreflightRejection as exc:
        report["failure_service_records"] = dict(zero_call_ledger)
        await _write_failure(exc.stage, exc.detail)
        raise AdapterError(f"{exc.stage} (rejected before any call): {exc.detail}") from exc
    except json.JSONDecodeError as exc:
        report["failure_service_records"] = dict(zero_call_ledger)
        await _write_failure("pre-flight-parse", f"{type(exc).__name__}: {exc}")
        raise AdapterError(f"pre-flight parse failed (zero service calls): {exc}") from exc
    except AdapterError as exc:
        report["failure_service_records"] = dict(zero_call_ledger)
        await _write_failure("pre-flight", str(exc))
        raise
    except OSError as exc:
        report["failure_service_records"] = dict(zero_call_ledger)
        await _write_failure("pre-flight-read", f"{type(exc).__name__}: {exc}")
        raise AdapterError(f"pre-flight read failed (zero service calls): {exc}") from exc
    except Exception as exc:
        # R3 unified fallback: structural/config failures of ANY ordinary
        # exception type still write the zero-call terminal; original type
        # and cause preserved. BaseException deliberately not caught.
        report["failure_service_records"] = dict(zero_call_ledger)
        await _write_failure("pre-flight", f"{type(exc).__name__}: {exc}")
        raise
    report["gold_sha_verified"] = gold_sha

    try:
        pre = await _capture_identity(values)
    except Exception as exc:  # noqa: BLE001
        await _write_failure("identity-capture", f"{type(exc).__name__}: {exc}")
        raise AdapterError("pre-flight identity capture failed") from exc
    report["identity_before"] = {
        "matches_frozen": pre["matches_frozen"],
        "problems": pre["problems"],
        "counts": pre["identity"]["public_counts"],
        "source_fingerprint": pre["identity"]["source_fingerprint"],
        "catalog_active": pre["identity"]["catalog_active"],
        "search_active": pre["identity"]["search_active"],
        "gold_sha": pre["identity"]["gold_sha"],
        "env_sha": pre["identity"]["env_sha"],
    }
    if not pre["matches_frozen"]:
        await _write_failure("identity-before", pre["problems"])
        raise AdapterError("pre-flight identity mismatch: " + "; ".join(pre["problems"]))

    results: list[dict] = []
    run_error: str | None = None
    failed_query_id: str | None = None
    # R3/D2: the running query publishes its real call receipt into `live`
    # the moment the HTTP exchange completes — never only on a successful
    # return; a new query resets the slot BEFORE any contact (F3-b heritage).
    # The in-flight per-query record is shared, so a mid-query failure still
    # keeps its inputs/verification/repair evidence in the terminal.
    live: dict = {"query_id": None, "call": None, "partial": None}
    try:
        for qid in wanted:
            failed_query_id = qid
            live["query_id"] = qid
            live["call"] = None
            live["partial"] = None
            fused_result = fused_by_id.get(qid)
            if fused_result is not None:
                # R1: the replayed entry must carry this query's identity —
                # source/catalog/search/gold binding checked against the live
                # capture BEFORE any service contact. The binding lives on the
                # replay body (identity_after); per-result overrides win.
                binding = {
                    "identity_after": fused_result.get("identity_after") or fused_identity_after
                }
                _check_replay_or_raise(binding, report["identity_before"], qid)
            out = await _rerank_one(values, qid, by_id[qid], fused_result, transport, report, live)
            failed_query_id = None
            results.append(out)
    except Exception as exc:  # noqa: BLE001 — unified terminal
        run_error = f"{type(exc).__name__}: {exc}"
    finally:
        post = None
        post_error = None
        try:
            post = await _capture_identity(values)
        except Exception as exc:  # noqa: BLE001
            post_error = f"{type(exc).__name__}: {exc}"
            report["identity_after_error"] = post_error
        if post is not None:
            report["identity_after"] = {
                "matches_frozen": post["matches_frozen"],
                "problems": post["problems"],
                "counts": post["identity"]["public_counts"],
                "source_fingerprint": post["identity"]["source_fingerprint"],
                "catalog_active": post["identity"]["catalog_active"],
                "search_active": post["identity"]["search_active"],
                "gold_sha": post["identity"]["gold_sha"],
                "env_sha": post["identity"]["env_sha"],
            }
            drift = _identity_drift(pre["identity"], post["identity"])
            if drift:
                report["identity_drift"] = drift
        if run_error is not None:
            # D2: the failing query's partial in-flight record (already
            # mutated with whatever evidence was produced) rides along.
            partial = live.get("partial")
            if partial is not None and partial not in results:
                results.append(partial)
            report["results"] = results
            if live.get("call") is not None:
                report["failure_service_records"] = {
                    "query_id": live["query_id"] or failed_query_id,
                    "call_records": [live["call"]],
                    "note": "the failing query's real HTTP receipt, published at "
                    "exchange completion",
                }
            else:
                report["failure_service_records"] = {
                    "query_id": live["query_id"] or failed_query_id,
                    "call_records": [],
                    "note": "failure occurred before/without a captured rerank receipt",
                }
            await _write_failure("rerank", run_error)
        elif post_error:
            report["results"] = results
            await _write_failure("identity-after-capture-error", post_error)
        elif report.get("identity_drift"):
            report["results"] = results
            await _write_failure("identity-after-drift", report["identity_drift"])
        elif report.get("identity_after") and not report["identity_after"]["matches_frozen"]:
            report["results"] = results
            await _write_failure("identity-after", report["identity_after"]["problems"])

    if run_error is not None:
        raise AdapterError(f"rerank failed (terminal report written): {run_error}")
    if report.get("identity_after_error"):
        raise AdapterError(f"post-guard capture failed: {report['identity_after_error']}")
    if report.get("identity_drift"):
        raise AdapterError("post-guard identity drift: " + "; ".join(report["identity_drift"]))
    if report.get("identity_after") and not report["identity_after"]["matches_frozen"]:
        raise AdapterError(
            "post-guard identity mismatch: " + "; ".join(report["identity_after"]["problems"])
        )

    report["results"] = results
    report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    _write_terminal()
    return report


def _check_replay_or_raise(fused_result, identity_before, qid) -> None:
    """R1: refuse a replay whose provenance does not match the live capture."""
    if fused_result is None:
        return
    body = {"identity_after": fused_result.get("identity_after")}
    problems = _verify_replay_binding(body, identity_before)
    if problems:
        raise AdapterError(f"replay provenance mismatch for {qid}: " + "; ".join(problems))


def _fallback_ordered(inputs: list[dict]) -> list[dict]:
    """R2: the degraded fallback keeps the SAME full identity/provenance
    record on every entry as the success path — only the score is None."""
    return [
        {
            "input_index": i["input_index"],
            "workspace": i["workspace"],
            "chunk_id": i["chunk_id"],
            "doc_id": i["doc_id"],
            "content_sha256": i["content_sha256"],
            "rerank_score": None,
            "paths": i["paths"],
            "source_order": "fusion-original",
        }
        for i in inputs
    ]


async def _rerank_one(values, qid, gold_q, fused_result, transport, report, live) -> dict:
    out: dict = {
        "query_id": qid,
        "query": gold_q.get("question") or "",
        "workspace": gold_q.get("workspace") or "default",
        "skipped": None,
        "inputs": [],
        "call": None,
        "ordered": [],
        "degraded": [],
        "status": "ok",
    }
    # D2: share the in-flight record so a later raise (binding refusal,
    # enrichment failure, verification crash) still leaves this query's
    # partial evidence — including canonical-repair provenance — reachable
    # from the failure terminal.
    if live is not None:
        live["partial"] = out
    if fused_result is None:
        out["status"] = "skipped"
        out["skipped"] = "no fused result for this query id (zero rerank calls)"
        return out
    if fused_result.get("status") in ("missing", "stale"):
        out["status"] = "skipped"
        out["skipped"] = (
            f"fused status={fused_result.get('status')}; rerank never upgrades a "
            "missing/stale result (zero rerank calls)"
        )
        return out

    # C1: the replayed entry must be bound to THIS question/workspace —
    # candidates from a different question (or different explicit code/version
    # constraints) never become trusted inputs for this query just because
    # the live library is frozen. A missing replay question is likewise a
    # refusal (absence is never silently treated as equality).
    replay_query = fused_result.get("query")
    replay_workspace = fused_result.get("workspace") or out["workspace"]
    if replay_query != out["query"] or replay_workspace != out["workspace"]:
        raise AdapterError(
            f"replay binding mismatch for {qid}: replay query "
            f"{replay_query!r}/workspace {replay_workspace!r} != requested "
            f"{out['query']!r}/{out['workspace']!r}; candidates from another "
            "question or constraint set are never scored here"
        )

    # R2: typed doc/scope/table targets are carried through INDEPENDENTLY —
    # they are never dressed up as chunk text for the reranker.
    out["typed_targets"] = fused_result.get("typed_targets", [])

    raw_candidates = list(fused_result.get("usable", []))
    missing_text = [c.get("chunk_id") for c in raw_candidates if not c.get("content")]
    if missing_text:
        # R1: a candidate without read-back full text shrinks nothing and
        # claims nothing — the whole run degrades explicitly.
        out["status"] = "degraded"
        out["degraded"].append(
            f"{len(missing_text)} candidate(s) lack read-back full text "
            f"({missing_text[:5]}); the set is never silently reduced — refusing "
            "the joint rerank for this query"
        )
        return out

    # D1: the enrichment snapshot is the ACTIVE catalog snapshot verified by
    # the pre-flight identity guard (report.identity_before.catalog_active.
    # snapshot_id) — never an arbitrary field. Any snapshot the replay declares
    # (the real 5.3 shape nests it under pg.catalog_snapshot_id; a root field
    # counts too) must agree with it, otherwise the replay's provenance is
    # refused. A known active snapshot is never silently skipped.
    active_snapshot = ((report.get("identity_before") or {}).get("catalog_active") or {}).get(
        "snapshot_id"
    )
    declared_snapshots = {
        s
        for s in (
            (fused_result.get("pg") or {}).get("catalog_snapshot_id"),
            fused_result.get("catalog_snapshot_id"),
        )
        if s
    }
    if declared_snapshots and declared_snapshots != {active_snapshot}:
        raise AdapterError(
            f"replay provenance mismatch for {qid}: declared catalog snapshot(s) "
            f"{sorted(declared_snapshots)} disagree with the verified active "
            f"snapshot {active_snapshot!r}; enrichment refused"
        )
    enrichment_snapshot = active_snapshot
    if enrichment_snapshot is None and len(declared_snapshots) == 1:
        raise AdapterError(
            f"replay for {qid} declares a catalog snapshot but the active "
            "build is unknown to the verified identity; refusing without provenance"
        )

    # R2: enrich replayed paths missing table-fragment identity with the
    # REAL unit_chunk_links mapping (additive; no guessing). The fake test
    # transport path skips this (tests registered explicit rows already and
    # have no catalog), production replay always runs it.
    if transport is None:
        raw_candidates, enrich_notes = await _enrich_table_paths(
            values,
            out["workspace"],
            enrichment_snapshot,
            raw_candidates,
        )
        out["path_enrichment"] = enrich_notes

    # R1: every replayed candidate is verified against the CURRENT production
    # source (row exists, workspace/doc attribution, verified flag, text
    # byte-identical to the live row). Any problem refuses the whole query —
    # a rejected candidate cannot re-enter through another path.
    verified, problems = await _verify_candidates_against_source(
        values, out["workspace"], raw_candidates
    )
    out["source_verification"] = {
        "candidates_checked": len(raw_candidates),
        "verified": len(verified),
        "problems": problems,
    }
    if problems:
        out["status"] = "degraded"
        out["degraded"].append(
            f"replay source verification failed for {len(problems)} candidate(s); "
            "the joint rerank is refused (set never silently reduced)"
        )
        return out

    inputs, skipped = _rerank_inputs({"usable": verified})
    out["inputs"] = [
        {k: v for k, v in i.items() if k != "text"} | {"text_sha256": i["content_sha256"]}
        for i in inputs
    ]
    out["skipped_inputs"] = skipped
    if not inputs:
        out["status"] = "skipped"
        out["skipped"] = "empty scored input set (zero rerank calls)"
        return out
    if len(inputs) > RERANK_INPUT_BUDGET:
        out["status"] = "degraded"
        out["degraded"].append(
            f"{len(inputs)} inputs exceed the {RERANK_INPUT_BUDGET} budget; the run "
            "refuses rather than silently truncating"
        )
        return out

    call = await _call_rerank(
        values, out["query"], [i["text"] for i in inputs], transport=transport
    )
    # R3: publish THIS query's real receipt the moment the exchange completed
    # — the terminal must keep it even if response validation blows up.
    if live is not None:
        live["call"] = {k: v for k, v in call.items() if k != "payload"}
    # R4: strip the raw payload from the published call, keep the sanitized
    # RAW RESPONSE (index/score/meta) for independent re-verification.
    published_call = {k: v for k, v in call.items() if k != "payload"}
    raw_response = call.get("payload")
    if isinstance(raw_response, dict):
        published_call["raw_response"] = _sanitize_evidence(
            {
                "id": raw_response.get("id"),
                "results": raw_response.get("results"),
                "meta": raw_response.get("meta"),
            },
            values,
        )
    out["call"] = published_call

    if call.get("status") != "success":
        out["status"] = "degraded"
        out["degraded"].append(
            f"rerank call failed ({call.get('error')}); falling back to the original "
            "fusion order with NO fabricated scores"
        )
        out["ordered"] = _fallback_ordered(inputs)
        return out

    validated, err = _validate_response_safe(call.get("payload"), len(inputs))
    if err is not None:
        out["status"] = "degraded"
        out["degraded"].append(
            f"rerank response rejected ({err}); falling back to the original fusion "
            "order with NO fabricated scores"
        )
        out["ordered"] = _fallback_ordered(inputs)
        return out

    by_index = {i["input_index"]: i for i in inputs}
    for r in validated:
        src = by_index[r["index"]]
        out["ordered"].append(
            {
                "input_index": r["index"],
                "workspace": src["workspace"],
                "chunk_id": src["chunk_id"],
                "doc_id": src["doc_id"],
                "content_sha256": src["content_sha256"],
                "rerank_score": r["relevance_score"],
                "paths": src["paths"],
                "source_order": "rerank",
            }
        )
    return out
