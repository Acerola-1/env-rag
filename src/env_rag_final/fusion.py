"""Task 5.3: two-path candidate fusion — auditable merge, identity dedup,
source-path retention and explicit code/version constraints.

Contracts (handoff-phase-3-5.3.md):
- PG input is ``SearchResult.discovery_candidates`` ONLY — the budgeted
  discovery list. An explicit ``[]`` is authoritative zero discovery; a
  not-yet-captured ``None`` is handled explicitly (zero discovery + note).
  Enumeration answers (post-expansion ``candidates``) never backfill it.
- Candidate TYPES are never conflated: doc-level (catalog_row) and scope/table
  targets stay typed targets; only REAL chunk identities (keyword ``chunk_row``
  and table bindings through actual ``unit_chunk_links``) become chunk
  candidates. No guessing ``chunk-000`` / title / head-80 ids.
- Chunk candidates merge on ``(workspace, chunk_id)``; every path keeps its
  own raw score/rank kind. Scores are NEVER summed or converted — a missing
  scalar score is ``unknown``, never a fabricated cosine/joint score.
- Same ``(workspace, chunk_id)`` with conflicting doc attribution is REJECTED,
  not silently picked; unverified local candidates never enter the usable set.
- Explicit code/version constraints from the PG route bind the local path:
  local chunks must belong to a RESOLVED requested target (doc self_code /
  version read from the active search index); a missing target is never
  substituted by nearby versions; when NO requested target resolves, local is
  skipped entirely (zero model calls).
- Local failure with a usable PG route degrades EXPLICITLY to PG-only with the
  real error and the failing adapter's service receipts. PG stale/source drift
  is never upgraded to success by local output.
- Budget truncation records the rule + unretained ids and is NOT "complete".
- Identity guards (before/after + drift), cleanup and the unified failure
  terminal follow the accepted 5.2 contract.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import asyncpg
from dotenv import dotenv_values

from env_rag_final.compat_runtime import (
    _identity_drift,
    _identity_mismatch,
    capture_production_identity,
)
from env_rag_final.local_adapter import (
    GOLD_PATH,
    AdapterError,
    LocalCandidateAdapter,
    verify_config_guard,
    verify_gold_guard,
)

PG_CHUNK_DISCOVERIES = {
    "keyword_and",
    "keyword_synonym_and",
    "keyword_core_and",
    "keyword_or_relaxed",
}


def _pg_dsn(values: dict) -> dict:
    return {
        "host": values["POSTGRES_HOST"],
        "port": int(values["POSTGRES_PORT"]),
        "user": values["POSTGRES_USER"],
        "password": values["POSTGRES_PASSWORD"],
        "database": values["POSTGRES_DATABASE"],
        "statement_cache_size": 0,
        "timeout": 15,
        "server_settings": {"default_transaction_read_only": "on"},
    }


class _PreflightRejection(Exception):
    """F3-a: an unknown-query-id refusal inside the unified pre-flight
    boundary; carries the terminal stage and detail for the failure report."""

    def __init__(self, stage: str, detail):
        super().__init__(f"{stage}: {detail}")
        self.stage = stage
        self.detail = detail


async def _capture_identity(values: dict) -> dict:
    identity = await capture_production_identity(values, "fusion")
    problems = _identity_mismatch(identity)
    return {"identity": identity, "problems": problems, "matches_frozen": not problems}


# ---------------------------------------------------------------------------
# Input normalization (no behaviour beyond reading + tagging)
# ---------------------------------------------------------------------------


def _pg_targets(pg_result) -> tuple[list[dict], list[dict]]:
    """Requested vs resolved (code, version) targets from the code route trace."""
    requested: list[dict] = []
    resolved: list[dict] = []
    for step in pg_result.trace:
        if step.get("stage") != "code_exact":
            continue
        target = {"code": step.get("code"), "version": step.get("version_requested")}
        requested.append(target)
        if step.get("selected_docs"):
            resolved.append(
                {
                    **target,
                    "docs": list(step["selected_docs"]),
                    "versions": [v for v in (step.get("selected_versions") or []) if v],
                }
            )
    return requested, resolved


def _normalize_pg(pg_result) -> tuple[list[dict], list[dict], list[str]]:
    """Split the budgeted discovery list into CHUNK candidates and TYPED targets.

    Never reads ``pg_result.candidates`` — that list may have been replaced by
    full enumeration (expand) and must not feed fusion.
    """
    issues: list[str] = []
    discovery = pg_result.discovery_candidates
    if discovery is None:
        issues.append(
            "discovery_candidates not captured (None): explicit compatibility — "
            "treated as zero discovery; enumeration answers are never used as input"
        )
        discovery = []
    chunks: list[dict] = []
    targets: list[dict] = []
    for c in discovery:
        citation = c.get("citation") or {}
        kind = citation.get("kind")
        if kind == "chunk_row":
            chunks.append(
                {
                    "path": "pg",
                    "workspace": pg_result.workspace,
                    "chunk_id": c.get("chunk_id"),
                    "doc_id": c.get("doc_id"),
                    "heading": c.get("heading"),
                    "chunk_order": c.get("chunk_order"),
                    "discovery": c.get("discovery"),
                    "citation_verified": bool(c.get("citation_verified")),
                    "score": {"kind": "pg_ts_rank", "value": c.get("score")},
                }
            )
        elif kind == "catalog_row":
            targets.append(
                {
                    "target_type": "doc",
                    "workspace": pg_result.workspace,
                    "doc_id": c.get("doc_id"),
                    "doc_name": c.get("doc_name"),
                    "self_code": c.get("self_code"),
                    "self_code_version": c.get("self_code_version"),
                    "discovery": c.get("discovery"),
                    "membership_basis": c.get("membership_basis"),
                    "citation": citation,
                    "citation_verified": bool(c.get("citation_verified")),
                }
            )
        elif kind == "table_unit":
            targets.append(
                {
                    "target_type": "table_unit",
                    "workspace": pg_result.workspace,
                    "doc_id": c.get("doc_id"),
                    "unit_id": c.get("unit_id"),
                    "heading": c.get("heading"),
                    "chunk_ids": list(c.get("chunk_ids") or []),
                    "discovery": c.get("discovery"),
                    "scope_status": c.get("scope_status"),
                    "membership_basis": c.get("membership_basis"),
                    "citation": citation,
                }
            )
            # REAL unit_chunk_links may map range tables to chunks — allowed;
            # nothing is fabricated when the link list is empty. F2: each
            # mapped chunk path keeps the PHYSICAL fragment identity it came
            # from (unit_id/table_id) and the ORIGINAL citation verbatim, so
            # two fragments linked to the same chunk stay distinguishable ON
            # THE PATHS — no invented locators, no dropped upstream fields.
            for cid in c.get("chunk_ids") or []:
                chunks.append(
                    {
                        "path": "pg",
                        "workspace": pg_result.workspace,
                        "chunk_id": cid,
                        "doc_id": c.get("doc_id"),
                        "heading": c.get("heading"),
                        "chunk_order": None,
                        "unit_id": c.get("unit_id"),
                        "table_id": c.get("table_id") or c.get("unit_id"),
                        "citation": citation,
                        "discovery": c.get("discovery"),
                        "citation_verified": bool(c.get("citation_verified")),
                        "score": {"kind": "none", "value": None},
                    }
                )
        elif kind == "scope":
            targets.append(
                {
                    "target_type": "scope",
                    "workspace": pg_result.workspace,
                    "doc_id": c.get("doc_id"),
                    "scope_id": c.get("scope_id"),
                    "heading": c.get("heading"),
                    "member_units": list(c.get("member_units") or []),
                    "discovery": c.get("discovery"),
                    "scope_status": c.get("scope_status"),
                    "citation": citation,
                    "citation_verified": bool(c.get("citation_verified")),
                }
            )
        else:
            targets.append(
                {
                    "target_type": "unclassified",
                    "workspace": pg_result.workspace,
                    "discovery": c.get("discovery"),
                    "raw": c,
                }
            )
            issues.append(f"PG candidate with unknown citation kind {kind!r} kept as typed target")
    return chunks, targets, issues


def _normalize_local(local_result) -> list[dict]:
    chunks: list[dict] = []
    pick = (local_result.sorting_sources or {}).get("chunk_pick")
    for c in local_result.candidates:
        chunks.append(
            {
                "path": "local",
                "workspace": c.workspace,
                "chunk_id": c.chunk_id,
                "doc_id": c.full_doc_id or None,
                "heading": None,
                "chunk_order": None,
                "source_type": c.source_type,
                "reached_via": list(c.reached_via or []),
                "verified": bool(c.verified),
                "verify_error": c.verify_error,
                "similarity_order": c.similarity_order,
                "score": {
                    "kind": "local_selection_order",
                    "value": c.similarity_order,
                    "source_type": c.source_type,
                    "method": pick,
                },
            }
        )
    return chunks


def _merge_chunks(pg_chunks: list[dict], local_chunks: list[dict]) -> list[dict]:
    """Merge on (workspace, chunk_id); every path entry is retained verbatim.

    A conflicting doc attribution across paths is recorded on the merged entry
    (``conflict``) — the merge never picks one attribution to override the
    other; the usable filter rejects it."""
    merged: dict[tuple, dict] = {}
    order: list[tuple] = []

    def _entry(key: tuple) -> dict:
        if key not in merged:
            merged[key] = {"workspace": key[0], "chunk_id": key[1], "paths": [], "conflict": None}
            order.append(key)
        return merged[key]

    for item in pg_chunks + local_chunks:
        entry = _entry((item["workspace"], item["chunk_id"]))
        entry["paths"].append(item)

    out: list[dict] = []
    for key in order:
        entry = merged[key]
        docs = sorted({p.get("doc_id") for p in entry["paths"] if p.get("doc_id")})
        if len(docs) > 1:
            entry["conflict"] = (
                f"conflicting doc attribution across paths: {docs}; "
                "the entry is rejected, no attribution is picked"
            )
        entry["doc_id"] = docs[0] if len(docs) == 1 else None
        # path-level constraint rejection propagates to the merged entry: a
        # path that cannot be bound to a resolved target rejects the entry —
        # it must never slip into the usable set via another path's identity.
        reasons = [
            p.get("constraint_rejected") for p in entry["paths"] if p.get("constraint_rejected")
        ]
        if reasons:
            entry["constraint_rejected"] = reasons[0]
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Explicit code/version constraints binding BOTH paths
# ---------------------------------------------------------------------------


def _allowed_docs(
    resolved: list[dict], typed_targets: list[dict], question: str
) -> tuple[set[str] | None, list[dict]]:
    """Doc ids of the RESOLVED requested targets, PLUS explicitly verified
    attributed documents (F1).

    When the request explicitly asks for related/amended documents (含修改单/
    相关文件/整合版 — the SAME R1 predicate the PG attribution route uses),
    the PG route verifies documents whose NAME/TITLE carries the requested
    code (``doc_attribution``, membership_basis recorded, no self_code
    fabricated). Those verified attribution targets are part of THIS
    request's legitimate allowed set — their local chunks must not be
    rejected as "not a resolved target".

    A plain standard query / 自身编号 request keeps the strict code_exact-only
    set even if an attribution target is somehow present in the discovery
    list; a missing self_code target stays missing. Returns (allowed, basis)
    where basis documents the attribution evidence kept for review."""
    from env_rag_final.search.expand import _attribution_requested

    docs: set[str] = set()
    for t in resolved:
        docs.update(t.get("docs") or [])
    attributions: list[dict] = []
    if _attribution_requested(question or ""):
        for t in typed_targets:
            if (
                t.get("target_type") == "doc"
                and t.get("discovery") == "doc_attribution"
                and t.get("doc_id")
                and t.get("citation_verified")
            ):
                docs.add(t["doc_id"])
                attributions.append(
                    {
                        "doc_id": t["doc_id"],
                        "self_code": t.get("self_code"),
                        "self_code_version": t.get("self_code_version"),
                        "membership_basis": t.get("membership_basis"),
                        "note": "verified doc_attribution target joins the allowed set; "
                        "no self_code is fabricated",
                    }
                )
    return (docs or None), attributions


def _apply_doc_constraint(entries: list[dict], allowed: set[str] | None) -> list[dict]:
    """Mark (never silently drop) entries outside the resolved target docs."""
    if allowed is None:
        return entries
    for e in entries:
        if e.get("doc_id") and e["doc_id"] not in allowed:
            e["constraint_rejected"] = (
                f"doc {e['doc_id']} is not a RESOLVED requested target; a nearby "
                "version/other document is never substituted"
            )
        elif not e.get("doc_id"):
            e["constraint_rejected"] = (
                "chunk attribution could not be established; it cannot be bound to "
                "any resolved requested target"
            )
    return entries


# ---------------------------------------------------------------------------
# Read-only source verification + full-text read-back (production PG)
# ---------------------------------------------------------------------------


async def _verify_chunks(values: dict, workspace: str, entries: list[dict]) -> dict:
    """Read the REAL production rows for every merged chunk candidate.

    Verifies (workspace, chunk_id) existence, full_doc_id attribution against
    every path's claim, and reads back the FULL text (content_head is only a
    display summary in local output; it is never treated as the text)."""
    report = {"requested": 0, "verified": 0, "missing": 0, "attribution_conflict": 0}
    ids = sorted({e["chunk_id"] for e in entries if e.get("chunk_id")})
    if not ids:
        return report
    conn = await asyncpg.connect(**_pg_dsn(values))
    try:
        rows = await conn.fetch(
            """SELECT id, workspace, full_doc_id, content, file_path
               FROM public.lightrag_doc_chunks
               WHERE workspace = $1 AND id = ANY($2)""",
            workspace,
            ids,
        )
    finally:
        await conn.close()
    by_id = {r["id"]: r for r in rows}
    report["requested"] = len(ids)
    for e in entries:
        cid = e.get("chunk_id")
        if not cid:
            e["verified"] = False
            e["verify_error"] = "no chunk identity"
            continue
        if e.get("workspace") != workspace:
            # different workspace, same chunk_id is a DIFFERENT source identity —
            # it must never be looked up here as if it were this query's source.
            e["verified"] = False
            e["verify_error"] = (
                f"cross-workspace entry rejected: entry workspace {e.get('workspace')!r} "
                f"!= query workspace {workspace!r}; sources are never mixed"
            )
            report["cross_workspace"] = report.get("cross_workspace", 0) + 1
            continue
        row = by_id.get(cid)
        if row is None:
            e["verified"] = False
            e["verify_error"] = "missing-in-production-pg"
            report["missing"] += 1
            continue
        e["file_path"] = row["file_path"]
        content = row["content"] or ""
        e["content_len"] = len(content)
        e["content_sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
        e["content"] = content  # full read-back text (read-only)
        if e.get("doc_id") and row["full_doc_id"] != e["doc_id"]:
            e["verified"] = False
            e["verify_error"] = (
                f"doc attribution conflict: paths claim {e['doc_id']} but production "
                f"row says {row['full_doc_id']}"
            )
            report["attribution_conflict"] += 1
            continue
        e["doc_id"] = e.get("doc_id") or row["full_doc_id"]
        e["verified"] = True
        e["verify_error"] = None
        report["verified"] += 1
    return report


# ---------------------------------------------------------------------------
# Local path invocation under the PG hard constraints
# ---------------------------------------------------------------------------


class _LocalOutcome:
    def __init__(self) -> None:
        self.ran = False
        self.skipped_reason: str | None = None
        self.error: str | None = None
        self.receipts: dict | None = None
        self.chunks: list[dict] = []
        self.result = None


async def _run_local(
    values: dict,
    workspace: str,
    question: str,
    query_id: str,
    gold_sha: str,
    allowed_docs: set[str] | None,
    adapter_factory=None,
) -> _LocalOutcome:
    """One local fetch; failures never raise — they become a PG-only degrade
    with the REAL error and the failing adapter's service receipts."""
    outcome = _LocalOutcome()
    adapter = (adapter_factory or LocalCandidateAdapter)(values, workspace=workspace)
    try:
        res = await adapter.fetch(question, query_id=query_id, frozen_gold_sha=gold_sha)
    except Exception as exc:  # noqa: BLE001 — explicit PG-only degrade
        outcome.error = f"{type(exc).__name__}: {exc}"
        boundary = getattr(adapter, "boundary", None)
        if boundary is not None:
            outcome.receipts = {
                "query_id": query_id,
                "call_records": [vars(r) for r in boundary.records],
                "group_records": [vars(r) for r in boundary.group_records],
                "by_service": boundary.counts(),
                "groups": boundary.group_counts(),
            }
        else:
            outcome.receipts = {"query_id": query_id, "call_records": [], "note": "no adapter"}
        return outcome
    outcome.ran = True
    outcome.result = res
    outcome.receipts = {
        "query_id": query_id,
        "call_records": list(res.call_records),
        "by_service": (res.service_calls or {}).get("by_service", {}),
        "groups": (res.service_calls or {}).get("groups", {}),
        "degraded": list(res.degraded),
    }
    outcome.chunks = _normalize_local(res)
    if allowed_docs is not None:
        outcome.chunks = _apply_doc_constraint(outcome.chunks, allowed_docs)
    return outcome


