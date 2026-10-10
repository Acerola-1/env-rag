"""Independent raw citation reread of the three formal CLI outputs."""

import json
from pathlib import Path

from env_rag_final.audit.identity import PARSED_ROOT
from env_rag_final.catalog.units import parse_blocks
from env_rag_final.enumerate_.tables import read_html_table

OUT = Path(__file__).parent
gold = json.loads(Path("reports/pg-retrieval/gate-2/review-r5/gold-approved.json").read_text())
docs = {d["doc_id"]: d["doc_name"] for q in gold["questions"] for d in q["target_docs"]}
cache = {}
checks = []
for run in json.loads((OUT / "cli-runs.json").read_text()):
    stdout = run["stdout"]
    result, _ = json.JSONDecoder().raw_decode(stdout[stdout.index("{") :])
    expansions = (
        [result]
        if run["name"] == "prose-direct"
        else [e for s in result["trace"] for e in s.get("expansions", [])]
    )
    for expansion in expansions:
        for item in expansion.get("items", []):
            cit = item["citation"]
            doc_id = cit["doc_id"]
            if doc_id not in cache:
                pdir = PARSED_ROOT / (docs[doc_id] + ".parsed")
                _, blocks = parse_blocks(pdir)
                tables = json.loads(next(pdir.glob("*.tables.json")).read_text())["tables"]
                cache[doc_id] = ({b["blockid"]: b["content"] for b in blocks}, tables)
            blocks, tables = cache[doc_id]
            if cit["kind"] == "table_row":
                raw = read_html_table(tables[cit["table_id"]]["content"])[cit["row_in_fragment"]]
                passed = raw == item["cells"]
            else:
                raw = blocks[cit["unit_id"]][cit["unit_rel_start"] : cit["unit_rel_end"]]
                passed = raw.lstrip().startswith(cit["quote"].strip())
            assert passed, (run["name"], cit)
            checks.append(
                {
                    "run": run["name"],
                    "kind": cit["kind"],
                    "citation": cit,
                    "raw": raw,
                    "verified_by_source": True,
                }
            )
summary = {
    name: sum(c["run"] == name for c in checks)
    for name in ["category", "table_top1", "prose-direct"]
}
(OUT / "cli-citation-reread.json").write_text(
    json.dumps({"summary": summary, "failed": 0, "checks": checks}, ensure_ascii=False, indent=2)
    + "\n"
)
print(summary)
