"""Logical-table continuation linking (task 3.1, corrected per Gate 1 E2/E3).

Chapter-scoped grouping: every attribution step binds on
(document, snapshot, chapter scope, table number). A numbered continuation
whose base group does not exist **within its own chapter scope** is never
attached to a previous chapter's table — it stays ambiguous (E2).

Header/data-row recognition (E3) no longer relies on "first cell is a
number": rows carrying name+value pairs (e.g. "pH" | "6~9") are data rows;
an unrecognizable structure marks the table ambiguous.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import html as lxml_html

_CAPTION_BASE_RE = re.compile(r"^表\s*([A-Z]?\d+(?:\.\d+)?)[\s:：]?\s*(.*)$")
_CAPTION_CONT_RE = re.compile(
    r"^(?:表\s*([A-Z]?\d+(?:\.\d+)?)\s*[\(（](完|续)[)）]|续表\s*([A-Z]?\d+(?:\.\d+)?))\s*(.*)$"
)
_CONTINUATION_HINTS = ("(完)", "（完）", "(续)", "（续）", "续表")
_NUM_RE = re.compile(r"^\d+(\.\d+)?$")


def parse_caption(caption: str | None) -> tuple[str | None, str | None, str]:
    """Classify a caption → (number, title, kind ∈ base|continuation|other|empty)."""
    c = (caption or "").strip()
    if not c:
        return None, None, "empty"
    m = _CAPTION_BASE_RE.match(c)
    if m and not any(h in c for h in _CONTINUATION_HINTS):
        return m.group(1), m.group(2).strip() or None, "base"
    if any(h in c for h in _CONTINUATION_HINTS):
        m2 = _CAPTION_CONT_RE.match(c)
        number = (m2.group(1) or m2.group(3)) if m2 else None
        return number, None, "continuation"
    return None, c, "other"


@dataclass
class Fragment:
    table_id: str
    caption: str | None
    order: int
    blockid: str | None
    heading: str | None
    html: str
    table_seq: int | None = None

    @property
    def sort_key(self) -> int:
        return self.order * 1000 + (self.table_seq if self.table_seq is not None else 0)

    def grid(self) -> list[list[str]] | None:
        try:
            return read_html_table(self.html) if self.html else None
        except Exception:
            return None

    def header_signature(self) -> tuple | None:
        grid = self.grid()
        if not grid:
            return None
        return tuple(c.strip() for c in grid[0])


@dataclass
class LogicalTable:
    number: str | None
    title: str | None
    scope_key: str
    fragments: list[Fragment] = field(default_factory=list)
    status: str = "confirmed"  # confirmed | partial | ambiguous

    @property
    def table_id(self) -> str:
        return self.fragments[0].table_id


def link_logical_tables(table_units: list[dict], html_provider=None) -> list[LogicalTable]:
    """Group table fragments into logical tables, chapter-scoped (E2).

    The chapter scope key is the fragment's block-level heading. Numbered
    continuations only join a base with the same number in the SAME scope;
    otherwise they remain ambiguous. Cross-chapter same-number never merges.
    """
    logical: list[LogicalTable] = []
    unresolved: list[Fragment] = []
    deferred_other: list[Fragment] = []
    deferred_continuation: list[Fragment] = []

    for u in sorted(table_units, key=lambda x: x.get("table_seq") or 0):
        loc = u["locator"]
        if isinstance(loc, str):
            import json

            loc = json.loads(loc)
        frag = Fragment(
            table_id=u["unit_id"],
            caption=u.get("caption"),
            order=u["unit_order"],
            blockid=(loc or {}).get("blockid"),
            heading=u.get("heading"),
            html=html_provider(u["unit_id"]) if html_provider else "",
            table_seq=u.get("table_seq"),
        )
        number, title, kind = parse_caption(frag.caption)
        scope = frag.heading or ""

        if kind == "base":
            logical.append(
                LogicalTable(number=number, title=title, scope_key=scope, fragments=[frag])
            )
        elif kind == "empty":
            unresolved.append(frag)
        elif kind == "continuation":
            if number:
                target = next(
                    (
                        lt
                        for lt in reversed(logical)
                        if lt.number == number and lt.scope_key == scope
                    ),
                    None,
                )
            else:
                target = next((lt for lt in reversed(logical) if lt.scope_key == scope), None)
            if target is not None:
                target.fragments.append(frag)
            else:
                deferred_continuation.append(frag)
        else:
            deferred_other.append(frag)

    # ---- pass 2: captionless fragments, header-signature first (E3/E4) ----
    candidate_deferred = list(deferred_continuation)
    for frag in deferred_other:
        sig = frag.header_signature() if html_provider else None
        if sig:
            group_hits = [
                lt
                for lt in logical
                if lt.number is not None
                and lt.scope_key == (frag.heading or "")
                and lt.fragments
                and (
                    lt.fragments[0].header_signature() == sig
                    or lt.fragments[-1].header_signature() == sig
                )
            ]
            deferred_hits = [
                f
                for f in candidate_deferred
                if (f.heading or "") == (frag.heading or "") and f.header_signature() == sig
            ]
            if deferred_hits and (
                not group_hits
                or min(f.sort_key for f in deferred_hits)
                < min(lt.fragments[0].sort_key for lt in group_hits)
            ):
                frag2 = min(deferred_hits, key=lambda f: f.sort_key)
                num, _, _ = parse_caption(frag2.caption or "")
                lt = LogicalTable(
                    number=num,
                    title=None,
                    scope_key=frag.heading or "",
                    fragments=sorted([frag, frag2], key=lambda f: f.sort_key),
                    status="partial",
                )
                logical.append(lt)
                candidate_deferred.remove(frag2)
                deferred_continuation.remove(frag2)
                continue
            if group_hits:
                lt = min(group_hits, key=lambda g: abs(g.fragments[0].sort_key - frag.sort_key))
                if lt.fragments[0].sort_key > frag.sort_key:
                    lt.fragments.insert(0, frag)
                else:
                    lt.fragments.append(frag)
                lt.status = "partial"
                continue
        # no header evidence → conservative ambiguity (E3)
        unresolved.append(frag)

    # ---- pass 3: orphan numbered continuations, still scope-bound (E2) -----
    for frag in sorted(deferred_continuation, key=lambda f: f.sort_key):
        number, _, _ = parse_caption(frag.caption)
        target = next(
            (lt for lt in logical if lt.number == number and lt.scope_key == (frag.heading or "")),
            None,
        )
        if target is not None:
            target.fragments.append(frag)
            target.status = "partial" if target.status == "confirmed" else target.status
        else:
            unresolved.append(frag)

    logical.extend(
        LogicalTable(
            number=None,
            title=f.caption,
            scope_key=f.heading or "",
            fragments=[f],
            status="ambiguous",
        )
        for f in unresolved
    )
    return logical


# ---------------------------------------------------------------------------
# 3.2: header/data-row recognition and grid expansion (E3)
# ---------------------------------------------------------------------------

_FOOTNOTE_RE = re.compile(r"^注\s*[:：]")


def _looks_like_data_row(row: list[str]) -> bool:
    """Data row = leading numeric sequence OR name+value pair (e.g. "pH"|"6~9")."""
    cells = [c.strip() for c in row if c.strip()]
    if not cells:
        return False
    if _NUM_RE.match(cells[0]):
        return True
    if len(cells) >= 2 and re.search(r"\d", "".join(cells[1:3])):
        return True
    return False


def _expand_table(table_el) -> list[list[str]]:
    grid: dict[tuple[int, int], str] = {}
    occupied: set[tuple[int, int]] = set()
    max_col = 0
    for r, tr in enumerate(table_el.xpath(".//tr")):
        c = 0
        for cell in tr.xpath("./td|./th"):
            while (r, c) in occupied:
                c += 1
            span_r = int(cell.get("rowspan", 1) or 1)
            span_c = int(cell.get("colspan", 1) or 1)
            text = " ".join("".join(cell.itertext()).split())
            for dr in range(span_r):
                for dc in range(span_c):
                    grid[(r + dr, c + dc)] = text
                    occupied.add((r + dr, c + dc))
            c += span_c
            max_col = max(max_col, c)
    rows = []
    r = 0
    while any((r, c) in grid for c in range(max_col)):
        rows.append([grid.get((r, c), "") for c in range(max_col)])
        r += 1
    return rows


def read_html_table(html: str) -> list[list[str]]:
    """All expanded rows of one physical table fragment (headers included)."""
    root = lxml_html.fragment_fromstring(html, create_parent="div")
    grids: list[list[str]] = []
    for t in root.xpath(".//table"):
        grids.extend(_expand_table(t))
    return grids


@dataclass
class TableRows:
    header: list[list[str]]
    rows: list[list[str]]
    row_origins: list[tuple[int, int]]  # (fragment_index, row_index_in_fragment_grid)
    footnotes: list[str]
    units: list[str]
    n_fragments: int
    n_fragments_readable: int
    sequence_numbers: list
    sequence_ok: bool | None
    structure_status: str  # confirmed | ambiguous


def enumerate_logical_table(fragments: list[Fragment]) -> TableRows:
    """Enumerate a logical table from Fragment objects (with HTML) in order.

    E3: header/data recognition uses content shape; a fragment yielding no
    data rows counts as unreadable for coverage; when no fragment yields data
    rows the structure is ``ambiguous`` — callers must not emit complete.
    """
    header: list[list[str]] = []
    rows: list[list[str]] = []
    origins: list[tuple[int, int]] = []
    footnotes: list[str] = []
    units: list[str] = []
    readable = 0
    structure_ambiguous = False

    for fi, frag in enumerate(fragments):
        grid = frag.grid()
        if not grid:
            continue
        data_here = [row for row in grid if _looks_like_data_row(row)]
        if not data_here:
            continue  # unreadable/headers-only fragment: not counted as read
        readable += 1
        # R2: header/footnote removal must NOT renumber rows — keep the RAW
        # grid and track the offset where data rows begin.
        data_start = 0
        if fi == 0 and not header:
            h_end = 0
            for row in grid:
                if _looks_like_data_row(row):
                    break
                cells = [c.strip() for c in row if c.strip()]
                if len(cells) == 1:
                    units.append(cells[0])
                h_end += 1
            header = grid[:h_end]
            data_start = h_end
        elif header and grid and grid[0] == (header[0] if header else None):
            # repeated header in continuation: skip its rows, keep raw indices
            data_start = len(header)
        for ri in range(data_start, len(grid)):
            row = grid[ri]
            joined = " ".join(c for c in row if c).strip()
            if _FOOTNOTE_RE.match(joined):
                footnotes.append(joined)
                continue
            if not _looks_like_data_row(row):
                structure_ambiguous = True
                footnotes.append(joined)
                continue
            rows.append(row)
            origins.append((fi, ri))

    seq = [(r[0] or "").strip() if r else "" for r in rows]
    numeric = [s for s in seq if _NUM_RE.match(s or "")]
    sequence_ok = None
    if len(numeric) >= 2:
        # R4: a sequence number labels a POLLUTANT ITEM, not each physical row —
        # multi-row items (平均时间/排气筒高度) legitimately repeat the label.
        # Continuity is therefore judged on DISTINCT labels: [1,1,2] is fine,
        # [1,2,5] still flags a likely missing row. Missing FRAGMENTS remain
        # covered by the unreadable-fragment / logical-linking checks.
        labels = sorted({int(n) for n in numeric})
        sequence_ok = labels == list(range(1, len(labels) + 1))

    return TableRows(
        header=header,
        rows=rows,
        row_origins=origins,
        footnotes=footnotes,
        units=units,
        n_fragments=len(fragments),
        n_fragments_readable=readable,
        sequence_numbers=seq,
        sequence_ok=sequence_ok,
        structure_status="ambiguous" if structure_ambiguous else "confirmed",
    )
