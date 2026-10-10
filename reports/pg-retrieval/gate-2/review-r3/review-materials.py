"""Local evidence inspection; no database or model calls."""

import hashlib
import json
from pathlib import Path

BASE = Path("reports/pg-retrieval/gate-2/review-r3")
gold_path = Path("reports/pg-retrieval/phase-2/gold-candidates.json")
gold = json.loads(gold_path.read_text())
raw = json.loads(Path("reports/pg-retrieval/gate-2/raw-gold-materials.json").read_text())
by_name = {v["doc_name"]: v for v in raw.values()}
bench = json.loads((BASE / "benchmark.json").read_text())
rows = {r["query_id"]: r for r in bench["rows"]}
files = json.loads((BASE / "files-and-final-source.json").read_text())
files_by_id = {r["name"]: r for r in files["runs"]}

notes = {
    "fact-001": "二级年平均SO2=60 μg/m³，一级20；按原始表头和平均时间核对。",
    "fact-002": "表1总汞0.05 mg/L；两片全表不替代定位到该物理行。",
    "fact-003": "3.2定义及混合污水条件均在真实正文块内。",
    "fact-004": "III类COD=20 mg/L，列序I/II/III/IV/V已核对。",
    "fact-005": "二级新扩改建20/现有30两个条件均保留。",
    "fact-006": "发布2012-02-29/实施2016-01-01由封面正文核对。",
    "fact-007": "pH两建设时间范围均6~9有原始表格依据；typed组目前仅表4，按前轮意见应补表2的必要目标组。",
    "prose-enum-001": "四个术语依据正确；固定题面3章未被解析，真实运行ambiguous。",
    "prose-enum-002": "县级/20床及排放去向条件在原文；现有打分只比编号，不验证这些必要条件。",
    "prose-enum-003": "4.3.1–4.3.4依据正确；同一请求出现重复展开，末条文本含后续表格。",
    "prose-enum-004": "五类功能依据正确；OCR类号映射需显式保留；真实运行ambiguous。",
    "prose-enum-005": "一级/二级/三级有正文依据；无题面范围号的生产请求仍ambiguous。",
    "prose-enum-006": "4.2质量要求三项有依据；生产输出却是4.3/4.4且complete，不能计对。",
    "table-enum-001": "全13行cells与原始两片grid逐项相等；评分仍只用seq，丢名称和限值。",
    "table-enum-002": "六污染物名字有依据；生产返回14物理行，未投影去重为六项目。",
    "table-enum-003": "九污染物名字有依据；72物理行保守ambiguous应保留为失败，不能缩小分母。",
    "table-enum-004": "24项seq/name与原始表一致；打分只看seq，不核对name。",
    "table-enum-005": "32原始grid行含表头/注释，30数据行对应24控制项目；full-grid材料正确，但不能直接作answer expected_items，需项目/子项/预处理值和注释分开。",
    "table-enum-006": "十污染物名字有依据；生产返回14物理行，评分用序号且拆分含空格的化学式，合同不一致。",
    "syn-001": "两表数值正确；2030末/2031起条件正文在eebc13e2a0348fa67955192750d4e9e6（亦见2026 4.4），当前typed组仅两表，缺必要日期证据组。",
    "syn-002": "监测目标已改为真实e0dae056正文，两个6.1.2独立要求均在支持引句；保留真实排序未中失败。",
    "syn-003": "第一/第二类取样位置正文依据正确；完整目标块存在，引用不得只取无关块头。",
    "syn-004": "两个适用范围已改为正文块；不再指目次，逐字quote回读正确。",
    "syn-005": "4.1.1/4.1.2条件完整；两表caption不是适用条件唯一来源，必须保留正文组。",
    "syn-006": "两建设时间对应表组和批准日期规则有原文依据；日期条件不能省略。",
}
reviews = []
for q in gold["questions"]:
    probes = []
    names = {t["doc_id"]: t["doc_name"] for t in q.get("target_docs", [])}
    for te in q["gold"].get("target_evidence", []):
        uid = te.get("unit_id")
        name = names.get(te["doc_id"])
        doc = by_name.get(name)
        if not uid:
            probes.append({"identity": te, "type": "document", "review": "catalog identity read"})
            continue
        if uid in (doc or {}).get("tables", {}):
            probes.append(
                {
                    "identity": te,
                    "type": "table",
                    "target_exists": True,
                    "raw_grid_rows": len(doc["tables"][uid]["grid"]),
                    "quote_rule": "structured grid cells, not a verbatim prose quotation",
                }
            )
            continue
        b = next((b for b in (doc or {}).get("blocks", []) if b["blockid"] == uid), None)
        quote = te.get("quote") or q["gold"].get("supporting_quote") or ""
        probes.append(
            {
                "identity": te,
                "type": "block",
                "target_exists": b is not None,
                "entire_submitted_quote_is_substring": bool(b and quote and quote in b["content"]),
            }
        )
    runtime = rows[q["query_id"]]
    note = notes.get(q["query_id"])
    if q["category"] == "file_enum":
        fr = files_by_id[q["query_id"]]
        note = "目录完整分页独立重跑，期望doc_id集合与实际完全相等；当前benchmark未调用文件枚举且set_check=null。"
    reviews.append(
        {
            "query_id": q["query_id"],
            "category": q["category"],
            "review_note": note,
            "target_reread": probes,
            "runtime_status_expand": runtime["status"],
            "submitted_set_check": runtime["enum_set_check"],
            "gold_review_status_for_metrics": "unreviewed",
            "reference_review": "checked; does not approve incomplete scoring representation",
            "benchmark_frozen": False,
        }
    )
negative = [
    {
        "counter_id": c["counter_id"],
        "expectation": c["expected_behavior"],
        "review": "expectation retained from previous full review; current status-only logs do not independently prove all source/answer semantics",
    }
    for c in gold["counter_examples"]
]
out = {
    "review_date": "2026-10-06",
    "reviewer": "main agent",
    "submitted_sha256": hashlib.sha256(gold_path.read_bytes()).hexdigest(),
    "questions_reexamined": len(reviews),
    "counter_expectations_reexamined": len(negative),
    "formal_gold_frozen": False,
    "metrics_approved": False,
    "note": "Review opinions only; no approved labels written to submitted gold. Preserve difficult questions and correct projection/scoring before freezing.",
    "questions": reviews,
    "counter_examples": negative,
}
(BASE / "gold-review-v3.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
print("reviewed", len(reviews), len(negative))
