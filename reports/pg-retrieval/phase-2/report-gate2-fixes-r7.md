> 主agent第八轮复审：原G1–G3反例通过，但合法跨unit、numeric绑定缺源、空segment三个既定边界失败。174既有通过/新3失败，Gate2未通过。当前31题指标和真实引用通过；以gate-2/review-r8/review.md为最新状态，以下提交原文保留。

# Phase 2 Gate 2 第七轮补正报告（G1–G3）

执行日期：2026-10-06。范围：按 `handoff-phase-2-fixes-r7.md` 完善 F1 验证器三处。**停 Gate 2 复审；4.1–4.3、4.5 保持完成；4.4/4.6 留主 agent。**

## 独立反例

- 原 43 项断言：**保持通过**。
- 第七轮 3 项（`tests/test_gate2_review_r7.py`）：**3/3 通过**。
- 完整测试 **174 passed**。

## 三处修复（均在 `verify_citations`）

1. **G1 完整 quote**：删除"前 60 字前缀放行"。绑定 unit 的数值引用要求**完整 quote（空白归一化）被声明跨度包含**；跨单元引用按原始 assembled 顺序重建全部有效 segment 切片，重建结果必须包含完整 quote——任一 segment 缺失/空切片/重建不含全 quote 即失败。仅主 owner 中的短前缀或片段各自存在于全文都不再通过。
2. **G2 偏移坐标系**：`unit_rel` 是 raw 单元坐标、`UnitText.text` 是裁切后的片段——owner 与 `unit_segments` 切片统一减去 `span_offset_in_unit`，并核验边界（负起点/越界/空区间 → 拒绝）。合法 requires_span 正例（binding 后 raw 回读等于 quote）verified=True，错误跨度被拒。
3. **G3 旧接口安全退化**：无 units 的两参数调用恢复**完整 quote 全文存在性**检查（`停车场` vs `门诊、病房` 被拒）；全文存在性是所有分支的基线。绑定了 unit 但来源不可用时**拒绝**（不再凭非空 quote 通过）；`citation_verified=False` 不升级、locator_missing/ambiguous 拒绝保持。

## 复跑

- 审核副本（`review-r5/gold-approved.json`，SHA 未改）31 题 benchmark（`bench-r7.json`）：evidence recall **56/59 = 0.949**、file doc recall **1.0**；集合 file **6/6**、prose **5/6**、table **5/6** EXACT（分母各 6，prose-005/table-003 保留）。
- **位置级正文引用回读 60/60**；8 项真实入口反例 8/8。
- 174 项测试、Ruff check/format、OpenSpec strict、`git diff --check` 全过；public 八表冻结计数不变、catalog/search active 未变；仅改验证器实现，未重建索引、未调用模型。