# ---------------------------------------------------------------------------
# Fusion entry
# ---------------------------------------------------------------------------

FUSION_BUDGET = 40  # usable chunk candidates per query (documented budget)


def _usable(entry: dict) -> tuple[bool, str | None]:
    if entry.get("conflict"):
        return False, entry["conflict"]
    if entry.get("constraint_rejected"):
        return False, entry["constraint_rejected"]
    local_paths = [p for p in entry["paths"] if p["path"] == "local"]
    if local_paths and not any(p.get("verified") for p in local_paths):
        errs = {p.get("verify_error") for p in local_paths if p.get("verify_error")}
        return (
            False,
            f"local path rejected its candidate ({'/'.join(sorted(errs)) or 'unverified'})",
        )
    if not entry.get("verified"):
        return False, entry.get("verify_error") or "production read-back failed"
    return True, None


async def run_fusion(
    report_dir: Path,
    queries: list[str] | None = None,
    pg_only: bool = False,
) -> dict:
    """Fuse the PG discovery path and the local semantic path per query."""
    from env_rag_final.search.query import run_query

    report: dict = {
        "task": "5.3 two-path candidate fusion (read-only, guarded)",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "pg_only_switch": pg_only,
        "frozen_contract": {
            "source_fingerprint": None,  # filled below from the captured identity
        },
    }
    report_dir.mkdir(parents=True, exist_ok=True)

    def _write_terminal() -> None:
        stamp = time.strftime("%Y%m%dT%H%M%S")
        body = json.dumps(report, ensure_ascii=False, indent=1) + "\n"
        (report_dir / f"fusion-runtime-{stamp}.json").write_text(body, encoding="utf-8")
        (report_dir / "fusion-runtime-latest.json").write_text(body, encoding="utf-8")

    async def _write_failure(stage: str, detail) -> None:
        report["failure"] = {"stage": stage, "detail": detail}
        _write_terminal()

    values = dict(dotenv_values(".env"))
    wanted = queries or ["fact-002", "syn-001", "neg-001"]

    # ---- F3-a/F4: the WHOLE pre-flight (gold read, JSON parse, structure
    # prep, unknown ids, config guards, SHA verification) sits inside ONE
    # zero-backend-contact failure boundary. Any rejection — regardless of
    # its exception type — writes the auditable zero-call failure terminal
    # (real error type/reason kept, no finished_at) before re-raising. The
    # frozen gold and .env are never modified to pass the checks.
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
                    "target_docs": [],
                    "counter": {
                        "type": c.get("type"),
                        "expected_status": c.get("expected_status"),
                    },
                }
        unknown = [q for q in wanted if q not in by_id]
        if unknown:
            raise _PreflightRejection("unknown-query-id", unknown)
        for qid in wanted:
            verify_config_guard(values, by_id[qid].get("workspace") or "default")
        gold_sha = verify_gold_guard(GOLD_PATH)
    except _PreflightRejection as exc:
        report["failure_service_records"] = dict(zero_call_ledger)
        await _write_failure(exc.stage, exc.detail)
        raise AdapterError(f"{exc.stage} (rejected before any call): {exc.detail}") from exc
    except json.JSONDecodeError as exc:
        report["failure_service_records"] = dict(zero_call_ledger)
        await _write_failure("gold-parse", f"{type(exc).__name__}: {exc}")
        raise AdapterError(f"gold parse failed (zero backend calls): {exc}") from exc
    except AdapterError as exc:
        # covers config-guard, gold-guard (SHA), and any guard refusal
        report["failure_service_records"] = dict(zero_call_ledger)
        await _write_failure("pre-flight", str(exc))
        raise
    except OSError as exc:
        report["failure_service_records"] = dict(zero_call_ledger)
        await _write_failure("gold-read", f"{type(exc).__name__}: {exc}")
        raise AdapterError(f"gold read failed (zero backend calls): {exc}") from exc
    except Exception as exc:
        # F3-a unified fallback: structural/config failures of ANY ordinary
        # exception type (KeyError on a missing gold field, TypeError on a
        # null structure, ValueError on a non-integer dim, ...) must still
        # write the zero-call terminal with the ORIGINAL type auditable.
        # BaseException (KeyboardInterrupt/SystemExit) is deliberately NOT
        # caught, and the exception is never swallowed — always re-raised
        # with its cause preserved.
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
    report["frozen_contract"]["source_fingerprint"] = pre["identity"]["source_fingerprint"]
    if not pre["matches_frozen"]:
        await _write_failure("identity-before", pre["problems"])
        raise AdapterError("pre-flight identity mismatch: " + "; ".join(pre["problems"]))

    results: list[dict] = []
    fetch_error: str | None = None
    failed_query_id: str | None = None
    # F3: the running query publishes its ledger/partial state into `live` as
    # it works, so a failure AFTER the local stage (e.g. PG read-back) still
    # carries THIS query's real service receipts — never a previous query's,
    # never zero. The reference is authoritative at exception time.
    live: dict = {"query_id": None, "receipts": None, "partial": None}
    try:
        for qid in wanted:
            q = by_id[qid]
            workspace = q.get("workspace") or "default"
            failed_query_id = qid
            out = await _fuse_one(values, workspace, q, qid, gold_sha, pg_only, run_query, live)
            failed_query_id = None
            results.append(out)
    except Exception as exc:  # noqa: BLE001 — unified terminal
        fetch_error = f"{type(exc).__name__}: {exc}"
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
        if fetch_error is not None:
            report["results"] = results
            report["failure_service_records"] = _collect_failure_receipts(
                results, failed_query_id, live
            )
            await _write_failure("fuse", fetch_error)
        elif post_error:
            report["results"] = results
            await _write_failure("identity-after-capture-error", post_error)
        elif report.get("identity_drift"):
            report["results"] = results
            await _write_failure("identity-after-drift", report["identity_drift"])
        elif report.get("identity_after") and not report["identity_after"]["matches_frozen"]:
            report["results"] = results
            await _write_failure("identity-after", report["identity_after"]["problems"])

    if fetch_error is not None:
        raise AdapterError(f"fusion failed (terminal report written): {fetch_error}")
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
    jsonl = "\n".join(json.dumps(r, ensure_ascii=False) for r in results) + "\n"
    (report_dir / "fusion-candidates.jsonl").write_text(jsonl, encoding="utf-8")
    return report


