"""Candidate → scope confirmation → COMPLETE range expansion (task 4.4, r2).

R1: cover-attribution (修改单/相关文件) is ONLY enabled when the request
explicitly asks for it (含修改单/相关文件/整合版); a self-code ("自身编号…")
or plain standard query keeps its EXACT target — a document whose title merely
names the standard is never added to its range reads.

R2: multi-target document predicates are BRANCH SETS: each requested
(code, version) pair is its own AND-limited branch, branches merge with OR.
An empty enumeration that contradicts already-resolved targets is reported
ambiguous, never "complete with 0/0".

R3: the request may name MULTIPLE ranges (3章/第4.3节/4.1.1–4.1.2/表1、表2).
Every target resolves; numbers inside code spans or latin compounds (PM2.5)
are never treated as clause numbers; sub-clause requests read the parent
scope with Phase-1 ``requested_clauses``/``locate_span``. The chapter heading
itself is not an item. Unresolvable requests stay ambiguous, and all
expansion failures propagate to the top-level status.
"""

from __future__ import annotations

import re

from env_rag_final.audit import identity as sid

from . import tokenizer as tk
from .index import check_search_stale

# attribution requests only (R1)
_ATTRIBUTION_RE = re.compile(r"含修改单|修改单|相关文件|整合版|归属文件")
_SELF_CODE_RE = re.compile(r"自身编号")

# code spans / latin+digit compounds must never read as clause numbers (R3)
_CODE_SPAN_RE = re.compile(
    r"(?:GB|HJ|DB\d{0,2})\s*/?\s*T?\s*\d+(?:\.\d+)?(?:\s*[-—–－/]\s*\d{2,4})?"
    r"|[A-Za-z]+\d+(?:\.\d+)?(?:%|‰)?",
    re.IGNORECASE,
)
# chapter syntax: 第N章/节/部分 AND the bare "N 章" form ("3 章" without 第)
_CHAPTER_RE = re.compile(r"第?\s*([0-9]+(?:\.[0-9]+)*)\s*章")
_SECTION_RE = re.compile(r"第\s*([0-9]+(?:\.[0-9]+)*)\s*(?:节|部分)")
_TABLE_RE = re.compile(r"表\s*([A-Z]?\d+(?:\.\d+)?)")
_CLAUSE_NUM_RE = re.compile(r"(?<![A-Za-z0-9.])([0-9]+(?:\.[0-9]+){1,3})(?![0-9])")
_CLAUSE_RANGE_RE = re.compile(
    r"(?<![A-Za-z0-9.])([0-9]+(?:\.[0-9]+){1,3})\s*(?:至|到|~|～|—|－)\s*"
    r"([0-9]+(?:\.[0-9]+){1,3})(?![0-9])"
)


def _attribution_requested(text: str) -> bool:
    """True only for explicit related/amended-document requests (R1)."""
    if _SELF_CODE_RE.search(text or ""):
        return False
    return bool(_ATTRIBUTION_RE.search(text or ""))


def _requested_targets(result) -> list[dict]:
    """All range targets the request explicitly names (R3), or [].

    Each target: {"kind": "chapter"|"clause"|"table", "value": str,
    "clauses": [str, ...] | None}. Sub-clause values resolve through their
    parent scope at read time.
    """
    text = tk.normalize_text(getattr(result, "query_text", "") or "")
    # numbers inside codes (GB3095-2012) and latin compounds (PM2.5, HJ2.2)
    # are NOT range references — strip them before any numeric scan
    text = _CODE_SPAN_RE.sub(" ", text)

    targets: list[dict] = []

    for m in _TABLE_RE.finditer(text):
        targets.append({"kind": "table", "value": m.group(1), "clauses": None})

    for m in _CLAUSE_RANGE_RE.finditer(text):
        lo, hi = m.group(1), m.group(2)
        clauses = _expand_clause_range(lo, hi)
        if clauses:
            parent = lo.rsplit(".", 1)[0] if "." in lo else lo
            targets.append({"kind": "clause", "value": parent, "clauses": clauses})

    seen_clause: set[str] = set()
    for m in _CHAPTER_RE.finditer(text):
        targets.append({"kind": "chapter", "value": m.group(1), "clauses": None})
    for m in _SECTION_RE.finditer(text):
        targets.append({"kind": "chapter", "value": m.group(1), "clauses": None})
    # clause numbers already covered by an expanded RANGE are not separate
    # targets — "4.1.1 至 4.1.2" is ONE read with two clauses, not three
    covered: set[str] = set()
    for m in _CLAUSE_RANGE_RE.finditer(text):
        covered.update(_expand_clause_range(m.group(1), m.group(2)))
    for m in _CLAUSE_NUM_RE.finditer(text):
        num = m.group(1)
        if num in seen_clause or num in covered:
            continue
        seen_clause.add(num)
        targets.append({"kind": "clause", "value": num, "clauses": [num]})

    # dedupe identical targets
    deduped: list[dict] = []
    seen: set[tuple] = set()
    for t in targets:
        key = (t["kind"], t["value"], tuple(t["clauses"] or []))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(t)
    return deduped


def _expand_clause_range(lo: str, hi: str) -> list[str]:
    """4.1.1 至 4.1.3 → [4.1.1, 4.1.2, 4.1.3] when both share a parent."""
    lo_parts, hi_parts = lo.split("."), hi.split(".")
    if len(lo_parts) != len(hi_parts) or lo_parts[:-1] != hi_parts[:-1]:
        return [lo, hi]
    try:
        a, b = int(lo_parts[-1]), int(hi_parts[-1])
    except ValueError:
        return [lo, hi]
    if b < a or b - a > 50:
        return [lo, hi]
    prefix = ".".join(lo_parts[:-1])
    return (
        [f"{prefix}.{i}" for i in range(a, b + 1)] if prefix else [str(i) for i in range(a, b + 1)]
    )


