"""Source units and unit↔chunk links (task 2.4).

source_units are raw locators (blocks + physical tables) built from the local
parsed artifacts; unit_chunk_links records the many-to-many mapping to PG
chunks with an explicit match basis:

- ``sidecar_ref``      — the chunk's sidecar.refs contains the block id
- ``inline_table_id``  — the chunk content embeds ``<table id="tb-…-NNNN">``
- ``inferred``         — content overlap only; never auto-upgraded to confirmed

Coverage status: ``full`` (all chunk refs / full block) vs ``partial``. Empty
sidecar chunks yield no links by themselves; the inline table ids remain the
fallback evidence and are recorded as such.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from env_rag_final.audit import identity as sid  # sidecar path resolution from audit

_TABLE_ID_ATTR_RE = re.compile(r"""<table\b[^>]*\bid\s*=\s*["']([^"']+)["']""", re.I)


def extract_table_ids(content: str) -> set[str]:
    """Exact ``<table id="…">`` attribute values found in chunk content.

    A bare mention of an id in prose, or an id that merely shares a prefix
    with a table id, does NOT match — only the full attribute value counts.
    Malformed/split fragments yield no match and stay unlinked (partial by
    absence, never upgraded).
    """
    return set(_TABLE_ID_ATTR_RE.findall(content or ""))


def parse_blocks(parsed_dir: Path) -> tuple[dict, list[dict]]:
    """Return (meta, content_blocks) from a parsed dir's blocks.jsonl."""
    bl = sorted(parsed_dir.glob("*.blocks.jsonl"))
    if not bl:
        raise FileNotFoundError(f"no blocks.jsonl in {parsed_dir}")
    lines = bl[0].read_text().splitlines()
    meta = json.loads(lines[0])
    blocks = [json.loads(line) for line in lines[1:]]
    return meta, [b for b in blocks if b.get("type") == "content"]


def parse_tables(parsed_dir: Path) -> dict[str, dict]:
    """Return table_id → table entry from tables.json (empty when absent)."""
    tj = sorted(parsed_dir.glob("*.tables.json"))
    if not tj:
        return {}
    payload = json.loads(tj[0].read_text())
    return payload.get("tables", {})


def build_units_and_links(
    doc_id: str,
    doc_name: str,
    snapshot_id: str,
    chunk_rows: list,
    parsed_dir: Path,
) -> tuple[list[dict], list[dict]]:
    """Compute units + links for one document.

    ``chunk_rows``: ordered records from lightrag_doc_chunks (id, chunk_order_index,
    sidecar, content). Returns (units, links) as plain dicts ready for insert.
    """
    meta, blocks = parse_blocks(parsed_dir)
    tables = parse_tables(parsed_dir)
    order_by_block = {b["blockid"]: i for i, b in enumerate(blocks)}

    units: list[dict] = []
    links: list[dict] = []

    # --- block units -------------------------------------------------------
    for b in blocks:
        bid = b["blockid"]
        units.append(
            {
                "workspace": "default",
                "doc_id": doc_id,
                "snapshot_id": snapshot_id,
                "unit_id": bid,
                "unit_kind": "block",
                "unit_order": order_by_block.get(bid, 0),
                "heading": b.get("heading"),
                "parent_headings": json.dumps(b.get("parent_headings") or [], ensure_ascii=False),
                "level": b.get("level"),
                "caption": None,
                "table_seq": None,
                "dimension": None,
                "content_length": len(b.get("content") or ""),
                "requires_span": False,
                "locator": json.dumps(
                    {
                        "kind": "block",
                        "blockid": bid,
                        "parsed_dir": parsed_dir.name,
                        "file": "blocks.jsonl",
                    },
                    ensure_ascii=False,
                ),
            }
        )

    # --- table units (physical fragments; logical grouping is a scope) -----
    for tid, te in sorted(tables.items()):
        seq_m = re_last_segment(tid)
        units.append(
            {
                "workspace": "default",
                "doc_id": doc_id,
                "snapshot_id": snapshot_id,
                "unit_id": tid,
                "unit_kind": "table",
                "unit_order": order_by_block.get(te.get("blockid"), 0),
                "heading": te.get("heading"),
                "parent_headings": json.dumps(te.get("parent_headings") or [], ensure_ascii=False),
                "level": None,
                "caption": te.get("caption") or None,
                "table_seq": seq_m,
                "dimension": json.dumps(te.get("dimension"), ensure_ascii=False)
                if te.get("dimension")
                else None,
                "content_length": len(te.get("content") or ""),
                "requires_span": False,
                "locator": json.dumps(
                    {
                        "kind": "table",
                        "table_id": tid,
                        "blockid": te.get("blockid"),
                        "parsed_dir": parsed_dir.name,
                        "file": "tables.json",
                        "self_ref": te.get("self_ref"),
                    },
                    ensure_ascii=False,
                ),
            }
        )
        # table → chunk via actual inline <table id="…"> element attributes
        # (S7: strict match of the full id attribute value, not a substring —
        # prose mentions or prefix-similar ids must not create links).
        for c in chunk_rows:
            if tid in extract_table_ids(c["content"] or ""):
                links.append(_link(doc_id, snapshot_id, tid, c, "inline_table_id", "partial"))

    # --- block → chunk links from sidecar.refs (primary basis) -------------
    for c in chunk_rows:
        sidecar = c["sidecar"]
        if sidecar is None or sidecar == "{}":
            continue  # empty sidecar chunk: no link rows; inline ids handled above
        sc = json.loads(sidecar) if isinstance(sidecar, str) else sidecar
        refs = sc.get("refs") or []
        for ref in refs:
            if ref.get("type") != "block":
                continue  # sidecar only carries block refs in this corpus
            bid = ref["id"]
            if not any(u["unit_id"] == bid for u in units):
                continue  # ref to unknown block: leave unmapped, recorded in build report
            links.append(_link(doc_id, snapshot_id, bid, c, "sidecar_ref", "partial"))

    return units, links


def _link(doc_id, snapshot_id, unit_id, chunk_row, basis, coverage):
    return {
        "workspace": "default",
        "doc_id": doc_id,
        "snapshot_id": snapshot_id,
        "unit_id": unit_id,
        "chunk_id": chunk_row["id"],
        "chunk_order": chunk_row["chunk_order_index"],
        "match_basis": basis,
        "coverage_status": coverage,
    }


def re_last_segment(table_id: str) -> int | None:
    m = re.search(r"-(\d{4})$", table_id)
    return int(m.group(1)) if m else None


def parsed_dir_for(doc_name: str) -> Path:
    """Resolve the parsed dir for a doc via sidecar_location, else name."""
    return sid.PARSED_ROOT / f"{doc_name}.parsed"


def sidecar_dir_for(sidecar_location: str | None, doc_name: str) -> Path | None:
    return parsed_dir_for(doc_name)