def _collect_failure_receipts(results, failed_query_id, live: dict | None) -> dict:
    """F3/F3-b: the failing query's own ledger only.

    Priority: (1) the live slot if the CURRENT query recorded receipts (its
    local stage completed), (2) the live slot's explicitly-empty ledger when
    the current query failed BEFORE its local stage (never a previous
    query's receipts), (3) a completed result whose own local stage failed —
    only that result's receipts, only if it IS the failing query. The
    previous query's successful ledger stays on its own result, never
    substitutes here."""
    if live is not None and live.get("query_id") is not None:
        if live.get("receipts") is not None:
            return live["receipts"]
        return {
            "query_id": live["query_id"],
            "call_records": [],
            "group_records": [],
            "by_service": {},
            "groups": {},
            "note": "the failing query's local stage had not completed; zero local "
            "calls belong to this query (previous queries' ledgers stay on "
            "their own results)",
            "partial_stage": live.get("partial"),
        }
    for r in reversed(results):
        if r.get("local", {}).get("error") and r.get("local", {}).get("receipts"):
            return r["local"]["receipts"]
    return {
        "query_id": failed_query_id,
        "call_records": [],
        "group_records": [],
        "by_service": {},
        "groups": {},
        "note": "failure occurred before/without a captured local receipt",
    }


