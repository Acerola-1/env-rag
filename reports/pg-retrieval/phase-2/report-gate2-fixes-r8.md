> 主agent第九轮复审：H1/H2/空segment原反例已通过，仅非整数偏移类型检查在减法之后的问题残留；177既有通过、新1模型JSON/bind/verify模拟链路反例失败。Gate2未通过，固定31题指标与实际引用仍通过；以gate-2/review-r9/review.md为最新状态，以下汇报原文保留。

# Phase 2 Gate 2 第八轮补正报告（H1–H3）

执行日期：2026-10-06。范围：按 `handoff-phase-2-fixes-r8.md` 修正 `verify_citations` 的三个边界条件。**停 Gate 2 复审；4.1–4.3、4.5 保持完成；4.4/4.6 留主 agent。**

## 独立反例

- 原 46 项断言：**保持通过**。
- 第八轮 3 项（`tests/test_gate2_review_r8.py`）：**3/3 通过**。
- 完整测试 **177 passed**。

## 三处修复（verify_citations 判断顺序与条件）

1. **H1 结构有效与 quote 覆盖分离**：先统一验证来源可用性与每片区间有效（owner 与全部 segments）；存在 segments 时**独立**按 assembled 顺序重建并判断完整 quote 覆盖——不再以"主 owner 单片包含完整 quote"为前置条件（跨单元引句的主 owner 本来就不含全 quote，旧短路使其永远失败）。无 segments 时才做 owner 单片覆盖判断。两条路径使用独立变量，不复用已 False 的单片标志。
2. **H2 来源缺失统一拒绝**：声明了 `unit_id` 的引用**无条件**先查 by_id——缺源即 False/partial，无论 numeric 字段是否齐全、quote 是否恰好在全文中；未绑定 unit 的裸旧接口保持全文存在性兼容。
3. **H3 空区间拒绝**：owner 与 segments 共用同一 `_slice` 边界规则——offset 换算后 `0≤lo<hi≤len(text)`，`lo==hi` 的空 segment 被拒绝，不会在拼接时被静默忽略；非整数偏移同样拒绝。

## 复跑

- 审核副本（`review-r5/gold-approved.json`，SHA 未改）31 题 benchmark（`bench-r8.json`）：evidence recall **56/59 = 0.949**、file doc recall **1.0**；集合 file **6/6**、prose **5/6**、table **5/6** EXACT（分母各 6，prose-005/table-003 保留）。
- **位置级正文引用回读 60/60**；8 项真实入口反例 8/8（neg-001/003/006/006b/010/011/012/013）。
- 177 项测试、Ruff check/format、OpenSpec strict、`git diff --check` 全过；public 八表冻结计数不变、catalog/search active 未变；仅改验证器条件，未重建索引、未调用模型。
