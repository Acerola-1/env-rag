"""Review current candidate answers against preserved unchanged raw sources."""

import hashlib
import json
from pathlib import Path

BASE = Path(__file__).parent
path = Path("reports/pg-retrieval/phase-2/gold-candidates.json")
gold = json.loads(path.read_text())
raw = json.loads(Path("reports/pg-retrieval/gate-2/raw-gold-materials.json").read_text())
by_name = {d["doc_name"]: d for d in raw.values()}
prior = json.loads(Path("reports/pg-retrieval/gate-2/review-r3/gold-review-v3.json").read_text())
prior_notes = {q["query_id"]: q["review_note"] for q in prior["questions"]}
bench = json.loads((BASE / "benchmark.json").read_text())
rows = {r["query_id"]: r for r in bench["rows"]}
notes = {
    "fact-007": "表2 pH真实物理片来源组已补，表4/表2同值6~9有原始网格依据。",
    "prose-enum-001": "3章解析已修复，四术语正确；每条引句身份与原文回读成立。",
    "prose-enum-002": "两条内容gold已包含必要适用条件和排放去向；实测内容满足，保留原始跨度来源。",
    "prose-enum-003": "实际四条可读且引用来源存在，但expected仍仅短关键词/4.3.4编号；反向篡改四条要求仍exact=True。冻结前须完整要求或必要主张合同。",
    "prose-enum-004": "候选已命中文档，但无auto_targets/无scope读取。scope3 confirmed、363字、requires_span=False、读取1/1 complete；不是Phase1大块/保守结构阻断。",
    "prose-enum-005": "无题面范围号，Phase2没有确认scope。scope4.1 confirmed、225字、requires_span=False、读取1/1 complete；需题意定位及一级/二级/三级名称投影。",
    "prose-enum-006": "正文语义不再混到4.3/4.4，但新fallback绕过引用绑定/验证并截400字；唯一条目无workspace/doc/snapshot/unit身份却verified=True，程序exact不能当引用合格。",
    "table-enum-001": "13原始行引用正确，完整cells期望正确；评分器对同名额外错行仍放行，需修复full-row模式额外项判断。",
    "table-enum-002": "六污染物名称期望正确，程序按名称投影可比较14物理行；应分别标原始行数与投影项目数。",
    "table-enum-003": "九污染物期望及72行来源存在；ambiguous保留失败，不强行放宽Phase1结构关系。",
    "table-enum-004": "24个seq/name期望和原始表相符，名称比较已有效。",
    "table-enum-005": "答案材料实际为30数据行/24控制项目，另存表头/脚注上下文；报告称24数据行应更正。预处理浓度/负荷及总余氯条件均留在材料中。",
    "table-enum-006": "十污染物名称期望和原始表相符，14原始方法行按名称投影比对。",
    "syn-001": "两表数值及新增前言日期组均有原文支持；前言未进候选预算为保留的真实召回失败。",
    "syn-002": "真实正文目标和重复6.1.2要求保留，排序失败不改gold。",
    "syn-005": "适用条件正文及两表各自的行quote已分开，当前逐字依据成立。",
}
reviews = []
for q in gold["questions"]:
    doc_names = {t["doc_id"]: t["doc_name"] for t in q.get("target_docs", [])}
    proof = []
    for target in q["gold"].get("target_evidence", []):
        uid = target.get("unit_id")
        if not uid:
            proof.append(
                {
                    "identity": target,
                    "kind": "document",
                    "reference": "catalog matched-set identity",
                }
            )
            continue
        source = by_name[doc_names[target["doc_id"]]]
        quote = target.get("quote") or q["gold"].get("supporting_quote") or ""
        if uid in source["tables"]:
            table = source["tables"][uid]

            def norm(t):
                return " ".join(t.split())

            quoted_columns = len(quote.split("|"))
            grid_lines = {
                norm(" | ".join(r[:quoted_columns]))
                for r in table["grid"]
                if len(r) >= quoted_columns
            }
            proof.append(
                {
                    "identity": target,
                    "kind": "table",
                    "target_exists": True,
                    "quote_is_supported_raw_cells": norm(quote) in grid_lines,
                    "quoted_prefix_columns": quoted_columns,
                }
            )
        else:
            block = next(b for b in source["blocks"] if b["blockid"] == uid)
            proof.append(
                {
                    "identity": target,
                    "kind": "block",
                    "target_exists": True,
                    "entire_quote_is_substring": bool(quote and quote in block["content"]),
                }
            )
    note = notes.get(q["query_id"], prior_notes[q["query_id"]])
    if q["category"] == "file_enum":
        note = "完整枚举入口已进入benchmark，当前集合与期望doc IDs一致；但用于discovery recall的候选仍被完整枚举替换，不能认可recall指标。"
    reviews.append(
        {
            "query_id": q["query_id"],
            "category": q["category"],
            "review_note": note,
            "typed_source_reread": proof,
            "runtime_status": rows[q["query_id"]]["status"],
            "current_program_set_check": rows[q["query_id"]]["enum_set_check"],
            "gold_review_status_for_metrics": "unreviewed",
            "benchmark_frozen": False,
        }
    )
result = {
    "review_date": "2026-10-06",
    "reviewer": "main agent",
    "submitted_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    "positive_questions_reexamined": 31,
    "counter_expectations_reexamined": 10,
    "formal_gold_frozen": False,
    "metrics_approved": False,
    "questions": reviews,
    "counter_examples": prior["counter_examples"],
    "note": "Submitted labels were not changed. Source references checked; incomplete expected requirements/scoring and a real unbound citation still block freezing.",
}
(BASE / "gold-review-v4.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print("reviewed", len(reviews), "negative", len(result["counter_examples"]))
print(
    "reread_errors",
    [
        (q["query_id"], t["kind"])
        for q in reviews
        for t in q["typed_source_reread"]
        if t.get("quote_is_supported_raw_cells") is False
        or t.get("entire_quote_is_substring") is False
    ],
)
