"""Read-only offline rollup: r3 adjudication rows + post-change evidence linkage.

Zero network / database / model requests. Inputs are accepted artifacts only:
phase-4-round-1-assessment-r3/adjudication.json (pre-change final verdicts,
123 rows kept key-for-key), the two accepted live batches' leg-verdicts, and
the improvement generations' stored offline replays. No row's pre-change
status is rewritten; post-change evidence is attached as a separate object.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ADJ = ROOT / "reports/pg-retrieval/phase-4-round-1-assessment-r3/adjudication.json"
OUT = Path(__file__).resolve().parent / "remaining-cases.jsonl"

LIVE_PG = "phase-4-improvements123-pg-validation-r1/leg-verdicts.json (accepted live, PG)"
LIVE_LOCAL = (
    "phase-4-improvements123-local-validation-r1/leg-verdicts.json (accepted live, fresh local)"
)

LIVE = {
    ("file-enum-002", "pg"): LIVE_PG,
    ("file-enum-005", "pg"): LIVE_PG,
    ("prose-enum-002", "pg"): LIVE_PG,
    ("prose-enum-003", "pg"): LIVE_PG,
    ("prose-enum-006", "pg"): LIVE_PG,
    ("prose-enum-001", "local"): LIVE_LOCAL,
    ("prose-enum-006", "local"): LIVE_LOCAL,
    ("neg-004", "local"): LIVE_LOCAL,
    ("file-enum-005", "local"): LIVE_LOCAL,
}

IM2 = "phase-4-improvement-2-r2/four-leg-preservation.json (stored inputs, owning offline)"
IM3 = "phase-4-improvement-3-r2/union-reconcile.json + replays (stored inputs, owning offline)"
IM1 = "phase-4-improvement-1-r2/replay-evidence-r2.json stored-trace prose-enum-003 replay"
OFFLINE = {
    ("file-enum-005", "pg"): IM3,
    ("file-enum-005", "local"): IM3,
    ("file-enum-001", "local"): IM3,
    ("file-enum-002", "local"): IM3,
    ("table-enum-001", "local"): IM2,
    ("prose-enum-001", "local"): IM2,
    ("prose-enum-006", "local"): IM2,
    ("neg-004", "local"): IM2,
    ("prose-enum-003", "pg"): IM1,
}

# relevance of accepted code changes to the row's root cause (never a waiver)
RELEVANT = {
    "foreign_doc_rows": "improvement-2 canonical target gate + discovery-only demotion directly address this root cause",
    "no_delivery_coverage_partial": "local scope mixing root cause addressed by im2; PG discovery gap unchanged",
    "coverage_not_complete": "not addressed by im1-3 unless listed in evidence",
    "counter_coverage_not_complete": "not addressed by im1-3",
    "partial_fragment_correct": "neg-004-type merge handled by table fragment assembly (live recheck for local)",
    "pending_behaviour_review": "scorer/behaviour interpretation, not an im1-3 code change",
    "projection_mismatch": "table projection scoring — pipeline unchanged",
    "set_mismatch": "collection scoring — pipeline unchanged",
    "set_violation": "collection scoring — pipeline unchanged",
    "unverified_citation": "citation path unchanged by im1-3",
    "behaviour_violation_merges_or_overclaims": "counter semantics unchanged",
    "pending_fact_carrier_review": "fact carrier review is a gold-side decision; code unchanged",
    "counter_pending_gold_projection": "gold-side projection review pending; code unchanged",
    "pending_status_review": "gold-side status review pending; code unchanged",
    "budget_refused_at_pg_guard_expected": "budget control observation; envelope calibration is post-change config, not code",
    "synthesis_pending_human_review": "answer contract only tightened verbatim/binding; paraphrase still refused",
    "pass_mechanical": None,
    "behaviour_ok_mechanical": None,
}

# Gate-4 mapping: judgement -> (attribution bucket, gate blocked or kept boundary)
ATTR = {
    "foreign_doc_rows": (
        "范围未确认/读不全（外来文档晋升混入）",
        "G4-4 enum 集合完全正确率 / G4-5 违规混入=0",
    ),
    "no_delivery_coverage_partial": (
        "发现缺口或范围未确认（交付为空/部分）",
        "G4-2 范围覆盖 / G4-4 enum",
    ),
    "coverage_not_complete": ("范围未确认/读不全", "G4-2 范围覆盖"),
    "counter_coverage_not_complete": (
        "反例覆盖状态不符期望",
        "G4-2 反例无 false complete/期望落空",
    ),
    "partial_fragment_correct": ("范围未确认/读不全（片段对而整题不全）", "G4-2/G4-4"),
    "pending_behaviour_review": ("行为状态裁决待人工（partial≠ambiguous 类）", "G4-2 反例状态语义"),
    "projection_mismatch": ("交付内容与已绑行投影不符（数值/名称级）", "G4-4 enum 集合完全正确率"),
    "set_mismatch": ("集合完全性不符（漏/多项）", "G4-4 enum"),
    "set_violation": ("集合越界（违规混入）", "G4-4/G4-5"),
    "unverified_citation": ("声明与来源关系不成立（引用未过验证）", "G4-5 引用错误=0"),
    "behaviour_violation_merges_or_overclaims": ("归属/版本错误或过度合并声明", "G4-1/G4-5"),
    "pending_fact_carrier_review": (
        "载体口径待 gold 人工裁决（fact 散文载体）",
        "G4-4 分母口径（可保留公开边界）",
    ),
    "pending_citation_metadata_gap": (
        "引用元数据缺口（归属文档缺 doc_name，证据不全不可判）",
        "G4-5 引用证据缺口（已列 file-004 待审，公开边界）",
    ),
    "counter_pending_gold_projection": ("gold 侧投影人工裁决待定", "分母待审（公开边界）"),
    "pending_status_review": ("gold 侧状态人工裁决待定", "分母待审（公开边界）"),
    "budget_refused_at_pg_guard_expected": (
        "预算控制观测但未完成本题",
        "G4-7 降级报告项（构造信封，不计能力失败）",
    ),
    "synthesis_pending_human_review": (
        "见 synthesis_notes 细分（改述/前置/数值支持）",
        "G4-6 fact/synthesis 不下降",
    ),
    "pass_mechanical": (None, None),
    "behaviour_ok_mechanical": (None, None),
}


def syn_split(model_status, reason):
    reason = str(reason)
    if model_status == "incomplete_conditions":
        return "前置条件不足（版本对/范围条件未解决，HTTP 未发出、0 调用）"
    if "不对题" in reason or "4.1" in reason and "6.1" in reason:
        return "选错题面要求的范围（真实引用≠回答所问；如 syn-003/fusion 交付 4.1 而 gold 问 6.1 采样位置）"
    if "合同全拒" in reason or "0 合格" in reason or "拒收后" in reason:
        return "改述不满足连续逐字合同（HTTP 200 后逐条拒绝、0 交付）"
    if "绑定" in reason and ("缺" in reason or "未" in reason):
        return "部分绑定正确但整题要素不全（数值/单位/对象关系不支持或漏项）"
    return "HTTP 200 后答案拒绝（合同拒绝），与服务失败区分"


rows = json.loads(ADJ.read_text())["rows"]
assert len(rows) == 123, len(rows)
with OUT.open("w", encoding="utf-8") as fh:
    for r in rows:
        line = dict(r)  # original keys & pre-change verdicts kept verbatim
        key = (r["qid"], r["path"])
        ev = []
        if key in LIVE:
            ev.append({"kind": "本路径本题已现场核验", "source": LIVE[key]})
        if key in OFFLINE:
            ev.append({"kind": "只有构造/离线回放证据", "source": OFFLINE[key]})
        if not ev:
            ev.append({"kind": "尚无改后证据", "source": None})
        line["post_change_evidence"] = ev
        j = r["judgement"]
        attr, gate = ATTR.get(j, ("未分类——需人工补录", "待裁决"))
        line["gate4_attribution"] = {
            "bucket": attr,
            "gate_or_boundary": gate,
            "code_relevance": RELEVANT.get(j),
        }
        if r.get("masked_citations"):
            line["gate4_attribution"]["masking_note"] = (
                f"{r['masked_citations']} 个交付单元格被净化掩码——该行还有其它归因，掩码是附加的证据缺口"
                "（G4-5 复核受阻；修掩码须另立评分接口交接，本组不动）"
            )
        if r["category"] == "synthesis" or r["qid"] == "neg-010":
            line["gate4_attribution"]["bucket"] = "合成拒绝细分：" + syn_split(
                r.get("model_status"), r.get("final_reason")
            )
        # 'ok'=120 rows ran the pipeline; 'absent'=3 are neg-008 constructed
        # envelopes stopped at the guard (budget control, NOT a service failure).
        line["gate4_attribution"]["is_real_service_failure"] = r.get("runtime") not in (
            "ok",
            "absent",
        )
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")
print("wrote", OUT.name, "rows:", len(rows))
