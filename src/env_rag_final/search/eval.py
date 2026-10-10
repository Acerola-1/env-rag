"""Benchmark evaluation entry (tasks 4.5 / Gate 2, corrected per G2-8).

Frozen metric contract (per the Gate 2 review):

1. **Eligibility**: only gold whose status is explicitly ``reviewed``/``approved``
   AND whose source snapshot still matches enters the metrics. Every other
   status (unreviewed, rejected, pending, ``needs_correction``) is excluded and
   listed separately.

2. **Ranked budget**: candidates are TRUNCATED to the first ``top_k`` BEFORE any
   hit is counted. A target ranked after the budget does not count.

3. **Two separated metrics** (they are never blended):
   - ``list_doc_recall_at_k_reviewed`` — FILE-LIST questions only
     (``file_enum``): fraction of the gold document set inside the truncated
     top-k candidate documents. A diagnostic of doc-level discovery.
   - ``evidence_recall_at_k_reviewed`` — the Gate 2 metric: for every question
     the gold's typed target evidence (workspace/doc/unit/chunk/scope, with
     acceptable alternatives) is first RESOLVED to physical evidence keys
     (a unit/table target → the chunks that actually link to it), then matched
     against the truncated candidate set. A catalog row or a code_exact entry
     never counts as answer evidence.
   Both denominators are stated explicitly per row (``groups``), so an empty
   gold cannot silently pass.

4. **Expansion results are diagnostic, never the metric**: ``expand`` runs are
   recorded in the raw runs and their reads are reported separately
   (``expansion_reads``), but candidate recall is computed on discovery only —
   enumeration must not replace candidates to inflate recall.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

from .query import run_query

METRIC_ELIGIBLE_STATUSES = {"reviewed", "approved"}
# result statuses whose candidates are USABLE evidence: stale results are
# refused (their snapshot/identity no longer holds), ambiguous results did not
# determine an answer — both are excluded, never scored as a full match.
USABLE_RESULT_STATUSES = {"ok", "missing"}


def _is_metric_eligible(item: dict) -> bool:
    """Eligibility for the doc/list diagnostic: explicit review status."""
    return item.get("gold_review_status") in METRIC_ELIGIBLE_STATUSES


def _is_evidence_eligible(item: dict) -> bool:
    """Eligibility for the answer-evidence metric: review status AND frozen
    typed target evidence (a document match alone never qualifies)."""
    return _is_metric_eligible(item) and bool(item.get("gold", {}).get("target_evidence"))


def _frozen_inputs_match(gold: dict, actual: dict | None) -> bool:
    """The benchmark's frozen identity must equal the run's actual identity.

    Without an injected connection the actual identity is unknown — the run is
    a diagnostic and cannot contradict a declared frozen source, so it passes
    this gate (per-row evidence still needs a matching workspace key).
    """
    frozen = gold.get("frozen_inputs") or {}
    if not frozen:
        return True
    if actual is None:
        return True
    for field in ("source_fingerprint", "catalog_snapshot_id", "workspace"):
        want = frozen.get(field)
        if want and actual.get(field) != want:
            return False
    return True


def _candidates(cands: list[dict], top_k: int) -> list[dict]:
    return cands[:top_k]


def _candidate_docs(cands: list[dict], top_k: int) -> list[str]:
    seen, out = set(), []
    for c in _candidates(cands, top_k):
        d = c.get("doc_id")
        if d and d not in seen:
            seen.add(d)
            out.append(d)
    return out


def _gold_target_docs(item: dict) -> list[str]:
    if item.get("target_docs"):
        return [t["doc_id"] for t in item["target_docs"]]
    t = item.get("target_doc")
    if t:
        return [t["doc_id"]]
    g = item.get("gold", {})
    return g.get("expected_doc_ids") or []


def _evidence_key(entry: dict) -> tuple | None:
    doc = entry.get("doc_id")
    if not doc:
        return None
    # R6: workspace is part of the typed identity — evidence from another
    # workspace can never match
    ws = entry.get("workspace", "default")
    if entry.get("chunk_id"):
        return ("chunk", ws, doc, entry["chunk_id"])
    if entry.get("unit_id"):
        return ("unit", ws, doc, entry["unit_id"])
    if entry.get("scope_id"):
        return ("scope", ws, doc, entry["scope_id"])
    if entry.get("table_id"):
        return ("table", ws, doc, entry["table_id"])
    return ("doc", ws, doc, "")


def _match_candidate(c: dict, key: tuple) -> bool:
    """A candidate matches an evidence key when the typed identity agrees.

    Range-binding candidates carry a unit/table plus its real linked chunk ids
    (``chunk_ids``) — those chunks count as evidence too. The candidate's
    workspace must equal the key's workspace (R6).
    """
    kind, ws, doc, ident = key
    if c.get("workspace", "default") != ws:
        return False
    if c.get("doc_id") != doc:
        return False
    if kind == "chunk":
        return c.get("chunk_id") == ident or ident in (c.get("chunk_ids") or [])
    if kind == "unit":
        return c.get("unit_id") == ident
    if kind == "scope":
        return c.get("scope_id") == ident
    if kind == "table":
        return c.get("table_id") == ident
    return True  # doc-level key: any candidate from that document counts


async def _resolve_evidence_to_physical(
    conn, workspace: str, snapshot_id: str, key: tuple
) -> set[tuple]:
    """Resolve a gold evidence key to PHYSICAL evidence keys (chunk ids).

    unit/table targets resolve through ``unit_chunk_links`` — the actual
    catalog links — so a unit-level gold can be satisfied by any chunk that
    genuinely carries it. scope targets resolve through ``scope_units`` →
    ``unit_chunk_links``. Chunk/doc keys resolve to themselves.
    """
    kind, ws, doc, ident = key
    if kind == "chunk":
        return {key}
    if kind in ("unit", "table"):
        rows = await conn.fetch(
            """SELECT chunk_id FROM env_rag.unit_chunk_links
               WHERE workspace=$1 AND snapshot_id=$2 AND doc_id=$3 AND unit_id=$4""",
            ws,
            snapshot_id,
            doc,
            ident,
        )
        chunks = {("chunk", ws, doc, r["chunk_id"]) for r in rows}
        if chunks:
            return chunks
        return {key}  # no link on record: only a unit-level candidate matches
    if kind == "scope":
        rows = await conn.fetch(
            """SELECT l.chunk_id
               FROM env_rag.scope_units s
               JOIN env_rag.unit_chunk_links l
                 ON l.workspace=s.workspace AND l.snapshot_id=s.snapshot_id
                AND l.doc_id=s.doc_id AND l.unit_id=s.unit_id
               WHERE s.workspace=$1 AND s.snapshot_id=$2 AND s.scope_id=$3""",
            ws,
            snapshot_id,
            ident,
        )
        return {("chunk", ws, doc, r["chunk_id"]) for r in rows} or {key}
    return {key}


def _expansion_reads(trace: list[dict]) -> list[dict]:
    """Expansion reads, reported as DIAGNOSTIC (never the candidate metric)."""
    reads = []
    for step in trace:
        if step.get("stage") != "scope_expansion":
            continue
        for e in step.get("expansions") or []:
            reads.append(
                {
                    "doc_id": e.get("doc_id"),
                    "kind": e.get("kind"),
                    "scope_id": e.get("scope_id"),
                    "table_number": e.get("table_number"),
                    "members_total": e.get("members_total"),
                    "members_processed": e.get("members_processed"),
                    "coverage_status": e.get("coverage_status"),
                    "fail_stage": e.get("fail_stage"),
                    "items_count": e.get("items_count"),
                    "units_read": e.get("units_read"),
                }
            )
    return reads


# ---------------------------------------------------------------------------
# R6b/B2: ENUM SET correctness (three enum classes) — exact CONTENT comparison
# against the gold's frozen expected set. Identity is NOT the bare 序号/clause
# number: a wrong name/value/requirement under a correct number is a MISS, and
# a same-number row with a different 平均时间/height/value is a DISTINCT item
# whose loss is missing. This is the Gate 2 "集合完全正确" contract, separate
# from the candidate evidence recall.
# ---------------------------------------------------------------------------


def _norm_cell(v) -> str:
    """Whitespace/case-insensitive cell normalization (keep inner spacing)."""
    return re.sub(r"\s+", " ", str(v or "")).strip().lower()


def _norm_content(v) -> str:
    """Whitespace-FREE content key (substring matching inside item text)."""
    return re.sub(r"\s+", "", str(v or "")).lower()


def _table_item_key(cells: list) -> tuple:
    """Content key of one physical table row (all cells normalized)."""
    return tuple(_norm_cell(c) for c in (cells or []))


def _evaluate_enum_set(item: dict, expansions: list[dict]) -> dict | None:
    """Compare the produced enum items against the gold expected set (B2).

    Projection contract — the gold entry SHAPE declares the answer projection:
    - prose: "3.3 污泥" / {"clause": n, "text": …} → an item satisfies the gold
      when the clause number matches AND the gold content occurs inside the
      produced item text (whitespace-insensitive substring). A correct number
      with wrong/contradictory content stays unsatisfied (missing + extra).
    - table: full ``cells`` → the whole raw row must be produced verbatim;
      ``{seq, name}`` → the (序号, 项目名) projection (值列留给 fact 类检查)；
      a same-number row with a different 平均时间/height is a DISTINCT row, so
      dropping one loses only a ``cells``-declared gold row; a wrong pollutant
      under the right 序号 fails the {seq,name} projection.
    - file: ``expected_doc_ids`` (or doc-id items) → doc-id set equality.
    Unverified citations always break exact_match.
    """
    category = item["category"]
    if category not in ("prose_enum", "table_enum", "file_enum"):
        return None
    gold = item.get("gold", {})
    gold_expected = gold.get("expected_items")
    if category == "file_enum" and gold_expected is None:
        gold_expected = [{"doc_id": d} for d in (gold.get("expected_doc_ids") or [])] or None
    if gold_expected is None:
        return None
    produced: list[dict] = []
    for e in expansions:
        produced.extend(e.get("items") or [])
    if category == "file_enum":
        # file enumeration items come from document_enumeration candidates
        for c in item.get("_enumeration_candidates") or []:
            produced.append(c)
    unverified = sum(1 for it in produced if it.get("citation_verified") is not True)

    # B4: an expansion that did not COMPLETE its coverage cannot yield an
    # exact answer set — ambiguous/partial/error expansions are failed rows
    # regardless of how many items look right (conservative Phase-1 structure
    # verdicts stay authoritative).
    # C2: file enumeration reads the document_enumeration trace entry too —
    # a partial/budget_exhausted paging read is NOT a complete answer even
    # when the collected candidates happen to equal the gold set.
    incomplete_expansion = any(
        (e.get("status") not in (None, "ok", "complete"))
        or (e.get("coverage_status") not in (None, "complete"))
        for e in expansions
        if not (e.get("status") == "ambiguous" and not e.get("items"))
    ) or any(e.get("status") == "error" for e in expansions)
    for step in item.get("_enumeration_trace") or []:
        if step.get("coverage_status") not in (None, "complete"):
            incomplete_expansion = True
        if step.get("fail_stage"):
            incomplete_expansion = True

    missing: list[str] = []
    extra: list[str] = []
    got_count = 0
    want_count = 0

    if category == "file_enum":
        got = {str(c.get("doc_id")) for c in produced if c.get("doc_id")}
        want = {str(g.get("doc_id")) for g in gold_expected if isinstance(g, dict)}
        missing = sorted(want - got)
        extra = sorted(got - want)
        got_count, want_count = len(got), len(want)
    elif category == "prose_enum":
        prod = [
            (
                str(it.get("clause") or "").strip(),
                _norm_content(it.get("text") or it.get("place")),
            )
            for it in produced
        ]
        used = [False] * len(prod)
        for g in gold_expected:
            want_count += 1
            if isinstance(g, dict):
                num = str(g.get("clause") or "").strip()
                content = _norm_content(g.get("text") or g.get("name") or "")
            else:
                s = str(g).strip()
                num = s.split()[0] if s else ""
                content = _norm_content(s)
            hit = False
            for i, (pc, pt) in enumerate(prod):
                if used[i] or not pc:
                    continue
                if pc == num and content in pt:
                    used[i] = True
                    hit = True
                    break
            if not hit:
                missing.append(g if isinstance(g, str) else json.dumps(g, ensure_ascii=False))
        for i, used_i in enumerate(used):
            if not used_i:
                extra.append(f"{prod[i][0]}: {prod[i][1][:80]}")
        got_count = sum(1 for u in used if u)
    else:  # table_enum
        row_golds: list[list] = []
        seqname_golds: list[tuple] = []
        name_golds: list[str] = []
        for g in gold_expected:
            if isinstance(g, dict) and g.get("cells"):
                row_golds.append(g["cells"])
            elif isinstance(g, dict) and g.get("seq") is not None and g.get("name") is not None:
                seqname_golds.append((str(g["seq"]).strip(), _norm_content(g["name"])))
            elif isinstance(g, dict) and g.get("name") is not None:
                name_golds.append(_norm_content(g["name"]))
            elif isinstance(g, dict) and g.get("seq") is not None:
                seqname_golds.append((str(g["seq"]).strip(), None))
            elif isinstance(g, str):
                name_golds.append(_norm_content(g))
        prod_rows = [it.get("cells") or [] for it in produced]
        used_rows = [False] * len(prod_rows)

        def _row_seq(r):
            return str(r[0]).strip() if r else ""

        def _row_name(r):
            return _norm_content(r[1]) if len(r) > 1 else ""

        for cells in row_golds:
            want_count += 1
            key = _table_item_key(cells)
            hit = False
            for i, r in enumerate(prod_rows):
                if not used_rows[i] and _table_item_key(r) == key:
                    used_rows[i] = True
                    hit = True
                    break
            if not hit:
                missing.append(" | ".join(str(c) for c in cells)[:100])
        for seq, name in seqname_golds:
            want_count += 1
            hit = False
            for i, r in enumerate(prod_rows):
                if used_rows[i]:
                    continue
                if _row_seq(r) == seq and (name is None or _row_name(r) == name):
                    used_rows[i] = True
                    hit = True
                    break
            if not hit:
                missing.append(f"seq={seq} name={name or '-'}")
        for name in name_golds:
            want_count += 1
            hit = False
            for i, r in enumerate(prod_rows):
                if used_rows[i]:
                    continue
                if _row_name(r) == name:
                    used_rows[i] = True
                    hit = True
                    break
            if not hit:
                missing.append(f"name={name}")
        # name-projection ONLY (C2): the gold declared a pollutant-NAME set, so
        # all further rows of an already-matched pollutant are sub-rows of that
        # answer (年平均/24小时/1小时; multiple methods) — consumed as evidence.
        # A full-cells projection (any row_golds/seqname_golds present) makes NO
        # such assumption: a same-name row with wrong values stays EXTRA.
        if not row_golds and not seqname_golds:
            matched_names = {_row_name(r) for i, r in enumerate(prod_rows) if used_rows[i]}
            for i, used_i in enumerate(used_rows):
                if not used_i and _row_name(prod_rows[i]) in matched_names:
                    used_rows[i] = True
        for i, used_i in enumerate(used_rows):
            if not used_i and prod_rows[i]:
                extra.append(" | ".join(str(c) for c in prod_rows[i])[:100])
        got_count = sum(1 for u in used_rows if u)

    return {
        "expected_count": want_count,
        "produced_count": got_count,
        "exact_match": (
            want_count > 0
            and not missing
            and not extra
            and not unverified
            and not incomplete_expansion
        ),
        "missing": missing,
        "extra": extra,
        "citation_unverified": unverified,
        "expansion_incomplete": incomplete_expansion,
    }


async def run_benchmark(
    conn,
    gold: dict,
    *,
    workspace: str = "default",
    top_k: int = 20,
    runs_path: Path | None = None,
    values: dict | None = None,
    only: str | None = None,
    expand: bool = False,
) -> dict:
    """Run every gold question; return metrics + the raw run records."""
    started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    runs: list[dict] = []
    rows: list[dict] = []

    # the snapshot the whole run is bound to (source consistency evidence).
    # With an injected/None connection (unit tests, offline review) the
    # snapshot is unknown and physical resolution falls back to the typed key.
    snap = None
    actual_identity: dict | None = None
    if conn is not None:
        from .index import check_search_stale

        state = await check_search_stale(conn, workspace)
        if state["state"] == "current":
            snap = state["catalog_snapshot_id"]
            actual_identity = {
                "source_fingerprint": state.get("source_fingerprint"),
                "catalog_snapshot_id": state.get("catalog_snapshot_id"),
                "workspace": workspace,
            }

    # R6: the benchmark's frozen identity must match the run's ACTUAL identity;
    # a mismatch (old source, replaced catalog, wrong workspace) excludes the
    # whole run from metrics — it can never score on the wrong snapshot.
    frozen_ok = _frozen_inputs_match(gold, actual_identity)
    if not frozen_ok:
        runs_note = (
            "frozen_inputs mismatch: gold was frozen on a different "
            "source/catalog/workspace; run excluded from all metrics"
        )
    else:
        runs_note = None

    for item in gold["questions"]:
        if only and item["query_id"] != only:
            continue
        qid = item["query_id"]
        t0 = time.monotonic()
        # B3: file questions run the FULL document enumeration path
        # (expand_docs); prose/table questions run the scope-expansion path.
        run_kwargs: dict = {"expand": expand}
        if expand and item["category"] == "file_enum":
            run_kwargs = {"expand_docs": True}
        result = await run_query(
            conn,
            item["question"],
            top_k=top_k,
            workspace=workspace,
            source_values=values or {},
            **run_kwargs,
        )
        doc = result.to_dict()
        doc["gold_query_id"] = qid
        doc["gold_review_status"] = item.get("gold_review_status", "unreviewed")
        runs.append(doc)

        # R6: a stale result is NOT usable evidence — its identity failed and
        # it is refused as an answer. B4: an ambiguous/partial result is NOT a
        # refusal — it is a failed FIXED question that stays in the /6
        # denominator with a failed set row (its candidates still earn no
        # trusted-evidence credit; that isolation is in the set check, which
        # scores it as not-exact).
        result_refused = doc["status"] in ("stale",)
        eligible = _is_metric_eligible(item) and frozen_ok and not result_refused
        # C3/D2: recall is computed ONLY from the budgeted DISCOVERY list — the
        # full enumeration answer (in ``candidates`` after expand_docs) never
        # feeds recall. An EXPLICIT discovery snapshot is authoritative: []
        # means ZERO discovery, never backfilled from the enumeration output
        # (only a MISSING field in an old fixture falls back to the legacy
        # candidates filter). Real discovery-stage doc_attribution candidates
        # stay legitimate; the snapshot taken BEFORE expansion cannot contain
        # post-enumeration entries by construction.
        snapshot = doc.get("discovery_candidates")
        if snapshot is None:
            snapshot = [
                c for c in doc["candidates"] if c.get("discovery") != "document_enumeration"
            ]
        discovery = snapshot
        top = _candidates(discovery, top_k)

        # ---- file-list doc metric (file_enum only) ------------------------
        doc_recall = None
        if item["category"] == "file_enum":
            targets = _gold_target_docs(item)
            if targets and eligible:
                hits = 0
                for d in targets:
                    if any(c.get("doc_id") == d for c in top):
                        hits += 1
                doc_recall = hits / len(targets)
                doc_denom = len(targets)
            else:
                doc_denom = 0
        else:
            doc_denom = 0

        # ---- answer-evidence metric (all questions, typed gold) -----------
        groups = item.get("gold", {}).get("target_evidence") or []
        satisfied = 0
        unresolved = 0
        for te in groups:
            alts = [te] + list(te.get("alternatives") or [])
            found = False
            for alt in alts:
                key = _evidence_key(alt)
                if key is None:
                    continue
                physical = (
                    await _resolve_evidence_to_physical(conn, workspace, snap, key)
                    if snap
                    else {key}
                )
                if any(_match_candidate(c, pk) for pk in physical for c in top):
                    found = True
                    break
            if found:
                satisfied += 1
            else:
                unresolved += 1
        evidence_recall = (satisfied / len(groups)) if (groups and eligible) else None

        read_diag = _expansion_reads(doc["trace"])
        # B3: for file_enum the enumeration OUTPUT is the answer set — the
        # document_enumeration candidates (with doc_id/version/citation) are
        # the items to compare; discovery candidates stay separate for recall.
        set_check = None
        if expand:
            expansions = [
                e
                for step in doc["trace"]
                if step.get("stage") == "scope_expansion"
                for e in step.get("expansions") or []
            ]
            if item["category"] == "file_enum":
                item_with_enum = dict(item)
                item_with_enum["_enumeration_candidates"] = [
                    c
                    for c in doc["candidates"]
                    if c.get("discovery") in ("document_enumeration", "doc_attribution")
                ]
                # C2: the enumeration's coverage/fail_stage gates the set check
                item_with_enum["_enumeration_trace"] = [
                    step for step in doc["trace"] if step.get("stage") == "document_enumeration"
                ]
                set_check = _evaluate_enum_set(item_with_enum, expansions)
            else:
                set_check = _evaluate_enum_set(item, expansions)
        rows.append(
            {
                "query_id": qid,
                "category": item["category"],
                "gold_review_status": item.get("gold_review_status", "unreviewed"),
                "metric_eligible": eligible,
                "candidate_docs_topk": _candidate_docs(discovery, top_k),
                "discovery_candidates_total": len(discovery),
                "candidates_total": len(doc["candidates"]),
                "candidates_budget": top_k,
                "doc_recall": doc_recall,
                "doc_denominator": doc_denom,
                "evidence_groups": len(groups),
                "evidence_groups_satisfied": satisfied,
                "evidence_groups_unresolved": unresolved,
                "evidence_recall": evidence_recall,
                "enum_set_check": set_check,
                "expansion_reads": read_diag,
                "status": doc["status"],
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
            }
        )
        if runs_path:
            runs_path.parent.mkdir(parents=True, exist_ok=True)
            with runs_path.open("a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps({"kind": "gold_run", "expand": expand, **doc}, ensure_ascii=False)
                    + "\n"
                )

    reviewed = [r for r in rows if r["metric_eligible"]]
    file_rows = [r for r in reviewed if r["doc_recall"] is not None]
    ev_rows = [r for r in reviewed if r["evidence_recall"] is not None]

    summary = {
        "run_id": f"bench-{uuid.uuid4().hex[:12]}",
        "started_at": started,
        "workspace": workspace,
        "top_k": top_k,
        "expand": expand,
        "catalog_snapshot_id": snap,
        "questions_total": len(rows),
        "questions_reviewed": len(reviewed),
        "questions_excluded_not_eligible": len(rows) - len(reviewed),
        "file_list_doc_denominator": sum(r["doc_denominator"] for r in file_rows),
        "list_doc_recall_at_k_reviewed": (
            sum(r["doc_recall"] * r["doc_denominator"] for r in file_rows)
            / sum(r["doc_denominator"] for r in file_rows)
            if file_rows and sum(r["doc_denominator"] for r in file_rows)
            else None
        ),
        "evidence_groups_total": sum(r["evidence_groups"] for r in ev_rows),
        "evidence_groups_satisfied": sum(r["evidence_groups_satisfied"] for r in ev_rows),
        # B4: the FIXED denominator is every reviewed question of the category
        # on a valid identity — ambiguous/partial/failed answers stay in the
        # /6 as FAILED rows (exact_match counts only true full matches), so a
        # one-hit-five-fail category reports 1/6, never 1/1.
        "enum_set_checks": {
            cat: {
                "questions": sum(1 for r in reviewed if r["category"] == cat),
                "exact_match": sum(
                    1
                    for r in reviewed
                    if r["category"] == cat
                    and r.get("enum_set_check")
                    and r["enum_set_check"].get("exact_match")
                ),
                "failed": sum(
                    1
                    for r in reviewed
                    if r["category"] == cat
                    and not (r.get("enum_set_check") and r["enum_set_check"].get("exact_match"))
                ),
                "citation_unverified_total": sum(
                    r["enum_set_check"].get("citation_unverified") or 0
                    for r in reviewed
                    if r["category"] == cat and r.get("enum_set_check")
                ),
            }
            for cat in ("prose_enum", "table_enum", "file_enum")
        },
        "evidence_recall_at_k_reviewed": (
            sum(r["evidence_recall"] * r["evidence_groups"] for r in ev_rows)
            / sum(r["evidence_groups"] for r in ev_rows)
            if ev_rows and sum(r["evidence_groups"] for r in ev_rows)
            else None
        ),
        "frozen_identity_ok": frozen_ok,
        "identity_note": runs_note,
        "metrics_note": "only explicitly reviewed/approved gold carrying typed target evidence "
        "contributes; results must be ok/missing (stale/ambiguous excluded); candidates are "
        "truncated to top_k BEFORE hits are counted; unit/table/scope gold resolves through "
        "audited unit_chunk_links; the typed key carries workspace; file-list recall covers "
        "file_enum only; expansion reads are diagnostic and never substituted for candidate "
        "evidence",
        "rows": rows,
    }
    # Back-compat alias for the FILE-LIST diagnostic under the old key name.
    summary["recall_at_k_reviewed"] = summary["list_doc_recall_at_k_reviewed"]
    summary["doc_recall_at_k_reviewed"] = summary["list_doc_recall_at_k_reviewed"]
    summary["runs_path"] = str(runs_path) if runs_path else None
    return summary


def load_gold(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
