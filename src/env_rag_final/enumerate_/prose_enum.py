"""Prose scope reading and clause extraction (task 3.3, corrected per E1/E4/E5).

Reading layer (``read_prose_scope``, the orchestration entry):
- Unit text comes from the ORIGINAL parsed blocks located by the unit's
  blockid — bounded to the unit, not a chunk-content concatenation. Chunk
  links are recorded as supplementary read evidence with doc attribution.
- ``requires_span`` units are only read as a located character span; an
  unlocatable sub-request yields partial with fail_stage=unresolved_span
  (the 273-chunk reference span is never a sub-clause answer).
- The budget constrains BOTH member count and assembled characters during
  assembly, not after unbounded loading.
- A unit with no readable source is NOT counted as processed; coverage is
  complete only when every member contributed its bounded text.
- Snapshot/identity checks wrap the whole read (before AND after), and the
  requested catalog snapshot must be the active one (E5).

Extraction layer: chunk-truncated duplicates keep the LONGEST body; every
citation carries workspace/doc_id/snapshot/unit_id/locator/char span and a
verbatim quote verified against the bound unit text.

I1 (improvement-1, corrected per r1 review F1-F3 and r2 review F3-a): clause
bodies end at the EARLIEST of next clause head or an independent structure
start. An independent structure is NOT every line-start table: a
<table>/<table-unit> whose current clause intro attributes it (the
announcing line ends with a colon AND names a 表/图 object — "本条限值如下，
表内规定属于本条："; the announcement is looked up THROUGH the table's own
title lines, so an intervening "表 1"/"## 表 1 限值" caption can never reset a
proven attribution, while the walk stops at any other line so attribution
never crosses into the next independent clause)
stays inside the clause body, so its rows and the prose after it are never
silently dropped; a colon-announced boundary WITHOUT such an object
reference is genuinely undeterminable — the cut is reported as an ambiguity
note so the caller surfaces partial + warning instead of claiming complete
over truncated requirements. Cross-unit assembly uses the PROTOCOL
separator ``ASSEMBLY_SEPARATOR`` ("\\n\\n"): verifiers reconstruct ONLY with
it — the citation's declared ``assembly_separator`` is validated against the
protocol, never trusted as the reconstruction rule — so a fabricated
separator can never manufacture source text, and a non-string separator
refuses instead of crashing. Numeric-span items declare themselves by the
PRESENCE of ``char_start``/``char_end``: a malformed declaration (null,
string, bool, float, missing one side) REFUSES instead of silently
downgrading to the quote-only path. The quote-only model path (no numeric
keys at all) and the C1 verbatim contract are unchanged.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from env_rag_final.audit import identity as sid

from .contract import EnumResult, FailStage

_CLAUSE_HEAD_RE = re.compile(r"^\s*#{0,4}\s*(\d+(?:\.\d+)*)\s*(\S[^\n]*)", re.M)
_NUM_TAIL_RE = re.compile(r"\d")

# F1 (r1 review): THE assembly protocol. read_prose_scope/`_expand_prose` join
# consecutive units with exactly this string, and BOTH verifiers reconstruct
# cross-unit declarations with it. A citation may DECLARE
# ``assembly_separator``; verifiers validate the declaration against this
# protocol and never join raw pieces with the citation's own value — otherwise
# "real pieces + fabricated separator + text built by the fabricated
# separator" would self-certify source the documents never contained.
ASSEMBLY_SEPARATOR = "\n\n"


def _collapse_ws(s: str) -> str:
    """I1: whitespace COLLAPSED to single spaces (word boundaries preserved).

    Used for the full-delivered-text re-read: stripping whitespace entirely
    could make "in coming" equal "incoming" or hide table content shifts, so
    containment checks on whole declarations collapse runs instead of removing
    them."""
    return " ".join((s or "").split())


@dataclass
class UnitText:
    unit_id: str
    text: str  # bounded to this unit (may be a located span)
    chunk_ids: list[str]
    locator: dict
    char_start: int  # offset in the assembled scope text
    char_end: int
    requires_span: bool
    source: str  # parsed_block | chunk_fallback
    span_offset_in_unit: int = 0  # R3: where a located span starts in the raw unit
    # I1 (improvement-1): catalog structural kind ('block' | 'table').
    # Table-kind units are HARD clause boundaries — an independent table that
    # merely shares the section scope must never be swallowed into the last
    # clause's body. Default keeps legacy constructors working.
    unit_kind: str = "block"


def locate_first_numbered_clause(text: str) -> tuple[int, int] | None:
    starts = [m.start() for m in re.finditer(r"(?m)^\s*#{0,4}\s*\d+(?:\.\d+)+\s", text)]
    if not starts:
        return None
    start = starts[0]
    nxt = re.compile(r"(?m)^\s*#{0,4}\s*\d+(?:\.\d+)+\s", re.M)
    following = [m.start() for m in nxt.finditer(text) if m.start() > start]
    end = following[0] if following else len(text)
    return start, end


def locate_span(text: str, clause_number: str) -> tuple[int, int] | None:
    pattern = re.compile(rf"(?m)^\s*#{{0,4}}\s*{re.escape(clause_number)}\s")
    starts = [m.start() for m in pattern.finditer(text)]
    if not starts:
        return None
    start = starts[0]
    while start < len(text) and text[start] in " \t\n#":
        start += 1
    nxt = re.compile(r"(?m)^\s*#{0,4}\s*\d+(?:\.\d+)+\s", re.M)
    following = [m.start() for m in nxt.finditer(text) if m.start() > start]
    end = following[0] if following else len(text)
    return start, end


def _unit_text_from_blocks(parsed_dir: Path, unit_id: str) -> str | None:
    blocks_file = sorted(parsed_dir.glob("*.blocks.jsonl"))
    if not blocks_file:
        return None
    for line in blocks_file[0].read_text().splitlines()[1:]:
        b = json.loads(line)
        if b.get("type") == "content" and b.get("blockid") == unit_id:
            return b.get("content") or None
    return None


async def read_prose_scope(
    adapter,
    conn,
    workspace: str,
    doc_id: str,
    catalog_snapshot_id: str,
    scope_id: str | None = None,
    member_unit_ids: list[str] | None = None,
    max_members: int = 200,
    max_chars: int = 400_000,
    parsed_root: Path | None = None,
    requested_clauses: list[str] | None = None,
) -> tuple[list[UnitText], EnumResult]:
    """Orchestration entry: read a scope's units with bounded text (E1/E5/R3).

    ``requested_clauses``: explicit sub-clause targets (e.g. ["7.5"]). A
    requires_span unit is located at the REQUESTED clause inside it; a full
    scope request reads the unit's whole (span-bounded) range, never just the
    first numbered clause. When nothing can be located for the request the
    unit is unresolved — the first clause is never substituted.
    """
    from env_rag_final.catalog.builder import check_stale

    parsed_root = parsed_root or sid.PARSED_ROOT
    query_id = f"prose-{uuid.uuid4().hex[:12]}"

    def _result(**kw) -> EnumResult:
        base = dict(
            query_id=query_id,
            kind="prose",
            workspace=workspace,
            catalog_snapshot_id=catalog_snapshot_id,
            source_snapshot_id=stored_fp,
            scope_ids=[scope_id] if scope_id else list(member_unit_ids or []),
        )
        base.update(kw)
        r = EnumResult(**base)
        return r

    stale_before = await check_stale(conn)
    stored_fp = stale_before.get("stored_fingerprint") or ""
    if stale_before.get("state") != "current":
        return [], _result(
            coverage_status="stale",
            fail_stage=FailStage.STALE,
            warnings=[f"catalog state={stale_before.get('state')}: {stale_before.get('action')}"],
        )
    active_snapshot = stale_before.get("active_snapshot_id")
    if active_snapshot != catalog_snapshot_id:
        return [], _result(
            coverage_status="stale",
            fail_stage=FailStage.SNAPSHOT,
            warnings=[
                f"requested catalog snapshot {catalog_snapshot_id} is not active "
                f"(active={active_snapshot}); refusing old-snapshot read"
            ],
        )

    if member_unit_ids is None:
        if scope_id is None:
            raise ValueError("scope_id or member_unit_ids required")
        rows = await conn.fetch(
            """SELECT su.unit_id FROM env_rag.scope_units su
               WHERE su.workspace=$1 AND su.snapshot_id=$2 AND su.scope_id=$3
               ORDER BY su.seq""",
            workspace,
            catalog_snapshot_id,
            scope_id,
        )
        member_unit_ids = [r["unit_id"] for r in rows]
    total = len(member_unit_ids)
    if total == 0:
        return [], _result(
            coverage_status="ambiguous",
            fail_stage=FailStage.SNAPSHOT,
            warnings=["scope has no member units in the requested catalog snapshot"],
        )

    doc_name = await conn.fetchval(
        "SELECT doc_name FROM env_rag.documents WHERE workspace=$1 AND snapshot_id=$2 AND doc_id=$3",
        workspace,
        catalog_snapshot_id,
        doc_id,
    )
    if doc_name is None:
        return [], _result(
            coverage_status="stale",
            fail_stage=FailStage.SNAPSHOT,
            warnings=[f"doc {doc_id} not found in catalog snapshot {catalog_snapshot_id}"],
        )

    warnings: list[str] = []
    units: list[UnitText] = []
    processed = 0
    assembled_len = 0
    budget_hit = False
    span_unresolved = False
    pdir = sid.PARSED_ROOT / f"{doc_name}.parsed"

    for uid in member_unit_ids:
        if processed >= max_members or assembled_len >= max_chars:
            budget_hit = True
            warnings.append(
                f"budget: members {processed}/{total}, chars {assembled_len}/{max_chars}; "
                f"remaining range starts at {member_unit_ids[processed] if processed < total else 'n/a'}"
            )
            break
        urow = await conn.fetchrow(
            """SELECT unit_id, unit_kind, heading, requires_span, content_length, locator
               FROM env_rag.source_units
               WHERE workspace=$1 AND snapshot_id=$2 AND doc_id=$3 AND unit_id=$4""",
            workspace,
            catalog_snapshot_id,
            doc_id,
            uid,
        )
        if urow is None:
            warnings.append(f"unit {uid} missing from catalog snapshot; NOT counted as processed")
            continue
        loc = urow["locator"]
        loc = json.loads(loc) if isinstance(loc, str) else (loc or {})

        text = _unit_text_from_blocks(pdir, uid)
        source = "parsed_block"
        chunk_ids: list[str] = []
        if text is None:
            links = await conn.fetch(
                """SELECT chunk_id, chunk_order FROM env_rag.unit_chunk_links
                   WHERE workspace=$1 AND snapshot_id=$2 AND doc_id=$3 AND unit_id=$4
                   ORDER BY chunk_order""",
                workspace,
                catalog_snapshot_id,
                doc_id,
                uid,
            )
            chunk_ids = [lk["chunk_id"] for lk in links]
            parts = []
            for cid in chunk_ids:
                chunk = await adapter.get_chunk(workspace, cid)
                if chunk["full_doc_id"] != doc_id:
                    warnings.append(f"chunk {cid} belongs to another doc; excluded")
                    continue
                parts.append(chunk["content"] or "")
            text = "\n\n".join(parts) or None
            source = "chunk_fallback"

        if not text or not text.strip():
            warnings.append(f"unit {uid} has no readable source text; NOT counted as processed")
            continue

        if urow["requires_span"]:
            span = None
            if requested_clauses:
                # R3: locate the REQUESTED clause(s); never substitute another
                for cl in requested_clauses:
                    s = locate_span(text, cl)
                    if s is not None:
                        span = s
                        break
            else:
                # R3: full-scope request on a requires_span unit. The whole
                # unit is only readable when the block actually contains
                # locatable sub-clauses; with no numbered structure the
                # scope-to-block projection cannot be proven → unresolved.
                if locate_first_numbered_clause(text) is None:
                    span_unresolved = True
                    warnings.append(
                        f"unit {uid} requires span extraction but contains no "
                        "locatable sub-clause structure for the scope request"
                    )
                    continue
                span = (0, len(text))
                warnings.append(
                    f"unit {uid} requires_span read as FULL unit range for a "
                    "scope-level request (sub-clause projection needs "
                    "requested_clauses); coverage claims are scoped to the unit"
                )
            if span is None:
                span_unresolved = True
                warnings.append(
                    f"unit {uid} requires span extraction but none of the requested "
                    "clauses could be located; treated as unresolved (not processed)"
                )
                continue
            # R3: keep the cut offset — assembly coordinates remain unit-
            # relative to the ORIGINAL unit text, not the sliced copy
            unit_span_offset = span[0]
            text = text[span[0] : span[1]]
        else:
            unit_span_offset = 0

        if len(text) > max_chars - assembled_len:
            text = text[: max_chars - assembled_len]
            budget_hit = True
            warnings.append(f"unit {uid} truncated by character budget")

        # chunk evidence with doc attribution
        links = await conn.fetch(
            """SELECT chunk_id FROM env_rag.unit_chunk_links
               WHERE workspace=$1 AND snapshot_id=$2 AND doc_id=$3 AND unit_id=$4
               ORDER BY chunk_order""",
            workspace,
            catalog_snapshot_id,
            doc_id,
            uid,
        )
        chunk_ids = [lk["chunk_id"] for lk in links]

        units.append(
            UnitText(
                unit_id=uid,
                text=text,
                chunk_ids=chunk_ids,
                locator=loc,
                char_start=assembled_len,
                char_end=assembled_len + len(text),
                requires_span=bool(urow["requires_span"]),
                source=source,
                span_offset_in_unit=unit_span_offset,
                # I1: carry the catalog structural kind so the extraction layer
                # can treat table-kind members as hard clause boundaries
                unit_kind=str(urow["unit_kind"] if "unit_kind" in urow.keys() else "block"),
            )
        )
        assembled_len += len(text) + len(ASSEMBLY_SEPARATOR)
        processed += 1

    stale_after = await check_stale(conn)
    if (
        stale_after.get("state") != "current"
        or stale_after.get("active_snapshot_id") != catalog_snapshot_id
    ):
        return [], _result(
            coverage_status="stale",
            fail_stage=FailStage.STALE,
            warnings=["catalog/source changed during scope read"],
        )

    # G4: this is the READING layer. Its status is read_status; the ANSWER
    # coverage is decided by the orchestrator after extraction/binding.
    read_status = "complete"
    fail = FailStage.NONE
    if span_unresolved:
        read_status, fail = "partial", FailStage.UNRESOLVED_SPAN
    elif budget_hit:
        read_status, fail = "partial", FailStage.BUDGET
    elif processed < total:
        read_status, fail = "partial", FailStage.MISSING_FRAGMENT
        warnings.append(f"{total - processed} member units unreadable")

    result = _result(
        members_total=total,
        members_processed=processed,
        coverage_status="partial" if read_status != "complete" else "ambiguous",
        warnings=warnings,
        fail_stage=fail,
        read_status=read_status,
    )
    result.validate()
    return units, result


# ---------------------------------------------------------------------------
# extraction layer
# ---------------------------------------------------------------------------

# I1 (improvement-1, corrected per r1 review F3): candidate structure markers
# in the ASSEMBLED text — line-start table HTML, a pure "表 N"/"图 N"/
# "表 N（续）" caption line, a "#"-marked table title, a numbered appendix
# heading. The markers are LINE START only; a clause citing "表1"
# mid-sentence ("执行表1的规定") is untouched. A marker is an INDEPENDENT
# boundary only with attribution evidence — see structural_boundaries.
_TABLE_HTML_START = re.compile(r"(?m)^[ \t]*<table[\s>]")
_PURE_TABLE_CAPTION = re.compile(
    r"(?m)^[ \t]*(?:#{1,4}[ \t]*)?(?:附\s?表|[表图])[ \t]*[0-9０-９]+(?:[（(]\s*续\s*[）)])?[ \t]*$"
)
_TABLE_TITLE_HEAD = re.compile(r"(?m)^[ \t]*#{1,4}[ \t]*(?:附\s?表|[表图])[ \t]*[0-9０-９]")
_APPENDIX_HEAD = re.compile(r"(?m)^[ \t]*#{1,4}[ \t]*附\s?录[ \t]*[0-9A-Z]")


# A table-title line (F3-a, review r2): "表 1", "表 1（续）", "## 表 1 限值",
# "附图 2…". The title and its HTML body are ONE table object, so the
# object's attribution is judged on the line BEFORE the title — a caption
# can never reset a proven attribution.
_TABLE_HEAD_FORM = re.compile(r"^[ \t]*#{0,4}[ \t]*(?:附\s?表|[表图])[ \t]*[0-9０-９]")


def _intro_line_before(text: str, upto: int) -> str:
    """The announcing prose line for a structure marker at ``upto``.

    Walks back over blank lines AND the table's own title lines — for a
    "见下表：" → "表 1" → "<table …>" chain the marker's intro is the colon
    sentence, so title and body stay attributed together. The walk is
    BOUNDED: it stops at the first other line (clause sentence, clause head,
    a previous table's closing row, page header, caption subtitle…), so an
    attributed intro never propagates past one object's own title run into
    the next independent clause or a later unrelated table.
    """
    pos = upto
    while pos > 0:
        j = text.rfind("\n", 0, pos)
        seg = text[j + 1 : pos] if j >= 0 else text[:pos]
        s = seg.strip()
        if not s or _TABLE_HEAD_FORM.match(s):
            pos = j if j >= 0 else 0
            continue
        return s
    return ""


def _structure_intro(line: str) -> str:
    """Attribution state of the clause text BEFORE a structure marker.

    'attributed'  — the clause announces an object AND names it a 表/图
      ("…本条限值如下，表内规定属于本条："): the structure belongs to THIS
      clause, so it is not an independent boundary.
    'ambiguous'   — a colon intro announces something without naming a 表/图
      object ("…本条限值如下："): whether what follows belongs to the clause
      cannot be decided from the source.
    'independent' — otherwise (preceding prose ends with a sentence mark, a
      page header, or nothing): an independent structure boundary.

    The sentence-mark end is what keeps confirmed real cases stable:
    GB 3095 4.2 "…质量要求见表 1和表 2。" references tables but ENDS its own
    sentence — its tables are separate catalog objects and stay out; the
    embedded-table case above uses the colon announcement and stays in.
    """
    if not line.endswith(("：", ":")):
        return "independent"
    return "attributed" if ("表" in line or "图" in line) else "ambiguous"


def structural_boundaries(units: list, text: str) -> tuple[list[int], list[dict]]:
    """(cut offsets, ambiguity notes) over the ASSEMBLED text.

    Candidates are table-kind catalog units (their unit start) and the
    line-start markers above. Every candidate is judged by its announcing
    clause text — walking through the table object's own title lines, never
    reset by a caption between intro and body (F3-a): attributed structures
    are NOT cuts (the clause body keeps running — through the table and its
    following prose — until the next clause head), independent ones cut
    cleanly, and an announced-but-undecidable colon intro cuts WHILE
    RECORDING an ambiguity note so the caller surfaces partial + warning
    instead of claiming complete over a possibly truncated requirement.
    Nothing is keyed to a question number, doc id or fixed length.
    """
    ordered = sorted(units, key=lambda u: int(u.char_start))
    candidates = {int(u.char_start) for u in ordered if getattr(u, "unit_kind", "block") == "table"}
    for rx in (_TABLE_HTML_START, _PURE_TABLE_CAPTION, _TABLE_TITLE_HEAD, _APPENDIX_HEAD):
        candidates.update(m.start() for m in rx.finditer(text))

    cuts: set[int] = set()
    notes: list[dict] = []
    for c in sorted(candidates):
        intro = _structure_intro(_intro_line_before(text, c))
        if intro == "attributed":
            continue
        cuts.add(c)
        if intro == "ambiguous":
            notes.append(
                {
                    "pos": c,
                    "detail": (
                        f"structure boundary at offset {c} was announced by a colon intro "
                        "without an explicit 表/图 object reference — whether the structure "
                        "belongs to the clause cannot be determined from the source; the "
                        "clause body is cut at the boundary and coverage must stay partial"
                    ),
                }
            )
    return sorted(cuts), notes


def structural_cut_positions(units: list, text: str) -> list[int]:
    """Back-compatible wrapper: the independent-boundary offsets only."""
    return structural_boundaries(units, text)[0]


def extract_clauses_regex(
    text: str, wanted: list[str] | None = None, hard_ends: list[int] | None = None
) -> list[dict]:
    """Deterministic clause extraction; chunk-truncated duplicates keep the
    LONGEST body (the second fragment often carries the lost tail).

    I1: ``hard_ends`` are assembly offsets of independent structures (tables,
    captions, appendices, table-kind units). A clause body ends at the EARLIEST
    of the next clause head, the next hard boundary after its start, or the end
    of the assembled text — the last clause is no longer 'everything to EOF'.
    """
    spans = [(m.start(), m.group(1)) for m in _CLAUSE_HEAD_RE.finditer(text)]
    cuts = sorted(hard_ends or [])
    best: dict[str, dict] = {}
    for i, (start, num) in enumerate(spans):
        end = spans[i + 1][0] if i + 1 < len(spans) else len(text)
        for cut in cuts:
            if start < cut < end:
                end = cut
                break
        body = text[start:end].strip()
        if wanted and num not in wanted:
            continue
        if num in best:
            if len(body) > len(best[num]["text"]):
                # R3: the replacement span must agree with its text — update
                # start AND end together
                best[num]["text"] = body
                best[num]["citation"]["char_start"] = start
                best[num]["citation"]["char_end"] = end
                best[num]["citation"]["quote"] = body[:120]
            continue
        best[num] = {
            "clause": num,
            "text": body,
            "citation": {
                "kind": "char_span",
                "char_start": start,
                "char_end": end,
                "quote": body[:120],
            },
            "citation_verified": True,
            "source": "regex_clause_split",
        }
    return [best[k] for k in sorted(best)]


def bind_citations(
    items: list[dict], workspace: str, doc_id: str, snapshot_id: str, units: list
) -> list[dict]:
    """Bind every item's citation to re-readable identity (E4/G1).

    Two paths:
    - Numeric char span (regex extraction): bound to the owning unit, clipped
      to the unit boundary, with the unit-relative coordinate adjusted by the
      unit's span_offset_in_unit (sliced requires_span units). Cross-unit
      spans keep every touched unit as separate evidence and use the unit of
      the largest overlap as the primary owner.
    - Quote-only (model items): the verbatim quote is located INSIDE the raw
      unit text (each unit's own text plus its span_offset_in_unit), giving an
      exact, re-readable unit-relative span. An ambiguous or missing location
      leaves the citation unverified for the orchestrator to degrade — never
      a fabricated coordinate.
    """
    for it in items:
        cit = it.get("citation")
        if not isinstance(cit, dict):
            it["citation"] = cit = {}
        g_start = cit.get("char_start")
        g_end = cit.get("char_end")
        quote = (cit.get("quote") or "").strip()

        if isinstance(g_start, int) and isinstance(g_end, int):
            # clip the span to the assembled units and attribute by overlap
            touches = []  # (overlap, unit, lo_in_unit, hi_in_unit)
            for u in units:
                lo = max(g_start, u.char_start)
                hi = min(g_end, u.char_end)
                if hi > lo:
                    touches.append(
                        (
                            hi - lo,
                            u,
                            lo - u.char_start + u.span_offset_in_unit,
                            hi - u.char_start + u.span_offset_in_unit,
                        )
                    )
            if touches:
                # D1/R5: the ANCHOR unit — the one containing the span's start —
                # is the primary owner. A clause span that runs past its own
                # unit's end (extract_clauses_regex ends the last clause at
                # end-of-text) must NOT be attributed to the following unit
                # just because the leaked tail is longer there.
                touches.sort(
                    key=lambda x: (
                        0 if x[1].char_start <= g_start < x[1].char_end else 1,
                        -x[0],
                    )
                )
                _ov, owner, rel_lo, rel_hi = touches[0]
                # G1: coordinates are relative to the RAW unit text (which starts
                # span_offset_in_unit chars before the sliced copy)
                cit["unit_rel_start"] = max(0, rel_lo)
                cit["unit_rel_end"] = min(rel_hi, owner.span_offset_in_unit + len(owner.text))
                cit["unit_id"] = owner.unit_id
                cit["locator"] = owner.locator
                cit["chunk_ids"] = owner.chunk_ids
                cit["unit_source"] = owner.source
                if len(touches) > 1:
                    # cross-unit claim: keep every touched unit as evidence.
                    # I1 (fix): the segments list is DECLARED IN ASSEMBLED
                    # ORDER (u.char_start), not by per-unit rel_start — those
                    # restart at 0 in each unit and permute legitimate
                    # continuations whose second unit starts at offset 0.
                    # The assembly joins consecutive units with "\n\n", and the
                    # clause body slice contains those separators; the
                    # declared separator lets an independent verifier re-join
                    # the raw pieces and re-read the WHOLE delivered text, not
                    # just the short quote.
                    cit["unit_segments"] = [
                        {"unit_id": u.unit_id, "rel_start": lo, "rel_end": hi}
                        for _o, u, lo, hi in sorted(touches, key=lambda x: x[1].char_start)
                    ]
                    cit["assembly_separator"] = ASSEMBLY_SEPARATOR
            else:
                cit["unit_ids"] = [u.unit_id for u in units]
                cit["unit_chunk_ids"] = {u.unit_id: u.chunk_ids for u in units}
        elif quote:
            # G1 model path: locate the verbatim quote in a raw unit
            hits = []
            for u in units:
                raw = u.text
                pos = raw.find(quote)
                if pos >= 0:
                    hits.append((u, pos, pos + len(quote)))
            if len(hits) == 1:
                owner, pos, end = hits[0]
                cit["unit_id"] = owner.unit_id
                cit["locator"] = owner.locator
                cit["chunk_ids"] = owner.chunk_ids
                cit["unit_source"] = owner.source
                cit["unit_rel_start"] = pos + owner.span_offset_in_unit
                cit["unit_rel_end"] = end + owner.span_offset_in_unit
            elif len(hits) > 1:
                # ambiguous location across units: keep candidates, no verify
                cit["unit_candidates"] = [u.unit_id for u, _p, _e in hits]
                cit["locator_ambiguous"] = True
            else:
                cit["locator_missing"] = True
        if units and "unit_ids" not in cit and "unit_id" not in cit:
            cit["unit_ids"] = [u.unit_id for u in units]
            cit["unit_chunk_ids"] = {u.unit_id: u.chunk_ids for u in units}

        it["citation_verified"] = (
            it.get("citation_verified") is True
            and not cit.get("locator_ambiguous")
            and not cit.get("locator_missing")
        )
        cit.update(
            {
                "workspace": workspace,
                "doc_id": doc_id,
                "snapshot_id": snapshot_id,
            }
        )
    return items


def verify_citations(items: list[dict], text: str, units: list | None = None) -> list[dict]:
    """Re-verify every item's citation (F1): the quote must be supported by the
    DECLARED span, not merely exist somewhere in the assembled text.

    - numeric-span citations with a bound unit: the RAW unit text sliced at
      the declared unit-relative offsets must CONTAIN the whole quote
      (whitespace-normalized) — a position error fails even when the quote
      exists elsewhere in the assembled text;
    - cross-unit segments: every declared segment re-read and the WHOLE text
      re-joined with the PROTOCOL separator — the declared
      ``assembly_separator`` is only validated against the protocol, never
      used as the reconstruction rule; a non-list/non-dict segment shape or a
      mismatching/non-string separator refuses safely;
    - a citation that PRESENCE-declares char_start/char_end is numeric-span
      by contract: malformed coordinates refuse instead of downgrading to the
      quote-only path (F2);
    - quote-only (model) citations — no numeric keys at all — are located by
      verbatim search during binding, so the bound unit span supports the
      quote by construction; the locator flags decide;
    - without units (legacy callers), verification degrades to whole-text
      existence, which can never CREATE a pass — positional checks happen
      wherever the units are available.
    """
    by_id = {u.unit_id: u for u in units or []}

    def _norm(s: str) -> str:
        return re.sub(r"\s+", "", s or "")

    for it in items:
        cit = it.get("citation")
        if not isinstance(cit, dict):
            cit = {}
        qraw = cit.get("quote")
        quote = qraw.strip() if isinstance(qraw, str) else ""
        # G3: whole-text existence is the BASELINE in every branch — a quote
        # that does not exist in the assembled text can never be verified,
        # with or without units (legacy two-argument callers included).
        supported = bool(quote) and _norm(quote) in _norm(text)
        has_bound_unit = cit.get("unit_id") is not None

        # F2 (r1 review): the PRESENCE of char_start/char_end declares the
        # item a numeric-span item. A malformed declaration (null/string/
        # bool/float value or one side missing) REFUSES here — it must never
        # slip into the quote-only path, or a ≤120-char quote would vouch for
        # whatever tail the text field carries.
        declares = "char_start" in cit or "char_end" in cit
        if declares and not (
            "char_start" in cit
            and "char_end" in cit
            and type(cit["char_start"]) is int
            and type(cit["char_end"]) is int
        ):
            supported = False
        if declares and supported and not has_bound_unit and "text" in it:
            # numeric item whose span never bound a unit: the delivered text
            # must still be fully re-readable from the assembled source —
            # the quote alone never backs it. (An item that delivers no text
            # field at all keeps the legacy quote-equals-span shape.)
            full = it.get("text")
            supported = (
                isinstance(full, str)
                and bool(full.strip())
                and _collapse_ws(full) in _collapse_ws(text)
            )

        if supported and has_bound_unit:
            # H2: a declared unit_id MUST resolve in the supplied sources —
            # numeric or quote-only fields do not change this; a bound source
            # missing from the call refuses, never falls back to whole-text.
            owner = by_id.get(cit["unit_id"])
            seg_raw = cit.get("unit_segments")
            # F2: a non-list / non-dict-element segment shape is a corrupted
            # declaration — refuse it safely, never crash out of the chain.
            segments_malformed = bool(seg_raw) and not (
                isinstance(seg_raw, list) and all(isinstance(s, dict) for s in seg_raw)
            )
            if segments_malformed:
                supported = False
            segments = seg_raw if isinstance(seg_raw, list) else []
            if owner is None:
                supported = False
            else:
                # H2/H3/I1: unified interval rule — RAW offsets must be true
                # integers BEFORE any arithmetic (string/null offsets from a
                # malformed model JSON must refuse safely, never raise);
                # then offset-translated 0≤lo<hi≤len. Empty (lo == hi) rejected.
                def _slice(u, rel_lo, rel_hi) -> str | None:
                    if type(rel_lo) is not int or type(rel_hi) is not int:
                        return None  # bool/str/None/float all refuse here
                    off = u.span_offset_in_unit
                    lo, hi = rel_lo - off, rel_hi - off
                    if lo < 0 or hi > len(u.text) or lo >= hi:
                        return None
                    return u.text[lo:hi]

                owner_span = _slice(owner, cit.get("unit_rel_start"), cit.get("unit_rel_end"))
                if owner_span is None:
                    supported = False

                # I1: for a numeric-DECLARED item the whole delivered text —
                # not just the ≤120-char quote — must be re-readable from the
                # declared span (F2: the declaration is keyed on key PRESENCE,
                # already validated above; malformed ones never reach here).
                # Whitespace is COLLAPSED, never stripped wholesale, so
                # word/table boundaries stay observable.
                def _full_backed(recon: str | None) -> bool:
                    if not declares:
                        return True  # genuine quote-only model path is unchanged
                    if "text" not in it:
                        # declared span with NO delivered text (Gate-2 r8
                        # quote-equals-span shape): the quote baseline covers
                        # everything there is to re-read.
                        return True
                    full = it.get("text")
                    if not (isinstance(full, str) and full.strip()):
                        return False  # a delivered text field must be full text
                    return bool(recon) and _collapse_ws(full) in _collapse_ws(recon)

                if segments:
                    # H1: cross-unit claims are validated INDEPENDENTLY of the
                    # owner single-piece check — reconstruct from ALL declared
                    # segments in assembled order; the whole quote must be
                    # covered by the reconstruction (not by any single piece).
                    ids = [seg.get("unit_id") for seg in segments]
                    if len(set(ids)) != len(ids):
                        supported = False  # I1: duplicated unit segments refuse
                    else:
                        seg_parts: list[tuple[int, str]] = []
                        for seg in segments:
                            su = by_id.get(seg.get("unit_id"))
                            if su is None:
                                supported = False
                                break
                            part = _slice(su, seg.get("rel_start"), seg.get("rel_end"))
                            if part is None:
                                supported = False  # includes empty (lo == hi) segments
                                break
                            seg_parts.append((su.char_start, part))
                        if supported and seg_parts:
                            # I1: the DECLARED order is part of the contract —
                            # it must already equal assembled order
                            ordered_units = [
                                u.unit_id
                                for u in sorted(
                                    (by_id[i] for i in ids if i in by_id),
                                    key=lambda u: u.char_start,
                                )
                            ]
                            if ids != ordered_units:
                                supported = False  # I1: permuted declared order refuses
                        if supported and segments:
                            # F1: the declaration is VALIDATED against the
                            # protocol, never used AS the rule — a citation
                            # self-declaring a fabricated separator cannot
                            # manufacture source the documents never contained.
                            # A non-string value simply != the protocol string
                            # and refuses instead of crashing.
                            if (
                                "assembly_separator" in cit
                                and cit["assembly_separator"] != ASSEMBLY_SEPARATOR
                            ):
                                supported = False
                            else:
                                seg_parts.sort(key=lambda x: x[0])  # assembled order
                                recon = ASSEMBLY_SEPARATOR.join(part for _s, part in seg_parts)
                                supported = bool(_norm(recon)) and _norm(quote) in _norm(recon)
                                if supported:
                                    supported = _full_backed(recon)
                elif owner_span is not None:
                    # no segments: the single owner piece must cover the quote
                    supported = _norm(quote) in _norm(owner_span)
                    if supported:
                        supported = _full_backed(owner_span)
        if it.get("citation_verified") is not False:
            it["citation_verified"] = (
                supported and not cit.get("locator_ambiguous") and not cit.get("locator_missing")
            )
    return items


@dataclass
class ModelCallLog:
    model: str
    request_messages: list
    response_text: str
    latency_ms: int
    ok: bool
    error: str = ""


def _model_shape_valid(item) -> bool:
    """E6: every item needs dict shape, text, and a non-empty quote."""
    if not isinstance(item, dict):
        return False
    cit = item.get("citation")
    if not isinstance(cit, dict):
        return False
    quote = (cit.get("quote") or item.get("quote") or "").strip()
    primary = item.get("text") or item.get("clause") or item.get("place") or ""
    return bool(quote) and bool(primary.strip())


async def extract_items_with_model(
    text: str, instruction: str, model_config: dict, validate_quotes: bool = True
) -> tuple[list[dict], list[ModelCallLog], str | None]:
    """Small-range prose extraction via the existing OpenAI-compatible model.

    E6: invalid JSON, non-list shape, invalid item shape, missing/empty
    quotes, fabricated quotes, transport failures all return model_failure:*.
    """
    import httpx

    logs: list[ModelCallLog] = []
    base_url = model_config["LLM_BINDING_HOST"].rstrip("/")
    model = model_config.get("QUERY_LLM_MODEL") or model_config["LLM_MODEL"]
    messages = [
        {
            "role": "system",
            "content": (
                "你是严谨的文本抽取助手。只输出 JSON 数组，每个元素形如 "
                '{"clause": "编号", "text": "条目全文", "citation": {"quote": "支持该条目的逐字原文引句"}}。'
                "quote 必须逐字来自原文且直接支持对应条目。"
            ),
        },
        {"role": "user", "content": f"{instruction}\n\n原文：\n{text}"},
    ]
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                json={"model": model, "messages": messages, "temperature": 0},
                headers={"Authorization": f"Bearer {model_config['LLM_BINDING_API_KEY']}"},
            )
            resp.raise_for_status()
            payload = resp.json()
            content = payload["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001 — logged, never surfaced with DSN
        logs.append(
            ModelCallLog(
                model, messages, "", int((time.monotonic() - t0) * 1000), False, type(exc).__name__
            )
        )
        return [], logs, f"model_failure:{type(exc).__name__}"
    logs.append(ModelCallLog(model, messages, content, int((time.monotonic() - t0) * 1000), True))

    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", cleaned.strip()).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return [], logs, "model_failure:invalid_json"
    if not isinstance(parsed, list):
        return [], logs, "model_failure:invalid_shape"

    bad_shape = sum(1 for it in parsed if not _model_shape_valid(it))
    if bad_shape:
        return parsed, logs, f"model_failure:invalid_item_shape({bad_shape})"

    if validate_quotes:
        unsupported = 0
        for it in parsed:
            quote = (it.get("citation") or {}).get("quote", "").strip()
            # Literal names must occur in full in their quote. Longer text
            # items need a verbatim source match containing the cited excerpt.
            place = (it.get("place") or "").strip()
            primary = (it.get("text") or it.get("clause") or "").strip()
            supported = bool(quote) and quote in text
            if supported and place:
                # G4: an explicitly named place must appear IN FULL in the
                # quote — partial-word overlap never verifies ("门诊停车场"
                # backed by a 门诊、病房 quote stays unverified)
                supported = place in quote
            elif supported and primary and not _quote_supports(primary, quote, text):
                supported = False
            it["citation_verified"] = supported
            if not supported:
                unsupported += 1
        if unsupported:
            return (
                parsed,
                logs,
                f"model_failure:unsupported_or_fabricated_citation({unsupported})",
            )
    return parsed, logs, None


def _quote_supports(primary: str, quote: str, source_text: str | None = None) -> bool:
    """Verify literal extraction; paraphrased claims remain unverified.

    A short item must occur in its quote. A longer verbatim item may use an
    excerpt citation when the full item occurs in the source and the excerpt
    occurs inside that item. Shared words alone never prove support.
    """
    primary_norm = re.sub(r"\s+", "", primary)
    quote_norm = re.sub(r"\s+", "", quote)
    if not primary_norm or not quote_norm:
        return False
    if primary_norm in quote_norm:
        return True
    source_norm = re.sub(r"\s+", "", source_text or "")
    return primary_norm in source_norm and quote_norm in primary_norm
