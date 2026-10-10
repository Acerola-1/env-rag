"""Query routing for the PG keyword path (task 4.3, corrected per Gate 2).

Route order (design.md decision 4): 编号定位 → 元数据限定 → 关键词候选 →
范围确认 → 全部范围读取. Discovery is candidate-only (top-k bounded); the
complete range read is task 4.4 (``expand.py``), never truncated by top-k.

Gate 2 corrections:
- G2-1: the query text is NORMALIZED FIRST (full-width/dashes/spaces via the
  tokenizer's canonical form), then ALL explicit codes are detected and routed.
  Any requested code/version that does not exist makes the whole result
  ``missing``: evidence already resolved for other requested targets is kept,
  but a missing target is never substituted by keyword candidates and a bare
  (version-less) absent code is just as binding as a versioned one.
- G2-3: identity (source fingerprint, catalog snapshot, active search build)
  is re-verified before EVERY result is returned — including early exits.
- G2-6: synonyms are per-concept OR choices combined with AND between
  concepts; the original term is kept, and an OOV term is NOT dropped before
  its controlled synonyms are actually attempted.
"""

from __future__ import annotations

import json
import re
import time
import uuid

from env_rag_final.catalog.lexical_norm import normalize_code

from . import tokenizer as tk
from .expand import _attribution_requested
from .index import check_search_stale

_CODE_IN_QUERY = re.compile(
    r"(?:GB|HJ|DB\d{0,2})\s*/?\s*T?\s*\d+(?:\.\d+)?(?:\s*[-/]\s*\d{2,4})?",
    re.IGNORECASE,
)

DEFAULT_TOP_K = 20

_ACTIVE_SEARCH_SQL = """SELECT search_id, catalog_snapshot_id, source_fingerprint
                        FROM env_rag.search_builds WHERE workspace=$1 AND status='active'"""


class SearchResult:
    def __init__(self, query_id: str, workspace: str):
        self.query_id = query_id
        self.workspace = workspace
        self.status = "ok"  # ok | missing | ambiguous | partial | stale
        self.candidates: list[dict] = []
        # C3: the BUDGETED DISCOVERY list — the ranked candidates as they stood
        # when discovery finished, BEFORE any full enumeration replaced them.
        # Recall is computed from this list only; the enumeration answer set
        # lives in ``candidates``/expansion output and never feeds recall.
        # None until a discovery snapshot is taken (finish() or the expansion
        # path); an EXPLICIT [] is an authoritative zero-discovery result (D2).
        self.discovery_candidates: list[dict] | None = None
        self.notes: list[str] = []
        self.trace: list[dict] = []  # every routing/relaxation step, with terms
        self.search_id = ""
        self.catalog_snapshot_id = ""
        self.source_snapshot_id = ""
        self.parsed_code: dict | None = None
        self.parsed_codes: list[dict] = []
        self.query_text = ""
        self.elapsed_ms = 0

    def to_dict(self) -> dict:
        return {
            "query_id": self.query_id,
            "workspace": self.workspace,
            "status": self.status,
            "search_id": self.search_id,
            "catalog_snapshot_id": self.catalog_snapshot_id,
            "source_snapshot_id": self.source_snapshot_id,
            "parsed_code": self.parsed_code,
            "parsed_codes": self.parsed_codes,
            "query_text": self.query_text,
            "candidates": self.candidates,
            "discovery_candidates": self.discovery_candidates,
            "notes": self.notes,
            "trace": self.trace,
            "elapsed_ms": self.elapsed_ms,
        }


def _split_codes(text: str) -> tuple[list[dict], str]:
    """Extract explicit standard codes; NORMALIZE the text first (G2-1).

    Full-width forms, dash variants and embedded spaces are canonicalized
    before pattern matching, so ``ＧＢ３０９５－１９９６`` routes exactly like
    ``GB3095-1996`` instead of falling through to keyword relaxation.
    """
    t = tk.normalize_text(text or "")
    codes: list[dict] = []
    for m in _CODE_IN_QUERY.finditer(t):
        norm = normalize_code(m.group(0))
        if not norm:
            continue
        base = re.sub(r"-\d+$", "", norm)
        year_m = re.search(r"-(\d{2,4})$", norm)
        codes.append(
            {"raw": m.group(0), "code": base, "version": year_m.group(1) if year_m else None}
        )
    rest = _CODE_IN_QUERY.sub(" ", t)
    return codes, rest


