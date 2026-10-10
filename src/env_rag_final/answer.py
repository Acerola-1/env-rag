"""Task 5.5: post-rerank FULL scope expansion + per-question-type answers.

End-to-end entry over the ACCEPTED stages (5.3 fusion + 5.4 joint rerank are
replayed from their runtime reports; keyword/embedding/local/rerank rounds are
never re-run here). Contract highlights, per handoff-phase-3-5.5:

- Replay provenance is explicit: both input reports are bound by SHA and by
  the generation identity they recorded; the replay is refused BEFORE any
  backend read when it disagrees with the live frozen capture.
- Rerank order only PRIORITIZES scope selection. The actual reads go through
  the formal entries (search.expand.expand_candidates → enumerate_
  table/prose/document) which read the FULL membership: continuation
  fragments, every requested clause and the complete paged document set are
  never top-k truncated (``table_structure``/clause shortage keep
  ambiguous/partial — a successful generation never upgrades coverage).
- fact/file/prose/table answers are rendered DETERMINISTICALLY from
  re-verified items (zero answer-model calls). Only a synthesis question may
  consume one answer model call per run (hard budget ``MAX_ANSWER_MODEL_CALLS``),
  via the plain chat-completions HTTP path — no LightRAG instantiation, no
  hashing_kv, no cache table access; the frozen identity counts prove the
  cache row total is unchanged before/after (data, not function names).
- Every answer item must survive an INDEPENDENT re-read: table rows against
  the raw HTML grid of their bound fragment, prose items against the raw unit
  block text at the declared unit-relative span. Model claims bind edition
  identity from the APPLICATION context (the model never relabels sources)
  and every numeric/date token of a claim must occur in the verbatim quote.
- coverage=complete requires: scope read processed == total with a confirmed
  status, every requested clause found, every item citation re-verified, no
  blocking failure, and (for model answers) every claim verified. Zero items
  over a non-empty scope, an empty/ambiguous scope, a budget refusal or a
  degraded rerank that lost sources can never be complete.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import asyncpg
import httpx
from dotenv import dotenv_values

from env_rag_final.audit import identity as sid
from env_rag_final.catalog.lexical_norm import normalize_code
from env_rag_final.enumerate_.prose_enum import ASSEMBLY_SEPARATOR, _unit_text_from_blocks
from env_rag_final.enumerate_.tables import read_html_table
from env_rag_final.fusion import (
    GOLD_PATH,
    AdapterError,
    _capture_identity,
    _identity_drift,
    verify_config_guard,
    verify_gold_guard,
)
from env_rag_final.rerank import _sanitize_evidence
from env_rag_final.search import tokenizer as tk
from env_rag_final.search.expand import _attribution_requested, expand_candidates
from env_rag_final.search.query import SearchResult, _dedupe_codes, _split_codes, _version_matches

MAX_ANSWER_MODEL_CALLS = 1  # 5.5 handoff: at most ONE necessary answer request
MAX_MODEL_CONTEXT_CHARS = 40_000  # refuse-not-truncate budget for the model call

DEFAULT_RERANK_REPORT = Path("reports/pg-retrieval/phase-3-rerank-r2/rerank-runtime-latest.json")
DEFAULT_FUSED_REPORT = Path("reports/pg-retrieval/phase-3-fusion/fusion-runtime-latest.json")

_MODEL_CONTRACT = {
    "endpoint": "{LLM_BINDING_HOST}/chat/completions (POST, OpenAI-compatible)",
    "request": ["model", "messages", "temperature=0 (frozen)"],
    "response": ["choices[0].message.content"],
    "cache": (
        "code-path evidence: plain HTTP only — no LightRAG/ClientManager "
        "instantiation and no openai_complete_if_cache/hashing_kv call, so the "
        "answer path issues no cache SQL. The frozen lightrag_llm_cache count "
        "checked before/after (16514 unchanged) is a DRIFT check only: an "
        "unchanged row count does not by itself prove zero reads or zero "
        "in-place updates, so it is never presented as that proof "
        "(answer-review r1)."
    ),
    "replay_summaries": (
        "input-file SHA256 + generation identity are COMPUTED AND RECORDED by "
        "this entry, and the entry REFUSES when the generation identity "
        "disagrees with the live frozen capture; the cross-check of recorded "
        "digests against the previously accepted digests is the reviewer's "
        "comparison, never claimed as done here"
    ),
}

_DOC_NAME_SQL = """SELECT doc_name FROM env_rag.documents
   WHERE workspace=$1 AND snapshot_id=$2 AND doc_id=$3"""
_DOC_META_SQL = """SELECT doc_name, self_code, self_code_version FROM env_rag.documents
   WHERE workspace=$1 AND snapshot_id=$2 AND doc_id=$3"""
_UNIT_META_SQL = """SELECT unit_id, caption, heading FROM env_rag.source_units
   WHERE workspace=$1 AND snapshot_id=$2 AND doc_id=$3 AND unit_kind='table'"""


class _PreflightRejection(Exception):
    """A structured pre-flight rejection carrying its own stage/detail."""

    def __init__(self, stage: str, detail) -> None:
        super().__init__(f"{stage}: {detail}")
        self.stage = stage
        self.detail = detail


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _collapse_ws(s: str) -> str:
    """I1 (improvement-1): whitespace COLLAPSED to single spaces, not stripped.

    Used for re-reading whole DELIVERED declarations against the declared raw
    span: stripping whitespace entirely could make "in coming" equal
    "incoming" or mask table content shifts, so containment checks on full
    item text collapse runs instead of removing them."""
    return " ".join((s or "").split())


def _norm_ci(s: str) -> str:
    """case-folded whitespace-stripped form: claim/element/term comparisons
    are case-INSENSITIVE (query_terms renders "pm2.5" while the row cell says
    "PM2.5"); byte-equality of raw re-reads keeps using _norm_ws."""
    return _norm_ws(s).lower()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Replay loading / provenance / generation binding
# ---------------------------------------------------------------------------


def _load_replay(rerank_path: Path, fused_path: Path) -> tuple[dict, dict, dict, dict, dict]:
    """Read BOTH replay reports ONCE; returns (rerank_report, fused_report,
    rerank_by_id, fused_by_id, provenance with each file's SHA)."""
    rerank_text = rerank_path.read_text(encoding="utf-8")
    fused_text = fused_path.read_text(encoding="utf-8")
    rerank = json.loads(rerank_text)
    fused = json.loads(fused_text)
    rerank_by_id = {r["query_id"]: r for r in rerank.get("results") or []}
    fused_by_id = {r["query_id"]: r for r in fused.get("results") or []}
    provenance = {
        "rerank_report": {
            "path": str(rerank_path),
            "sha256": _file_sha(rerank_path),
            "task": rerank.get("task"),
            "started_at": rerank.get("started_at"),
            "finished_at": rerank.get("finished_at"),
            "query_ids": sorted(rerank_by_id),
        },
        "fused_report": {
            "path": str(fused_path),
            "sha256": _file_sha(fused_path),
            "task": fused.get("task"),
            "started_at": fused.get("started_at"),
            "finished_at": fused.get("finished_at"),
            "query_ids": sorted(fused_by_id),
        },
        "note": (
            "discovery/fusion/rerank are REPLAYED from these accepted "
            "generations; this run performs only scope expansion reads "
            "(and at most one answer model call) — no new retrieval round"
        ),
    }
    return rerank, fused, rerank_by_id, fused_by_id, provenance


def _bind_replay_generation(
    rerank_report: dict, fused_report: dict, live_pre_identity: dict
) -> tuple[list[str], list[str]]:
    """Cross-generation provenance: the replayed generation's recorded
    identity must equal the live frozen capture on source/catalog/search/gold
    (and public counts — the cache invariance rides on the same comparison).
    An env_sha difference is recorded as a warning, never silently dropped
    and never a hard refusal (the frozen library is what the replay is bound
    to). A replay report that itself recorded a failure/drift is refused —
    a refused generation cannot feed the answer stage."""
    problems: list[str] = []
    warnings: list[str] = []
    for name, rep in (("rerank", rerank_report), ("fused", fused_report)):
        if rep.get("failure"):
            problems.append(f"{name} replay generation recorded a failure: {rep['failure']}")
        if rep.get("identity_drift"):
            problems.append(
                f"{name} replay generation recorded identity drift: {rep['identity_drift']}"
            )
        ident = rep.get("identity_before") or {}
        if not ident.get("matches_frozen"):
            problems.append(f"{name} replay generation did not match the frozen contract")
            continue
        for field in ("source_fingerprint", "catalog_active", "search_active", "gold_sha"):
            if ident.get(field) != live_pre_identity.get(field):
                problems.append(
                    f"{name} replay {field} {ident.get(field)!r} != live "
                    f"{live_pre_identity.get(field)!r} (different generation)"
                )
        if ident.get("counts") != live_pre_identity.get("counts"):
            problems.append(
                f"{name} replay public counts {ident.get('counts')!r} != live "
                f"{live_pre_identity.get('counts')!r}"
            )
        if ident.get("env_sha") != live_pre_identity.get("env_sha"):
            warnings.append(
                f"{name} replay env_sha differs from the live .env capture "
                "(recorded, not a refusal: the frozen library identity is bound above)"
            )
    return problems, warnings


# ---------------------------------------------------------------------------
# Replaying the 5.3/5.4 outcome as a SearchResult for the formal expand entry
# ---------------------------------------------------------------------------

_FUSED_STATUS_MAP = {
    "ok": "ok",
    "partial": "partial",
    "ambiguous": "ambiguous",
    "missing": "missing",
    "stale": "stale",
    "degraded": "partial",
}


def _replay_candidates(fused_result: dict, rerank_result: dict | None) -> list[dict]:
    score_by_chunk: dict[str, float | None] = {}
    if rerank_result:
        for row in rerank_result.get("ordered") or []:
            if row.get("source_order") == "rerank":
                score_by_chunk[row["chunk_id"]] = row.get("rerank_score")
    cands: list[dict] = []
    for c in fused_result.get("usable") or []:
        paths = c.get("paths") or []
        discoveries = [p.get("discovery") for p in paths if p.get("discovery")]
        discovery = (
            "code_exact"
            if "code_exact" in discoveries
            else (discoveries[0] if discoveries else "fused_replay")
        )
        score = score_by_chunk.get(c.get("chunk_id"))
        cands.append(
            {
                "doc_id": c.get("doc_id"),
                "chunk_id": c.get("chunk_id"),
                "workspace": c.get("workspace"),
                "discovery": discovery,
                "score": {"kind": "rerank_score", "value": score}
                if score is not None
                else (paths[0].get("score") if paths else None),
                "heading": next((p.get("heading") for p in paths if p.get("heading")), None),
                "paths": paths,
                "content_sha256": c.get("content_sha256"),
            }
        )
    return cands


def _build_replay_result(qid: str, gold_q: dict, fused_result: dict, rerank_result: dict | None):
    workspace = gold_q.get("workspace") or "default"
    result = SearchResult(f"answer-{qid}", workspace)
    result.query_text = gold_q.get("question") or ""
    codes = _dedupe_codes(_split_codes(result.query_text)[0])
    result.parsed_codes = codes
    result.parsed_code = codes[0] if codes else None
    result.status = _FUSED_STATUS_MAP.get(fused_result.get("status") or "ok", "partial")
    pg = fused_result.get("pg") or {}
    result.search_id = pg.get("search_id") or ""
    result.catalog_snapshot_id = pg.get("catalog_snapshot_id") or ""
    result.source_snapshot_id = pg.get("source_snapshot_id") or ""
    result.candidates = _replay_candidates(fused_result, rerank_result)
    # FAITHFUL replay reconstruction: a real run_query code route appends
    # DOC-LEVEL candidates tagged discovery="code_exact" (query.py
    # _code_route) alongside keyword chunk candidates; the C5 title
    # confirmation is keyed exactly on those candidates. 5.3 preserved them
    # as typed doc targets — dropping them here would silently disable the
    # formal title-confirmation path, so they are reconstructed as-is.
    seen_exact_docs: set[str] = set()
    for tt in fused_result.get("typed_targets") or []:
        if tt.get("target_type") != "doc" or tt.get("discovery") != "code_exact":
            continue
        doc = tt.get("doc_id")
        if not doc or doc in seen_exact_docs:
            continue
        seen_exact_docs.add(doc)
        result.candidates.append(
            {
                "doc_id": doc,
                "chunk_id": None,
                "workspace": tt.get("workspace") or workspace,
                "doc_name": tt.get("doc_name"),
                "title": tt.get("title"),
                "self_code": tt.get("self_code"),
                "self_code_version": tt.get("self_code_version"),
                "discovery": "code_exact",
                "score": {"kind": "code_exact", "value": 1.0},
                "heading": None,
                "paths": [],
                "citation": {
                    "kind": "catalog_row",
                    "workspace": workspace,
                    "snapshot_id": result.catalog_snapshot_id,
                    "doc_id": doc,
                },
                "citation_verified": True,
            }
        )
    # the replayed BUDGETED discovery snapshot (kept verbatim from 5.3/5.4):
    # recall-style accounting never re-reads the live index in this stage.
    result.discovery_candidates = list(result.candidates)
    for note in fused_result.get("degraded") or []:
        result.notes.append(f"fusion degraded (replayed): {note}")
    if rerank_result and rerank_result.get("degraded"):
        for note in rerank_result["degraded"]:
            result.notes.append(f"rerank degraded (replayed): {note}")
    return result


def _scope_priority(result, rerank_result) -> list[dict]:
    """Rerank selects scope PRIORITY only — every distinct document among the
    replayed candidates is expanded below; nothing is top-k truncated."""
    best: dict[str, tuple] = {}
    for c in result.candidates:
        doc = c.get("doc_id")
        if not doc:
            continue
        score = (c.get("score") or {}).get("value")
        rank = None
        if rerank_result:
            for i, row in enumerate(rerank_result.get("ordered") or []):
                if row.get("chunk_id") == c.get("chunk_id"):
                    rank = i
                    break
        key = (
            rank if rank is not None else 10_000,
            -(score if isinstance(score, (int, float)) else 0.0),
        )
        if doc not in best or key < best[doc]:
            best[doc] = key
    ordered = sorted(best.items(), key=lambda kv: kv[1])
    return [
        {"doc_id": d, "rerank_rank_or_none": (k[0] if k[0] < 10_000 else None)} for d, k in ordered
    ]


def _expansion_stages(result) -> tuple[list[dict], dict | None]:
    expansions: list[dict] = []
    doc_enum: dict | None = None
    for stage in result.trace or []:
        if stage.get("stage") == "scope_expansion":
            expansions.extend(stage.get("expansions") or [])
        if stage.get("stage") == "document_enumeration":
            doc_enum = stage
    return expansions, doc_enum


# ---------------------------------------------------------------------------
# Independent citation re-read (never the same in-memory object re-deciding)
# ---------------------------------------------------------------------------


def _doc_parsed_dir(doc_name: str | None) -> Path:
    if not doc_name:
        raise AdapterError("cannot re-verify citations: document name unresolved in the catalog")
    return sid.PARSED_ROOT / f"{doc_name}.parsed"


def _tables_sidecar(parsed_dir: Path) -> dict:
    tj = sorted(parsed_dir.glob("*.tables.json"))
    if not tj:
        return {}
    return json.loads(tj[0].read_text(encoding="utf-8")).get("tables") or {}


def _reverify_table_items(items: list[dict], parsed_dir: Path) -> list[str]:
    problems: list[str] = []
    tables = _tables_sidecar(parsed_dir)
    grids: dict[str, list[list[str]]] = {}
    for tid, entry in tables.items():
        content = (entry or {}).get("content") or ""
        if content.strip():
            grids[tid] = read_html_table(content)
    for it in items:
        cit = it.get("citation") or {}
        tid, ri = cit.get("table_id"), cit.get("row_in_fragment")
        grid = grids.get(tid)
        if grid is None:
            problems.append(f"table fragment {tid} not re-readable from the sidecar")
            it["citation_reverified"] = False
            continue
        if not isinstance(ri, int) or ri < 0 or ri >= len(grid):
            problems.append(f"row index {ri!r} outside fragment {tid} raw grid ({len(grid)} rows)")
            it["citation_reverified"] = False
            continue
        row = [_norm_ws(cell) for cell in grid[ri]]
        cells = [_norm_ws(cell) for cell in it.get("cells") or []]
        if row != cells:
            problems.append(
                f"row re-read mismatch at {tid}[{ri}]: grid {grid[ri]!r} != item {it.get('cells')!r}"
            )
            it["citation_reverified"] = False
        else:
            it["citation_reverified"] = True
    return problems


def _reverify_prose_items(items: list[dict], parsed_dir: Path) -> list[str]:
    """Independent raw re-read (I1, improvement-1).

    For every numeric-DECLARED item the WHOLE delivered text — not just the
    ≤120 char quote — must be re-readable from the declared raw coordinates:
    single unit → the unit-relative piece; cross-unit → the declared segments
    joined with the PROTOCOL separator ``ASSEMBLY_SEPARATOR`` in DECLARED
    ORDER. F1 (r1 review): the citation's declared ``assembly_separator`` is
    only VALIDATED against the protocol, never used as the reconstruction
    rule — a fabricated (or non-string) separator refuses instead of letting
    "real pieces + fake separator" manufacture source text. F2: PRESENCE of
    char_start/char_end declares a numeric-span item; a malformed
    declaration (null/string/bool/float, one side missing) refuses with its
    own problem — it can never downgrade to the quote-only path. Whitespace
    is collapsed (never stripped wholesale) so word/table boundaries stay
    observable; a duplicated/permuted/missing segment or an unsupported tail
    fails, and the caller turns any problem into partial coverage. A genuine
    quote-only model citation (no numeric keys at all) keeps the existing
    verbatim-quote semantics."""
    problems: list[str] = []
    raw_by_unit: dict[str, str | None] = {}
    for it in items:
        cit = it.get("citation")
        if not isinstance(cit, dict):
            problems.append(
                f"item {it.get('clause') or it.get('place')} has no citation mapping to re-read"
            )
            it["citation_reverified"] = False
            continue
        qraw = cit.get("quote")
        quote = qraw.strip() if isinstance(qraw, str) else ""

        declares = "char_start" in cit or "char_end" in cit
        declared_ok = (
            "char_start" in cit
            and "char_end" in cit
            and type(cit["char_start"]) is int
            and type(cit["char_end"]) is int
        )
        if declares and not declared_ok:
            problems.append(
                f"item {it.get('clause') or it.get('place')} declares a numeric span with "
                f"malformed coordinates (char_start={cit.get('char_start')!r}, "
                f"char_end={cit.get('char_end')!r}) — refusing instead of downgrading to "
                "the quote-only path"
            )
            it["citation_reverified"] = False
            continue
        if not quote:
            problems.append(f"item {it.get('clause') or it.get('place')} carries no quote")
            it["citation_reverified"] = False
            continue

        def _raw(unit_id):
            if unit_id not in raw_by_unit:
                raw_by_unit[unit_id] = _unit_text_from_blocks(parsed_dir, unit_id)
            return raw_by_unit[unit_id]

        def _piece(unit_id, lo, hi):
            raw = _raw(unit_id)
            if raw is None:
                return None
            if type(lo) is not int or type(hi) is not int or lo < 0 or hi > len(raw) or lo >= hi:
                return None
            return raw[lo:hi]

        def _text_backed(recon: str) -> bool:
            if not declares:
                return True  # genuine quote-only model path unchanged
            if "text" not in it:
                return True  # legacy quote-equals-span shape (Gate-2 r8)
            delivered = it.get("text")
            if not (isinstance(delivered, str) and delivered.strip()):
                return False  # a delivered text field must be fully re-readable
            return _collapse_ws(delivered) in _collapse_ws(recon)

        seg_raw = cit.get("unit_segments")
        if seg_raw is not None and not (
            isinstance(seg_raw, list) and all(isinstance(s, dict) for s in seg_raw)
        ):
            problems.append(
                f"cross-unit segment declaration for {it.get('clause') or it.get('place')} "
                "is not a list of segment objects"
            )
            it["citation_reverified"] = False
            continue
        segments = seg_raw or []
        if segments:
            if "assembly_separator" in cit and cit["assembly_separator"] != ASSEMBLY_SEPARATOR:
                problems.append(
                    f"declared assembly_separator {cit['assembly_separator']!r} for "
                    f"{it.get('clause') or it.get('place')} is not the protocol join "
                    f"{ASSEMBLY_SEPARATOR!r} — a separator cannot manufacture source text"
                )
                it["citation_reverified"] = False
                continue
            parts: list[str] = []
            ok = True
            seen: set = set()
            for seg in segments:
                uid = seg.get("unit_id")
                if uid in seen:
                    problems.append(f"duplicated unit segment {uid!r} for {it.get('clause')}")
                    ok = False
                    break
                seen.add(uid)
                piece = _piece(uid, seg.get("rel_start"), seg.get("rel_end"))
                if piece is None:
                    ok = False
                    break
                parts.append(piece)
            recon = ASSEMBLY_SEPARATOR.join(parts) if ok else ""
            if not ok:
                problems.append(
                    f"cross-unit quote not covered by re-read segments for "
                    f"{cit.get('unit_id') or cit.get('unit_ids')}"
                )
                it["citation_reverified"] = False
            elif _norm_ws(quote) not in _norm_ws(recon) or not _text_backed(recon):
                problems.append(
                    f"cross-unit quote/text not covered by the declared-order segment "
                    f"reconstruction for {cit.get('unit_id') or cit.get('unit_ids')}"
                )
                it["citation_reverified"] = False
            else:
                it["citation_reverified"] = True
            continue
        unit_id = cit.get("unit_id")
        piece = _piece(unit_id, cit.get("unit_rel_start"), cit.get("unit_rel_end"))
        if piece is None or _norm_ws(quote) not in _norm_ws(piece):
            problems.append(
                f"quote not supported by the raw unit re-read at "
                f"unit={unit_id!r} rel=({cit.get('unit_rel_start')!r},{cit.get('unit_rel_end')!r})"
            )
            it["citation_reverified"] = False
        elif not _text_backed(piece):
            problems.append(
                f"delivered text not fully re-readable from the raw unit span at "
                f"unit={unit_id!r} rel=({cit.get('unit_rel_start')!r},{cit.get('unit_rel_end')!r}) "
                f"— unsourced tail, omission or position error in the declaration"
            )
            it["citation_reverified"] = False
        else:
            it["citation_reverified"] = True
    return problems


# ---------------------------------------------------------------------------
# Deterministic per-category answer rendering
# ---------------------------------------------------------------------------

_QUESTION_FRAME = re.compile(
    r"(多少|哪些|分别|什么|列出|逐条|逐项|逐行|请问|是多少|的|是|吗|？|\?)"
)


def _fact_terms(question: str) -> list[str]:
    """Subject terms of a fact question: tokenizer terms PLUS adjacent-CJK
    bigrams of the normalized question (the same gram-pieces technique the
    formal title confirmation uses — jieba can split 总汞 into single chars,
    the bigram keeps the subject recoverable). Code tokens, pure-ASCII and
    question-frame fragments never enter; nothing is taken from gold text."""
    codes = {c["raw"] for c in _split_codes(question)[0]} | {
        c["code"] for c in _split_codes(question)[0]
    }
    codes_n = {_norm_ci(c) for c in codes}
    raw_terms: list[str] = []
    for g in tk.query_terms(question):
        t = g.render().strip()
        if len(t) < 2 or _norm_ci(t) in codes_n or not _norm_ws(t):
            continue
        if re.fullmatch(r"[\d.\-]+", t):
            continue
        raw_terms.append(t)
    norm_q = re.sub(r"\s+", "", tk.normalize_text(question))
    for i, ch in enumerate(norm_q):
        if i + 1 < len(norm_q) and "\u4e00" <= ch <= "\u9fff":
            bigram = norm_q[i : i + 2]
            if "\u4e00" <= bigram[1] <= "\u9fff":
                raw_terms.append(bigram)
    stop = tk.stopwords()
    terms: list[str] = []
    for t in raw_terms:
        if t in stop or _QUESTION_FRAME.search(t):
            continue
        if t not in terms:
            terms.append(t)
    return terms


def _select_fact_items(items: list[dict], terms: list[str]) -> list[dict]:
    scored: list[tuple[int, dict]] = []
    for it in items:
        hay = _norm_ci("".join(str(c) for c in it.get("cells") or []) + (it.get("text") or ""))
        hits = sum(1 for t in terms if _norm_ci(t) and _norm_ci(t) in hay)
        if hits:
            scored.append((hits, it))
    if not scored:
        return []
    top = max(h for h, _ in scored)
    return [it for h, it in scored if h == top]


def _table_structure_from_warnings(warnings: list[str]) -> dict:
    for w in warnings or []:
        # the delimiter fields are the anchors: cell text containing "];" is
        # possible, so each group stops at the NEXT named delimiter
        m = re.match(r"table_structure: header=(.*?); units=(.*?); footnotes=(.*)$", w)
        if m:
            return {
                "header": json.loads(m.group(1)),
                "units": json.loads(m.group(2)),
                "footnotes": json.loads(m.group(3)),
            }
    return {}


def _frag_conditions(conn_rows: list[dict], tables: dict) -> dict[str, dict]:
    meta: dict[str, dict] = {}
    for r in conn_rows:
        meta[r["unit_id"]] = {
            "caption": r["caption"],
            "heading": r["heading"],
            "block_caption": (tables.get(r["unit_id"]) or {}).get("caption"),
        }
    return meta


def _render_answer(category, result, expansions, doc_enum, rerank_result) -> dict:
    """Deterministic rendering by question type; file/prose/table enumerate
    verified items from the FULL expansion (never a top-k slice)."""
    answer = {"mode": "deterministic", "generated_by": "enumerate/expand entries", "items": []}
    if category == "file_enum":
        if doc_enum is None:
            answer["items"] = []
            return answer
        for c in result.candidates:
            answer["items"].append(
                {
                    "kind": "document",
                    "doc_id": c.get("doc_id"),
                    "doc_name": c.get("doc_name"),
                    "title": c.get("title"),
                    "self_code": c.get("self_code"),
                    "self_code_version": c.get("self_code_version"),
                    "attribution": c.get("discovery") == "doc_attribution"
                    or "doc_attribution_catalog" in (c.get("sources") or [])
                    or c.get("discovery") == "doc_attribution_catalog",
                    "citation": c.get("citation"),
                    "citation_verified": c.get("citation_verified") is True,
                }
            )
        return answer
    if category in ("table_enum", "fact"):
        for exp in expansions:
            if exp.get("kind") != "table":
                continue
            structure = _table_structure_from_warnings(exp.get("warnings") or [])
            # caption/heading were resolved onto the items by the caller from
            # the REAL catalog rows — never guessed here
            for it in exp.get("items") or []:
                cit = it.get("citation") or {}
                answer["items"].append(
                    {
                        "kind": "table_row",
                        "doc_id": exp.get("doc_id"),
                        "table_number": exp.get("table_number"),
                        "seq": it.get("seq"),
                        "cells": it.get("cells"),
                        "header": structure.get("header"),
                        "units": structure.get("units"),
                        "footnotes": structure.get("footnotes"),
                        "citation": cit,
                        "citation_verified": it.get("citation_verified") is True,
                        "citation_reverified": it.get("citation_reverified") is True,
                        "caption": it.get("caption"),
                    }
                )
    if category in ("prose_enum", "fact"):
        for exp in expansions:
            if exp.get("kind") != "prose":
                continue
            for it in exp.get("items") or []:
                answer["items"].append(
                    {
                        "kind": "prose_item",
                        "doc_id": exp.get("doc_id"),
                        "scope_id": exp.get("scope_id"),
                        "clause": it.get("clause") or it.get("place"),
                        "text": it.get("text"),
                        "citation": it.get("citation"),
                        "citation_verified": it.get("citation_verified") is True,
                        "citation_reverified": it.get("citation_reverified") is True,
                    }
                )
    if category == "fact":
        terms = _fact_terms(result.query_text)
        all_items = answer["items"]
        kept = _select_fact_items(all_items, terms)
        answer["selection"] = {
            "terms": terms,
            "candidates": len(all_items),
            "kept": len(kept),
            "rule": "rows/items whose raw text contains the most subject terms "
            "of the QUESTION (never gold text); ties keep every match",
        }
        if not kept and all_items:
            answer["not_located"] = (
                f"no expanded item matches the question subject terms {terms}; "
                "the fact target was not located — never guessed"
            )
        answer["items"] = kept
        # A1-5 (answer-review r1): a quantitative fact row is only a COMPLETE
        # fact when its unit is recoverable from the READ source — row 单位
        # cell, header/caption unit text, or an explicit 无量纲 declaration.
        # Absent source → the verified number stays as evidence but the
        # answer is explicitly incomplete (never filled from gold/common sense).
        answer["unit_blockers"] = []
        for it in kept:
            if it.get("kind") != "table_row":
                continue
            status, unit = _fact_unit_evidence(it)
            it["unit_status"] = status
            it["unit"] = unit
            if status == "unverified_absent" and any(
                _NUM_RE.search(str(c)) for c in (it.get("cells") or [])[1:]
            ):
                answer["unit_blockers"].append(
                    {
                        "cells": it.get("cells"),
                        "note": "quantitative fact without a verifiable unit/condition "
                        "in the read source — number kept, coverage stays partial",
                    }
                )
    return answer


# ---------------------------------------------------------------------------
# Synthesis: one answer model call, application-bound citations
# ---------------------------------------------------------------------------

_SYNTH_SYSTEM = (
    "你是严谨的环境标准比对助手。只依据给定上下文回答，输出 JSON："
    '{"summary": "...", "items": [{"edition": "上下文中的版本标签之一", '
    '"claim": "结论", "quote": "支持结论的逐字原文引句"}]}。'
    "每个 claim 的所有数值/日期必须出现在其 quote 中；quote 必须逐字来自该版本上下文；"
    "edition 只能原样使用上下文中给出的标签；不得改写归属，不得补充上下文之外的内容。"
    "正文类 claim 必须直接引用该版本上下文中连续的逐字原文片段，"
    "不得改写、拼接或概括（仅可附加同版本年份前缀和句末标点）；"
    "表格行 claim 须按绑定行列明主体、平均时间、级别及对应数值和单位。"
)


def _item_row(item: dict) -> str:
    """Per-item line of the model context — the SAME rendering both the
    context assembly and the quote→citation binding use."""
    if item.get("kind") == "table_row":
        return f"[{item.get('clause') or ''}] " + " | ".join(
            str(c) for c in item.get("cells") or []
        )
    return f"[{item.get('clause') or ''}] {item.get('text') or ''}"


def _synthesis_context(doc_sections: list[dict]) -> tuple[str, int]:
    """The EXACT context sent to the model. Returns (text, char_len)."""
    parts: list[str] = []
    for section in doc_sections:
        lines = [f"=== 版本标签: {section['label']} (doc_id={section['doc_id']}) ==="]
        lines.extend(_item_row(item) for item in section["items"])
        parts.append("\n".join(lines))
    text = "\n\n".join(parts)
    return text, len(text)


async def _call_answer_model(values, payload, transport):
    host = values["LLM_BINDING_HOST"].rstrip("/")
    url = f"{host}/chat/completions"
    api_key = (values.get("LLM_BINDING_API_KEY") or "").strip()
    if not api_key:
        raise AdapterError("LLM_BINDING_API_KEY missing in .env — refusing (never 'Bearer None')")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    t0 = time.monotonic()
    receipt = {
        "service": "answer-model",
        "endpoint": url,
        "model": payload["model"],
        "status": None,
        "error": None,
        "latency_ms": None,
        "content": None,
    }
    try:
        if transport is not None:
            resp = await transport(url, headers, payload)
        else:
            async with httpx.AsyncClient(timeout=90) as client:
                resp = await client.post(url, headers=headers, json=payload)
        status = int(getattr(resp, "status_code", 0))
        receipt["latency_ms"] = int((time.monotonic() - t0) * 1000)
        if status != 200:
            receipt["status"] = "failure"
            receipt["error"] = f"http_{status}"
            return receipt
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
        receipt["status"] = "success"
        receipt["content"] = content
        return receipt
    except Exception as exc:  # noqa: BLE001 — receipt keeps the failure honest
        receipt["latency_ms"] = receipt["latency_ms"] or int((time.monotonic() - t0) * 1000)
        receipt["status"] = "failure"
        receipt["error"] = f"{type(exc).__name__}"
        return receipt


def _parse_model_items(content: str) -> tuple[list[dict] | None, str | None]:
    cleaned = (content or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", cleaned).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return None, "invalid_json"
    if not isinstance(parsed, dict) or not isinstance(parsed.get("items"), list):
        return None, "invalid_shape"
    return parsed["items"], None


_NUM_RE = re.compile(r"\d+(?:[./-]\d+)*")
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
# A1 (answer-review r1): a verbatim quote alone does not prove the CLAIM —
# the relation between subject / level-column / value token / unit and the
# read table structure is checked field by field against the bound row.
_LEVEL_TERMS = ("一级", "二级", "三级", "四级", "五级")
_UNIT_LEXICON_RE = re.compile(
    r"(mg/L|mg/m³|mg/m3|μg/m³|ug/m³|g/L|kg/h|t/h|Bq/L|mg·L|℃|吨|毫克|微克|无量纲|倍|%)"
)
_SUBJECT_HEADER_RE = re.compile(r"(污染物|项目|指标|名称|要素|术语|分类|参数)")


# standalone VALUE numbers, SIGN-AWARE (answer-review r2 B1): "-35" and "35"
# are different measurements; digit runs embedded in alphanumeric tokens
# (the 2.5 inside "PM2.5") are part of the substance name, not a value.
_VALUE_NUM_RE = re.compile(r"(?<![A-Za-z0-9.\-+])[-−+]?\d+(?:\.\d+)*(?![0-9A-Za-z.])")
# value + trailing unit string: every number that ASSERTS a unit must bind it
# to the read row's unit — an unrecognized unit string is never a skip
# (B1-1 "g/m³" vs "μg/m³" is a million-fold error, not an unchecked case).
_MEASURE_RE = re.compile(
    r"(?<![A-Za-z0-9.])(?P<num>[-−+]?\d+(?:\.\d+)*)(?P<unit>[ \u3000]?[^\s，。；、,;\d]*)"
)
# 平均时间 / quantity terms the row must carry verbatim
_AVG_RE = re.compile(
    r"(?:(?:\d+(?:\.\d+)?|一|两|三|四|五|六|七|八|九|十|二十|二十四)?(?:小时|时|日|周|月|季|年|瞬))平均"
)
# generic structure/table words: they never ATTRIBUTE a 无量纲 note to a
# specific substance (B3: a pH note must not override 总汞's mg/L).
_GENERIC_NOTE_WORDS = (
    "无量纲",
    "单位",
    "指标",
    "控制",
    "限值",
    "浓度",
    "要求",
    "标准",
    "项目",
    "污染物",
    "排放",
    "允许",
    "最高",
    "最低",
    "第一类",
    "第二类",
    "一类",
    "二类",
    "表",
    "注",
    "见",
    "和",
    "与",
    "或",
    "为",
    "的",
    "均",
    "值",
)


def _norm_unit(text: str) -> str:
    return _norm_ws((text or "").replace("³", "3").replace("²", "2").replace("µ", "μ").lower())


def _num_tokens(text: str) -> set[str]:
    """MAXIMAL, sign-aware value tokens — substring support is exactly what
    A1-4/B1 forbids ("3" never supported by "35", "-35" ≠ "35"). An explicit
    leading "+" is the same quantity as the unsigned source value ("+35"==
    "35"); a MINUS is never equal to the unsigned form."""
    return {tok[1:] if tok.startswith("+") else tok for tok in _VALUE_NUM_RE.findall(text or "")}


def _row_value_tokens(cells: list) -> set[str]:
    out: set[str] = set()
    for c in cells or []:
        out |= _num_tokens(str(c))
    return out


def _header_cells(item: dict) -> list[str]:
    header = item.get("header") or []
    out: list[str] = []
    for row in header:
        out.extend(str(c) for c in row or [])
    return out


def _subject_cells(item: dict) -> list[str]:
    cells = item.get("cells") or []
    header = item.get("header") or []
    first = header[0] if header else []
    subs: list[str] = []
    for i, hcell in enumerate(first):
        if _SUBJECT_HEADER_RE.search(str(hcell)) and i < len(cells):
            val = str(cells[i] or "").strip()
            if val:
                subs.append(val)
    return subs


def _level_column_value(item: dict, level: str) -> set[str] | None:
    cells = item.get("cells") or []
    header = item.get("header") or []
    first = header[0] if header else []
    for i, hcell in enumerate(first):
        if level in str(hcell) and i < len(cells):
            return _num_tokens(str(cells[i] or ""))
    return None


def _unit_hay(item: dict) -> str:
    cells_text = " | ".join(str(c) for c in item.get("cells") or [])
    return _norm_ws(
        cells_text
        + "".join(_header_cells(item))
        + str(item.get("caption") or "")
        + " ".join(str(u) for u in item.get("units") or [])
        + " ".join(str(f) for f in item.get("footnotes") or [])
    )


def _row_unit_cell(item: dict) -> str:
    cells = item.get("cells") or []
    for row in item.get("header") or []:
        for i, hcell in enumerate(row or []):
            if "单位" in str(hcell) and i < len(cells):
                val = str(cells[i] or "").strip()
                if val:
                    return val
    return ""


_NOTE_PUNCT_SPLIT = re.compile(r"[，。；;、！!？?\n]")
_NOTE_BRACKET_RE = re.compile(r"[（(][^（）()]*[）)]")


def _unit_note_segments(note: str) -> list[str]:
    """C3+D2 (answer-review r3/r4): split caption/footnote text into LOCAL
    clauses — bracketed groups keep their boundary marker BUT their internal
    clauses are split further on punctuation, because ONE bracket can carry
    several unit assertions about different subjects:
    "（总汞单位为mg/L；pH为无量纲）" is TWO local assertions, and a subject
    named by one of them never vouches for the other. The modifier object of
    a unit assertion is decided inside its own clause, never across the whole
    title or the whole bracket."""
    segs: list[str] = []
    pos = 0
    for m in _NOTE_BRACKET_RE.finditer(note):
        segs.extend(s for s in _NOTE_PUNCT_SPLIT.split(note[pos : m.start()]) if s)
        segs.extend(s for s in _NOTE_PUNCT_SPLIT.split(m.group(0)) if s)
        pos = m.end()
    segs.extend(s for s in _NOTE_PUNCT_SPLIT.split(note[pos:]) if s)
    return segs


def _note_applies_to_row(item: dict) -> bool:
    """C3 (answer-review r3, supersedes r2-B3): a 无量纲 declaration covers this
    row only per LOCAL clause: "表 1 总汞及pH限值（pH为无量纲）" — the title
    listing 总汞 does NOT vouch for the bracketed assertion, which names pH;
    for a 总汞 row the note never applies. An unattributed 无量纲 clause
    ("表 8 无量纲控制指标") is a table-wide declaration and applies. Attribution
    reads ONLY tokenizer words INSIDE the clause that carries 无量纲 (no
    bigrams — gram noise would misattribute), against the generic structure
    lexicon."""
    note = str(item.get("caption") or "") + " ".join(str(f) for f in item.get("footnotes") or [])
    subjects = _subject_cells(item) or [str(c) for c in (item.get("cells") or [])[1:2]]
    row_norm = _norm_ci("".join(subjects))
    for seg in _unit_note_segments(note):
        if "无量纲" not in seg:
            continue
        attributed: list[str] = []
        for g in tk.query_terms(seg):
            t = g.render().strip()
            if len(t) < 2 or t == "无量纲":
                continue
            if re.fullmatch(r"[\d.\-/]+", t):
                continue
            if any(w in t or t in w for w in _GENERIC_NOTE_WORDS):
                continue
            if _QUESTION_FRAME.search(t):
                continue
            attributed.append(_norm_ci(t))
        if not attributed:
            return True  # an unattributed 无量纲 clause declares the whole table
        if any(s in row_norm for s in attributed):
            return True
    return False


def _fact_unit_evidence(item: dict) -> tuple[str, str | None]:
    """A1-5 + B3: unit priority for a quantitative fact is
    1) the row's OWN 单位 cell (explicit per-row unit wins — a caption note
       about another substance can never override it);
    2) an attributed-or-table-wide 无量纲 declaration ("dimensionless" is a
       real source judgment, never an assumption);
    3) a unit stated in the header/caption/units text for the table.
    Absent all → ("unverified_absent", None): the verified number stays as
    evidence but the answer is NOT complete (no gold/common-sense fill)."""
    cell_unit = _row_unit_cell(item)
    if cell_unit:
        if "无量纲" in cell_unit:
            return "dimensionless", cell_unit
        return "source_unit", cell_unit
    hay = _unit_hay(item)
    if "无量纲" in hay and _note_applies_to_row(item):
        return "dimensionless", "无量纲"
    source_text = (
        "".join(str(c) for row in item.get("header") or [] for c in row or [])
        + str(item.get("caption") or "")
        + " ".join(str(u) for u in item.get("units") or [])
    )
    for found in _UNIT_LEXICON_RE.findall(source_text):
        if found != "无量纲":
            return "source_context", found
    return "unverified_absent", None


def _row_unit_candidates(item: dict) -> set[str]:
    """The units the READ row can bind a claim's asserted unit to: its own 单位
    cell plus lexicon units named in header/caption/units/footnotes."""
    cands: set[str] = set()
    cell = _row_unit_cell(item)
    if cell:
        cands.add(_norm_unit(cell))
        if "无量纲" in cell:
            cands.add("无量纲")
    text = (
        "".join(_header_cells(item))
        + str(item.get("caption") or "")
        + " ".join(str(u) for u in item.get("units") or [])
        + " ".join(str(f) for f in item.get("footnotes") or [])
    )
    for m in _UNIT_LEXICON_RE.findall(text):
        if m != "无量纲":
            cands.add(_norm_unit(m))
        elif _note_applies_to_row(item):
            cands.add("无量纲")
    return cands


_EDITION_PREFIX_RE = re.compile(r"^(?:19|20)\d{2}\s*版")


def _prose_claim_problems(claim: str, quote: str, cited: dict | None) -> list[str]:
    """C1 (answer-review r3): the content-term/number-set is NOT a support proof
    — "总汞限值为0.1，总镉限值为0.05" swapped from a source that states the exact
    opposite contains every term and every number of the source and must be
    refused. A prose claim is accepted only as a CONTINUOUS VERBATIM statement of
    the bound source; the only decorations the application may see added are an
    edition-year prefix ("2012版…") and trailing punctuation. Any other rewrite
    is refused as a model_failure (partial) — no word-set fallback, and no
    second LLM call to re-ask."""
    hay_src = (cited.get("text") or "") if cited else ""
    hay = _norm_ci(hay_src + quote)
    core = _EDITION_PREFIX_RE.sub("", claim.strip(), count=1).strip("。；;，,、 \t　")
    core_n = _norm_ci(core)
    if core_n and core_n in hay:
        return []
    return [
        "prose claim is not a continuous verbatim statement of the bound source "
        "(only an edition-year prefix or trailing punctuation may be added on the "
        "application side) — every word and number merely OCCURRING in the source "
        "does not prove which subject carries which value; a rewritten or "
        "value-swapped claim is refused as model_failure without a second call"
    ]


def _claim_relation_problems(claim: str, quote: str, label: str, cited: dict | None) -> list[str]:
    """Full measurement relation for a claim against the cited READ row:
    signed complete value tokens, subject, quantity/average-time, level
    column, and the unit actually asserted after every value — plus verbatim
    word support for prose sources (answer-review r1 A1 + r2 B1)."""
    problems: list[str] = []
    # the average-time phrase ("24小时平均") is a QUANTITY marker, not a value:
    # strip it before pulling numbers so its digits never masquerade as values
    claim_vals_src = _AVG_RE.sub(" ", claim)
    claim_nums = _num_tokens(claim_vals_src)
    year_tokens = {t for t in _YEAR_RE.findall(label)}
    if cited is not None and cited.get("kind") == "table_row":
        allowed = _num_tokens(quote) | _row_value_tokens(cited.get("cells") or [])
        # the edition identity legitimately carries its YEAR — nothing else from
        # the label backs a factual value
        allowed |= year_tokens
        unsupported = sorted(n for n in claim_nums if n not in allowed)
        if unsupported:
            problems.append(
                f"claim numbers {unsupported} are not complete signed value tokens of "
                f"the quoted row (edition {label})"
            )
        subs = _subject_cells(cited)
        if subs and not any(_norm_ci(s) in _norm_ci(claim) for s in subs):
            problems.append(
                f"claim subject is not the row's subject cell(s) {subs}; a valid "
                "quote attached to a different subject never supports the claim"
            )
        # quantity / average-time: the row must state the SAME averaging term
        for term in set(_AVG_RE.findall(claim)):
            row_norm = _norm_ci(" ".join(str(c) for c in cited.get("cells") or []) + quote)
            if _norm_ci(term) not in row_norm:
                problems.append(
                    f"claim asserts {term}平均 but the bound row states no such "
                    "quantity/averaging time"
                )
        for level in _LEVEL_TERMS:
            if level in claim:
                col_vals = _level_column_value(cited, level)
                if col_vals is not None:
                    non_year = {n for n in claim_nums if n not in year_tokens}
                    bad = sorted(n for n in non_year if n not in col_vals)
                    if bad:
                        problems.append(
                            f"{level}-column values are {sorted(col_vals)}; the claim's "
                            f"{bad} belong to another column of the same row"
                        )
        # every value that ASSERTS a trailing unit must bind it to the row's
        # unit candidates — unrecognized unit strings are never a free pass
        cands = _row_unit_candidates(cited)
        for m in _MEASURE_RE.finditer(claim_vals_src):
            num, unit = m.group("num"), (m.group("unit") or "").strip()
            if num in year_tokens:
                # an edition year is identity, not a measurement value
                continue
            if not unit:
                continue
            if _norm_unit(unit) not in cands:
                problems.append(
                    f"value {num} claims unit {unit!r} but the bound row's units are "
                    f"{sorted(cands) or ['(none stated)']} — no proven equivalence, refused"
                )
    else:
        allowed = _num_tokens(quote) | year_tokens
        unsupported = sorted(n for n in claim_nums if n not in allowed)
        if unsupported:
            problems.append(f"claim numbers {unsupported} are not supported by the quote")
        problems.extend(_prose_claim_problems(claim, quote, cited))
    return problems


# C2 (answer-review r3): closed ABSTRACT question verbs/nouns — they state the
# comparison act, never a required subject slot (contrast 总汞/PM2.5, which are
# substances/metrics). Structural column words drop out via _SUBJECT_HEADER_RE.
_SLOT_FRAME_WORDS = ("对比", "定义", "区别", "变化", "差异", "哪些", "什么")


def _question_slot_terms(query: str) -> tuple[list[str], list[str], list[str]]:
    """C2 (answer-review r3): the required slot dimensions are read FROM THE
    QUESTION itself — subject/metric tokens, quantity/averaging time, level —
    never intersected with the already-read text (a condition no row happens
    to carry, like the level column word 二级, stays a REQUIRED slot; dropping
    it is exactly what let an on-topic wrong-level answer pass)."""
    codes = {c["raw"] for c in _split_codes(query)[0]} | {c["code"] for c in _split_codes(query)[0]}
    codes_n = {_norm_ci(c) for c in codes}
    avgs: list[str] = []
    for a in _AVG_RE.findall(query):
        if all(_norm_ci(a) != _norm_ci(x) for x in avgs):
            avgs.append(a)
    levels = [level for level in _LEVEL_TERMS if level in query]
    subjects: list[str] = []
    for g in tk.query_terms(query):
        t = g.render().strip()
        tn = _norm_ci(t)
        if len(t) < 2 or not _norm_ws(t):
            continue
        if tn in codes_n or t in avgs or t in levels:
            continue
        if re.fullmatch(r"[\d.\-/]+", t):
            continue
        if _QUESTION_FRAME.search(t) or _SUBJECT_HEADER_RE.search(t):
            continue
        if t in _SLOT_FRAME_WORDS or any(w in t or t in w for w in _GENERIC_NOTE_WORDS):
            continue
        if t not in subjects:
            subjects.append(t)
    return subjects, avgs, levels


def _alnum_flank(ch: str) -> bool:
    return bool(ch) and ch.isascii() and (ch.isalnum() or ch in ".-")


def _slot_subject_hit(slot: str, cell: str) -> bool:
    """Subject identity, not substring: CJK substance names use containment
    (Chinese text has no word delimiters and cells are short); ASCII/numeric
    metrics must appear as a WHOLE token — the PM1 slot is never filled by a
    PM10 row (and PM2.5 is found inside "PM2.5（细颗粒物）")."""
    if any("一" <= ch <= "鿿" for ch in slot):
        return slot in cell
    for m in re.finditer(re.escape(slot), cell):
        before = cell[m.start() - 1] if m.start() else ""
        after = cell[m.end()] if m.end() < len(cell) else ""
        if not _alnum_flank(before) and not _alnum_flank(after):
            return True
    return False


def _bound_fills_slot(b: dict, slot: dict) -> bool:
    """One verified claim may fill every slot it legitimately answers; the
    slot matrix is checked per slot, never as one big AND over a single
    claim (a multi-metric question is complete once each (edition × subject ×
    averaging × level) slot has SOME bound item).
    D1 (answer-review r4): the answered scope differs by source kind — a
    table row is atomic (its cells ARE the assertion), while a prose claim
    citing a whole paragraph answers only what its own text asserts: the
    paragraph's other subjects/averages stay READ evidence and can never
    fill a slot the model left unanswered."""
    if b["edition"]["label"].lower() != slot["edition"]:
        return False
    prose = b.get("source_kind") != "table_row"
    if slot["subject"] is not None:
        subject = _norm_ci(slot["subject"])
        if prose:
            if not _slot_subject_hit(subject, b["claim_norm"]):
                return False
        else:
            cells = b.get("subject_cells") or [b["row_norm"]]
            if not any(_slot_subject_hit(subject, c) for c in cells):
                return False
    if slot["avg"]:
        avg = _norm_ci(slot["avg"])
        if prose:
            if avg not in b["claim_norm"]:
                return False
        elif not (avg in b["row_norm"] or avg in b["claim_norm"]):
            return False
    if slot["level"] and _norm_ci(slot["level"]) not in b["claim_norm"]:
        # an asked level is only answered when the claim ATTRIBUTES that level;
        # a correct row read for the other column is on-topic but off-request
        return False
    return True


def _verify_model_items(
    items: list[dict], doc_sections: list[dict]
) -> tuple[list[dict], list[str]]:
    """Every claim must be bound to ONE context edition, its quote verbatim
    IN THAT EDITION's context, AND the claim's subject / level-column / value
    tokens / unit must match the read structure of the cited row (A1).
    Edition identity (doc/snapshot) is applied by the program — the model only
    selects a label; label matching is case-insensitive and collisions are
    refused before any model contact."""
    by_label: dict[str, dict] = {}
    for s in doc_sections:
        key = s["label"].lower()
        if key in by_label:
            raise AdapterError("synthesis labels collide — refusing before model use")
        by_label[key] = s
    problems: list[str] = []
    bound: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            problems.append("model item is not an object")
            continue
        model_label, claim, quote = (
            it.get("edition"),
            (it.get("claim") or "").strip(),
            (it.get("quote") or "").strip(),
        )
        section = by_label.get((model_label or "").strip().lower())
        if section is None or not claim or not quote:
            problems.append(f"claim missing or edition {model_label!r} is not a context label")
            continue
        label = section["label"]  # application-canonical edition label
        haystack = _norm_ws(section["context_text"])
        if _norm_ws(quote) not in haystack:
            problems.append(f"quote not verbatim in edition {label}'s read context")
            continue
        # application-bound citation identity for the claim: locate the quote
        # in the SAME per-item row rendering the context was assembled from
        cited_item = next(
            (i for i in section["items"] if _norm_ws(quote) in _norm_ws(_item_row(i))),
            None,
        )
        relation = _claim_relation_problems(claim, quote, label, cited_item)
        if relation:
            problems.extend(relation)
            continue
        bound.append(
            {
                "kind": "synthesis_claim",
                "edition": {
                    "label": label,
                    "doc_id": section["doc_id"],
                    "workspace": section["workspace"],
                    "snapshot_id": section["snapshot_id"],
                },
                "claim": claim,
                "quote": quote,
                # C2 slot coverage works on the application-rendered row /
                # claim text — normalized once here, never re-parsed ad hoc
                "claim_norm": _norm_ci(claim),
                "row_norm": _norm_ci(_item_row(cited_item)) if cited_item else _norm_ci(haystack),
                # the bound row's OWN subject cells (whole-token identity from
                # the READ structure — what subject slot this item can fill)
                "subject_cells": (
                    [_norm_ci(str(s)) for s in _subject_cells(cited_item)]
                    if cited_item is not None and cited_item.get("kind") == "table_row"
                    else []
                ),
                # D1 (answer-review r4): the answered scope of an item. A table
                # row is ATOMIC (its cells are what the bound claim asserts);
                # for prose the citation may span a whole paragraph while the
                # claim asserts only one clause of it — the paragraph's other
                # subjects/averages are READ evidence, never ANSWERED slots.
                # The claim itself (continuous-verbatim over the source by C1)
                # is what the model actually answered.
                "source_kind": cited_item.get("kind") if cited_item is not None else "context_only",
                "citation": cited_item.get("citation")
                if cited_item
                else {
                    "kind": "context_only",
                    "doc_id": section["doc_id"],
                    "quote": quote,
                },
                "citation_verified": bool(cited_item)
                and cited_item.get("citation_verified") is True
                and cited_item.get("citation_reverified") is True,
                "relation_basis": "subject/column/value-token/unit checked against the cited row",
            }
        )
    return bound, problems


# ---------------------------------------------------------------------------
# Per-query orchestration
# ---------------------------------------------------------------------------


def _attribution_evidence_map(fused_result: dict, workspace: str, snapshot_id: str) -> dict:
    """improvement-2 r2 (A): harvest the REAL 5.3-published attribution evidence.

    A document is a candidate for the membership relaxation ONLY when the
    upstream replay itself publishes the full accepted shape:

    - a typed document target (``target_type == "doc"``) whose
      ``discovery == "doc_attribution"`` carries ``citation_verified is True``,
      a non-empty string ``membership_basis`` (a boolean or an empty string
      is never evidence), and a workspace consistent with THIS request;
    - its ``citation`` is a ``catalog_row`` reference bound to this same
      workspace, the ACTIVE catalog snapshot and the same ``doc_id`` — the
      exact shape ``search/query.py`` ``_doc_attribution_route`` records and
      ``fusion._allowed_docs`` publishes;
    - the same document with the IDENTICAL membership_basis appears in
      ``allowed_set_basis.verified_attributions`` — the upstream's own
      allowed-set record. An unbacked typed entry is as refused as an
      unbacked basis entry (the closure is bidirectional).

    Candidate self-labels (a path tagged ``discovery="doc_attribution"``, an
    arbitrary ``membership_basis`` string on a replayed candidate, a merely
    similar name) are NEVER evidence here — they feed nothing into this map.
    The catalog row for the doc is still required and re-checked by the
    identity gate (existence + identity through the owning guarded
    connection); this map only records what upstream PUBLISHED.
    """
    basis_entries = [
        b
        for b in ((fused_result.get("allowed_set_basis") or {}).get("verified_attributions") or [])
        if isinstance(b, dict)
    ]
    out: dict[str, dict] = {}
    for tt in fused_result.get("typed_targets") or []:
        if not isinstance(tt, dict):
            continue
        if tt.get("target_type") != "doc" or tt.get("discovery") != "doc_attribution":
            continue
        d = tt.get("doc_id")
        if not d:
            continue
        if (tt.get("workspace") or workspace) != workspace:
            continue
        if tt.get("citation_verified") is not True:
            continue
        mb = tt.get("membership_basis")
        if not (isinstance(mb, str) and mb.strip()):
            continue
        cit = tt.get("citation") or {}
        if (
            cit.get("kind") != "catalog_row"
            or cit.get("workspace") != workspace
            or cit.get("snapshot_id") != snapshot_id
            or cit.get("doc_id") != d
        ):
            continue
        if not any(b.get("doc_id") == d and b.get("membership_basis") == mb for b in basis_entries):
            continue
        out[d] = {
            "doc_id": d,
            "doc_name": tt.get("doc_name"),
            "membership_basis": mb,
            "citation": dict(cit),
            "source": "typed doc_attribution target cross-checked against "
            "allowed_set_basis.verified_attributions (5.3 published shape)",
        }
    return out


async def _confirm_scope_identities(
    conn,
    workspace: str,
    snapshot_id: str,
    branches: list[tuple[str, str | None]],
    docs: list[str],
    attributions: dict[str, dict],
    attribution_wanted: bool,
) -> tuple[list[str], list[dict], list[dict], list[dict], dict[str, str]]:
    """improvement-2: canonical target identity confirmation (answer policy).

    Discovery never defines the answer scope. For every document proposed as a
    target (or merely discovered), the catalog's canonical self_code /
    self_code_version is read through the SAME guarded workspace+snapshot the
    readers use (no second connection, no bypass of the budget wrapper). The
    candidate file_path and any replay-declared title are audit clues ONLY;
    a typed label (even ``code_exact``) never bypasses confirmation:

    - canonical code+version matches a requested branch → allowed (branch
      covered); a version-less branch accepts every catalog version (the
      original multi-version contract, never a first-pick);
    - canonical identity matches NO branch → rejected with its canonical code
      recorded for audit;
    - catalog row missing / self_code unknown → unresolved, never guessed from
      a name. The ONLY relaxation is the already-accepted membership route: an
      explicitly requested 含修改单/相关文件/整合版 question may allow an
      unknown-self_code document ONLY on the upstream-published 5.3
      doc_attribution evidence (``attributions``, built by
      ``_attribution_evidence_map``) whose catalog_row citation matches the
      current row's doc_name — a candidate's own discovery/membership label, a
      boolean citation flag or a merely similar name never does. An
      upstream-confirmed attribution target with no usable chunk still joins
      the full scope read (the caller registers allowed docs absent from the
      candidates).

    Returns (allowed_doc_ids, rejected, unresolved, unconfirmed_branches,
    allowed_basis).
    """
    allowed: list[str] = []
    rejected: list[dict] = []
    unresolved: list[dict] = []
    basis: dict[str, str] = {}
    covered: set[int] = set()
    for d in docs:
        row = await conn.fetchrow(_DOC_META_SQL, workspace, snapshot_id, d)
        if row is None:
            unresolved.append(
                {
                    "doc_id": d,
                    "reason": "catalog documents row missing for this workspace+snapshot — "
                    "identity unresolvable (this is NOT a verified corpus absence)",
                }
            )
            continue
        code = str(row.get("self_code") or "")
        ver = str(row.get("self_code_version") or "")
        if not code:
            evd = attributions.get(d) if attribution_wanted else None
            if evd is not None:
                ev_name, row_name = str(evd.get("doc_name") or ""), str(row.get("doc_name") or "")
                if ev_name and row_name and ev_name != row_name:
                    unresolved.append(
                        {
                            "doc_id": d,
                            "reason": "the upstream attribution evidence names a different "
                            "document than the current catalog row (evidence doc_name "
                            f"{ev_name!r} != catalog {row_name!r}) — identity not confirmed",
                        }
                    )
                    continue
                allowed.append(d)
                basis[d] = (
                    "membership via the upstream-published 5.3 doc_attribution evidence "
                    f"(catalog_row citation @ workspace+active snapshot, cross-checked in "
                    f"allowed_set_basis.verified_attributions; basis: "
                    f"{json.dumps(evd['membership_basis'], ensure_ascii=False)[:120]}); "
                    "self_code unknown in the catalog — cover attribution, never a "
                    "candidate label, never a fabricated code"
                )
            else:
                unresolved.append(
                    {
                        "doc_id": d,
                        "reason": "self_code unknown in the catalog — never guessed from a "
                        "name; only the upstream-published, allowed-set-cross-checked "
                        "attribution evidence may carry such a document",
                    }
                )
            continue
        norm = (normalize_code(code) or code).casefold()
        matched = False
        for idx, (bcode, bver) in enumerate(branches):
            bn = (normalize_code(bcode or "") or bcode or "").casefold()
            if norm != bn:
                continue
            if bver is None:
                allowed.append(d)
                basis[d] = (
                    f"canonical {code}-{ver or '?'} matches requested code {bcode} "
                    "(no version given — the multi-version contract keeps every catalog version)"
                )
                covered.add(idx)
                matched = True
                break
            if _version_matches(ver, bver, strict=True):
                allowed.append(d)
                basis[d] = (
                    f"canonical {code}-{ver} matches requested branch {bcode}-{bver} "
                    "(catalog documents row via the guarded workspace+snapshot)"
                )
                covered.add(idx)
                matched = True
                break
        if not matched:
            rejected.append(
                {
                    "doc_id": d,
                    "reason": f"canonical identity {code}-{ver or '?'} matches no requested "
                    f"branch {[f'{c}-{v}' if v else c for c, v in branches]}",
                }
            )
    unconfirmed = [
        {"code": bc, "version": bv} for idx, (bc, bv) in enumerate(branches) if idx not in covered
    ]
    return allowed, rejected, unresolved, unconfirmed, basis


async def _answer_one(values, qid, gold_q, replay, report, ctx) -> dict:
    out: dict = {
        "query_id": qid,
        "query": gold_q.get("question") or "",
        "category": gold_q.get("category") or ("counter" if gold_q.get("counter") else "unknown"),
        "workspace": gold_q.get("workspace") or "default",
        "coverage_status": "partial",
        "fail_stage": "",
        "flags": [],
        "replay": None,
        "scope_selection": None,
        "expansions": [],
        "answer": None,
        "reverification": None,
        "model": None,
        "status": "ok",
    }
    # D2/F3-b heritage: the in-flight record is registered BEFORE any await
    # so a mid-query failure still reaches the terminal.
    if ctx.get("live") is not None:
        ctx["live"]["partial"] = out
    fused_result, rerank_result = replay
    if fused_result is None:
        out["coverage_status"] = "missing"
        out["flags"].append("no fused replay for this query id (zero model calls)")
        return out

    # C1 heritage: the replay must be bound to THIS question/workspace.
    if (fused_result.get("query") or "") != out["query"] or (
        fused_result.get("workspace") or "default"
    ) != out["workspace"]:
        raise AdapterError(
            f"replay binding mismatch for {qid}: fused query/workspace "
            f"{fused_result.get('query')!r}/{fused_result.get('workspace')!r} != gold "
            f"{out['query']!r}/{out['workspace']!r}"
        )

    out["replay"] = {
        "fused_status": fused_result.get("status"),
        "fused_degraded": fused_result.get("degraded") or [],
        "rerank_status": rerank_result.get("status") if rerank_result else "absent",
        "rerank_degraded": (rerank_result or {}).get("degraded") or [],
        "rerank_ordered_chunks": len((rerank_result or {}).get("ordered") or []),
        "typed_targets": (rerank_result or {}).get("typed_targets")
        or fused_result.get("typed_targets")
        or [],
        "note": "rerank order is SCOPE PRIORITY only; every replayed candidate "
        "document is expanded with its FULL membership below",
    }
    if rerank_result is None:
        out["flags"].append(
            "no rerank replay for this query id — scope priority falls back to "
            "fusion path order, explicitly recorded (no fabricated scores)"
        )
    elif rerank_result.get("status") == "degraded":
        out["flags"].append(
            "rerank degraded (replayed): scope priority is the fusion order, never a claimed rerank success"
        )

    result = _build_replay_result(qid, gold_q, fused_result, rerank_result)
    prov = fused_result.get("path_provenance") or {}
    if fused_result.get("status") == "missing" and prov.get("discovery_only"):
        out["coverage_status"] = "ambiguous"
        out["flags"].append(
            "the local discovery path found NOTHING ON THIS PATH — target identity is "
            "UNCONFIRMED; this is not a verified absence from the whole corpus and the "
            "answer layer must not publish a corpus-wide missing (zero expansion reads)"
        )
        return out
    if fused_result.get("status") in ("missing", "stale"):
        out["coverage_status"] = fused_result["status"]
        out["flags"].append(
            "fused replay is missing/stale — expansion refused, the answer layer "
            "never upgrades a missing/stale discovery (zero expansion reads)"
        )
        return out

    category = out["category"]
    # ---- SCOPE SELECTION + TARGET IDENTITY CONFIRMATION (improvement-2).
    # Discovery never defines the answer scope: proposed documents (upstream
    # targets_resolved / typed labels / replayed candidates) are confirmed
    # against the catalog's canonical self_code/self_code_version through the
    # SAME guarded workspace+snapshot connection. file_enum keeps its original
    # contract — document enumeration IS the answer and must never be gated
    # empty. Upstream-resolved targets keep the full-read principle: membership
    # is never top-k bounded, rerank order only prioritizes. Incidental noise
    # documents stay auditable (expanded records / exclusion reasons) but
    # cannot enter the answer or degrade confirmed targets.
    resolved: list[str] = []
    for t in fused_result.get("targets_resolved") or []:
        for d in t.get("docs") or []:
            if d and d not in resolved:
                resolved.append(d)
    for tt in out["replay"]["typed_targets"]:
        d = tt.get("doc_id")
        if d and d not in resolved:
            resolved.append(d)
    candidate_docs: list[str] = []
    for c in result.candidates:
        _cd = c.get("doc_id")
        if _cd and _cd not in candidate_docs:
            candidate_docs.append(_cd)
    branches = [
        (c.get("code") or "", c.get("version"))
        for c in (result.parsed_codes or [])
        if c.get("code")
    ]
    branch_source = "local parse of the question"
    snapshot_id = report["identity_before"]["catalog_active"]["snapshot_id"]
    # upstream-PUBLISHED attribution evidence only (r2 A): candidate labels
    # never enter this map; see _attribution_evidence_map.
    attributions = _attribution_evidence_map(fused_result, out["workspace"], snapshot_id)
    if not branches:
        # improvement-2 r2 (B): a code-less question still needs a CONFIRMED
        # scope basis. A self-reported targets_resolved is NOT confirmation —
        # the local synthesis path (discovery_only / targets_confirmed False)
        # can never confirm its own targets. Only a trustworthy upstream
        # replay may declare the branch here, and only in the real 5.3
        # code_exact resolution shape (code+version+docs); the documents stay
        # subject to the SAME catalog identity gate below.
        trusted = (
            not prov.get("discovery_only") and fused_result.get("targets_confirmed") is not False
        )
        if trusted:
            for t in fused_result.get("targets_resolved") or []:
                if isinstance(t, dict) and (t.get("code") or ""):
                    b = (str(t["code"]), t.get("version") or None)
                    if b not in branches:
                        branches.append(b)
            if branches:
                branch_source = (
                    "upstream 5.3 code_exact resolution trace (every document is "
                    "re-confirmed against the CURRENT catalog below)"
                )
    confirmation: dict | None = None
    if category == "file_enum":
        confirmation = {
            "skipped": "file enumeration lists documents by metadata predicate — "
            "the identity gate must not bound the listing",
        }
        selected_docs = resolved or list(candidate_docs)
    elif branches:
        universe: list[str] = []
        for d in resolved + candidate_docs:
            if d not in universe:
                universe.append(d)
        (
            allowed,
            rejected,
            unresolved_docs,
            unconfirmed_branches,
            allowed_basis,
        ) = await _confirm_scope_identities(
            ctx["conn"],
            out["workspace"],
            snapshot_id,
            branches,
            universe,
            attributions,
            _attribution_requested(result.query_text or ""),
        )
        selected_docs = allowed
        confirmation = {
            "request_branches": [{"code": b[0], "version": b[1]} for b in branches],
            "branch_source": branch_source,
            "identity_source": "catalog documents rows (self_code/self_code_version) read "
            "through the guarded workspace+catalog-snapshot connection",
            "allowed": allowed,
            "allowed_basis": allowed_basis,
            "rejected": rejected,
            "unresolved": unresolved_docs,
            "unconfirmed_branches": unconfirmed_branches,
            "rule": "discovery never defines the answer scope; a typed label or a "
            "replay-declared name is an audit clue, never canonical identity",
        }
        have = set(candidate_docs)
        for d in allowed:
            if d not in have:
                result.candidates.append(
                    {
                        "doc_id": d,
                        "chunk_id": None,
                        "workspace": out["workspace"],
                        "discovery": "target_resolved_replay",
                        "score": None,
                        "heading": None,
                        "paths": [
                            {"path": "pg", "doc_id": d, "discovery": "target_resolved_replay"}
                        ],
                    }
                )
                out["flags"].append(
                    f"resolved target document {d} is absent from the replayed "
                    "candidates — registered for the FULL scope read (the confirmed "
                    "resolution, not discovery top-k, defines the membership)"
                )
        for rj in rejected:
            out["flags"].append(
                f"discovery document {rj['doc_id']} excluded from the answer scope: {rj['reason']}"
            )
        for ur in unresolved_docs:
            out["flags"].append(
                f"discovery document {ur['doc_id']} identity unresolved: {ur['reason']}"
            )
        if unconfirmed_branches:
            out["flags"].append(
                "requested target branch(es) "
                + json.dumps(unconfirmed_branches, ensure_ascii=False)
                + " have NO confirmed document on this path — items of the confirmed "
                "targets are kept, but the answer is not complete"
            )
        if not allowed:
            out["flags"].append(
                "no discovered document carries a canonical identity matching the "
                "requested branch(es): THIS PATH confirmed no target — this is not a "
                "verified absence from the whole corpus"
            )
    else:
        # improvement-2 r2 (B): no code branch — neither the local parse nor a
        # TRUSTWORTHY upstream 5.3 resolution supplies one. A non-empty
        # typed_targets/targets_resolved list is NOT a confirmation basis:
        # old synthetic local inputs promoted every discovery into a typed doc
        # target (discovery="local"), pure local inputs can self-report
        # targets_resolved, and a field name or a bare confirmed boolean proves
        # nothing. Discovery proposals stay recorded for audit with their
        # refusal reason; the answer scope is EMPTY, zero expansion reads.
        proposals: list[dict] = []
        for tt in out["replay"]["typed_targets"]:
            if isinstance(tt, dict) and tt.get("doc_id"):
                proposals.append(
                    {
                        "kind": "typed_target",
                        "doc_id": tt.get("doc_id"),
                        "target_type": tt.get("target_type"),
                        "discovery": tt.get("discovery"),
                    }
                )
        for t in fused_result.get("targets_resolved") or []:
            if isinstance(t, dict):
                proposals.append(
                    {
                        "kind": "targets_resolved",
                        "code": t.get("code"),
                        "version": t.get("version"),
                        "discovery": t.get("discovery"),
                        "docs": list(t.get("docs") or []),
                    }
                )
        if prov.get("discovery_only") or fused_result.get("targets_confirmed") is False:
            refusal_reason = (
                "the replayed path self-declares discovery-only (path_provenance."
                "discovery_only / targets_confirmed False): its typed_targets and "
                "targets_resolved fields re-report DISCOVERY, never a confirmation"
            )
        elif proposals:
            refusal_reason = (
                "no typed/resolved entry carries a 5.3 code_exact resolution "
                "(code+version+docs) or a current-workspace+snapshot-verifiable "
                "metadata/scope predicate — a field name or a bare confirmed "
                "boolean is not a scope basis"
            )
        else:
            refusal_reason = (
                "no requested code branch and no resolution of any kind: the "
                "replay carries discovery only"
            )
        out["scope_selection"] = {
            "candidates": len(result.candidates),
            "selected_docs": [],
            "priority": _scope_priority(result, rerank_result),
            "target_confirmation": {
                "rule": "discovery documents alone are not a scope basis; a "
                "typed/targets_resolved label without a code_exact resolution "
                "or a catalog-verifiable scope is discovery, not confirmation "
                "(improvement-2 r2)",
                "verdict": "ambiguous — no requested code branch, no trustworthy "
                "upstream 5.3 resolution, no logical scope/metadata predicate to "
                "confirm",
                "discovery_proposals_kept_for_audit": proposals,
                "refusal_basis": refusal_reason,
            },
        }
        out["coverage_status"] = "ambiguous"
        out["flags"].append(
            "the question names no code branch and no trustworthy upstream "
            "resolution supplies a scope basis: discovered documents alone never "
            "define the answer scope — explicit ambiguous, never a silent full "
            "expansion (zero expansion reads; a this-path refusal is not a "
            "verified corpus absence)"
        )
        return out
    out["scope_selection"] = {
        "candidates": len(result.candidates),
        "selected_docs": selected_docs,
        "priority": _scope_priority(result, rerank_result),
        "target_confirmation": confirmation,
        "basis": "confirmed canonical target identity defines the answer scope (improvement-2); "
        "discovery/top-k/rerank order never bound or promote membership — unconfirmed "
        "documents are excluded with recorded reasons and cannot enter the answer",
    }

    await expand_candidates(
        ctx["conn"],
        result,
        out["workspace"],
        values,
        expand_docs=(category == "file_enum"),
        prose_budget=(ctx.get("expand_budgets") or {}).get(qid),
    )
    expansions_all, doc_enum = _expansion_stages(result)
    sel = set(selected_docs)
    expansions = [e for e in expansions_all if e.get("doc_id") in sel]
    unselected = [e for e in expansions_all if e.get("doc_id") not in sel]
    if unselected:
        out["flags"].append(
            f"{len(unselected)} expansion record(s) from non-target candidate "
            "documents are recorded but cannot degrade the selected scope"
        )

    # independent re-read of every carried citation -------------------------
    problems: list[str] = []
    checked = 0
    parsed_dirs: dict[str, Path] = {}
    for exp in expansions:
        if exp.get("kind") not in ("table", "prose"):
            continue
        doc_id = exp.get("doc_id")
        if doc_id not in parsed_dirs:
            doc_name = await ctx["conn"].fetchval(
                _DOC_NAME_SQL, out["workspace"], snapshot_id, doc_id
            )
            parsed_dirs[doc_id] = _doc_parsed_dir(doc_name)
        pdir = parsed_dirs[doc_id]
        items = exp.get("items") or []
        checked += len(items)
        if exp.get("kind") == "table":
            problems.extend(_reverify_table_items(items, pdir))
        else:
            problems.extend(_reverify_prose_items(items, pdir))
    out["reverification"] = {
        "items_checked": checked,
        "problems": problems,
        "basis": "table rows re-read against the raw HTML grid of their bound "
        "fragment; prose items re-read against the raw unit block text at the "
        "declared unit-relative span (independent of the in-memory objects)",
    }

    # deterministic per-category rendering ----------------------------------
    answer = await _render_with_docs(
        category, result, expansions, doc_enum, rerank_result, ctx, out, snapshot_id, parsed_dirs
    )
    out["answer"] = answer

    # synthesis: at most one answer model call over the read context ---------
    if category == "synthesis":
        await _synthesis_generate(values, result, out, expansions, ctx, snapshot_id)

    # ------------------------------------------------------------------ coverage
    statuses = [(e.get("status") or e.get("coverage_status") or "").lower() for e in expansions]
    if doc_enum is not None:
        statuses.append((doc_enum.get("coverage_status") or "").lower())
    missing_clauses = [
        c
        for e in expansions
        if e.get("kind") == "prose"
        for c in (e.get("missing_requested_clauses") or [])
    ]
    out["expansions"] = [
        {k: v for k, v in e.items() if k != "items"}
        | {"items_count": len(e.get("items") or []), "selected": True}
        for e in expansions
    ] + [
        {k: v for k, v in e.items() if k != "items"}
        | {
            "items_count": len(e.get("items") or []),
            "selected": False,
            "note": "non-target candidate document — recorded for transparency, "
            "excluded from the answer scope and coverage decision",
        }
        for e in unselected
    ]
    if doc_enum is not None:
        out["expansions"].append({"stage": "document_enumeration"} | dict(doc_enum))
    if missing_clauses:
        statuses.append("partial")
        out["flags"].append(f"requested clauses missing from the read scope: {missing_clauses}")
    if problems:
        statuses.append("partial")
    if (confirmation or {}).get("unconfirmed_branches"):
        statuses.append("partial")
    if not expansions and doc_enum is None and category != "counter":
        statuses.append("partial")
        out["flags"].append("expansion requested but nothing confirmed — never a guessed range")
    items_all = [it for e in expansions for it in (e.get("items") or [])]
    unverified = [it for it in items_all if it.get("citation_verified") is not True] + [
        it for it in items_all if it.get("citation_reverified") is False
    ]
    if any(s == "stale" for s in statuses):
        cov = "stale"
    elif any(s == "ambiguous" for s in statuses):
        cov = "ambiguous"
    elif any(s in ("partial", "error", "") for s in statuses):
        cov = "partial"
    elif not statuses:
        cov = "partial"
    elif category == "file_enum":
        doc_items = answer["items"]
        if doc_enum.get("members_processed") != doc_enum.get("members_total"):
            cov = "partial"
            out["flags"].append("document enumeration did not process every page member")
        elif not doc_items:
            cov = "partial"
            out["flags"].append("zero-item enumeration is never reported as complete")
        elif any(not d.get("citation_verified") for d in doc_items):
            cov = "partial"
            out["flags"].append("enumerated documents carry unverified citations")
        else:
            cov = "complete"
    elif unverified:
        cov = "partial"
        out["flags"].append(f"{len(unverified)} item(s) failed citation verification/re-read")
    elif not items_all and any((e.get("members_total") or 0) > 0 for e in expansions):
        cov = "partial"
        out["flags"].append("zero answer items over a non-empty scope is never complete")
    elif category == "fact" and not answer["items"]:
        cov = "partial"
    elif category == "fact" and answer.get("unit_blockers"):
        cov = "partial"
        out["flags"].append(
            "quantitative fact(s) lack a verifiable unit/condition in the READ "
            "source — the numbers stay as evidence but coverage is not complete"
        )
    elif category == "synthesis":
        claims = answer.get("items") or []
        if answer.get("model_failure") or not claims:
            cov = "partial"
            out["fail_stage"] = (
                "model_failure" if answer.get("model_failure") else out["fail_stage"]
            )
        elif any(not c.get("citation_verified") for c in claims):
            cov = "partial"
            out["flags"].append("synthesis claims must each bind a re-verified source citation")
        else:
            cov = "complete"
    else:
        cov = "complete"
    if cov == "complete" and (fused_result.get("budget") or {}).get("truncated"):
        cov = "partial"
        out["flags"].append(
            "fusion budget truncated the replayed set — the answer is NOT complete "
            "(truncation is recorded, never claimed as full coverage)"
        )
    out["coverage_status"] = cov
    out["status"] = "ok" if cov == "complete" else cov
    return out


async def _render_with_docs(
    category, result, expansions, doc_enum, rerank_result, ctx, out, snapshot_id, parsed_dirs
) -> dict:
    """Render deterministic answer items; table fragment conditions are
    resolved from the REAL catalog caption/heading rows (no guessing)."""
    for exp in expansions:
        if exp.get("kind") != "table":
            continue
        doc_id = exp.get("doc_id")
        rows = await ctx["conn"].fetch(_UNIT_META_SQL, out["workspace"], snapshot_id, doc_id)
        pdir = parsed_dirs.get(doc_id)
        tables = _tables_sidecar(pdir) if pdir else {}
        cond = _frag_conditions([dict(r) for r in rows], tables)
        for it in exp.get("items") or []:
            meta = cond.get((it.get("citation") or {}).get("table_id")) or {}
            it.setdefault("caption", meta.get("caption"))
    answer = _render_answer(category, result, expansions, doc_enum, rerank_result)
    if category == "file_enum":
        # improvement-3: a published document item is verified only by an
        # INDEPENDENT re-read of the catalog row through the SAME guarded
        # workspace+snapshot connection — a self-assigned boolean or a
        # citation bound to an empty/foreign snapshot never survives this
        # (the related scan's rows already carry the observed snapshot; this
        # is the answer layer refusing to trust it blindly).
        for it in answer["items"]:
            cit = it.get("citation") or {}
            doc_id = it.get("doc_id")
            ok = (
                cit.get("kind") == "catalog_row"
                and cit.get("workspace") == out["workspace"]
                and bool(cit.get("snapshot_id"))
                and cit.get("snapshot_id") == snapshot_id
                and bool(doc_id)
                and cit.get("doc_id") == doc_id
            )
            if ok:
                row = await ctx["conn"].fetchrow(
                    _DOC_META_SQL, out["workspace"], snapshot_id, doc_id
                )
                # F1: identity fields participate in the row re-read too — a
                # re-registered version under the same snapshot fails here AND
                # in the full-match-set publication guard (separate
                # responsibilities, both evidenced)
                ok = (
                    bool(row)
                    and (row.get("doc_name") or "") == (it.get("doc_name") or "")
                    and (row.get("self_code") or "") == (it.get("self_code") or "")
                    and (row.get("self_code_version") or "") == (it.get("self_code_version") or "")
                )
            it["citation_verified"] = bool(ok) and it.get("citation_verified") is True
            if not it["citation_verified"]:
                it["citation_reverified"] = False
                out["flags"].append(
                    f"file item {doc_id} did not survive the independent catalog-row "
                    "re-read — never published as verified (identity or snapshot unbound)"
                )
            else:
                it["citation_reverified"] = True
    return answer


async def _synthesis_generate(values, result, out, expansions, ctx, snapshot_id) -> None:
    answer = out["answer"]
    workspace = out["workspace"]
    category_sections: list[dict] = []
    for exp in expansions:
        if exp.get("kind") not in ("table", "prose"):
            continue
        doc_id = exp.get("doc_id")
        row = await ctx["conn"].fetchrow(_DOC_META_SQL, workspace, snapshot_id, doc_id)
        code = (row["self_code"] if row else "") or ""
        ver = (row["self_code_version"] if row else "") or ""
        label = (
            f"{normalize_code(code)}-{ver}"
            if code and ver
            else ((row["doc_name"] if row else None) or doc_id)
        )
        structure = _table_structure_from_warnings(exp.get("warnings") or [])
        items = [
            {
                "kind": "table_row" if exp.get("kind") == "table" else "prose_item",
                "clause": it.get("clause")
                or (it.get("seq") if exp.get("kind") == "table" else None),
                "cells": it.get("cells"),
                "text": it.get("text"),
                "citation": it.get("citation"),
                "citation_verified": it.get("citation_verified") is True,
                "citation_reverified": it.get("citation_reverified") is True,
                # A1: the read structure travels with the row so the claim's
                # subject/column/unit relations are checkable field by field
                "header": structure.get("header") or [],
                "units": structure.get("units") or [],
                "footnotes": structure.get("footnotes") or [],
                "caption": it.get("caption"),
            }
            for it in exp.get("items") or []
        ]
        existing = next((s for s in category_sections if s["doc_id"] == doc_id), None)
        if existing is None:
            existing = {
                "label": label,
                "doc_id": doc_id,
                "code_norm": normalize_code(code) if code else "",
                "version": ver,
                "workspace": workspace,
                "snapshot_id": snapshot_id,
                "items": [],
            }
            category_sections.append(existing)
        existing["items"].extend(items)
    for s in category_sections:
        text, _ = _synthesis_context([s])
        s["context_text"] = text

    # BEFORE any model contact: the compared editions must ALL be resolved
    # (a missing version is missing/incomplete — never substituted by the
    # neighbouring version or by gold), labels must be unique, and every
    # section must carry verified read context.
    model: dict = {
        "used": False,
        "sections": [
            {k: v for k, v in s.items() if k not in ("items", "context_text")}
            | {"item_count": len(s["items"]), "context_chars": len(s["context_text"])}
            for s in category_sections
        ],
    }
    out["model"] = model

    def _refuse(status: str, reason: str) -> None:
        model["status"] = status
        model["failure"] = reason
        answer["mode"] = "model"
        answer["items"] = []
        answer["model_failure"] = reason

    have = {(s["code_norm"].lower(), s["version"]) for s in category_sections if s["code_norm"]}
    expected = {
        (c["code"].lower(), c["version"]) for c in result.parsed_codes or [] if c.get("version")
    }
    missing_editions = sorted(f"{code}-{ver}" for code, ver in expected - have)
    if missing_editions:
        _refuse(
            "incomplete_conditions",
            f"requested edition(s) {missing_editions} are not resolved in the "
            "read scope — a version comparison missing one edition is "
            "incomplete, never answered from the neighbouring version or from gold",
        )
        return
    if not category_sections:
        _refuse(
            "incomplete_conditions",
            "no read context resolved for the comparison — refusing the answer "
            "model call (zero model calls), never answering from gold",
        )
        return
    empty_sections = [s["label"] for s in category_sections if not s["items"]]
    if empty_sections:
        _refuse(
            "incomplete_conditions",
            f"edition(s) {empty_sections} have no verified read context — a "
            "version comparison with a missing edition is incomplete",
        )
        return
    labels = sorted({s["label"] for s in category_sections})
    if len({s["label"].lower() for s in category_sections}) != len(category_sections):
        _refuse(
            "incomplete_conditions",
            "synthesis edition labels collide — the application cannot bind "
            "claim attribution unambiguously; refusing before any model call",
        )
        return

    if not ctx.get("allow_model", True):
        # the delivery protocol: scope/edition/condition verification runs
        # read-only FIRST; the single necessary call is explicitly authorized.
        _refuse(
            "model_not_authorized",
            "answer model call not authorized in this run — the compared editions' "
            "scopes and citations were verified read-only above; synthesis is "
            "reported incomplete, never answered from gold (0 model calls)",
        )
        return

    state = ctx["model_state"]
    if state["calls"] >= MAX_ANSWER_MODEL_CALLS:
        _refuse(
            "model_budget_refused",
            f"answer model budget ({MAX_ANSWER_MODEL_CALLS} per run) exhausted — "
            "the synthesis is reported partial, never answered by a second call",
        )
        return

    context_text, context_len = _synthesis_context(category_sections)
    if context_len > MAX_MODEL_CONTEXT_CHARS:
        _refuse(
            "model_budget_exhausted",
            f"context of {context_len} chars exceeds the model-call budget of "
            f"{MAX_MODEL_CONTEXT_CHARS}; the run REFUSES instead of silently "
            "truncating the compared evidence",
        )
        return

    payload = {
        "model": values.get("QUERY_LLM_MODEL") or values["LLM_MODEL"],
        "messages": [
            {"role": "system", "content": _SYNTH_SYSTEM},
            {
                "role": "user",
                "content": f"问题：{out['query']}\n\n版本标签：{labels}\n\n上下文：\n{context_text}",
            },
        ],
        "temperature": 0,
    }
    state["calls"] += 1
    model["used"] = True
    model["context_sha256"] = hashlib.sha256(context_text.encode("utf-8")).hexdigest()
    receipt = await _call_answer_model(values, payload, ctx["transport"])
    # publish the REAL receipt the moment the exchange completed
    if ctx.get("live") is not None:
        ctx["live"]["call"] = {k: v for k, v in receipt.items() if k != "content"}
    model["call"] = {k: v for k, v in receipt.items() if k != "content"}
    model["request_messages"] = payload["messages"]  # sanitized at the write point
    model["raw_response"] = receipt.get("content")
    if receipt["status"] != "success":
        _refuse(
            "model_failure",
            f"answer call failed: {receipt['error']} — degraded answer refused "
            "without a fabricated synthesis",
        )
        return
    items, shape_err = _parse_model_items(receipt.get("content") or "")
    if shape_err:
        _refuse("model_failure", f"answer response rejected: {shape_err}")
        return
    bound, problems = _verify_model_items(items, category_sections)
    answer["mode"] = "model"
    answer["generated_by"] = f"one answer model call ({payload['model']})"
    answer["items"] = bound
    answer["unverified_claims"] = problems
    if bound and not problems:
        # A2 (answer-review r1): reading both editions is not answering both
        # editions — the REQUIRED set comes from the parsed targets/resolved
        # scopes (never a hardcoded query id or year list). Verified answers
        # are kept; a missing one is explicit incompleteness.
        if expected:
            required = {
                s["label"].lower()
                for s in category_sections
                if (s["code_norm"].lower(), s["version"]) in expected
            }
        else:
            # multi-document comparison without version pins: every confirmed
            # section is a required answer element
            required = {s["label"].lower() for s in category_sections}
        # C2 (answer-review r3): the required set is a SLOT MATRIX read from
        # the QUESTION — edition × subject/metric × quantity/averaging × level.
        # Each slot is filled by SOME verified bound item (several items may
        # jointly cover a multi-metric comparison — one claim never has to
        # carry every metric); the denominator is NEVER intersected with the
        # already-read text (the asked level 二级 stays required though no row
        # cell spells it), and subject identity is whole-token, not substring
        # (a PM10 row never fills the PM1 slot). Verified-but-off-slot rows
        # stay in the answer as evidence.
        subjects, avgs, levels = _question_slot_terms(out["query"])
        model["question_elements"] = subjects + avgs
        model["question_levels"] = levels
        uncovered: list[str] = []
        for lab in sorted(required):
            for subject in subjects or [None]:
                for avg in avgs or [None]:
                    for level in levels or [None]:
                        slot = {"edition": lab, "subject": subject, "avg": avg, "level": level}
                        if not any(_bound_fills_slot(b, slot) for b in bound):
                            uncovered.append(
                                "/".join([lab] + [p for p in (subject, avg, level) if p])
                            )
        missing_answer = sorted(uncovered)
        if missing_answer:
            model["status"] = "incomplete_answer_coverage"
            model["missing_answer_editions"] = missing_answer
            answer["missing_answer_editions"] = missing_answer
            answer["model_failure"] = (
                f"required slot(s) {missing_answer} have no verified bound claim — "
                "a comparison missing one edition, missing one asked metric, or "
                "answered for the WRONG level (a correct first-level row never "
                "fills the asked second-level slot), or answered only with valid "
                "but OFF-TOPIC rows, is incomplete (the summary line never "
                "substitutes a citable answer item)"
            )
        else:
            model["status"] = "ok"
            answer["model_failure"] = None
    else:
        model["status"] = "model_failure"
        model["verification_problems"] = problems or ["no claim passed verification"]
        model["failure"] = (
            f"{len(problems)} claim(s) failed source verification"
            if problems
            else "no claim passed verification"
        )
        answer["model_failure"] = model["failure"]


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


async def run_answer(
    report_dir: Path,
    query_ids: list[str] | None = None,
    *,
    rerank_report_path: Path | None = None,
    fused_report_path: Path | None = None,
    transport=None,
    conn=None,
    values: dict | None = None,
    allow_model: bool = True,
    category_overrides: dict | None = None,
    expand_budgets: dict | None = None,
) -> dict:
    """5.5 end-to-end entry: replay the accepted fusion/rerank outcome, expand
    the FULL membership through the formal entries, render answers by question
    type (deterministic; synthesis may consume ONE answer model call when
    ``allow_model`` is set) and decide coverage from independent re-reads.
    Everything outside the guards is read-only; failures still terminate with
    per-query evidence."""
    rerank_path = Path(rerank_report_path or DEFAULT_RERANK_REPORT)
    fused_path = Path(fused_report_path or DEFAULT_FUSED_REPORT)
    wanted = list(query_ids or ["fact-002"])

    report: dict = {
        "task": "5.5 full scope expansion + per-type answers over replayed 5.3/5.4",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "service_contract": _MODEL_CONTRACT,
        "model_budget": MAX_ANSWER_MODEL_CALLS,
        "query_ids": wanted,
    }
    report_dir.mkdir(parents=True, exist_ok=True)

    values_ref = {"v": None}
    if values is None:
        values_ref["v"] = dict(dotenv_values(".env"))
    else:
        values_ref["v"] = dict(values)
    vals = values_ref["v"]

    def _write_terminal() -> None:
        safe = _sanitize_evidence(report, values_ref["v"])
        stamp = time.strftime("%Y%m%dT%H%M%S")
        body = json.dumps(safe, ensure_ascii=False, indent=1) + "\n"
        (report_dir / f"answer-runtime-{stamp}.json").write_text(body, encoding="utf-8")
        (report_dir / "answer-runtime-latest.json").write_text(body, encoding="utf-8")

    async def _write_failure(stage: str, detail) -> None:
        report["failure"] = {"stage": stage, "detail": detail}
        _write_terminal()

    # ---- pre-flight: config/gold/replay parsing, ALL before any backend read
    zero_call_ledger = {
        "query_id": None,
        "call_records": [],
        "note": "pre-flight rejection before any backend read or model call",
    }
    try:
        gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
        by_id = {q["query_id"]: q for q in gold["questions"]}
        for c in gold.get("counter_examples", []):
            cid = c.get("counter_id")
            if cid and cid not in by_id:
                by_id[cid] = {
                    "query_id": cid,
                    "question": c.get("question") or "",
                    "workspace": "default",
                    "counter": {"type": c.get("type"), "expected_status": c.get("expected_status")},
                }
        # 6.1 evaluation seam: the Phase-4 adapter supplies question routing
        # metadata (counter categories / enumerated budgets); default None
        # preserves the accepted gold-only behavior exactly.
        for qid, cat in (category_overrides or {}).items():
            if qid in by_id:
                by_id[qid] = {**by_id[qid], "category": cat}
        unknown = [q for q in wanted if q not in by_id]
        if unknown:
            raise _PreflightRejection("unknown-query-id", unknown)
        for qid in wanted:
            verify_config_guard(vals, by_id[qid].get("workspace") or "default")
        if any((by_id[q].get("category") == "synthesis") for q in wanted):
            for key in ("LLM_BINDING_HOST", "LLM_MODEL", "LLM_BINDING_API_KEY"):
                if not (vals.get(key) or "").strip():
                    raise AdapterError(f"{key} missing in .env (synthesis answer refused)")
        report["gold_sha_verified"] = verify_gold_guard(GOLD_PATH)
        rerank_report, fused_report, rerank_by_id, fused_by_id, provenance = _load_replay(
            rerank_path, fused_path
        )
        report["replay_sources"] = provenance
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
    except Exception as exc:  # noqa: BLE001 — unified terminal, never swallows
        report["failure_service_records"] = dict(zero_call_ledger)
        await _write_failure("pre-flight", f"{type(exc).__name__}: {exc}")
        raise

    # ---- first read-only backend contact: the identity guard
    try:
        pre = await _capture_identity(vals)
    except Exception as exc:  # noqa: BLE001
        await _write_failure("identity-capture", f"{type(exc).__name__}: {exc}")
        raise AdapterError("pre-flight identity capture failed") from exc
    live_ident = pre["identity"]
    report["identity_before"] = {
        "matches_frozen": pre["matches_frozen"],
        "problems": pre["problems"],
        "counts": live_ident["public_counts"],
        "source_fingerprint": live_ident["source_fingerprint"],
        "catalog_active": live_ident["catalog_active"],
        "search_active": live_ident["search_active"],
        "gold_sha": live_ident["gold_sha"],
        "env_sha": live_ident["env_sha"],
    }
    if not pre["matches_frozen"]:
        await _write_failure("identity-before", pre["problems"])
        raise AdapterError("pre-flight identity mismatch: " + "; ".join(pre["problems"]))

    gen_problems, gen_warnings = _bind_replay_generation(
        rerank_report, fused_report, report["identity_before"]
    )
    if gen_warnings:
        report["replay_generation_warnings"] = gen_warnings
    if gen_problems:
        report["failure_service_records"] = dict(zero_call_ledger)
        await _write_failure("replay-generation", gen_problems)
        raise AdapterError("replay generation binding refused: " + "; ".join(gen_problems))

    # ---- per-query expansion/answer loop — the connection ACQUISITION sits
    # INSIDE the unified resource/terminal boundary (A3): a failed connect
    # still runs the post guard, writes the failure terminal with an explicit
    # zero-answer ledger, and only ever closes a connection we actually got.
    own_conn = conn is None
    acquired_conn = None
    live: dict = {"query_id": None, "call": None, "partial": None}
    ctx = {
        "conn": conn,
        "transport": transport,
        "allow_model": allow_model,
        "live": live,
        "model_state": {"calls": 0},
        "expand_budgets": dict(expand_budgets or {}),
    }
    results: list[dict] = []
    run_error: str | None = None
    failed_query_id: str | None = None
    try:
        if own_conn:
            acquired_conn = await asyncpg.connect(
                host=vals["POSTGRES_HOST"],
                port=int(vals["POSTGRES_PORT"]),
                user=vals["POSTGRES_USER"],
                password=vals["POSTGRES_PASSWORD"],
                database=vals["POSTGRES_DATABASE"],
                statement_cache_size=0,
                timeout=15,
                server_settings={"default_transaction_read_only": "on"},
            )
            conn = acquired_conn
            ctx["conn"] = conn
        for qid in wanted:
            failed_query_id = qid
            live["query_id"] = qid
            live["call"] = None
            live["partial"] = None
            replay = (fused_by_id.get(qid), rerank_by_id.get(qid))
            out = await _answer_one(vals, qid, by_id[qid], replay, report, ctx)
            live["partial"] = out
            failed_query_id = None
            results.append(out)
    except Exception as exc:  # noqa: BLE001 — unified terminal
        run_error = f"{type(exc).__name__}: {exc}"
    finally:
        if own_conn and acquired_conn is not None:
            try:
                await acquired_conn.close()
            except Exception as exc:  # noqa: BLE001 — recorded, never swallowed
                report["conn_close_error"] = type(exc).__name__
        post = None
        post_error = None
        try:
            post = await _capture_identity(vals)
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
        report["model_calls_used"] = ctx["model_state"]["calls"]
        if run_error is not None:
            if live.get("partial") is not None and live["partial"] not in results:
                results.append(live["partial"])
            report["results"] = results
            if live.get("call") is not None:
                report["failure_service_records"] = {
                    "query_id": live["query_id"] or failed_query_id,
                    "call_records": [live["call"]],
                    "note": "the failing query's real answer-model receipt, "
                    "published at exchange completion",
                }
            else:
                report["failure_service_records"] = {
                    "query_id": live["query_id"] or failed_query_id,
                    "call_records": [],
                    "note": "failure occurred before/without a captured answer-model receipt",
                }
            await _write_failure("answer", run_error)
        elif post_error:
            report["results"] = results
            await _write_failure("identity-after-capture-error", post_error)
        elif report.get("identity_drift"):
            report["results"] = results
            await _write_failure("identity-after-drift", report["identity_drift"])
        elif report.get("identity_after") and not report["identity_after"]["matches_frozen"]:
            report["results"] = results
            await _write_failure("identity-after", report["identity_after"]["problems"])
        else:
            report["results"] = results
            _write_terminal()
    # A3: a failed guard is never a normal return — the caller (CLI) must see
    # non-zero. The terminal already holds the ORIGINAL run error plus the post
    # error/drift side by side; results stay in the report for diagnosis but
    # are NOT delivered as trustworthy complete answers.
    if run_error is not None:
        raise AdapterError(f"answer run failed: {run_error}")
    if report.get("failure"):
        raise AdapterError(
            "post-guard failure recorded, results are not trustworthy-complete: "
            + json.dumps(report["failure"], ensure_ascii=False)[:500]
        )
    return report
