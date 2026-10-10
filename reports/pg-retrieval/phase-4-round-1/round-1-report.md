# Phase 4 · 6.2 第一轮完整固定基线执行报告（round-1，2026-10-08）

按 `handoff-phase-4-6.2-round-1.md`：固定 gold（SHA `1bf130077c…` 核验一致）、41 题 × pg/local/fusion = **123 腿，单轮单次执行**，命令逐字一致，预算 `round-1-budget.json`（离线 schema/逐值核对与交接表一致后执行），输出新代次 `phase-4-round-1`（运行前不存在）。CLI exit 0，墙钟约 44 分钟。**未追加重试/预算/健康探测，未启动第二轮；写库 0，生产全只读；提示/合同/模型/锚/源码/冻结/gold 原样，expected 未回写。**

主 agent 裁决已执行：当前提示与合同保留，model_failure 计真实质量失败；PG 信封维持 1024。

## 1. 运行级守卫

- pre/post 身份 `matches_frozen=true`、drift=[]、无 after_error；`finished_at` 存在——无运行级拒绝。
- 配置锚零后端校验先 PASS（代次 `phase4-deepseek-restored-pilot-r1`：模型/端点/维度/prompt SHA/代码锚/参数含 temperature=0/env 守卫逐项）。
- 每腿自身新发现/回读/精排/冷生成；未读取 pilot-r2 或任何旧答案字段。

## 2. 账本（reserved / issued / 上限；预留≠实发）

| 服务 | 预留 | 实发 | 上限 | 判定 |
|---|---:|---:|---:|---|
| keyword LLM | 79 | 79 | 82 | 全部成功，零超限 |
| embedding | 201 批 | 201 | 328 | 全部成功（每批 ≤32 文本/64000 字符） |
| Qdrant 计量 | 201 | 201 | 656 | 全部成功 |
| Neo4j 计量 | 395 | 395 | 820 | 全部成功 |
| PG 计量读取 | 12197 | 12197 | 125952 | 单腿峰值 reserved=issued=176（fusion/syn-004）；1024 信封充裕 |
| 联合精排 | 38 | **38 executed** | 41 | 3 条 fusion 腿未预留：neg-001/neg-006 发现 missing 零候选（无输入可排，如实 skip）、neg-008 死于发现 |
| 答案 LLM | **21（恰触上限）** | **11** | 21 | 11 次真实 HTTP **全部 200**（receipt 无一条服务失败）；10 条预留后 `incomplete_conditions` 未发 HTTP——预留≠实发逐腿分列，未知凭证 0 条 |
| 拒绝事件 | — | — | — | 共 3 条，全部 neg-008 构造微信封（PG 守卫阶段 `readonly_select_chunks`/语句级），`issued=0` |

除 neg-008 三腿外，全部 120 腿逐服务 `issued == reserved`，无任何腿出现 issued≠reserved 的差额。

## 3. 耗时（仅计实际发生阶段，带样本数）

| 阶段 | n | p50 | p95 | max |
|---|---:|---:|---:|---:|
| 发现 discovery_ms | 120 | 2610 | 7930 | 11206 |
| 精排 rerank_ms | 38 | 2235 | 4137 | 4729 |
| 答案 answer_ms | 120 | 1629 | 6721 | 10726 |
| 端到端 total_ms | 120 | 4869 | 12317 | 18459 |

（neg-008 三腿无发现/答案计时——死于预算，如实不计入分布。）

## 4. 应用覆盖分布（app coverage，不等于题目正确性）

123 腿：complete **63** / partial **45** / ambiguous **8** / missing **4** / budget_failure **3**；腿级 hard failure 0。

按题类×路径（正例+反例并入合同类别；括号内为语义待审的 complete 反例）：