def _dedupe_codes(codes: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    out: list[dict] = []
    for c in codes:
        key = (c["code"], c["version"])
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


async def run_query(
    conn,
    query: str,
    *,
    code: str | None = None,
    top_k: int = DEFAULT_TOP_K,
    strict_code: bool = False,
    expand: bool = False,
    expand_docs: bool = False,
    scope_id: str | None = None,
    table_number: str | None = None,
    workspace: str = "default",
    parsed_root=None,
    source_values: dict | None = None,
) -> SearchResult:
    t0 = time.monotonic()
    result = SearchResult(f"search-{uuid.uuid4().hex[:12]}", workspace)
    result.query_text = query or ""

    captured = {"discovery": False}

    async def finish() -> SearchResult:
        """G2-3: re-verify identity before returning ANY result (all paths).

        D2: every return path leaves an authoritative discovery snapshot — a
        pre-expansion early exit captures the candidates as they stood (even
        empty); the expansion path overwrites it with the pre-expansion list.
        """
        if not captured["discovery"]:
            result.discovery_candidates = list(result.candidates)
        after = await check_search_stale(conn, workspace, parsed_root=parsed_root)
        active_after = await conn.fetchrow(_ACTIVE_SEARCH_SQL, workspace)
        changed = (
            after.get("state") != "current"
            or after.get("search_id") != result.search_id
            or active_after is None
            or active_after["search_id"] != result.search_id
            or active_after["catalog_snapshot_id"] != result.catalog_snapshot_id
        )
        if changed:
            result.status = "stale"
            result.notes.append(
                "source/catalog/search identity changed before the result was returned; "
                "result is stale, not usable"
            )
        result.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return result

    stale = await check_search_stale(conn, workspace, parsed_root=parsed_root)
    result.search_id = stale.get("search_id", "")
    if stale["state"] != "current":
        result.status = "stale"
        result.notes.append(
            f"search index state={stale['state']}: {stale.get('reasons') or stale.get('catalog_state')}"
        )
        result.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return result

    active = await conn.fetchrow(_ACTIVE_SEARCH_SQL, workspace)
    result.search_id = active["search_id"]
    result.catalog_snapshot_id = active["catalog_snapshot_id"]
    result.source_snapshot_id = active["source_fingerprint"]

    # ---- explicit code detection (G2-1: normalization FIRST) --------------
    query_codes, rest = _split_codes(query or "")
    if code:
        norm = normalize_code(tk.normalize_text(code))
        base = re.sub(r"-\d+$", "", norm)
        year_m = re.search(r"-(\d{2,4})$", norm)
        query_codes.insert(
            0, {"raw": code, "code": base, "version": year_m.group(1) if year_m else None}
        )
    query_codes = _dedupe_codes(query_codes)
    result.parsed_code = query_codes[0] if query_codes else None
    result.parsed_codes = query_codes

    if query_codes:
        # EVERY explicit code/version is a strong constraint. Each is routed;
        # a target that does not exist makes the whole result missing. A
        # bare (version-less) code is just as binding as a versioned one.
        missing = False
        missing_targets: list[str] = []
        for qc in query_codes:
            note_count = len(result.notes)
            resolved = await _code_route(conn, result, qc, workspace, strict=strict_code)
            if not resolved:
                missing = True
                missing_targets.append(
                    f"{qc['code']}-{qc['version']}" if qc["version"] else qc["code"]
                )
            _ = note_count
        if missing:
            result.status = "missing"
            result.notes.append(
                "requested target(s) missing: "
                + ", ".join(missing_targets)
                + "; resolved evidence for other requested targets is retained above, "
                "but keyword candidates never substitute a missing requested target"
            )
            return await finish()

    # design order: 编号定位 → 元数据限定 → 关键词候选. When the code route
    # matched documents, keyword search is RESTRICTED to those documents — the
    # strong constraint is metadata, not the top-k order.
    restrict_docs = {
        c["doc_id"] for c in result.candidates if c.get("discovery") == "code_exact"
    } or None

    # ---- metadata + keyword route -----------------------------------------
    terms = tk.query_terms(rest if query_codes else (query or ""))
    if not terms and not query_codes:
        result.notes.append("no searchable terms after stopword removal")
        result.status = "ambiguous"
        return await finish()

    # Document-level attribution (R1): a document whose NAME/TITLE explicitly
    # carries the requested code joins the related set ONLY when the request
    # explicitly asks for related/amended documents (含修改单/相关文件/整合版).
    # A self-code ("自身编号…") or plain standard/section query keeps its EXACT
    # target — related docs are never mixed into it, and no self_code is
    # fabricated for the attributed docs.
    if query_codes and terms and _attribution_requested(result.query_text):
        await _doc_attribution_route(conn, result, query_codes, terms, workspace, top_k)

    if terms:
        await _keyword_route(conn, result, terms, workspace, top_k, restrict_docs=restrict_docs)

    # ---- range confirmation (design order: 范围确认) -----------------------
    # When the request names a table number or a chapter/clause AND an explicit
    # code fixed the document set, bind the requested range to the ACTUAL
    # catalog units and emit them as candidates. This is discovery of the
    # answer evidence (unit/table scopes), not the full expansion — the read
    # of every member still happens in expand.py.
    await _range_route(conn, result, workspace, top_k)

    # code + keyword: intersect candidate docs when both produced results
    if query_codes and terms and result.candidates and restrict_docs is None:
        await _intersect_code_keyword(conn, result, workspace)

    if not result.candidates and result.status == "ok":
        result.status = "missing"
        result.notes.append("no candidate matched after controlled relaxation")

    # ---- scope/range expansion (task 4.4, G2-5) ---------------------------
    # C3: snapshot the BUDGETED discovery list BEFORE any full enumeration —
    # recall is computed from this list; the enumeration answer never feeds it.
    result.discovery_candidates = list(result.candidates)
    captured["discovery"] = True
    if expand_docs:
        from .expand import expand_candidates

        await expand_candidates(conn, result, workspace, source_values or {}, expand_docs=True)
    elif expand and result.candidates:
        from .expand import expand_candidates

        await expand_candidates(
            conn,
            result,
            workspace,
            source_values or {},
            scope_id=scope_id,
            table_number=table_number,
        )

    return await finish()


async def _range_route(conn, result: SearchResult, workspace: str, top_k: int) -> None:
    """Bind a requested table number / chapter to its real catalog units.

    ``表N`` in the request → the logical table's physical fragments in the
    code-fixed documents; ``第N章``/``N.N`` → the scope's member units. The
    emitted candidates carry the unit/table identity so answer-evidence recall
    measures the REAL evidence, and the top-k budget applies to this list like
    any other discovery stage (documented, counted).

    Only runs when explicit codes fixed a document set; a request with no
    confirmable range is left untouched (no guessed binding).
    """
    from .expand import _requested_targets

    targets = _requested_targets(result)
    if not targets:
        return
    code_docs = sorted(
        {c["doc_id"] for c in result.candidates if c.get("discovery") == "code_exact"}
    )
    if not code_docs:
        return
    snap = result.catalog_snapshot_id
    emitted: list[dict] = []
    for target in targets:
        if target["kind"] == "table":
            rows = await conn.fetch(
                """SELECT doc_id, unit_id, caption, table_seq, heading
                   FROM env_rag.source_units
                   WHERE workspace=$1 AND snapshot_id=$2 AND doc_id = ANY($3::text[])
                     AND unit_kind='table' AND (caption LIKE '%表' || $4 || '%'
                         OR caption LIKE '%表 ' || $4 || '%')
                   ORDER BY doc_id, unit_order, table_seq""",
                workspace,
                snap,
                code_docs,
                target["value"],
            )
            for r in rows:
                chunks = await conn.fetch(
                    """SELECT chunk_id FROM env_rag.unit_chunk_links
                       WHERE workspace=$1 AND snapshot_id=$2 AND doc_id=$3 AND unit_id=$4
                       ORDER BY chunk_order""",
                    workspace,
                    snap,
                    r["doc_id"],
                    r["unit_id"],
                )
                emitted.append(
                    {
                        "doc_id": r["doc_id"],
                        "unit_id": r["unit_id"],
                        "table_id": r["unit_id"],
                        "heading": r["heading"],
                        "chunk_ids": [c["chunk_id"] for c in chunks],
                        "score": None,
                        "discovery": "table_range_binding",
                        "citation": {
                            "kind": "table_unit",
                            "workspace": workspace,
                            "snapshot_id": snap,
                            "doc_id": r["doc_id"],
                            "table_id": r["unit_id"],
                            "chunk_ids": [c["chunk_id"] for c in chunks],
                        },
                        "citation_verified": True,
                    }
                )
        else:  # chapter / clause number
            rows = await conn.fetch(
                """SELECT s.doc_id, s.scope_id, s.title, s.number, s.confirm_status
                   FROM env_rag.scopes s
                   WHERE s.workspace=$1 AND s.snapshot_id=$2 AND s.doc_id = ANY($3::text[])
                     AND s.number=$4
                   ORDER BY s.doc_id, s.scope_id""",
                workspace,
                snap,
                code_docs,
                target["value"],
            )
            for r in rows:
                units = await conn.fetch(
                    """SELECT unit_id FROM env_rag.scope_units
                       WHERE workspace=$1 AND snapshot_id=$2 AND scope_id=$3
                       ORDER BY seq""",
                    workspace,
                    snap,
                    r["scope_id"],
                )
                emitted.append(
                    {
                        "doc_id": r["doc_id"],
                        "scope_id": r["scope_id"],
                        "heading": r["title"],
                        "chunk_ids": [],
                        "score": None,
                        "discovery": "scope_range_binding",
                        "scope_status": r["confirm_status"],
                        "member_units": [u["unit_id"] for u in units],
                        "citation": {
                            "kind": "scope",
                            "workspace": workspace,
                            "snapshot_id": snap,
                            "doc_id": r["doc_id"],
                            "scope_id": r["scope_id"],
                        },
                        "citation_verified": True,
                    }
                )
    if not emitted:
        result.trace.append(
            {
                "stage": "range_binding",
                "targets": targets,
                "code_docs": code_docs,
                "hits": 0,
                "note": "requested range does not resolve in the code-fixed documents; "
                "no guessed range binding",
            }
        )
        return
    # top-k is a ranked budget over this discovery stage too; the emitted order
    # is deterministic (doc, order) and the FULL set is recorded in the trace.
    selected = emitted[:top_k]
    result.candidates.extend(selected)
    result.trace.append(
        {
            "stage": "range_binding",
            "targets": targets,
            "code_docs": code_docs,
            "hits": len(emitted),
            "selected": len(selected),
            "budget": top_k,
            "units": [e.get("unit_id") or e.get("scope_id") for e in emitted],
            "note": "requested table/chapter bound to actual catalog units; full member read "
            "stays in expansion, top-k bounds this discovery list too",
        }
    )


async def _code_route(conn, result: SearchResult, qc: dict, workspace: str, strict: bool) -> bool:
    """Exact self_code routing; returns True when >=1 document was selected.

    A requested version that is absent, or a code that no document carries as
    its own number, is a MISSING target — other versions/documents are never
    substituted (G2-1).
    """
    sql = """SELECT doc_id, doc_name, self_code, self_code_version, title, doc_type
             FROM env_rag.search_documents
             WHERE workspace=$1 AND search_id=$2 AND self_code=$3
             ORDER BY self_code_version, doc_name"""
    rows = await conn.fetch(sql, workspace, result.search_id, qc["code"])
    step = {
        "stage": "code_exact",
        "code": qc["code"],
        "version_requested": qc["version"],
        "strict": strict,
        "hits": len(rows),
    }
    if qc["version"]:
        matched = [
            r for r in rows if _version_matches(r["self_code_version"], qc["version"], strict)
        ]
        step["version_matched"] = len(matched)
        others = [r for r in rows if r not in matched]
        if not matched:
            result.notes.append(
                f"requested {qc['code']}-{qc['version']} is not in the corpus "
                f"({len(others)} other version(s) exist: "
                f"{[r['self_code_version'] for r in others]}); "
                "another version is NOT substituted"
            )
            result.trace.append(step)
            return False
        rows = matched
    if not rows:
        result.notes.append(
            f"requested code {qc['code']} is not the own number (self_code) of any "
            "document; a missing explicit target is reported, not substituted by "
            "keyword candidates"
        )
        step["note"] = "no document carries this self_code"
        result.trace.append(step)
        return False
    step["selected_versions"] = [r["self_code_version"] for r in rows]
    step["selected_docs"] = [r["doc_id"] for r in rows]
    result.trace.append(step)
    for r in rows:
        result.candidates.append(
            {
                "doc_id": r["doc_id"],
                "doc_name": r["doc_name"],
                "self_code": r["self_code"],
                "self_code_version": r["self_code_version"],
                "title": r["title"],
                "doc_type": r["doc_type"],
                "discovery": "code_exact",
                "score": 1.0,
                "citation": {
                    "kind": "catalog_row",
                    "workspace": workspace,
                    "snapshot_id": result.catalog_snapshot_id,
                    "doc_id": r["doc_id"],
                },
                "citation_verified": True,
            }
        )
    return True


def _version_matches(stored: str | None, requested: str, strict: bool) -> bool:
    if not stored:
        return False
    if stored == requested:
        return True
    if strict:
        return False
    # 2-digit legacy years: GB14554-93 == GB14554-1993
    if len(requested) == 4 and len(stored) == 2:
        return requested[2:] == stored
    if len(requested) == 2 and len(stored) == 4:
        return stored[2:] == requested
    return False


def own_identity_tokens(doc_name: str | None, title: str | None) -> set:
    """Query-mode rendered tokens of the document's OWN name/title — the
    accepted attribution evidence surface (improvement-3: extracted from the
    keyword route's per-row judgement verbatim so the catalog-layer file
    enumeration reuses the SAME rule; the route's behavior is unchanged)."""
    name_render = {g.render() for g in tk.tokenize(doc_name or "", mode="query")}
    title_render = {g.render() for g in tk.tokenize(title or "", mode="query")}
    return name_render | title_render


def attribution_judgement(row: dict, query_codes: list[dict]) -> list[dict]:
    """Per-BRANCH name/title attribution judgement of the document's OWN identity.

    Each requested (code, version) branch is judged ALONE and the branches
    merge as a UNION at the set level — one branch's code is never combined
    with another branch's year inside a row. Statuses:

    - ``attributed``     — the row carries this branch's code in its name/
      title and its catalog identity does NOT already satisfy that branch:
      genuine RELATED evidence (amendment / integrated version). The plain
      body of a 含修改单 request can never fake the related set with this.
    - ``canonical``      — carried, but explained entirely by the row's own
      self_code/self_code_version: the standard itself. Recorded for overlap
      bookkeeping, never counted as evidence.
    - ``version_mismatch`` — carries the code but the code-bearing token
      states a different year than the requested branch (2/4-digit
      equivalence as elsewhere): excluded, never a substitution.
    - ``stated_conflict`` — the row's own self_code_version contradicts the
      branch the name/title would hit: excluded.
    - ``similar_prefix`` — a name/title token shares the code's prefix but is
      a different code (e.g. gb1846 vs gb18466): audited, not attributed.

    Body citations never qualify — only the row's own fields; unknown
    self_code stays unknown, never written into a standard number.
    Returns one entry per branch with a non-``none`` status; [] = no carry.
    """
    tokens = own_identity_tokens(row.get("doc_name"), row.get("title"))
    if not tokens:
        return []
    out: list[dict] = []
    for qc in query_codes or []:
        code = (qc.get("code") or "").lower()
        if not code:
            continue
        version = qc.get("version") or ""
        carrying = {rt for rt in tokens if rt == code or rt.startswith(code + "-")}
        basis = f"doc name/title carries the requested code (self_code={row.get('self_code')!r})"
        if not carrying:
            near = {
                rt
                for rt in tokens
                if rt.startswith(code[: max(len(code) - 1, 4)])
                and rt != code
                and not rt.startswith(code + "-")
                and not code.startswith(rt + "-")
            }
            if near:
                out.append(
                    {
                        "code": qc.get("code"),
                        "version": version or None,
                        "status": "similar_prefix",
                        "basis": f"similar-prefix token {sorted(near)} is NOT the requested code",
                        "canonical": False,
                    }
                )
            continue
        entry = {"code": qc.get("code"), "version": version or None, "basis": basis}
        if version:
            coded = {rt for rt in carrying if "-" in rt}
            if coded and not any(
                rt.endswith("-" + version) or rt.endswith("-" + version[2:]) for rt in coded
            ):
                entry["status"] = "version_mismatch"
                entry["canonical"] = False
                out.append(entry)
                continue
            stated = row.get("self_code_version") or ""
            if stated and not _version_matches(stated, version, strict=False):
                entry["status"] = "stated_conflict"
                entry["canonical"] = False
                out.append(entry)
                continue
        canon = (
            bool(row.get("self_code"))
            and (normalize_code(str(row["self_code"])) or str(row["self_code"])).casefold() == code
        )
        if canon and version:
            canon = canon and _version_matches(row.get("self_code_version"), version, strict=True)
        entry["status"] = "canonical" if canon else "attributed"
        entry["canonical"] = bool(canon)
        out.append(entry)
    return out


def _or_group_tsquery(group: list[tk.QueryToken]) -> str:
    """One concept's candidates as an OR group: ('a' | 'b' | 'c')."""
    return "(" + " | ".join(t.to_tsquery() for t in group) + ")"


async def _doc_attribution_route(
    conn,
    result: SearchResult,
    query_codes: list[dict],
    terms: list[tk.QueryToken],
    workspace: str,
    top_k: int,
) -> None:
    """Documents whose own name/title carries an explicitly requested code.

    The 修改单 / 含修改单整合版 documents have no self_code but their document
    NAME contains the standard's code ("GB18466" via the doc string). This
    route matches the code against the document name/title text — evidence
    about the document's own identity, not a citation in its body — and emits
    a doc-level candidate tagged ``doc_attribution``. It never sets a
    self_code; the membership basis is recorded for review.
    """
    # The code as it appears in names: GB18466 / GB 18466. Use the same code
    # pattern over the name text (index tokens already canonicalize 'gb18466').
    allowed_versions: dict[str, list[str]] = {}
    for qc in query_codes:
        # tokenizer canonical codes are lowercase ("gb18466"); normalize the
        # routing form the same way before comparing against name/title tokens
        allowed_versions.setdefault(qc["code"].lower(), []).append(qc.get("version") or "")
    rows = await conn.fetch(
        """SELECT doc_id, doc_name, title, self_code, self_code_version, doc_type
           FROM env_rag.search_documents
           WHERE workspace=$1 AND search_id=$2
             AND (tsv @@ to_tsquery('simple', $3) OR tsv @@ to_tsquery('simple', $4))
           ORDER BY doc_name LIMIT $5""",
        workspace,
        result.search_id,
        tk.or_tsquery([tk.QueryToken((code,)) for code in allowed_versions]),
        tk.or_tsquery(terms),
        max(top_k * 4, 40),
    )
    emitted = 0
    for r in rows:
        # rendered token groups: a code+year appears as the single rendered
        # token "gb18466-2005" (its lexemes joined), a bare code as "gb18466"
        # (improvement-3: same primitives as the catalog-layer enumeration —
        # a shared extraction, the route's judgement itself unchanged)
        own_tokens = own_identity_tokens(r["doc_name"], r["title"])
        code_hit = any(
            code in own_tokens or any(rt.startswith(code + "-") for rt in own_tokens)
            for code in allowed_versions
        )
        # the requested code must be part of the document's OWN name/title
        # (e.g. "gb18466-2005"), never a substring of unrelated text
        if not code_hit:
            continue
        if any(c.get("doc_id") == r["doc_id"] for c in result.candidates):
            continue
        # version guard: when a version was requested, the code occurrence in
        # the name/title must carry that version ("gb18466-2005"), or the doc
        # must not state a conflicting self_code_version
        wanted_versions = {qc["version"] for qc in query_codes if qc.get("version")}
        if wanted_versions:
            coded = {
                rt for rt in own_tokens if any(rt.startswith(c + "-") for c in allowed_versions)
            }
            if coded and not any(
                any(rt.endswith("-" + w) or rt.endswith("-" + w[2:]) for w in wanted_versions)
                for rt in coded
            ):
                continue
            if r["self_code_version"] and not any(
                _version_matches(r["self_code_version"], w, strict=False) for w in wanted_versions
            ):
                continue
        basis = f"doc name/title carries the requested code (self_code={r['self_code']!r})"
        result.candidates.append(
            {
                "doc_id": r["doc_id"],
                "doc_name": r["doc_name"],
                "title": r["title"],
                "self_code": r["self_code"],
                "self_code_version": r["self_code_version"],
                "doc_type": r["doc_type"],
                "score": None,
                "discovery": "doc_attribution",
                "membership_basis": basis,
                "citation": {
                    "kind": "catalog_row",
                    "workspace": workspace,
                    "snapshot_id": result.catalog_snapshot_id,
                    "doc_id": r["doc_id"],
                },
                "citation_verified": True,
            }
        )
        emitted += 1
    if emitted:
        result.trace.append(
            {
                "stage": "doc_attribution",
                "codes": sorted(allowed_versions),
                "emitted": emitted,
                "note": "name/title-explicit code attribution; no self_code fabricated",
            }
        )


async def _keyword_route(
    conn,
    result: SearchResult,
    terms: list[tk.QueryToken],
    workspace: str,
    top_k: int,
    restrict_docs: set[str] | None = None,
) -> None:
    """Document-level + chunk-level matching with a LOGGED relaxation ladder.

    ``restrict_docs``: when an explicit code matched, every keyword query is
    restricted to those documents (metadata restriction, design order).

    Ladder (each step recorded with its exact tsquery and hit count):
      A. AND over all terms (chunk + document level)
      B. AND over the terms that actually occur in the corpus
      C. per-concept OR groups (original term + controlled synonyms) combined
         with AND between concepts — an OOV term is NOT dropped before its
         synonyms are attempted (G2-6)
      D. OR over the occurring terms (last resort, still logged)

    A relaxation never drops a strong constraint: explicit code/version is
    enforced by the code route and the document restriction.
    """
    docs = sorted(restrict_docs) if restrict_docs else None

    # ---- A: AND over all terms -------------------------------------------
    and_q = tk.and_tsquery(terms)
    docs_and = [] if docs else await _rank_docs(conn, result.search_id, and_q, top_k, workspace)
    if docs_and:
        _add_doc_candidates(result, docs_and, "doc_and")

    t0 = time.monotonic()
    rows = await _rank_chunks(conn, result.search_id, and_q, top_k, workspace, docs)
    result.trace.append(
        {
            "stage": "keyword_and",
            "tsquery": and_q,
            "top_k": top_k,
            "restricted_to_code_docs": docs,
            "doc_hits": len(docs_and),
            "chunk_hits": len(rows),
            "elapsed_ms": int((time.monotonic() - t0) * 1000),
        }
    )
    if rows:
        _add_chunk_candidates(result, rows, workspace, "keyword_and")
    if rows or docs_and:
        return

    # ---- per-term diagnostics --------------------------------------------
    per_term = []
    for term in terms:
        n = await _term_hits(conn, result.search_id, term, workspace, docs)
        per_term.append({"term": term.render(), "chunk_hits": n})
    present = [t for t, st in zip(terms, per_term, strict=True) if st["chunk_hits"] > 0]
    absent = [st["term"] for st in per_term if st["chunk_hits"] == 0]
    result.trace.append(
        {"stage": "keyword_and_diagnostics", "per_term": per_term, "absent_terms": absent}
    )
    syn = tk.synonyms()
    absent_set = set(absent)

    def _alts_for(key: str) -> list[tk.QueryToken]:
        return [tk.QueryToken((a,)) for a in syn.get(key, []) if a not in tk.stopwords()]

    # ---- B: concept OR groups FIRST when an OOV term has synonyms (R7) -----
    # An OOV concept whose controlled synonyms exist must be attempted via its
    # OR group BEFORE any core-AND result is returned — a core hit on the other
    # concepts must not silently drop this concept's meaning.
    absent_with_syn = [t for t in terms if t.render() in absent_set and _alts_for(t.render())]
    if absent_with_syn:
        or_groups: list[str] = []
        applied: list[dict] = []
        skipped: list[str] = []
        for term in terms:
            key = term.render()
            alts = _alts_for(key)
            hit = key not in absent_set
            if alts or hit:
                group = [term, *alts]
                or_groups.append(_or_group_tsquery(group))
                if alts:
                    applied.append(
                        {"canon": key, "alts": [a.render() for a in alts], "present": hit}
                    )
            else:
                skipped.append(key)
        if or_groups:
            sub_q = " & ".join(or_groups)
            rows = await _rank_chunks(conn, result.search_id, sub_q, top_k, workspace, docs)
            result.trace.append(
                {
                    "stage": "keyword_synonym_and",
                    "tsquery": sub_q,
                    "synonyms_applied": applied,
                    "skipped_terms": skipped,
                    "oov_concepts_attempted": [t.render() for t in absent_with_syn],
                    "chunk_hits": len(rows),
                    "note": "OOV concept with controlled synonyms attempted via its OR group "
                    "BEFORE any core-AND result; concepts AND-combined; strong constraints kept",
                }
            )
            if rows:
                _add_chunk_candidates(result, rows, workspace, "keyword_synonym_and")
                return

    # ---- C: AND over occurring terms --------------------------------------
    if present:
        core_q = tk.and_tsquery(present)
        rows = await _rank_chunks(conn, result.search_id, core_q, top_k, workspace, docs)
        result.trace.append(
            {
                "stage": "keyword_core_and",
                "tsquery": core_q,
                "dropped_absent_terms": sorted(absent),
                "chunk_hits": len(rows),
                "note": "terms absent from the corpus cannot participate in AND",
            }
        )
        if rows:
            _add_chunk_candidates(result, rows, workspace, "keyword_core_and")
            return

    # ---- D: per-concept OR groups with controlled synonyms (remaining) -----
    groups: list[tk.QueryToken] = []
    or_groups: list[str] = []
    applied: list[dict] = []
    skipped: list[str] = []
    for term in terms:
        key = term.render()
        alts = _alts_for(key)
        hit = key not in absent_set
        if alts or hit:
            group = [term, *alts]
            groups.append(group)
            or_groups.append(_or_group_tsquery(group))
            if alts:
                applied.append({"canon": key, "alts": [a.render() for a in alts], "present": hit})
        else:
            skipped.append(key)
    if or_groups:
        sub_q = " & ".join(or_groups)
        rows = await _rank_chunks(conn, result.search_id, sub_q, top_k, workspace, docs)
        result.trace.append(
            {
                "stage": "keyword_synonym_and",
                "tsquery": sub_q,
                "synonyms_applied": applied,
                "skipped_terms": skipped,
                "chunk_hits": len(rows),
                "note": "each concept is an OR group (original + controlled synonyms); "
                "concepts are AND-combined; strong constraints kept",
            }
        )
        if rows:
            _add_chunk_candidates(result, rows, workspace, "keyword_synonym_and")
            return
    else:
        result.trace.append(
            {
                "stage": "keyword_no_terms_present",
                "skipped_terms": skipped,
                "note": "no term (or its synonyms) occurs in the index at all",
            }
        )

    # ---- D: OR over the occurring terms (last resort) ----------------------
    or_pool = present or [t for t in terms if t.render() not in skipped]
    if or_pool:
        or_q = tk.or_tsquery(or_pool)
        rows = await _rank_chunks(conn, result.search_id, or_q, top_k, workspace, docs)
        result.trace.append(
            {
                "stage": "keyword_or_relaxed",
                "tsquery": or_q,
                "synonyms_applied": applied,
                "chunk_hits": len(rows),
                "note": "last-resort OR over terms present in the corpus",
            }
        )
        if rows:
            _add_chunk_candidates(result, rows, workspace, "keyword_or_relaxed")
            return
    result.trace.append(
        {
            "stage": "keyword_or_original",
            "tsquery": tk.or_tsquery(terms),
            "chunk_hits": 0,
            "note": "OR over the original terms also returned nothing",
        }
    )


async def _term_hits(
    conn, search_id: str, term: tk.QueryToken, workspace: str, docs: list[str] | None
) -> int:
    if docs:
        return await conn.fetchval(
            """SELECT count(*) FROM env_rag.search_chunks
               WHERE workspace=$1 AND search_id=$2 AND doc_id = ANY($4::text[])
                 AND tsv @@ to_tsquery('simple',$3)""",
            workspace,
            search_id,
            term.to_tsquery(),
            docs,
        )
    return await conn.fetchval(
        """SELECT count(*) FROM env_rag.search_chunks
           WHERE workspace=$1 AND search_id=$2 AND tsv @@ to_tsquery('simple',$3)""",
        workspace,
        search_id,
        term.to_tsquery(),
    )


async def _rank_docs(conn, search_id: str, tsquery: str, top_k: int, workspace: str) -> list:
    """Document-level discovery over search_documents.tsv (name/title/code)."""
    return await conn.fetch(
        """SELECT doc_id, doc_name, title, self_code, self_code_version, doc_type,
                  ts_rank_cd(tsv, to_tsquery('simple',$3)) AS rank
           FROM env_rag.search_documents
           WHERE workspace=$1 AND search_id=$2 AND tsv @@ to_tsquery('simple',$3)
           ORDER BY rank DESC, doc_name
           LIMIT $4""",
        workspace,
        search_id,
        tsquery,
        top_k,
    )


def _add_doc_candidates(result: SearchResult, rows: list, stage: str) -> None:
    seen = {c["doc_id"] for c in result.candidates}
    for r in rows:
        if r["doc_id"] in seen:
            continue
        result.candidates.append(
            {
                "doc_id": r["doc_id"],
                "doc_name": r["doc_name"],
                "title": r["title"],
                "self_code": r["self_code"],
                "self_code_version": r["self_code_version"],
                "doc_type": r["doc_type"],
                "score": float(r["rank"]),
                "discovery": stage,
                "citation": {
                    "kind": "catalog_row",
                    "workspace": result.workspace,
                    "snapshot_id": result.catalog_snapshot_id,
                    "doc_id": r["doc_id"],
                },
                "citation_verified": True,
            }
        )


async def _rank_chunks(
    conn,
    search_id: str,
    tsquery: str,
    top_k: int,
    workspace: str = "default",
    docs: list[str] | None = None,
) -> list:
    """Discovery only: ranked chunk candidates, bounded by top_k.

    ``docs`` restricts to an explicit document set (code-matched metadata
    restriction) — the restriction is a strong constraint, not a ranking hint.
    """
    if docs:
        return await conn.fetch(
            """SELECT chunk_id, doc_id, heading, chunk_order,
                      ts_rank_cd(tsv, to_tsquery('simple',$3)) AS rank
               FROM env_rag.search_chunks
               WHERE workspace=$1 AND search_id=$2 AND doc_id = ANY($5::text[])
                 AND tsv @@ to_tsquery('simple',$3)
               ORDER BY rank DESC, doc_id, chunk_order
               LIMIT $4""",
            workspace,
            search_id,
            tsquery,
            top_k,
            docs,
        )
    return await conn.fetch(
        """SELECT chunk_id, doc_id, heading, chunk_order,
                  ts_rank_cd(tsv, to_tsquery('simple',$3)) AS rank
           FROM env_rag.search_chunks
           WHERE workspace=$1 AND search_id=$2 AND tsv @@ to_tsquery('simple',$3)
           ORDER BY rank DESC, doc_id, chunk_order
           LIMIT $4""",
        workspace,
        search_id,
        tsquery,
        top_k,
    )


def _add_chunk_candidates(result: SearchResult, rows: list, workspace: str, stage: str) -> None:
    for r in rows:
        result.candidates.append(
            {
                "doc_id": r["doc_id"],
                "chunk_id": r["chunk_id"],
                "heading": r["heading"],
                "chunk_order": r["chunk_order"],
                "score": float(r["rank"]),
                "discovery": stage,
                "citation": {
                    "kind": "chunk_row",
                    "workspace": workspace,
                    "snapshot_id": result.catalog_snapshot_id,
                    "doc_id": r["doc_id"],
                    "chunk_id": r["chunk_id"],
                },
                "citation_verified": True,
            }
        )


async def _intersect_code_keyword(conn, result: SearchResult, workspace: str) -> None:
    """Keep only keyword candidates from docs carrying the explicit code."""
    code_docs = {c["doc_id"] for c in result.candidates if c.get("discovery") == "code_exact"}
    if not code_docs:
        return
    kept, dropped = [], 0
    for c in result.candidates:
        if c.get("discovery") == "code_exact":
            kept.append(c)
            continue
        if c["doc_id"] in code_docs:
            kept.append(c)
        else:
            dropped += 1
    result.candidates = kept
    result.trace.append(
        {
            "stage": "intersect_code",
            "code_docs": sorted(code_docs),
            "dropped_keyword_candidates": dropped,
            "note": "strong code constraint filters the keyword candidate set",
        }
    )
    if not kept:
        result.status = "missing"
        result.notes.append("no keyword hits inside the requested code's documents")


async def explain_query(
    conn, search_id: str, tsquery: str, workspace: str = "default"
) -> list[str]:
    """EXPLAIN (ANALYZE, BUFFERS) of the exact discovery SQL — recorded evidence."""
    rows = await conn.fetch(
        """EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
           SELECT chunk_id FROM env_rag.search_chunks
           WHERE workspace=$1 AND search_id=$2 AND tsv @@ to_tsquery('simple',$3)
           ORDER BY ts_rank_cd(tsv, to_tsquery('simple',$3)) DESC LIMIT 20""",
        workspace,
        search_id,
        tsquery,
    )
    return [r[0] for r in rows]


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)
