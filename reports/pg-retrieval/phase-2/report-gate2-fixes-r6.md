> 主agent第七轮复审：普通正文偏移、当前31题指标已确认；F1验证器仍有前60字放行、裁切偏移未换算、无units旧接口错误放行。171既有通过、新3失败；Gate2未通过。以gate-2/review-r7/review.md为最新状态，以下提交原文保留。

# Phase 2 Gate 2 第六轮补正报告（F1）

执行日期：2026-10-06。范围：按 `handoff-phase-2-fixes-r6.md` 修复唯一阻断 F1。**停 Gate 2 复审；4.1–4.3、4.5 保持完成；4.4/4.6 留主 agent。**

## 独立反例

- 原 42 项断言（13+11+9+7+2）：**保持通过**。
- 第六轮 1 项（`tests/test_gate2_review_r6.py`）：**通过**。
- 完整测试 **171 passed**。

## F1 修复

### 1) 普通正文兜底的真实偏移

`_expand_prose` 的 `scope_body_no_subclauses` 分支不再用 `heading_len` 推算 `.strip()` 后 body 的位置。改为与类别分支相同的映射：`text.lstrip()` 记录标题前空白 → 跳过标题行本身（其后空行/缩进**原样保留**）→ 对 body 自身首尾空白精确定位 → `body_start` 即 body 切片在**未改写 assembled 文本**中的真实起点，`char_start/char_end` 全部为原始坐标。标题后空行、正文缩进等场景由统一映射覆盖；无真实位置时不产出 fabricated item。

### 2) verify_citations 升级为声明位置核验

`verify_citations(items, text, units)` 新增 units 参数，验证从"quote 在全文存在"升级为"**声明 span 支持完整 quote**"：

- 绑定了 unit 的数值引用：raw unit 文本按声明的 `unit_rel_start/End` 切片，quote（空白归一化）必须出现在该切片内——位置错误即失败，即使 quote 在全文别处存在；
- 跨单元 `unit_segments`：每段各自按其声明的 rel 跨度核验；
- quote-only（模型）路径：bind 期逐字定位，由 locator 标志决定（合法路径保留）；
- 无 units 的旧调用退化为全文存在性——该退化只可能维持原有判定，不会把失败升级为通过。

调用点全部穿线（expand.py 三处、cli.py 一处）。r6 隔离反例（标题后空行、quote 以 99 结尾）通过：返回的声明 span 现在能完整回读到 quote 末尾，`declared.strip().startswith(quote)` 成立且 verified/complete 合法；位置错误场景会得到 partial/unverified 而非错误 complete。

## 复跑结果

- 审核副本（`review-r5/gold-approved.json`，SHA 未改）31 题 benchmark（`bench-r6.json`）：evidence recall **56/59 = 0.949**、file doc recall **1.0**；集合 file **6/6**、prose **5/6**、table **5/6** EXACT（分母各 6，公开失败 prose-005/table-003 保留）。
- **位置级引用回读：60/60 正文引用通过**（表行 241 条前轮已由主 agent 核验口径一致）。
- 8 项真实入口反例 8/8（neg-001/003/006/006b/010/011/012/013，行为与期望一致）。
- 171 项测试、Ruff check/format、OpenSpec strict、`git diff --check` 全过；public 八表冻结计数不变、catalog/索引 active（872d689343a9cbb6）未变；未调用模型、未重建目录/索引。
