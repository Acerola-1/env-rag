"""Main-review reference material, separate from the submitted benchmark.

No model calls, source edits, or automatic benchmark approval.
"""

import hashlib
import json
import re
from pathlib import Path

OUT = Path(__file__).parent
raw = json.loads((OUT / "raw-gold-materials.json").read_text())
submitted = json.loads(Path("reports/pg-retrieval/phase-2/gold-candidates.json").read_text())


def table(key, seq, predicate=None):
    tid = next(t for t in raw[key]["tables"] if t.endswith(f"-{seq:04d}"))
    t = raw[key]["tables"][tid]
    return {
        "doc_name": raw[key]["doc_name"],
        "table_id": tid,
        "caption": t["caption"],
        "raw_headers": [r for r in t["grid"] if r and not r[0].isdigit()][:2],
        "rows": [
            {"row_in_fragment": n, "cells": r}
            for n, r in enumerate(t["grid"])
            if predicate is None or predicate(r)
        ],
        "representation": "expanded raw HTML grid cells; not a verbatim prose quote",
    }


def blocks(key, pattern):
    return [
        {"doc_name": raw[key]["doc_name"], "blockid": b["blockid"], "quote": b["content"]}
        for b in raw[key]["blocks"]
        if b.get("blockid")
        and not (b.get("content") or "").startswith("## 目次")
        and re.search(pattern, b.get("content") or "", re.M)
    ]


def data_row(r):
    return bool(r) and r[0].isdigit()