async def expand_candidates(
    conn,
    result,
    workspace: str,
    source_values: dict,
    scope_id: str | None = None,
    table_number: str | None = None,
    expand_docs: bool = False,
    prose_budget: dict | None = None,
) -> None:
    """Attach per-candidate expansion to a SearchResult (mutates in place).

    A scope belongs to ONE document, so expansion is performed once per
    distinct doc among the candidates. ``expand_docs`` replaces the discovery
    candidates with the FULL paged document set matching the parsed code(s) —
    top-k never defines the document list.
    """
    if expand_docs:
        await _expand_documents(conn, result, workspace)
        return

    # Range targets: explicit CLI args win; otherwise parse the request (R3).
    auto_targets: list[dict] = []
    if scope_id is None and table_number is None:
        auto_targets = _requested_targets(result)
        # B1: "第4.3节/4.3节" must not fire twice (as chapter AND as a bare
        # clause number) — a clause target whose value equals an already-listed
        # chapter/section target is the same range, drop the duplicate.
        seen_values = {t["value"] for t in auto_targets if t["kind"] in ("chapter",)}
        deduped: list[dict] = []
        for t in auto_targets:
            if t["kind"] == "clause" and t["value"] in seen_values:
                continue
            deduped.append(t)
        auto_targets = deduped

    expansions: list[dict] = []
    adapter = None
    if not table_number and (scope_id or auto_targets):
        from env_rag_final.catalog.source import SourceAdapter

        adapter = SourceAdapter(
            {
                "host": source_values["POSTGRES_HOST"],
                "port": int(source_values["POSTGRES_PORT"]),
                "user": source_values["POSTGRES_USER"],
                "password": source_values["POSTGRES_PASSWORD"],
                "database": source_values["POSTGRES_DATABASE"],
            }
        )

    # R3: an explicit expansion request that names NO confirmable range can
    # still be confirmed FROM THE KEYWORD EVIDENCE (C5): when a code fixed the
    # document set and keyword candidates exist, a catalog scope whose TITLE
    # matches the request's content terms confirms the range — title matching
    # is auditable (scope title vs query terms), never a guessed doc/scope id.
    confirmed_by_title: list[dict] = []
    if scope_id is None and table_number is None and not auto_targets:
        # title confirmation needs a live catalog connection (None conn in
        # tests = no catalog to confirm against → stays ambiguous)
        if conn is not None:
            confirmed_by_title = await _confirm_scope_by_title(
                conn, result, workspace, result.query_text or ""
            )
        if not confirmed_by_title:
            result.status = "ambiguous"
            result.trace.append(
                {
                    "stage": "scope_expansion",
                    "requested_scope_id": None,
                    "requested_table_number": None,
                    "auto_targets": [],
                    "expansions": [],
                    "note": "expansion requested but the names no confirmable chapter/clause/table "
                    "and no catalog scope title matched the request terms; "
                    "no guessed range — top-level status is ambiguous",
                }
            )
            return

    seen_docs: set[str] = set()
    for cand in result.candidates:
        doc_id = cand["doc_id"]
        if doc_id in seen_docs:
            continue
        seen_docs.add(doc_id)

        if scope_id is not None or table_number is not None:
            # explicit/diagnostic path (single fixed target)
            try:
                expansions.append(
                    await _expand_one(
                        conn,
                        workspace,
                        cand,
                        scope_id,
                        table_number,
                        adapter,
                        prose_budget=prose_budget,
                    )
                )
            except Exception as exc:  # noqa: BLE001 — reported state
                expansions.append(
                    {
                        "doc_id": doc_id,
                        "status": "error",
                        "fail_stage": "expansion_error",
                        "error": type(exc).__name__,
                    }
                )
            continue

        # auto targets: resolve EVERY named range for this document
        for target in auto_targets or (
            [t for t in confirmed_by_title if t.get("doc_id") == doc_id]
        ):
            if target.get("title_confirmed"):
                # C5: scope confirmed by TITLE match against the request terms
                try:
                    expansions.append(
                        await _expand_prose(
                            conn,
                            workspace,
                            doc_id,
                            target["scope_id"],
                            adapter,
                            prose_budget=prose_budget,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    expansions.append(
                        {
                            "doc_id": doc_id,
                            "status": "error",
                            "fail_stage": "expansion_error",
                            "error": type(exc).__name__,
                        }
                    )
                continue
            if target["kind"] == "table":
                try:
                    expansions.append(
                        await _expand_table(conn, workspace, doc_id, str(target["value"]))
                    )
                except Exception as exc:  # noqa: BLE001
                    expansions.append(
                        {
                            "doc_id": doc_id,
                            "status": "error",
                            "fail_stage": "expansion_error",
                            "error": type(exc).__name__,
                        }
                    )
                continue
            stale = await check_search_stale(conn, workspace)
            snap = stale.get("catalog_snapshot_id", "")
            scope_id_resolved, clauses = await _resolve_clause_target(
                conn, workspace, doc_id, snap, target
            )
            if scope_id_resolved is None:
                expansions.append(
                    {
                        "doc_id": doc_id,
                        "status": "ambiguous",
                        "auto_target": target,
                        "note": "requested range does not resolve to a catalog scope in this "
                        "document; no guessed expansion",
                    }
                )
                continue
            try:
                expansions.append(
                    await _expand_prose(
                        conn,
                        workspace,
                        doc_id,
                        scope_id_resolved,
                        adapter,
                        requested_clauses=clauses,
                        prose_budget=prose_budget,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                expansions.append(
                    {
                        "doc_id": doc_id,
                        "status": "error",
                        "fail_stage": "expansion_error",
                        "error": type(exc).__name__,
                    }
                )

    result.trace.append(
        {
            "stage": "scope_expansion",
            "requested_scope_id": scope_id,
            "requested_table_number": table_number,
            "auto_targets": auto_targets,
            "expansions": expansions,
            "note": "expansion reads the FULL ordered membership; discovery top-k is not a limit",
        }
    )
    _propagate_expansion_status(result, expansions)


def _propagate_expansion_status(result, expansions: list[dict]) -> None:
    """R3: all expansion outcomes surface in the top-level contract."""
    if not expansions:
        return
    current = getattr(result, "status", "ok")
    if current not in ("ok", "missing"):
        return
    statuses = [(e.get("status") or e.get("coverage_status") or "").lower() for e in expansions]
    if any(s == "stale" for s in statuses):
        result.status = "stale"
    elif any(s == "ambiguous" for s in statuses):
        result.status = "ambiguous"
    elif any(s == "partial" for s in statuses):
        result.status = "partial"
    elif any(s == "error" for s in statuses):
        result.status = "partial"
    # all complete → leave as-is


async def _expand_documents(conn, result, workspace: str, page_size: int = 100) -> None:
    """Replace discovery candidates with the FULL paged document set.

    R2: multi-target requests are BRANCH SETS — each requested (code, version)
    pair is its own AND-limited branch and the branches merge with OR. An
    empty enumeration that contradicts resolved targets is ambiguous, never
    complete-with-zero. Cover-attribution documents (修改单/整合版) join ONLY
    when the request explicitly asks for them (R1), via name/title evidence —
    never by fabricating a self_code.
    """
    from env_rag_final.enumerate_.doc_enum import enumerate_documents

    predicate, args, pred_text = _doc_predicate(result)
    if predicate is None:
        result.status = "ambiguous"
        result.trace.append(
            {
                "stage": "document_enumeration",
                "predicate": None,
                "note": "no verifiable document predicate could be derived from the request; "
                "refusing to enumerate the whole corpus as the matching set",
            }
        )
        return

    prior_docs = {c["doc_id"] for c in result.candidates}
    enum = await enumerate_documents(
        conn,
        predicate,
        args=args,
        predicate_text=pred_text,
        page_size=page_size,
        workspace=workspace,
    )
    result.candidates = [
        {
            "doc_id": it["doc_id"],
            "doc_name": it["doc_name"],
            "title": it["title"],
            "self_code": it["self_code"],
            "self_code_version": it["self_code_version"],
            "doc_type": it.get("doc_type"),
            "discovery": "document_enumeration",
            "score": None,
            "citation": it["citation"],
            "citation_verified": it["citation_verified"],
        }
        for it in enum.items
    ]
    # R2: an empty match against a request whose targets WERE resolved (or that
    # explicitly asked for membership) contradicts the request — ambiguous.
    if not result.candidates and (prior_docs or _attribution_requested(result.query_text)):
        result.status = "ambiguous"
        result.notes.append(
            "document enumeration matched 0 documents for the resolved predicate; "
            "this contradicts the request's explicit targets — reported ambiguous, "
            "not complete-with-zero"
        )

    # R1 + improvement-3: related/amended documents join ONLY for explicit
    # requests, by catalog-layer name/title evidence over the SAME workspace +
    # the SAME active snapshot the base set was enumerated from (never by
    # fabricated self_code, never through the search index or its search_id —
    # a local replay with an empty or foreign search_id must produce the very
    # same union). The union is published once per (snapshot, doc) with BOTH
    # source paths kept; related match counts and actual new additions are
    # recorded SEPARATELY.
    attribution_requested = _attribution_requested(result.query_text)
    codes = [c for c in (result.parsed_codes or []) if c.get("code")]
    related = None
    related_error = ""
    if attribution_requested:
        if codes:
            from env_rag_final.enumerate_.doc_enum import enumerate_attributed_documents

            related = await enumerate_attributed_documents(
                conn,
                codes,
                workspace,
                expected_snapshot_id=enum.catalog_snapshot_id,
                expected_source=enum.source_snapshot_id,
                page_size=page_size,
            )
        else:
            related_error = (
                "the request explicitly asks for related/amended documents but carries no "
                "parseable (code, version) branch — name/title attribution has nothing to "
                "verify against; refusing to publish a related set (this is a THIS-PATH "
                "refusal, not a claim that none exist)"
            )

    # ---- union: (workspace, snapshot, doc_id) dedup, sources preserved ----
    for c in result.candidates:
        c["sources"] = ["document_enumeration"]
    related_matched = related_evidence = attribution_added = 0
    overlap_evidence_ids: list[str] = []
    overlap_canonical_ids: list[str] = []
    excluded: list[dict] = []
    if related is not None:
        seen = {c["doc_id"]: c for c in result.candidates}
        for it in related.items:
            related_matched += 1
            hits = [b for b in it["attribution_branches"] if b["status"] == "attributed"]
            if not hits:
                mism = [b for b in it["attribution_branches"] if b["status"] != "canonical"]
                if mism:
                    excluded.append({"doc_id": it["doc_id"], "branches": mism})
                else:
                    overlap_canonical_ids.append(it["doc_id"])
                continue
            related_evidence += 1
            if it["doc_id"] in seen:
                overlap_evidence_ids.append(it["doc_id"])
                row = seen[it["doc_id"]]
                row["sources"] = ["document_enumeration", "doc_attribution_catalog"]
                row["attribution_evidence"] = hits
                continue
            attribution_added += 1
            result.candidates.append(
                {
                    "doc_id": it["doc_id"],
                    "doc_name": it["doc_name"],
                    "title": it["title"],
                    "self_code": it["self_code"],
                    "self_code_version": it["self_code_version"],
                    "doc_type": it.get("doc_type"),
                    "discovery": "doc_attribution_catalog",
                    "membership_basis": hits[0]["basis"],
                    "attribution_branches": hits,
                    "score": None,
                    "citation": it["citation"],
                    "citation_verified": it["citation_verified"],
                    "sources": ["doc_attribution_catalog"],
                }
            )

    # post-union publication guard: the merged publish window is guarded as ONE
    # (F1): identity AND a final bounded re-read of both matching sets against
    # the read bases — hashing the in-memory union alone is not verification.
    from env_rag_final.enumerate_.doc_enum import (
        publish_token,
        verify_publication_content,
    )

    guard_reason = await verify_publication_content(
        conn, workspace, enum, related, args, codes, page_size=page_size
    )

    union_total = len(result.candidates)
    union_processed = union_total if guard_reason == "" else len(result.candidates)
    branch_coverage = {
        "base": enum.coverage_status,
        "related": related.coverage_status
        if related is not None
        else (related_error or "not-requested"),
    }
    combined = enum.coverage_status
    if related is not None and related.coverage_status != "complete":
        rank = {"complete": 0, "partial": 1, "ambiguous": 2, "stale": 3}
        if rank[related.coverage_status] > rank[combined]:
            combined = related.coverage_status
    if guard_reason:
        combined = "stale"
    if attribution_requested and combined == "complete":
        if related is None and related_error:
            combined = "ambiguous"
        elif related_evidence == 0:
            combined = "partial"
    # members describe the FINAL matched union: base totals plus the related
    # rows the confirmed same-snapshot attribution actually added on top.
    members_total = enum.members_total + attribution_added
    members_processed = enum.members_processed + attribution_added
    related_note = ""
    if attribution_requested and related_evidence == 0:
        related_note = (
            "the request explicitly asks for 含修改单/相关文件: the attribution scan matched "
            f"{related_matched} row(s) but confirmed NO related evidence on this path "
            "(canonical self matches alone never satisfy a related request; this is not a "
            "claim that none exist in the corpus)"
        )
        result.notes.append(related_note)
    result.trace.append(
        {
            "stage": "document_enumeration",
            "predicate": pred_text,
            "predicate_args": [str(a) for a in args],
            "workspace": workspace,
            "catalog_snapshot_id": enum.catalog_snapshot_id,
            "source_snapshot_id": enum.source_snapshot_id,
            "identity_source": "observed catalog rows via the guarded workspace+snapshot "
            "connection (separate from any replayed PG search identity)",
            "attribution_branch": attribution_requested,
            "attribution_added": attribution_added,
            "related_matches": related_matched,
            "related_evidence": related_evidence,
            "overlap_evidence": overlap_evidence_ids,
            "overlap_canonical": overlap_canonical_ids,
            "related_excluded": excluded,
            "base_total": enum.members_total,
            "base_processed": enum.members_processed,
            "base_coverage": enum.coverage_status,
            "related_total": related.members_total if related is not None else 0,
            "related_processed": related.members_processed if related is not None else 0,
            "related_coverage": branch_coverage["related"],
            "related_warnings": list(related.warnings) if related is not None else [related_error],
            "related_request_note": related_note,
            "union_total": union_total,
            "union_processed": union_processed,
            "publication_guard": guard_reason or "stable",
            "members_total": members_total,
            "members_processed": members_processed,
            "coverage_status": combined,
            "read_token": publish_token(result.candidates),
            "fail_stage": enum.fail_stage
            if enum.fail_stage
            else (related.fail_stage if related is not None and related.fail_stage else ""),
            "warnings": list(enum.warnings)
            + (list(related.warnings) if related is not None else []),
            "note": "full paged base enumeration UNION the same-snapshot catalog attribution "
            "scan — not top-k ranked discovery, not the search index; members_total/processed "
            "describe the FINAL matched union",
        }
    )
    if combined != "complete":
        result.status = "partial" if combined == "partial" else combined


_FRAME_WORDS = {
    "库内",
    "列出",
    "列举",
    "文档",
    "文件名",
    "名称",
    "编号",
    "年份",
    "版本",
    "哪些",
    "哪个",
    "什么",
    "有",
    "无",
    "含",
}


def _name_phrase(text: str) -> str | None:
    """Longest contiguous CJK phrase left after masking frame/stop words.

    "库内有哪些中国移动源环境管理年报" → "中国移动源环境管理年报";
    "库内有哪些文档名称含“修改单"？" → "修改单".
    Only multi-character stopwords and the explicit frame words are masked —
    single characters like 中 may be the leading character of a real name.
    """
    t = tk.normalize_text(text or "")
    masked = list(t)
    words = {w for w in tk.stopwords() if len(w) >= 2} | _FRAME_WORDS
    for w in sorted(words, key=len, reverse=True):
        if not w:
            continue
        start = 0
        while True:
            i = t.find(w, start)
            if i < 0:
                break
            for j in range(i, i + len(w)):
                masked[j] = " "
            start = i + 1
    best = ""
    for m in re.finditer(r"[\u4e00-\u9fff]{2,}", "".join(masked)):
        if len(m.group(0)) > len(best):
            best = m.group(0)
    return best or None


def _acceptable_versions(version: str) -> list[str]:
    out = {version}
    if len(version) == 4:
        out.add(version[2:])
    elif len(version) == 2:
        out.add(("19" if int(version) > 50 else "20") + version)
    return sorted(out)


def _doc_predicate(result) -> tuple[str | None, tuple, str]:
    """Build the predicate SQL from the FULL request constraints (R2).

    ``$1``/``$2`` are workspace/snapshot inside the enumerator, so the first
    predicate parameter is ``$3``. Each requested (code, version) pair is one
    AND-limited branch; branches merge with OR — two versions of one standard
    are a UNION of targets, never an impossible same-row intersection.
    """
    code_branches: list[str] = []
    args: list = []
    codes = result.parsed_codes or ([result.parsed_code] if result.parsed_code else [])
    for c in codes:
        n = len(args) + 3
        if c.get("version"):
            versions = _acceptable_versions(c["version"])
            placeholders = ", ".join(f"${n + 1 + i}" for i in range(len(versions)))
            code_branches.append(f"(self_code = ${n} AND self_code_version IN ({placeholders}))")
            args.extend([c["code"], *versions])
        else:
            code_branches.append(f"(self_code = ${n})")
            args.append(c["code"])

    parts: list[str] = []
    if code_branches:
        parts.append("(" + " OR ".join(code_branches) + ")")

    # name phrase: a pure name request is its own predicate; with code branches
    # it only ANDs when the request does NOT ask for related/amended docs
    # (含修改单 → the amendment set is matched via the attribution branch).
    phrase = _name_phrase(result.query_text)
    if phrase and not code_branches:
        n = len(args) + 3
        parts.append(f"(doc_name LIKE '%' || ${n} || '%')")
        args.append(phrase)

    if not parts:
        return None, (), ""
    predicate = " AND ".join(parts)
    return predicate, tuple(args), predicate


async def _expand_one(
    conn,
    workspace: str,
    cand: dict,
    scope_id,
    table_number,
    adapter,
    prose_budget: dict | None = None,
) -> dict:
    doc_id = cand["doc_id"]

    if table_number:
        return await _expand_table(conn, workspace, doc_id, str(table_number))
    if scope_id:
        return await _expand_prose(
            conn, workspace, doc_id, scope_id, adapter, prose_budget=prose_budget
        )
    return {"doc_id": doc_id, "status": "not_expanded", "note": "no --scope-id/--table-number"}


# generic scope-title words: they appear in many headings and must never
# confirm a range by themselves (C5 title matching)
_GENERIC_TITLE_TERMS = {"标准值", "排放标准", "控制项目", "见表", "表", "规定", "标准"}


async def _confirm_scope_by_title(conn, result, workspace: str, query_text: str) -> list[dict]:
    """C5: confirm a range from KEYWORD evidence when the request names no
    explicit number.

    For each code-fixed document, catalog scopes whose TITLE (heading text)
    contains the request's core content terms (AND-combination, whitespace-
    normalized) are confirmed; the confirmed scope id comes from the CATALOG
    (never hardcoded), and the match basis is recorded for review. A document
    where multiple scopes match equally stays ambiguous (no auto-pick).
    """
    stale = await check_search_stale(conn, workspace)
    if stale["state"] != "current":
        return []
    snap = stale.get("catalog_snapshot_id", "")
    code_docs = sorted(
        {c["doc_id"] for c in result.candidates if c.get("discovery") == "code_exact"}
    )
    if not code_docs:
        return []
    terms = [g.render() for g in tk.query_terms(query_text) if len(g.render()) >= 2]
    if not terms:
        return []
    confirmed: list[dict] = []
    for doc_id in code_docs:
        rows = await conn.fetch(
            """SELECT scope_id, scope_kind, title, number, confirm_status
               FROM env_rag.scopes
               WHERE workspace=$1 AND snapshot_id=$2 AND doc_id=$3
                 AND confirm_status='confirmed' AND title IS NOT NULL
               ORDER BY scope_id""",
            workspace,
            snap,
            doc_id,
        )
        # strip the leading code token from the terms for TITLE matching —
        # the code matched the DOCUMENT, the scope title carries the CONTENT.
        # The term pool also includes the CONTROLLED-VOCAB bigrams of the
        # request (cut_for_search sub-words): "分级别" carries the decisive
        # term 分级 which the maximal-word cut loses to single chars.
        content_terms = [t for t in terms if not t[0].isascii()]
        content_terms = [t for t in content_terms if t not in _GENERIC_TITLE_TERMS]
        import jieba as _jb

        for raw in _jb.cut_for_search(tk.normalize_text(query_text), HMM=False):
            w = raw.strip()
            if (
                len(w) >= 2
                and not w[0].isascii()
                and w not in _GENERIC_TITLE_TERMS
                and w not in tk.stopwords()
                and w not in content_terms
            ):
                content_terms.append(w)
        # single-char CJK terms participate as GRAM pieces: a title containing
        # a two-char bigram of consecutive question grams (e.g. 标准分级 ⊃
        # 分+级 from 分级别) is a legitimate auditable title signal, so add
        # every CJK bigram formed from ADJACENT single-char terms in the
        # normalized request
        norm_q = re.sub(r"\s+", "", tk.normalize_text(query_text))
        for i, ch in enumerate(norm_q):
            if i + 1 < len(norm_q) and "\u4e00" <= ch <= "\u9fff":
                bigram = norm_q[i : i + 2]
                if (
                    bigram not in content_terms
                    and bigram not in _GENERIC_TITLE_TERMS
                    and bigram not in tk.stopwords()
                ):
                    content_terms.append(bigram)
        if not content_terms:
            continue

        def _title_hits(title: str) -> list[str]:
            title_n = re.sub(r"\s+", "", title or "")
            return [t for t in content_terms if t in title_n]

        # C5: a scope whose title is a TABLE REFERENCE (见表N) points to a
        # table, not a classification clause — a question asking for a
        # 级别/分类 enumeration can never be answered by that scope
        rows = [r for r in rows if "见表" not in (r["title"] or "")]

        # strict: every MULTI-CHAR content term inside the title (bigrams are
        # a fallback pool, not AND requirements)
        multi = [
            t
            for t in content_terms
            if len(t) >= 2 and t in [g2.render() for g2 in tk.query_terms(query_text)]
        ]
        matches = [
            dict(r)
            for r in rows
            if multi and all(t in re.sub(r"\s+", "", r["title"] or "") for t in multi)
        ]
        # logged relaxation: the title containing the MOST terms wins when the
        # strict AND fails and the best is unambiguous. C5: the relaxed match
        # must cover at least one BASE content term (a term the user actually
        # "said", not a tokenizer sub-word/bigram) — sub-word-only matches
        # (e.g. 恶臭污染物排放标准值 matching on 恶臭/污染) never confirm a
        # different scope over the one the question is about.
        base_multi = [t for t in terms if not t[0].isascii() and t not in _GENERIC_TITLE_TERMS]
        relaxed = False
        if not matches:
            best = max(
                (dict(r) for r in rows),
                key=lambda r: len(_title_hits(r["title"])),
                default=None,
            )
            if best:
                hits = _title_hits(best["title"])
                if hits and any(h in base_multi for h in hits):
                    ties = [dict(r) for r in rows if len(_title_hits(r["title"])) == len(hits)]
                    if len(ties) == 1:
                        matches = [best]
                        relaxed = True
                        content_terms = hits
        if len(matches) > 1 or not matches:
            # disambiguate / rescue by BODY evidence: the scope whose member
            # units' text contains the request's DISCRIMINATIVE terms (terms
            # not already covered by the title) — auditable via scope_units →
            # source_units content_length/heading plus the request terms
            # body evidence scores the BASE content terms (what the user
            # actually said, generic words removed) over each scope body
            discriminative = [
                t for t in terms if not t[0].isascii() and t not in _GENERIC_TITLE_TERMS
            ]
            if discriminative:
                body_hits: dict[str, int] = {}
                for m in matches or [dict(r) for r in rows]:
                    units_rows = await conn.fetch(
                        """SELECT u.unit_id, u.unit_kind, u.locator
                           FROM env_rag.scope_units s
                           JOIN env_rag.source_units u
                             ON u.workspace=s.workspace AND u.snapshot_id=s.snapshot_id
                            AND u.doc_id=s.doc_id AND u.unit_id=s.unit_id
                           WHERE s.workspace=$1 AND s.snapshot_id=$2 AND s.scope_id=$3
                           ORDER BY s.seq""",
                        workspace,
                        snap,
                        m["scope_id"],
                    )
                    # C5: read the scope BODY (same parsed blocks the reader
                    # uses — no extra authority) and count discriminative
                    # terms; a scope whose body never mentions the request's
                    # core nouns cannot be the answer range
                    from env_rag_final.enumerate_.prose_enum import _unit_text_from_blocks

                    chain = ""
                    for u_row in units_rows:
                        if u_row["unit_kind"] != "block":
                            continue
                        loc = u_row["locator"]
                        loc = __import__("json").loads(loc) if isinstance(loc, str) else (loc or {})
                        pdir_name = (loc or {}).get("parsed_dir")
                        if pdir_name:
                            block_text = _unit_text_from_blocks(
                                sid.PARSED_ROOT / pdir_name, u_row["unit_id"]
                            )
                            if block_text:
                                chain += " " + block_text
                    chain_n = re.sub(r"\s+", "", chain)
                    term_score = sum(1 for t in discriminative if t in chain_n)
                    # a question asking 哪几级/哪些类别 wants a scope whose
                    # body ENUMERATES levels/categories — count the distinct
                    # level markers (一级..五级 / N类) as an intent signal
                    level_markers = len(
                        set(
                            re.findall(
                                r"(?:一|二|三|四|五)级|[IVXⅠⅡⅢⅣⅤNn]{1,4}类",
                                chain_n,
                            )
                        )
                    )
                    body_hits[m["scope_id"]] = term_score + (level_markers >= 3) * 2
                best_n = max(body_hits.values()) if body_hits else 0
                if best_n > 0:
                    winners = [
                        m
                        for m in (matches or [dict(r) for r in rows])
                        if body_hits.get(m["scope_id"]) == best_n
                    ]
                    if len(winners) > 1:
                        # body-score tie: score the leaf contribution — a
                        # parent's body is its children's text; the scope whose
                        # OWN text (not inherited) carries the terms wins.
                        # 4.1 标准分级 owns 「厂界标准值分三级」; 4.2 标准值
                        # only inherits it from 4.2.2.
                        own_texts: dict[str, str] = {}
                        for w in winners:
                            units_rows3 = await conn.fetch(
                                """SELECT s.unit_id, u.unit_kind, u.locator,
                                          u.unit_order
                                   FROM env_rag.scope_units s
                                   JOIN env_rag.source_units u
                                     ON u.workspace=s.workspace
                                    AND u.snapshot_id=s.snapshot_id
                                    AND u.doc_id=s.doc_id AND u.unit_id=s.unit_id
                                   WHERE s.workspace=$1 AND s.snapshot_id=$2
                                     AND s.scope_id=$3
                                   ORDER BY s.seq""",
                                workspace,
                                snap,
                                w["scope_id"],
                            )
                            txt = ""
                            for u_row in units_rows3:
                                if u_row["unit_kind"] != "block":
                                    continue
                                loc = u_row["locator"]
                                loc = (
                                    __import__("json").loads(loc)
                                    if isinstance(loc, str)
                                    else (loc or {})
                                )
                                pd_dir = (loc or {}).get("parsed_dir")
                                if pd_dir:
                                    bt = _unit_text_from_blocks(
                                        sid.PARSED_ROOT / pd_dir, u_row["unit_id"]
                                    )
                                    if bt:
                                        txt += " " + bt
                            own_texts[w["scope_id"]] = txt

                        def _own_score(w) -> int:
                            txt_n = re.sub(r"\s+", "", own_texts.get(w["scope_id"], ""))
                            return (
                                sum(1 for t in discriminative if t in txt_n)
                                + (
                                    len(
                                        set(
                                            re.findall(
                                                r"(?:一|二|三|四|五)级|[IVXⅠⅡⅢⅣⅤNn]{1,4}类",
                                                txt_n,
                                            )
                                        )
                                    )
                                    >= 3
                                )
                                * 2
                            )

                        own_best = max(_own_score(w) for w in winners)
                        winners = [w for w in winners if _own_score(w) == own_best]
                        if len(winners) > 1:
                            deepest = max(
                                winners,
                                key=lambda w: (
                                    (w["number"] or "").count("."),
                                    w["number"] or "",
                                ),
                            )
                            dn = deepest.get("number") or ""
                            if dn and all(
                                (not w["number"]) or dn.startswith(w["number"])
                                for w in winners
                                if w is not deepest
                            ):
                                winners = [deepest]
                    if len(winners) == 1:
                        matches = winners
                        content_terms = list(dict.fromkeys(content_terms + discriminative[:best_n]))
                        relaxed = True
        if len(matches) == 1:
            m0 = matches[0]
            confirmed.append(
                {
                    "doc_id": doc_id,
                    "scope_id": m0["scope_id"],
                    "title_confirmed": True,
                    "matched_title": m0["title"],
                    "matched_terms": content_terms,
                    "relaxed_to_best_coverage": relaxed,
                    "basis": "catalog scope title contains the request content terms",
                }
            )
    if confirmed:
        result.trace.append(
            {
                "stage": "scope_confirmation_by_title",
                "terms": terms,
                "confirmed": confirmed,
                "note": "scope confirmed from catalog title vs request terms; no hardcoded ids",
            }
        )
    return confirmed


async def _resolve_clause_target(
    conn, workspace: str, doc_id: str, snap: str, target: dict
) -> tuple[str | None, list[str] | None]:
    """Resolve a chapter/clause request to a scope + requested clauses.

    Sub-clause numbers ("4.1.1") resolve through their PARENT scope ("4.1")
    with the Phase-1 requested_clauses/locate_span mechanism — no same-number
    scope is required for a bounded read. A chapter number must exist as a
    scope. Ambiguous (multiple) or unresolvable → (None, None).
    """
    value = target["value"]
    candidates_to_try = [value]
    if "." in value:
        parts = value.split(".")
        for depth in range(len(parts) - 1, 0, -1):
            candidates_to_try.append(".".join(parts[:depth]))

    for num in candidates_to_try:
        found = [
            dict(r)
            for r in await conn.fetch(
                """SELECT scope_id, scope_kind, title, number, confirm_status
                   FROM env_rag.scopes
                   WHERE workspace=$1 AND snapshot_id=$2 AND doc_id=$3 AND number=$4
                   ORDER BY scope_id""",
                workspace,
                snap,
                doc_id,
                num,
            )
        ]
        if len(found) == 1:
            # R3: a request for the scope's own number ("4.3") is a WHOLE-SCOPE
            # read — its numbered sub-items are the items (4.3.1–4.3.4); the
            # heading itself is filtered out by _expand_prose. Only a genuinely
            # narrower clause list (4.1.1 至 4.1.2) bounds the extraction.
            clauses = target.get("clauses")
            if clauses == [value] and found[0]["number"] == value:
                clauses = None
            return found[0]["scope_id"], clauses
        if len(found) > 1:
            return None, None  # ambiguous, never auto-picked
    return None, None


_CATEGORY_SENT_RE = re.compile(r"([IVXⅠⅡⅢⅣⅤ]+)\s*类\s*([^；;。\n]+)[；;。\n]?")


def _split_category_sentences(body: str, assembled_text: str) -> list[dict]:
    """C5: split a category/level enumeration body into per-category items.

    Fires ONLY when the body declares a category list (≥3 "N类/级" sentences,
    e.g. GB3838 §3 I–V 类) — otherwise returns [] and the whole-body fallback
    stands. Each item keeps the SOURCE's Roman numeral verbatim (OCR quirks
    stay in the label; the mapping to canonical numerals is review work) and a
    char span over the ASSEMBLED text for re-readable verification: ``body``
    is a suffix of ``assembled_text`` (heading removed), so every body offset
    is mapped back by the body's real start (D1).
    """
    # D1: the body's real start inside the assembled text — the body is the
    # assembled text with the heading line and surrounding whitespace removed
    body_start = assembled_text.find(body) if body else -1
    if body_start < 0:
        return []
    # locate every category marker inside the body; each sentence runs from
    # its marker to the next marker (or the end)
    marker_iter = list(
        re.finditer(
            # OCR note: the corpus renders Ⅱ/Ⅲ as Ⅰ and IV as N — those
            # defective numerals are accepted as markers and kept VERBATIM in
            # the item label (review maps them to canonical classes)
            r"(?:^|[；;。\n：:])(\s*(?:[IVXⅠⅡⅢⅣⅤNn]{1,4}\s*类|(?:一|二|三|四|五)级))",
            body,
        )
    )
    if len(marker_iter) < 3:
        return []
    items: list[dict] = []
    for idx, m in enumerate(marker_iter):
        label = re.sub(r"\s+", "", m.group(1))
        start = m.end(1)
        end = marker_iter[idx + 1].start() if idx + 1 < len(marker_iter) else len(body)
        text_s = body[start:end].strip().rstrip("；;。")
        if not text_s:
            continue
        # D1: map body offsets → ASSEMBLED offsets (marker start to sentence
        # end, inclusive of the trailing separator)
        asm_start = body_start + m.start(1)
        asm_end = body_start + end
        items.append(
            {
                "clause": label,
                "text": text_s,
                "citation": {
                    "kind": "char_span",
                    "char_start": asm_start,
                    "char_end": asm_end,
                    "quote": (assembled_text[asm_start:asm_end])[:120].rstrip("；;。"),
                },
                "citation_verified": True,  # regex-verifiable; re-decided by verify
                "source": "category_sentence_split",
            }
        )
    return items


async def _expand_table(conn, workspace: str, doc_id: str, table_number: str) -> dict:
    from env_rag_final.enumerate_.table_enum import enumerate_table

    r = await enumerate_table(conn, workspace, doc_id, table_number)
    return {
        "doc_id": doc_id,
        "kind": "table",
        "table_number": table_number,
        "scope_ids": r.scope_ids,
        "members_total": r.members_total,
        "members_processed": r.members_processed,
        "coverage_status": r.coverage_status,
        "fail_stage": r.fail_stage,
        "items_count": len(r.items),
        "items": r.items,
        "warnings": r.warnings[:8],
    }


async def _expand_prose(
    conn,
    workspace: str,
    doc_id: str,
    scope_id: str,
    adapter,
    requested_clauses: list[str] | None = None,
    prose_budget: dict | None = None,
) -> dict:
    from env_rag_final.enumerate_.prose_enum import (
        ASSEMBLY_SEPARATOR,
        bind_citations,
        extract_clauses_regex,
        read_prose_scope,
        structural_boundaries,
        verify_citations,
    )

    stale = await check_search_stale(conn, workspace)
    if stale["state"] != "current":
        return {"doc_id": doc_id, "status": "stale", "reason": stale.get("reasons")}
    catalog_snapshot = stale["catalog_snapshot_id"]

    units, r = await read_prose_scope(
        adapter,
        conn,
        workspace,
        doc_id,
        catalog_snapshot,
        scope_id=scope_id,
        requested_clauses=requested_clauses,
        **(prose_budget or {}),
    )
    text = ASSEMBLY_SEPARATOR.join(u.text for u in units)

    # B2: a scope's raw block can spill into the NEXT clause (4.2's block ends
    # inside 4.3/4.4). The answer range ends at the next clause head at the
    # same-or-shallower level — trim the assembled text before extraction so
    # the next section is never reported as this scope's answer.
    scope_number = scope_id.rsplit(":", 1)[-1] if ":" in scope_id else None
    if scope_number:
        scope_depth = scope_number.count(".") + 1
        for m in re.finditer(r"(?m)^#{0,4}\s*([0-9]+(?:\.[0-9]+)*)\s", text):
            num = m.group(1)
            if num == scope_number:
                continue
            if num.count(".") + 1 <= scope_depth and m.start() > 0:
                text = text[: m.start()]
                break

    # I1 (improvement-1, corrected F3): independent structures inside the
    # scope are HARD ends for clause bodies — but attribution matters: a table
    # whose clause intro announces it ("…如下，表内规定属于本条：") stays INSIDE
    # the body, while a colon-intro with no 表/图 object reference is an
    # ambiguity that must never claim complete over a truncated requirement.
    # The last clause ends at its sentence/independent-table boundary — never
    # "everything to EOF" with trailing independent tables swallowed.
    cuts, boundary_notes = structural_boundaries(units, text)
    items = extract_clauses_regex(text, requested_clauses, hard_ends=cuts) if units else []
    items = bind_citations(items, workspace, doc_id, catalog_snapshot, units)
    items = verify_citations(items, text, units)
    unverified = [it for it in items if it.get("citation_verified") is not True]

    # R3: the scope's OWN heading is a boundary, not an item — a chapter
    # request yields its numbered sub-items only (3.1–3.4, not "3" itself).
    # EXCEPTION (B2/C1): a scope with NO numbered sub-clauses (e.g. GB3095 4.2
    # — two provisions, no 4.2.x) answers with its own prose as ONE item. The
    # fallback answer goes through the SAME citation pipeline as every other
    # item: full text (no silent truncation), then bind_citations computes the
    # unit-relative offsets (the assembly map stays valid), then an INDEPENDENT
    # verification — never a hand-set verified flag.
    fallback_body_cut: int | None = None
    if scope_number:
        items = [it for it in items if (it.get("clause") or "") != scope_number]
        unverified = [it for it in unverified if (it.get("clause") or "") != scope_number]
        if not items:
            # F1: the body's REAL start inside the assembled text — never
            # derived from heading_len over a .strip()ed copy (a blank line
            # after the heading or leading indentation would shift the offset).
            # Same mapping as the category branch: locate the exact body slice
            # and keep original assembled coordinates.
            body = text.lstrip()
            heading_skipped = len(text) - len(body)  # leading whitespace
            body_lines = body.split("\n", 1)
            if len(body_lines) == 2 and body_lines[0].strip().startswith("#"):
                # keep the heading line AND everything after it verbatim —
                # including the blank line(s) between heading and body
                body = body_lines[1]
                heading_skipped += len(body_lines[0]) + 1
            body_start = heading_skipped
            # trim the body's own leading/trailing whitespace but keep the
            # trimmed slice mapped to its assembled offsets
            lead_ws = len(body) - len(body.lstrip())
            body = body.strip()
            body_start += lead_ws
            # I1 (improvement-1): a no-subclause scope body ends at the first
            # INDEPENDENT structure inside the scope (table object/caption,
            # appendix heading, table-kind unit) — never "body to EOF" with
            # the section's trailing tables swallowed into the prose answer.
            body_cut = next((c for c in cuts if c > body_start), None)
            if body_cut is not None:
                fallback_body_cut = body_cut
                body = text[body_start:body_cut].strip()
            if body:
                fallback_item = {
                    "clause": scope_number,
                    "text": body,  # FULL body — never silently truncated
                    "citation": {
                        "kind": "char_span",
                        # REAL assembled coordinates of the body slice
                        "char_start": body_start,
                        "char_end": body_start + len(body),
                        "quote": body[:120],
                    },
                    # the span is regex-verifiable (extract_clauses_regex
                    # produced the same shape) — bind_citations keeps True and
                    # verify_citations RE-DECIDES from the verbatim substring
                    "citation_verified": True,
                    "source": "scope_body_no_subclauses",
                }
                items = [fallback_item]
                items = bind_citations(items, workspace, doc_id, catalog_snapshot, units)
                items = verify_citations(items, text, units)
                unverified = [it for it in items if it.get("citation_verified") is not True]

                # C5: category/level LIST bodies (水域功能 I–V 类, 标准分级
                # 一/二/三级) carry the enumeration items INSIDE one block.
                # Each declared category sentence becomes its own answer item
                # with a verifiable span — the OCR'd Roman numeral in the
                # source is kept verbatim as the item label.
                category_items = _split_category_sentences(body, text)
                if category_items:
                    bound = bind_citations(
                        [dict(it) for it in category_items],
                        workspace,
                        doc_id,
                        catalog_snapshot,
                        units,
                    )
                    bound = verify_citations(bound, text, units)
                    if all(b.get("citation_verified") for b in bound):
                        items = bound
                        unverified = []

    # B1: the ANSWER must contain every requested clause. The reading layer
    # completes its read (read_status=complete) even when a requested clause
    # does not exist in the source; that shortage is computed HERE against the
    # extracted items and keeps coverage partial — a successful read never
    # upgrades a scope short of its requested clauses to complete.
    missing_requested: list[str] = []
    if requested_clauses:
        got = {it.get("clause") or it.get("place") for it in items}
        missing_requested = [c for c in requested_clauses if c not in got]

    # F3 (improvement r1): an AMBIGUOUS boundary (colon intro naming no 表/图
    # object) that actually CLIPPED a delivered item — a clause body ending at
    # that offset, or the fallback scope body cut there — is a genuine "cannot
    # determine attribution" case: coverage must be partial with an explicit
    # warning, never silent-complete over possibly truncated requirements.
    ambiguity_bit = [
        n
        for n in boundary_notes
        if (fallback_body_cut is not None and fallback_body_cut == n["pos"])
        or any(
            isinstance(it.get("citation"), dict) and it["citation"].get("char_end") == n["pos"]
            for it in items
        )
    ]

    # G2-5: the reading layer and the extraction layer are reported separately.
    # The reader's "ambiguous" with read_status=complete is its placeholder for
    # "answer layer decides"; here we decide from the actual items. An empty
    # range or a failed read keeps ambiguous/partial; a missing requested
    # clause, an extraction shortfall or unverified citations all stay partial —
    # only a full read where EVERY requested clause was extracted and verified
    # is complete.
    if r.members_total == 0 or r.coverage_status == "stale":
        coverage = r.coverage_status
    elif r.read_status != "complete" or missing_requested:
        coverage = "partial"
    elif unverified or not items:
        coverage = "partial"
    else:
        coverage = "complete"
    if ambiguity_bit and coverage == "complete":
        coverage = "partial"
    return {
        "doc_id": doc_id,
        "kind": "prose",
        "scope_id": scope_id,
        "requested_clauses": requested_clauses,
        "missing_requested_clauses": missing_requested,
        "members_total": r.members_total,
        "members_processed": r.members_processed,
        "coverage_status": coverage,
        "read_status": r.read_status,
        "fail_stage": r.fail_stage,
        "units_read": len(units),
        "unit_ids": [u.unit_id for u in units],
        "chunk_ids": sorted({c for u in units for c in u.chunk_ids}),
        "items_count": len(items),
        "items": items,
        # F3: the ambiguity explanations must be VISIBLE with the partial —
        # "cannot determine attribution" is recorded, never a silent truncation.
        "warnings": r.warnings[:8] + [n["detail"] for n in ambiguity_bit][:4],
        "boundary_ambiguities": ambiguity_bit,
    }
