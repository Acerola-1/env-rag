# 阶段 B：同范围 9 腿复跑报告（pilot-r2，2026-10-08）

前置：阶段 A 标定全门槛通过（见 `../phase-4-pilot-r2-pg-calibration/calibration-report.md`），按交接直接执行一次 B。命令逐字一致；预算仅 PG 改每腿 1024/整批 9216，**其余服务上限与 r1 完全相同**（keyword 6 / embedding 24 批≤32 文本·64000 字符 / Qdrant 48 / Neo4j 60 / 精排 3 / 答案 3）；新代次目录，未覆盖 r1；exit 0；未追加重试/健康探测；写库 0，生产全只读。

**结论一句话：端到端链路九腿全部走通（发现→回读→精排→范围展开→答案 HTTP→复核→合同判定），无任何预算事件与腿失败；DeepSeek 答案通道两次真实调用均 200 且实质答对了两环境要素，但 5.5 逐字合同按设计拒绝了改述 claims——syn-004 最终仍未交付答案（质量/稳定性问题，与 HY3 时期同类，非链路故障、非服务失败）。3 题不代表 31 题指标，6.2 不勾选。**

## 1. 账本（reserved≠issued，逐值如实）

| 服务 | 预留 | 实发 | 上限 | 说明 |
|---|---:|---:|---:|---|
| keyword LLM | 6 | **6** | 6 | 6 个含 local 侧的腿各 1 次，全部成功 |
| embedding | 16 | 16 | 24 | 16/16 成功 |
| Qdrant | 16 | 16 | 48 | 16/16 成功 |
| Neo4j | 30 | 30 | 60 | 30/30 成功 |
| PG 计量读取 | 1048 | 1048 | 9216 | 每腿 45–176；refusals=0 |
| 联合精排 | 3 | **3 executed** | 3 | 三条 fusion 腿各 1 次真实成功（ordered 10/6/21，degraded=[]） |
| 答案 LLM | 3 | **2** | 3 | 差值即合同语义：local/syn-004 预留 1 后因 incomplete_conditions 未发 HTTP → 实发 0；pg/fusion 的 2 次**真实发出且 HTTP 成功** |

pre/post 身份 matches_frozen=true、drift=[]；无 budget_failure、无腿级 failure、无运行级拒绝。r1 的"吞拒绝检出"合同本批未触发（无拒绝）。

## 2. 逐腿结果（业务覆盖，不预设 complete）

| 腿 | 发现 usable | 答案 | 判定 |
|---|---|---|---|
| pg/fact-002 | 1 | **partial**，1 项（缺单位边界保持，13 项复核 0 问题） | 与 A 及 r1 口径一致 |
| local/fact-002 | 10 | **ambiguous**，1 项 | 多源歧义如实呈现，未强判 complete |
| fusion/fact-002 | 10（精排 ok） | **partial**，1 项 | 同上 |
| pg/prose-enum-001 | 2 | **complete**，4 项 | |
| local/prose-enum-001 | 10 | **complete**，17 项 | 枚举超集差异留待 31 题批对照 |
| fusion/prose-enum-001 | 6（精排 ok） | **complete**，4 项 | |
| pg/syn-004 | 20（精排 n/a） | **partial**：模型 HTTP 200（2602ms）、claims 合同拒绝 → model_failure、0 项交付 | 见 §3 |
| local/syn-004 | 10 | **partial**：incomplete_conditions（请求版本 `GB3095-2012`/`GB3838-2002` 未在读取范围解析出）——0 模型调用 | 见 §3 |
| fusion/syn-004 | 21（精排 ok） | **partial**：模型 HTTP 200（4052ms）、12 claims 合同拒绝 → model_failure、0 项交付 | 见 §3 |

三路候选独立 fresh discovery（正文/资料性附录分列工件在 inputs/legs；local 出处保真字段完整、score 未伪造）。

## 3. syn-004 人工语义检查（交接要求）

**(a) 两环境要素是否被真正回答？**
- **实质内容层面：是。** pg/fusion 两腿的真实模型回执（`answer-runtime-latest.json` → `model.raw_response`，未删改）均正确映射 GB 3838-2002→地表水、GB 3095-2012→环境空气，fusion 腿还逐条给出附录 A 元素的年平均数值。
- **交付层面：否。** 应用合同拒绝整组 claims 后 `answer.items=0`——按 5.5 已验收合同"拒绝即不交付、不二次调用、不补造"，终态 partial/model_failure 为如实结果。
- local 腿则是前置条件不足：读取范围内两请求版本未解析绑定，**未发 HTTP**（incomplete_conditions，0 调用；预留≠实发在账本上分列）。

**(b) 附录句是否被错误升格为规范要求？**
- 未见升格表述：模型 claims 明确自带"附录A给出/附录A表中……参考浓度限值"措辞，将其归属附录 A 而非第 7 章强制要求（符合 Gate 3 裁决的区分方向）。
- 拒绝原因集中于另外两点（均合法有据）：**"claim 数字不被所绑定 quote 支持"**（如镉 0.005/汞 0.05 等数值出现在 claim 而绑定引句未含该数值）与 **"prose claim 非绑定来源的连续逐字陈述"**（改述而非逐字）——这正是 5.5 合同设计拦截的"数字散落≠主体承载值"的形态。

**(c) 定性**：服务与凭证健康（2 次答案 HTTP 均成功、耗时 2.6s/4.1s、context_sha 同值 `b0487919…` 同上下文合同）；失败发生在**模型输出形态与合同要求的差距**——与 HY3 时期 syn4/5/7 同型。质量/稳定性判读与是否调整提示或批次策略归主 agent 决策；本批未做任何现场修改。

## 4. 事实-002 / 精排 / 冷生成核对

- fact-002 三路均含缺单位/歧义边界（partial/ambiguous），未因期待 complete 而补造；13 项行级复核 0 问题。
- 三条 fusion 腿精排**真实发出且成功**（r1 从未到达的部分本批补验），fresh 报告回放进答案阶段；pg/local 六腿显式 absent 声明（无伪造排序）。
- 冷生成：所有答案为本轮新产出；未读取 r1/Gate3/syn6 任何旧答案字段（answer 阶段全部新代次目录）。

## 5. 边界与交付物

- 本批 9 腿成功与否均**不代表 31 题指标**；6.2 未勾选；未扩批；停止于主 agent 复审。
- 工件：`eval-runtime-{stamp,latest}.json`、`legs/r1/{pg,local,fusion}/{qid}/`（fusion/rerank/answer 各入口真实终态）、`inputs/{pg,local,fusion}/`（9 fusion + 9 rerank 声明）、`pilot-manifest.json`；r1 及 31 项 manifest 原样未动。敏感值扫描 0 命中；身份守卫前后一致。