plans = {
    "fact-001": [
        table("gb3095_2012", 1, lambda r: len(r) > 2 and "二氧化硫" in r[1] and r[2] == "年平均")
    ],
    "fact-002": [table("gb8978", 1, lambda r: len(r) > 1 and r[1] == "总汞")],
    "fact-003": blocks("gb18466", r"^3\.2\s"),
    "fact-004": [table("gb3838", 1, lambda r: len(r) > 1 and "化学需氧量" in r[1])],
    "fact-005": [table("gb14554", 1, lambda r: len(r) > 1 and r[1] == "臭气浓度")],
    "fact-006": blocks("gb3095_2012", r"2012-02-29\s*发布"),
    "fact-007": [
        table("gb8978", 7, lambda r: len(r) > 1 and r[1] == "pH"),
        table("gb8978", 3, lambda r: len(r) > 1 and r[1] == "pH"),
    ],
    "prose-enum-001": blocks("gb18466", r"^(?:##\s*)?3(?:\s|\.[1-4]\s)"),
    "prose-enum-002": blocks("gb18466", r"^4\.1\.1\s"),
    "prose-enum-003": blocks("gb8978", r"^##\s*4\.3\s*其他规定"),
    "prose-enum-004": blocks("gb3838", r"^## 3 水域功能"),
    "prose-enum-005": blocks("gb14554", r"^## 4\.1 标准分级"),
    "prose-enum-006": blocks("gb3095_2012", r"^## 4\.2 环境空气功能区质量要求"),
    "table-enum-001": [table("gb8978", seq, data_row) for seq in (1, 2)],
    "table-enum-002": [table("gb3095_2012", 1, data_row)],
    "table-enum-003": [table("gb14554", seq, data_row) for seq in (2, 3, 4)],
    "table-enum-004": [table("gb3838", 1, data_row)],
    "table-enum-005": [table("gb18466", 2, data_row)],
    "table-enum-006": [table("gb3095_2012", 3, data_row)],
    "syn-001": [
        table(key, 1, lambda r: len(r) > 2 and "2.5" in r[1] and r[2] == "年平均")
        for key in ("gb3095_2012", "gb3095_2026")
    ]
    + blocks("gb3095_2026", r"自2031年|2031年1月1日"),
    "syn-002": blocks("gb18466", r"^## (?:4\.1 污水|6\.1 污水)"),
    "syn-003": blocks("gb8978", r"^4\.2\.1\.1\s"),
    "syn-004": blocks("gb3838", r"^## 1 范围") + blocks("gb3095_2012", r"^## 1 适用范围"),
    "syn-005": blocks("gb18466", r"^4\.1\.1\s")
    + [table("gb18466", n, lambda r: False) for n in (1, 2)],
    "syn-006": blocks("gb8978", r"^4\.2\.2\.1\s"),
}
notes = {
    "fact-001": "值与一级/二级表头一致：二级60、一级20 μg/m³。",
    "fact-002": "0.05与总汞数据行一致；单位须同时保留caption。",
    "fact-003": "3.2定义原文可读；expected不能只写“3.2条定义原文”，需绑定完整定义跨度。",
    "fact-004": "提交值错误：III类是20 mg/L，15为I/II类。必须按表头索引，不可硬编码row[3]。",
    "fact-005": "问题未限定新扩改建/现有；二级分别20/30，不能只答20。保留原问题并输出两条件。",
    "fact-006": "发布2012-02-29，实施2016-01-01；两字段依据可确认。",
    "fact-007": "表4 pH一级/二级/三级均6~9；表2同值。题目可用，但两个年限范围须分别引用。",
    "file-enum-001": "两个自身编号GB3095文档（2012/2026）集合正确；须附活动目录逐行身份。",
    "file-enum-002": "2021–2025年报五份集合正确；查询/枚举谓词须保留标题条件。",
    "file-enum-003": "水利部2021–2025公报五份集合正确；目录为真源，parsed目录仅交叉核对。",
    "file-enum-004": "名称含修改单七份集合正确；名称谓词不能替代为主题相关性。",
    "file-enum-005": "仅列原标准不满足“含修改单”。修改单封面明确GB18466—2005；含修改单整合版本也须记录身份/归属依据，再冻结相关集合。不得把引用编号当自身编号。",
    "file-enum-006": "GB3838自身编号集合可确认一份；其他文档引用该标准不计入。",
    "prose-enum-001": "四术语正确，但提交quote截在3.2，不能支持3.3/3.4；已附四术语的各原始块。",
    "prose-enum-002": "4.1.2省略县级/20床条件，不能把无条件简述作为完整gold；应保留两条全文及两排放去向。",
    "prose-enum-003": "原文4.3.1–4.3.4齐全，提交regex未容忍##而产生空quote；已附真实块，排除后接表格。",
    "prose-enum-004": "五类顺序与正文一致，但III类摘要少了越冬场/洄游通道/水产养殖等；类号存在OCR异常，保留原号与审查映射，不能当逐字规范类号。",
    "prose-enum-005": "正文4.1明确一级/二级/三级及对应空气区类别，无须空gap；已附完整条款。",
    "prose-enum-006": "4.2两规定：一类区一级、二类区二级；见表1/2。已有短原文足以形成条款gold，表格应分开作为补充。",
    "table-enum-001": "可形成完整13行gold；共5数据行的提交quote含表头且非逐字来源。已附两片原始行坐标。",
    "table-enum-002": "六污染物集合正确；同污染物多平均时间去重，行级来源仍保留。",
    "table-enum-003": "三物理片控制项目按名称去重；不得把每种排气筒高度当新污染物项目，已附全部行。",
    "table-enum-004": "题干25项错误：网格25行包含表头，数据序号1–24，实际24项。保留问题版本历史，显式更正题干，不静默筛走。",
    "table-enum-005": "控制项目与预处理列应按多层/合并单元格读，保留脚注及总余氯细分；已附全部原始行。",
    "table-enum-006": "分析方法表污染物名称列去重，可形成项目清单；16网格行不是16污染物。",
    "syn-001": "2012 PM2.5年均一级15/二级35；2026过渡15/30、2031起10/25 μg/m³。必须携带过渡阶段日期条件，不能只给一对新旧值。",
    "syn-002": "4.1执行表与6.1采样点两范围已附；6.1存在重复6.1.2原始编号，不能按编号去重丢独立要求。",
    "syn-003": "第一类车间/车间处理设施口，第二类排污单位口；提交含省略号quote不是逐字引句，已附完整原块。",
    "syn-004": "地表水vs环境空气范围可核定；两原文单独引用，已附材料。",
    "syn-005": "传染病/结核病表1；满足县级或20床条件的综合/其他机构表2，保留条件/排放去向。单句4.1.1不能支持两类完整主张。",
    "syn-006": "前建设表1/2/3，起建设表1/4/5，建设时间以环评批准日期划分；两句均可取原文，不能只引前一版条件。",
}
corrections = {
    "fact-004",
    "fact-005",
    "file-enum-005",
    "prose-enum-002",
    "prose-enum-004",
    "table-enum-004",
    "syn-005",
}
reviews = []
for q in submitted["questions"]:
    qid = q["query_id"]
    material = plans.get(qid, [])
    if q["category"] == "file_enum":
        material = [
            {
                "expected_doc_ids_submitted": q["gold"]["expected_doc_ids"],
                "predicate_submitted": q["gold"]["match_predicate"],
                "note": "Identity and live matched sets require catalog proof; do not infer file availability from parsed-only artifacts",
            }
        ]
    if qid == "file-enum-005":
        material += blocks("modify18466", r"^# 《医疗机构水污染物排放标准》")
    assert material, f"missing material {qid}"
    reviews.append(
        {
            "query_id": qid,
            "category": q["category"],
            "question_submitted": q["question"],
            "reviewer": "main agent",
            "answer_review": "needs_correction" if qid in corrections else "reference_checked",
            "review_note": notes[qid],
            "reference_material": material,
            "submitted_gap": q["gold"].get("gap"),
            "benchmark_ready": False,
            "benchmark_blockers": [
                "No frozen typed target evidence (workspace/doc/unit/chunk/scope + acceptable alternatives)",
                "Search benchmark currently lacks complete expanded item-set and citation comparison",
            ],
            "gold_review_status_for_metrics": "unreviewed",
        }
    )