class _CountingConn:
    """Counts real SQL statements issued by the PG path (read-only conn)."""

    def __init__(self, conn):
        self._conn = conn
        self.counts: dict[str, int] = {}

    def _tick(self, op: str) -> None:
        self.counts[op] = self.counts.get(op, 0) + 1

    async def fetch(self, *a, **kw):
        self._tick("fetch")
        return await self._conn.fetch(*a, **kw)

    async def fetchrow(self, *a, **kw):
        self._tick("fetchrow")
        return await self._conn.fetchrow(*a, **kw)

    async def fetchval(self, *a, **kw):
        self._tick("fetchval")
        return await self._conn.fetchval(*a, **kw)

    async def execute(self, *a, **kw):
        self._tick("execute")
        return await self._conn.execute(*a, **kw)

    async def close(self):
        return await self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)


async def _fuse_one(
    values: dict,
    workspace: str,
    gold_q: dict,
    qid: str,
    gold_sha: str,
    pg_only: bool,
    run_query,
    live: dict | None = None,
) -> dict:
    """One query: PG discovery → constraint decision → local → merge → verify.

    F3/F3-b: entering a new query FULLY RESETS the live slot (query_id,
    partial stage AND receipts) BEFORE any backend contact or await — a
    failure before this query's local stage must produce an explicitly EMPTY
    ledger under THIS query's id, never the previous query's receipts. After
    the local stage completes, the slot carries this query's real receipts
    for any later (read-back/merge) failure."""

    def _publish(stage: str) -> None:
        if live is not None:
            live["query_id"] = qid
            live["partial"] = stage

    # F3-b: reset FIRST (synchronously, before any await) so the previous
    # query's receipts can never be attributed to this one.
    if live is not None:
        live["query_id"] = None
        live["partial"] = None
        live["receipts"] = None
    _publish("pg-discovery")
    from env_rag_final.search.index import check_search_stale

    question = gold_q.get("question") or ""
    out: dict = {
        "query_id": qid,
        "query": question,
        "workspace": workspace,
        "pg": None,
        "local": {"ran": False, "skipped_reason": None, "error": None, "receipts": None},
        "targets_requested": [],
        "targets_resolved": [],
        "typed_targets": [],
        "candidates": [],
        "usable": [],
        "rejected": [],
        "budget": {"limit": FUSION_BUDGET, "kept": 0, "truncated": [], "rule": None},
        "status": "ok",
        "degraded": [],
        "notes": [],
    }
    conn = _CountingConn(await asyncpg.connect(**_pg_dsn(values)))
    try:
        stale = await check_search_stale(conn, workspace)
        pg_result = await run_query(conn, question, workspace=workspace, expand=False)
    finally:
        await conn.close()
    pg_sql = dict(conn.counts)

    requested, resolved = _pg_targets(pg_result)
    out["targets_requested"] = requested
    out["targets_resolved"] = resolved
    pg_chunks, typed_targets, issues = _normalize_pg(pg_result)
    out["typed_targets"] = typed_targets
    out["notes"].extend(issues)
    out["pg"] = {
        "status": pg_result.status,
        "search_id": pg_result.search_id,
        "catalog_snapshot_id": pg_result.catalog_snapshot_id,
        "source_snapshot_id": pg_result.source_snapshot_id,
        "discovery_total": 0
        if pg_result.discovery_candidates is None
        else len(pg_result.discovery_candidates),
        "discovery_captured": pg_result.discovery_candidates is not None,
        "chunks": len(pg_chunks),
        "stale_state": stale.get("state"),
        "notes": list(pg_result.notes),
        "trace_stages": [t.get("stage") for t in pg_result.trace],
        "sql_statements": pg_sql,
        "trace": [dict(t) for t in pg_result.trace],
    }

    if stale.get("state") != "current" or pg_result.status == "stale":
        out["status"] = "stale"
        out["degraded"].append(
            "PG search identity stale; local output must not upgrade it to a usable result"
        )
        return out

    allowed, attribution_basis = _allowed_docs(resolved, typed_targets, question)
    out["allowed_set_basis"] = {
        "resolved_code_targets": [t.get("docs") for t in resolved],
        "verified_attributions": attribution_basis,
    }
    all_missing = bool(requested) and not resolved
    if pg_only:
        out["local"] = {
            "ran": False,
            "skipped_reason": "pg-only switch",
            "error": None,
            "receipts": None,
        }
    elif all_missing:
        out["local"] = {
            "ran": False,
            "skipped_reason": "all requested targets missing; local call skipped "
            "(nearby versions can never substitute a missing target)",
            "error": None,
            "receipts": None,
        }
    else:
        outcome = await _run_local(values, workspace, question, qid, gold_sha, allowed)
        _publish("local-done")
        if live is not None and outcome.receipts is not None:
            # F3: publish THIS query's real ledger the moment the local stage
            # finished — a post-local failure must still find it.
            live["receipts"] = outcome.receipts
        if outcome.error is not None:
            out["status"] = "pg-only-degraded"
            out["local"] = {
                "ran": True,
                "skipped_reason": None,
                "error": outcome.error,
                "receipts": outcome.receipts,
            }
            out["degraded"].append(
                f"local path failed ({outcome.error}); explicit PG-only fallback with the "
                "real error and service receipts retained"
            )
        else:
            out["local"] = {
                "ran": True,
                "skipped_reason": None,
                "error": None,
                "receipts": outcome.receipts,
                "sorting_sources": dict(outcome.result.sorting_sources or {}),
                "degraded": list(outcome.result.degraded or []),
                "keywords": dict(outcome.result.keywords or {}),
            }
            out["degraded"].extend(outcome.result.degraded or [])
            # 5.3 handoff: the degrade judgement independently re-checks the
            # per-stage completeness records — a global sorting label or one
            # boolean is not trusted on its own. Any incomplete observed
            # stage (or a vector_backed=false with a vector-similarity label)
            # is surfaced here as a fusion-level note.
            coverage = (outcome.result.sorting_sources or {}).get("chunk_pick_vectors") or {}
            stage_checks = [
                {
                    "stage": c.get("stage"),
                    "complete": c.get("complete"),
                    "vectors_requested": c.get("vectors_requested"),
                    "vectors_effective": c.get("vectors_effective"),
                }
                for c in (coverage.get("observed_calls") or [])
            ]
            out["local"]["stage_completeness"] = stage_checks
            incomplete = [c for c in stage_checks if not c["complete"]]
            label = (outcome.result.sorting_sources or {}).get("chunk_pick")
            if incomplete:
                out["degraded"].append(
                    f"{len(incomplete)} local selection stage(s) incomplete "
                    f"({[c['stage'] for c in incomplete]}); per-stage records disagree "
                    "with any optimistic global label"
                )
            if coverage and coverage.get("vector_backed") is False and label == "vector-similarity":
                out["degraded"].append(
                    "local reports vector-similarity while effective coverage is false; "
                    "stage records take precedence (degraded)"
                )
        local_chunks = outcome.chunks

    if pg_only or all_missing:
        local_chunks = []

    merged = _merge_chunks(pg_chunks, local_chunks)
    _publish("readback")
    verify_report = await _verify_chunks(values, workspace, merged)
    out["verify"] = verify_report

    usable: list[dict] = []
    rejected: list[dict] = []
    for e in merged:
        ok, reason = _usable(e)
        record = {
            "workspace": e["workspace"],
            "chunk_id": e["chunk_id"],
            "doc_id": e.get("doc_id"),
            "paths": e["paths"],
            "verified": e.get("verified", False),
            "verify_error": e.get("verify_error"),
            "content_sha256": e.get("content_sha256"),
            "content_len": e.get("content_len"),
            "content": e.get("content"),
            "file_path": e.get("file_path"),
        }
        if ok:
            usable.append(record)
        else:
            record["rejected_reason"] = reason
            rejected.append(record)

    kept = usable[:FUSION_BUDGET]
    truncated = usable[FUSION_BUDGET:]
    if truncated:
        out["notes"].append(
            f"budget {FUSION_BUDGET} truncated {len(truncated)} usable candidates; "
            "rule = first-seen order (PG discovery order, then local order); "
            "truncated ids are listed and the result is NOT complete"
        )
        out["budget"] = {
            "limit": FUSION_BUDGET,
            "kept": len(kept),
            "truncated": [e["chunk_id"] for e in truncated],
            "rule": "first-seen (PG discovery order, then local similarity order); "
            "truncation recorded, not complete",
        }
        if out["status"] == "ok":
            out["status"] = "partial"
    else:
        out["budget"] = {
            "limit": FUSION_BUDGET,
            "kept": len(kept),
            "truncated": [],
            "rule": "no truncation",
        }

    if requested and not resolved:
        out["status"] = "missing"
        out["notes"].append(
            "requested target(s) missing: "
            + ", ".join(
                f"{t['code']}-{t['version']}" if t.get("version") else t["code"] for t in requested
            )
            + "; resolved evidence for other requested targets is retained, "
            "but a missing target is never substituted"
        )
    elif requested and len(resolved) < len(requested):
        out["status"] = "missing"
        out["notes"].append(
            "some requested targets missing; found evidence retained, not substituted"
        )

    out["candidates"] = kept
    out["usable"] = kept
    out["rejected"] = rejected
    return out
