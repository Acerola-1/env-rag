"""Independently reread declared raw block coordinates and physical grid rows."""

import json
from pathlib import Path

from env_rag_final.audit.identity import PARSED_ROOT
from env_rag_final.catalog.units import parse_blocks
from env_rag_final.enumerate_.tables import read_html_table

OUT = Path(__file__).parent
GOLD = json.loads(Path("reports/pg-retrieval/gate-2/review-r5/gold-approved.json").read_text())
DOCS = {d["doc_id"]: d["doc_name"] for q in GOLD["questions"] for d in q["target_docs"]}
CACHE = {}


def source(doc_id):
    if doc_id not in CACHE:
        pdir = PARSED_ROOT / (DOCS[doc_id] + ".parsed")
        _, blocks = parse_blocks(pdir)
        tables = json.loads(next(pdir.glob("*.tables.json")).read_text())["tables"]
        CACHE[doc_id] = ({b["blockid"]: b["content"] for b in blocks}, tables)
    return CACHE[doc_id]


checks = []
for line in (OUT / "benchmark-runs.jsonl").read_text().splitlines():
    run = json.loads(line)
    for step in run["trace"]:
        for expansion in step.get("expansions", []):
            for item in expansion.get("items", []):
                cit = item.get("citation") or {}
                if cit.get("kind") not in ("char_span", "table_row"):
                    continue
                blocks, tables = source(cit["doc_id"])
                check = {
                    "query_id": run["gold_query_id"],
                    "kind": cit["kind"],
                    "citation": cit,
                    "claimed_verified": item.get("citation_verified") is True,
                }
                if cit["kind"] == "table_row":
                    grid = read_html_table(tables[cit["table_id"]]["content"])
                    row = cit["row_in_fragment"]
                    raw = grid[row] if 0 <= row < len(grid) else None
                    check.update(
                        raw_row=raw,
                        produced_cells=item.get("cells"),
                        verified_by_source=raw == item.get("cells"),
                    )
                else:
                    raw = blocks.get(cit.get("unit_id"), "")
                    a, b = cit.get("unit_rel_start", -1), cit.get("unit_rel_end", -1)
                    declared = raw[a:b] if 0 <= a <= b <= len(raw) else ""
                    quote = (cit.get("quote") or "").strip()
                    segments = []
                    for seg in cit.get("unit_segments", []):
                        full = blocks.get(seg["unit_id"], "")
                        lo, hi = seg["rel_start"], seg["rel_end"]
                        segments.append(
                            {"unit_id": seg["unit_id"], "bounds_valid": 0 <= lo <= hi <= len(full)}
                        )
                    valid = (
                        bool(quote)
                        and declared.lstrip().startswith(quote)
                        and all(s["bounds_valid"] for s in segments)
                    )
                    check.update(
                        raw_declared_span=declared,
                        raw_unit_length=len(raw),
                        quote_at_declared_start=bool(quote) and declared.lstrip().startswith(quote),
                        segments=segments,
                        verified_by_source=valid,
                    )
                checks.append(check)

summary = {
    kind: {
        "checked": sum(c["kind"] == kind for c in checks),
        "failed": sum(c["kind"] == kind and not c["verified_by_source"] for c in checks),
    }
    for kind in ["char_span", "table_row"]
}
(OUT / "citation-reread.json").write_text(
    json.dumps(
        {
            "source": "current unchanged MinerU blocks/tables",
            "rule": "entire quote must begin at declared raw unit span after whitespace; every segment in bounds; cells equal raw physical grid row",
            "summary": summary,
            "checks": checks,
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n"
)
print(summary)