neg_notes = {
    "neg-001": "缺1996版本确实missing，但多版本题缺其中一版的反例本轮失败，不能据单版正例外推。",
    "neg-002": "需验证本轮search/expand workspace，而非只引用Phase1适配器；文档展开未向enumerator传workspace。",
    "neg-003": "问题“涉及GB3838”含引用文档，期望却仅self_code，问题和期望不一致。显式更正为“自身编号为”，保留原问题检索语义另计。",
    "neg-004": "Gate1表1两片13行，Phase2手动table_number展开也通过；仍需候选自动确认目标范围的证据。",
    "neg-005": "文档身份不同，不同表1不得合并；本轮search展开应各文档独立验证。",
    "neg-006": "带年份单版缺失拒绝；无年份裸编号却回退其他文档，本轮真实复现，需新增反例。",
    "neg-007": "表2歧义保持；应给完整table_id，不用tb-…占位。",
    "neg-008": "已有reader预算反例仅说明读取合同；search展开的状态应传到结果并记录剩余范围。",
    "neg-009": "文件身份未导入与内容不可检索不同：该PDF内容与water44完全相同，内容可通过已入库原件检索；修正期望，不能把去重当内容丢失。",
    "neg-010": "原标准/修改单分开；加入带版本文档展开不扩到其他版本反例，本轮已失败。",
}
negative_reviews = [
    {
        "counter_id": q["counter_id"],
        "question_submitted": q["question"],
        "review_note": neg_notes[q["counter_id"]],
        "review_status": "needs_correction"
        if q["counter_id"] in {"neg-003", "neg-009"}
        else "expectation_checked_runtime_verification_required",
    }
    for q in submitted["counter_examples"]
]
payload = {
    "review_date": "2026-10-05",
    "reviewer": "main agent",
    "submitted_sha256": hashlib.sha256(
        Path("reports/pg-retrieval/phase-2/gold-candidates.json").read_bytes()
    ).hexdigest(),
    "positives_reviewed": len(reviews),
    "counter_examples_reviewed": len(negative_reviews),
    "gate2_metrics_frozen": False,
    "note": "All31 questions and10 negative expectations were examined; references are review material, not an approved evaluation dataset. Preserve submitted artifact and apply explicit revisions before freezing.",
    "questions": reviews,
    "counter_examples": negative_reviews,
}
(OUT / "gold-review.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
print(
    f"reviewed {len(reviews)} positives / {len(negative_reviews)} negatives; no Gate2 metric approved"
)
