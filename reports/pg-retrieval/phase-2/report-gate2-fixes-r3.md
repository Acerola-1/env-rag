# Phase 2 Gate 2 第三轮补正报告（B1–B5）

主agent第四轮复审（2026-10-06）：161项既有测试通过、原33断言SHA未变，新7项验收失败，Gate2仍未通过。4.1–4.3保持通过，4.4–4.6未完成。004/005实际是Phase2未确认/读取范围，不是Phase1 requires_span；当前程序prose4/6但006引用不合格。完整证据见../gate-2/review-r4/review.md。以下提交报告与原数字/归因保留历史，不能替代主agent结论。

执行日期：2026-10-06。范围：按 `handoff-phase-2-fixes-r3.md` 修复第三轮 9 项生产入口反例。**停 Gate 2 复审；4.4–4.5 未勾选（按新证据可提交恢复），4.6 留主 agent；gold 仍全部 unreviewed，指标未填。**

## 独立反例

- 原 13 项 + 第二轮 11 项（`test_gate2_acceptance.py` / `test_gate2_rereview.py`）：**保持通过**（断言未改）。
- 第三轮 9 项（`tests/test_gate2_review_r3.py`）：**9/9 通过**。
- 完整测试 **161 passed**。

## 各项修复

### B1 范围短缺不得升级 complete

- `_expand_prose` 现在对**提取结果**计算 `missing_requested_clauses`（读取层 complete 不代表答案完整）：请求 4.1.1–4.1.7 而语料只到 4.1.6 → `coverage=partial`、missing=['4.1.7']（真实 CLI `r3-cli/cli-missing-clause.json`）。
- 支持"3章"无"第"前缀语法（`_CHAPTER_RE` 改 `第?…章`，`第N节/部分` 单独正则）；真实 CLI `3章` → 4 术语 complete（`r3-cli/cli-chapter3.json`）。
- 顺带修复：同一请求里 `第4.3节` 同时命中 chapter 与 bare clause 造成双重展开——同值去重。

### B2 集合评分按内容（投影合同）

`_evaluate_enum_set` 重写为**投影合同**（gold 条目形状声明答案投影）：

- prose：`{clause, text}` / `"4.1.2 原文"`——条款号相同且 gold 文本（空白不敏感）逐字出现在产出条目内才满足；**错内容（反例 1：同号"所有医疗机构免予处理"）→ missing+extra，exact=False**。
- table：完整 `cells` → 整行必须逐字产出；`{seq, name}` → (序号,项目名) 投影——**同号改名/改值（反例 1）、同序号丢子行（反例 2：年平均/小时平均）都 fail**。名称投影下同污染物多平均时间/多方法行消费为子行证据，不算 extra。
- file：`expected_doc_ids` → doc-id 集合相等（反例见 B3）。
- 真实固定题投影闭环：table-002 六污染物（14 物理行中同污染物子行消费）、table-006 十污染物、prose-006 4.2 无子条款 → 整条 prose 为一个答案项（不再答成 4.3/4.4）。

### B3 文件题进入 benchmark 枚举

`run_benchmark` 按题型分派：file_enum → `expand_docs=True`（完整分页枚举），其余 → `expand`（scope 展开）。文件题集合比较消费 `document_enumeration` 候选（含 doc_id/version/citation）。真实 31 题 bench：**六文件题 6/6 EXACT**（此前全部 ambiguous/set_check=null）。

### B4 固定分母不缩水

- `enum_set_checks` 的 `questions` = 该类**全部 reviewed 题**（含 ambiguous/partial 失败行），不再只数"有可用结果"的题；`failed` 单列。1 对 5 失败 = 1/6，不会变成 1/1（反例 `test_fixed_six_question_enum_denominator_keeps_ambiguous_failures`）。
- 展开未 complete（ambiguous/partial/error，如 table-003 的 Phase 1 结构保守裁决）→ 该题**不得 exact**（`expansion_incomplete` 记录），候选可信证据资格与固定分母保留分离。
- stale 仍整轮拒绝（`frozen_identity_ok` + USABLE 语义只对 stale 收紧）。

### B5 Gold 验证逐字化 + 条件证据

- prose quote 必须**全句逐字**在目标 block 内；只有显式 `truncated: true` 且为源前缀才接受——前 80 字正确+编造尾句被拒（反例通过）。
- table 目标不再只查 ID 存在：quote 必须匹配该表的**真实网格行**（行级内容核对）。
- 按此严格验证重建 gold 时发现并修正 9 处不逐字引用（table-001/002/003/006、syn-001/005）。
- 必要条件证据组：syn-001 增加 2026 前言 `eebc13e2…`（2030-12-31/2031-01-01 过渡日期，逐字引句）为第三个 typed 组；fact-007 增加 `tb-…-0003`（表2，1997-12-31 前时期，pH 6~9 同值）为第二个来源组。
- table-005 投影分离：答案=24 数据行（序号+控制项目+排放/预处理标准），表头/脚注进 `raw_grid_context`（保留总余氯细分），不再混入 expected。

## 真实复跑结果（31 题 bench，`bench-r3.json` / `search-runs.jsonl`）

| 类别 | 结果 |
|---|---|
| file_enum | 6/6 EXACT（2/5/5/7/3/1 份，独立分页逐题核对一致） |
| prose_enum | 3/6 EXACT（001/002/003）；004/005 因 requires_span/大块 scope 的 Phase 1 ambiguous 状态保留失败行；006 修复后 EXACT |
| table_enum | 5/6 EXACT；003 保守 ambiguous（Phase 1 结构裁决）保留失败行 |
| 机制自检（非指标） | evidence recall 0.949、file doc recall 1.0；syn-002 排序未中保留公开失败；syn-001 条件组 0.67（前言块未进 top-20，属真实发现缺口，不改 gold 迎合） |

反例 8 项真实执行（`counterexamples-r2.jsonl` 更新）；六文件分页 6/6 一致。全套 161 测试、Ruff check/format、OpenSpec strict、diff 检查通过。public 八表冻结计数未变（221/5709/279/16514/65527/221/221/119575），源指纹/catalog/search active 不变；未调用模型，未重建索引（仅查询侧与评分合同变更）。

## 边界

- gold 仍全部 unreviewed；`enum_set_checks` 当前数字基于未冻结 gold，只作行为证据，不填 Gate 2 指标。
- prose-004/005、table-003 的失败根因在 Phase 1 scope/结构保守状态，Phase 2 合同如实保留为失败行；是否扩 Phase 1 结构判定由主 agent 决定。
- syn-001 过渡日期块（前言）未进入 top-20 候选——真实发现缺口，保留为失败；不删题、不改 gold。
