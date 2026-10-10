# Phase 2 Gate 2 第二轮补正报告（R1–R7）

主agent第三轮复审（2026-10-06）：原24反例保持通过，152既有测试通过；新增9项验收失败，Gate2未通过。4.1–4.3独立验收通过，4.4–4.6未完成。完整依据见../gate-2/review-r3/review.md；以下保留执行agent提交报告，不能替代主agent结论。

执行日期：2026-10-06。范围：按 `handoff-phase-2-fixes-r2.md` 修复复审 11 项生产入口反例。**停在 Gate 2 复审；4.1–4.5 未勾选，4.6 留主 agent；gold 仍全部 unreviewed，指标未填。**

## 独立反例

- 原 13 项（`tests/test_gate2_acceptance.py`）：**保持通过**（未删改）。
- 新 11 项（`tests/test_gate2_rereview.py`）：**11/11 通过**。
- 新增隔离守卫 5 项（`tests/test_search_guards.py`）：通过。
- 完整测试 **152 passed**（141 + 11）。

## 各项修复

### R1 文档身份条件

`_doc_attribution_route` 只在请求**显式**含"含修改单/修改单/相关文件/整合版/归属文件"时运行，且请求含"自身编号"时强制关闭。归属分支按名称/标题 token 证据匹配（code 或 code-year 词项），不伪造 self_code；版本不符（名称带其它年份）排除。真实 CLI：自身编号查询 → 仅原标准 1 份；第3章查询不再混入修改单/整合版。

### R2 文件集合谓词

`_doc_predicate` 改为**分支集合**：每个 (code, version) 对是一条 AND 限制分支，分支间 OR——两版本不再要求同一行同时两年。空枚举与已解析目标/请求矛盾时报 `ambiguous`（0/0 不称 complete）。含修改单请求由归属分支并入（正式 CLI 3 份：原标准 self_code + water-03/water-10 name/title 归属）。真实 CLI：两 GB3095 版本 2 份、含修改单 3 份、自身编号 1 份、原标准章节只展开原文档。

### R3 请求范围与答案闭环

- `_requested_targets` 支持多目标（`3章`/`第4.3节`/`4.1.1 至 4.1.2` 区间展开/`表1、表2`）；**先剔除编号跨度与字母数字复合词**（PM2.5/GB3095-2012 不再误作条款 2.5/3095）。
- 子条款请求经父 scope + Phase 1 `requested_clauses`/`locate_span` 回读（无需同号独立 scope）；scope 自身号的请求读全 scope、**章标题项被过滤**（第3章 → 恰好 3.1–3.4 四项）。
- 展开异常统一传顶层：无确认范围 → 顶层 `ambiguous`；partial/stale/error 传播（`_propagate_expansion_status`）。
- 真实 CLI：ch3 4 项 complete；4.3 4.3.1–4.3.4 complete；4.1.1–4.1.2 恰 2 项 complete；缺失范围 → ambiguous。

### R4 表格序号辅助化

`enumerate_logical_table` 序号连续性改按 **DISTINCT 标签**判定：多平均时间/排气筒高度导致的重复序号（1,1,2）不再误判缺行；真间隔（1,2,5）仍标记。原始网格坐标、全部成员与缺片检查（unreadable fragment、逻辑表链接状态）保持不变。真实复验：GB8978表1 13 项、GB3838表1 24 项、GB18466表2 30 行（含 rowspan 重复序号）均 complete。

### R5 Gold 修正

- `block_of` 跳过目次块（`目 次`/`目次`，含 `#` 前缀）——syn-002 监测目标现指正文 `e0dae0566f…`（6.1 污水取样与监测），syn-004 两范围指 `1be5a154…`/`6291e97f…`（与复审给定一致，非硬编码：由跳目次规则自然解析）。
- table-enum-001 附**全 13 行**期望（seq+cells）；table-enum-004 附**全 24 项**（seq+name）；table-enum-005 附**全行**（row_in_fragment+cells，含预处理标准列与脚注行）。
- **自动验证**：`verify_typed_targets` 对全部 31 题逐一验证 typed 目标存在（block/表）、quote 在目标单元内逐字可回读、目次块即报错——验证失败脚本退出 1。多目标题每目标附独立 quote。

### R6 评测资格与质量合同

- typed key 带 **workspace**；结果 status 必须 ok/missing 才计分（**stale/ambiguous 排除**，不保留候选计满分）；gold `frozen_inputs` 与实际 source/catalog/workspace 逐一比对，不符整轮排除（`frozen_identity_ok`/`identity_note` 记录）。
- 新增 **三类集合 exact-match**：`enum_set_check`（expected_count/produced_count/exact_match/missing/extra/citation_unverified），按 prose/table/file 分类汇总 `enum_set_checks`（问题数/全对数/引用未核验数）——`--expand` 运行时生效。
- 反例走正式入口真实执行 **8 项**（`counterexamples-r2.jsonl`）：neg-001/006/006b/011 missing、neg-003 仅自身编号 1 份、neg-010 归属集 4 候选、neg-012 missing+部分证据、neg-013 顶层 ambiguous。

### R7 同义词与探针

- **OOV 概念带受控同义词时，概念 OR 组先于 core-AND 结果尝试**（`absent_with_syn` 分支）：core 命中不再掩盖该概念的同义路径；日志记录 `oov_concepts_attempted`。
- 探针取消 `[:20]` 截断——**全部 25 例（含 5 例编号相邻）实际经 PG 回验**，逐例结果保存。由此发现并修复真实缺陷：`hj2.2-2018` 等**点号连接的编号**在 PG simple 中是单一 lexeme，短语查询失配——`QueryToken.to_tsquery` 现同时匹配 `(phrase | joined)` 两种形态，25/25 一致（含编号相邻）。

## 机制自检（非 Gate 2 指标）

31 题内存临时 approved 跑正式 bench（不落盘 gold）：file doc recall **1.0**、evidence recall **0.9655**。唯一未满 syn-002（4.1/6.1 chunks 未进 top-20）——链接解析已验证正确（ef6868c7→chunk-001/002、e0dae056→chunk-003），属真实排序未中，按复审意见作为**公开失败题**保留。该数字仍非 Gate 2 指标（gold 未审核）。

## 边界

- syn-002 排序未中是已知公开失败；三类集合完全正确率待 gold 审核冻结后按 `enum_set_checks` 正式计算。
- 原 13 项反例与 Gate 1 已核验结论不受 R4 序号语义影响（GB8978 表1 序号 1–13 连续）。
- 未重建索引（分词/清洗/索引派生未变，to_tsquery 为查询侧）；public/MinerU 只读，未调用模型。
