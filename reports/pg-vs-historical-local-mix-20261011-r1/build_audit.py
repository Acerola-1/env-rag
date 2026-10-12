"""Offline audit of the fixed historical cases and new PG evidence."""

import hashlib
import json
from pathlib import Path

from lxml import html

ROOT = Path("/Users/acerola/Dev/Python/RAG/env-rag-final")
OLD = ROOT.parent / "LightRAG"
OUT = Path(__file__).parent


def load(p):
    return json.loads(p.read_text())


gold = load(OLD / "runs/eval/frozen/rag_eval_dataset_v2.json")["test_cases"]
by_mode = {}
for mode, stamp in [("local", "000707"), ("mix", "005653")]:
    data = load(OLD / f"runs/ragas/ragas_{mode}_v2fresh_20261004_{stamp}_fixed_patched.json")
    by_mode[mode] = {r["question"]: r for r in data["enum_completeness"]["per_case"]}
matrix = []
for case in gold:
    if case["qtype"] != "enum":
        continue
    entry = {"id": case["id"], "question": case["question"], "ground_truth": case["ground_truth"]}
    for mode in by_mode:
        row = by_mode[mode][case["question"]]
        entry[mode] = {k: row[k] for k in ["n_expected", "n_hit", "missing"]}
    entry["both_under_old_item_name_metric"] = all(
        entry[m]["n_hit"] < entry[m]["n_expected"] for m in by_mode
    )
    entry["review"] = (
        "invalid_reference: expected target values are in PDF Table 3, not Table 2"
        if case["id"] == "enum-15"
        else "mix false negative: 铵离子 NH4+ is equivalent to 铵根 NH4+"
        if case["id"] == "enum-09"
        else "historical item-name metric only; not full exact-set/source/semantic acceptance"
    )
    matrix.append(entry)
(OUT / "historical-enumeration-matrix.json").write_text(
    json.dumps(matrix, ensure_ascii=False, indent=2)
)
parsed = next((OLD / "inputs/__parsed__").glob("air-47*.pdf.parsed/*.tables.json"))
tables = load(parsed)["tables"]
physical = tables["tb-13aaccec179aaa355c8c3d98abd0716e-0004"]
tree = html.fromstring(physical["content"])
source = {
    "pdf": str(
        OLD
        / "inputs/__parsed__/air-47_European-Commission_Directive-2024-2881-Ambient-Air-Quality_2024.pdf"
    ),
    "visually_checked_pdf_pages": [31, 32],
    "physical_table_id": physical["id"],
    "caption": physical["caption"],
    "blockid": physical["blockid"],
    "rows": [
        [" ".join(td.itertext()).strip() for td in tr.xpath("./th|./td")]
        for tr in tree.xpath(".//tr")
    ],
    "expected_target_names": ["Arsenic", "Cadmium", "Nickel", "Benzo(a)pyrene"],
    "verdict": "four target-value indicators exist in Table 3; old question/gold Table 2 reference is incorrect",
}
(OUT / "source-reference-audit.json").write_text(json.dumps(source, ensure_ascii=False, indent=2))
baseline = load(OUT / "historical-shared-failure.json")
assert all(
    hashlib.sha256(Path(p).read_bytes()).hexdigest() == v
    for p, v in baseline["historical_source_sha256"].items()
)
(OUT / "historical-preservation.json").write_text(
    json.dumps(
        {
            "all_historical_inputs_unchanged": True,
            "checked_files": len(baseline["historical_source_sha256"]),
            "source_pdf_sha256": hashlib.sha256(Path(source["pdf"]).read_bytes()).hexdigest(),
        },
        indent=2,
    )
)