| 类别 | pg | local | fusion |
|---|---|---|---|
| fact | complete 6 · missing 2 · partial 2 | partial 10 | complete 6 · missing 2 · partial 2 |
| file_enum | complete 7 · partial 1 | complete 7 · partial 1 | complete 7 · partial 1 |
| prose_enum | complete 5 · partial 1 · BF 1 | complete 3 · partial 3 · BF 1 | complete 5 · partial 1 · BF 1 |
| table_enum | complete 7 · partial 1 · ambiguous 1 | complete 3 · partial 1 · ambiguous 5 | complete 7 · partial 1 · ambiguous 1 |
| synthesis | partial 7 | partial 6 · ambiguous 1 | partial 7 |

完整 123 腿逐题表见 `round-1-table.md`（每格：覆盖/交付项数/HTTP×n/model_status/rerank），逐腿机器可读明细 `round-1-legs.json`。

## 5. 合成基线（质量失败的如实构成，非链路问题）

21 条预留行（18 正例 syn-001..006 × 3 路 + neg-010 × 3 路）：

- **incomplete_conditions（10 行）**：请求版本/上下文在装配前未解析，**0 次 HTTP**——syn-001 三路、syn-006 三路、syn-002/003/004/005 各含 local 路（syn-005 local 例外，见下）、neg-010 local。
- **HTTP 实际发出 11 行，全部 200 成功取回（无一条服务失败）**，随后按合同判定：`model_failure` 10 行 + `incomplete_answer_coverage` 1 行。其中 2 行在逐条复核后保留了通过合同的 claims（syn-002/pg 交付 4 项、syn-003/fusion 交付 5 项，覆盖仍判 partial），其余 9 行 0 项交付；反例 neg-010/fusion 交付 4 项（语义待审）。
- 正例 18 行无一 app-complete：**9 行 HTTP 后拒绝**（7 行 0 交付 + 2 行少量保留）、**9 行 incomplete_conditions 未发出**。**质量失败计入固定基线；不宣称任何合成成功率。**
- 与 pilot 期一致区分：本轮答案通道服务层面 0 失败——**答案质量差距 100% 属输出形态/覆盖与逐字合同的要求差距**。

## 6. 反例与边界如实注记

- **neg-008（构造微预算）**：三路均在 **PG 读取守卫**（`readonly_select_chunks`/语句信封 4）被拒——**成员/字符展开预算路径本轮未在生产执行**，不能声称已获生产验证；attribution 如实为 `production_readonly_with_constructed_budget`。
- **neg-002**：三路均仅记录"本腿观测未见外来 workspace"，未冒充同 ID 跨 workspace 对抗实弹。
- **counter 报 complete 的 8 条腿**（neg-003×3、neg-004×3、neg-005 pg/fusion）与正例 55 条 complete 一并列入**语义待审清单（unreviewed）**：应用覆盖不等于集合正确——pilot 教训（local/prose-enum-001 complete 但 13 项为他标准；quote 真≠claim 被支持）适用于本轮所有 complete 判定。未经审核项目标 unreviewed 保留在分母，**本报告不发布任何精确/召回汇总指标**；评分工具归 6.3 审查。
- table_enum local ambiguous×5、fact local 全 partial 与 pg/fusion complete 的分歧：app 行为差异如实入基线，语义孰对孰错待 6.3 逐题审。
- 融合对照：本轮数据仅作固定基线诊断，**不宣称融合稳定增益**。

## 7. 交付物与守卫工件

- `eval-runtime-{stamp,latest}.json`（终态：123 腿记录、26257 账本事件、拒绝原文、三态精排、身份前后观测）
- `round-1-legs.json` / `round-1-table.md`（123 腿机器可读 + 人读全表）
- `legs/r1/{pg,local,fusion}/{qid}/` 各入口真实终态 ×123、`inputs/*/{qid}-fusion.json` 120 + `-rerank.json` 120（含 pg/local 显式 absent 声明）、answer runtime 含 21 行合成腿的真实 receipt/context_sha/raw_response
- `pilot-manifest.json`（SHA 全清单）、敏感值扫描 0 命中、旧试点目录未动
- 6.2/6.3/Gate4 未勾选；第二轮未启动；默认路径未改。停止于主 agent 验收。
