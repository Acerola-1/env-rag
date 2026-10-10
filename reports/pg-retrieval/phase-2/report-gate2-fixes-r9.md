> 主agent最终验收（2026-10-06）：I1通过，Gate2通过，4.1–4.6完成。独立178测试、冻结31题全部门槛、60正文/241表行回读、8负例/25探针/3正式CLI完成；最终结论见phase-2/report.md和gate-2/final-review/review.md。以下补正提交原文保留。

# Phase 2 Gate 2 第九轮补正报告（I1）

执行日期：2026-10-06。范围：按 `handoff-phase-2-fixes-r9.md` 修复唯一阻断 I1。**停 Gate 2 复审；4.1–4.3、4.5 保持完成；4.4/4.6 留主 agent。**

## 独立反例

- 原 49 项断言：**保持通过**。
- 第九轮 1 项（`tests/test_gate2_review_r9.py`，模型 JSON→binding→verify 调用链，字符串/null 两种非整数偏移）：**通过**。
- 完整测试 **178 passed**。

## I1 修复

`verify_citations` 内部共享的 `_slice` 把**原始偏移的整数类型检查移到减法之前**：`type(rel_lo) is not int or type(rel_hi) is not int` 先行判 None（`bool`/`str`/`None`/`float` 全部拒绝，JSON bool 不作为整数坐标），然后才做 `rel - span_offset` 与既有 `0≤lo<hi≤len` 边界判断。owner 与 unit_segments 共用同一 `_slice`，来自畸形模型 JSON 额外 segments 的非整数偏移现在安全拒绝（verify=False → partial），不再抛 TypeError 逃出抽取/引用验证链路。

已验收的分支逻辑（H1 跨单元独立重建、H2 缺源拒绝、H3 空区间拒绝、anchor 优先归属、合法 requires_span/quote-only 路径）未改动。

## 复跑

- 审核副本（`review-r5/gold-approved.json`，SHA 未改）31 题 benchmark（`bench-r9.json`）：evidence recall **56/59 = 0.949**、file doc recall **1.0**；集合 file **6/6**、prose **5/6**、table **5/6** EXACT（分母各 6，prose-005/table-003 保留）。
- **位置级正文引用回读 60/60**；8 项真实入口反例 8/8。
- 178 项测试、Ruff check/format、OpenSpec strict、`git diff --check` 全过；public 八表冻结计数不变、catalog/search active 未变；仅改类型检查顺序，未重建索引、未调用模型。
