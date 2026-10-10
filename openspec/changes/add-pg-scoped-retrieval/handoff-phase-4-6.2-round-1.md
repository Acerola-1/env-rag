# 6.2 第一轮完整固定基线执行交接（主agent，2026-10-08）

工程试点A/B通过，6.1/Gate3保持。主agent取舍：**当前提示/合同/DeepSeek模型保留，model_failure作为真实质量失败；PG累计信封继续1024**。不得现场调整提示、放宽验证、改变范围或用多次采样挑选合格答案。本轮不是继续9腿试跑，用户将本交接交给执行agent后按以下第一轮预算运行；第二轮仍停主agent检查点后另行安排。

## 冻结与分母

固定gold：`reports/pg-retrieval/gate-2/review-r5/gold-approved.json`，SHA `1bf130077c21583a89c5ca14695694d9552c558a7d8dc5d45ff0d9f72cfd7a5e`。全部41题×pg/local/fusion，共123腿，不带query-id筛选。31正例93腿（fact7/file6/prose6/table6/synthesis6，每类每路径均保留分母）；10反例30腿单列。ambiguous/partial/model_failure/budget_failure不删行，不能用expected_status预先控制路由。

当前配置锚 `phase4-deepseek-restored-pilot-r1`、源码/提示/词表/embedding/rerank/上下文/候选预算/来源/workspace原样保持。答案与关键词DeepSeek，temperature0，答案单入口最多1次。新一轮预算文件仅提高整批规模，模型/源码/金标不变；入口实际身份只采集校验，不回写expected。输入各路独立、版本来源不混入、typed targets保真；pg/local精排策略为absent，fusion联合一次精排，结论限定为系统对照。

这里的local基线是“发布包local候选链路 + 本项目统一答案合同”，不是发布包原生回答接口的能力测量。冻结锚中的旧9腿review_disposition保留当时历史，不覆写导致旧manifest失配；用户本次下发的新交接决定这一轮执行范围，模型/代码/来源等冻结内容照旧。

## 第一轮调用护栏

预算文件：`reports/pg-retrieval/phase-4/round-1-budget.json`。已通过dry-run，123矩阵与派生上限见 `reports/pg-retrieval/phase-4-pilot-r2-review/round-1-dry-run/`。

| 服务 | 本轮总上限 |
|---|---:|
| keyword LLM | 82 |
| embedding | 328批（每批≤32文本/64000字符） |
| Qdrant计量查询/读取 | 656 |
| Neo4j计量读取 | 820 |
| PG计量读取 | 125952（每腿累计≤1024，既有双计与排除口径保持） |
| 联合精排 | 41 |
| 答案LLM | 21（31正例的6个synthesis×3路≤18；反例按真实类别另≤3） |

上限不代表实际必发次数或账单金额；reserved、issued、unknown、失败/skip分别记录。反例预置的小预算覆盖仍保留：若在PG守卫即预算拒绝，如实记录实际阶段，不能说未执行的成员/字符预算路径已获生产验证。neg-002仅记录观测隔离，不冒充same-id对抗实弹。

## 执行一次即停

先核对配置锚、已接受源码/gold SHA与新目录未占用，然后执行：

```sh
.venv/bin/env-rag-final eval-run --round 1 --paths pg,local,fusion --allow-model --budgets reports/pg-retrieval/phase-4/round-1-budget.json --report-dir reports/pg-retrieval/phase-4-round-1
```

本轮每腿自己新发现/回读/精排/装配/冷生成；不要复用pilot-r2或HY3旧答案，也不拿试点两次200补计本轮合成成功。单题失败按现行入口隔离并保留，其它已安排腿继续；运行级身份漂移按守卫拒绝并落终态。不得追加预算、编排/手工重试、健康探测、第二轮、mix、RAGAS/评审模型调用、写库/初始化/重建/改.env/源码/冻结/gold。完成或运行级拒绝即交主agent复审。

## 结果解释与交付

给出123腿完整逐题表与各题类/路径的分母、发现数/召回证据、范围选择/覆盖、已交付集合/漏项/多项、citation/版本混入、降级/失败/skip及服务耗时；分阶段p50/p95带实际样本数。所有原始runtime/inputs/rerank/answer/context/回执、SHA manifest、前后身份与敏感值扫描保留，旧试点不改。

评分仅离线使用本轮工件、固定gold与可定位的原始产物，不额外查询或生成答案。若没有已经核验的评分工具，先保留逐题证据与判定说明，完整评分工具另归6.3审查；不得偷偷改eval-run或镜像写断言来制造指标。未经审核项目标unreviewed但保留在分母/待审清单，不发布假精确汇总。

必须区分app coverage和题目正确性：pilot中local/prose-enum-001为complete但17项中13项来自别的标准，集合判失败；syn-004 raw summary媒体映射对而实际交付0项，合成仍失败。表格错值/错名称/缺子行、正文错条款内容与版本/文档错配均不能以数量相等代替正确；quote真实不等于claim被支持。资料性附录不升格规范要求，失败结果不因summary大意对而补分。

第一轮数据用于固定基线诊断，不宣称融合稳定增益；不勾6.2/6.3/Gate4、不改默认路径。提示或范围修复需独立交接与新配置代次，不能在本轮内或计划的两轮固定对照之间混入修复结果。
