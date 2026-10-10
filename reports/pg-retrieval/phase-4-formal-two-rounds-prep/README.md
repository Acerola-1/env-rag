# 固定版本正式两轮准备（尚未执行）

评分准备r4通过后主agent建立的新配置代次。所有生产源码、旧配置锚与历史保持，当前准备仅离线；**网络授权尚待用户选择，--authorized不能自行视为授权**。

## 范围与调用上限

固定31正例+10反例，pg/local/fusion三路，两轮独立目录，每轮123腿共246。模型使用已恢复DeepSeek抽词与合成；Qwen3-Embedding-4B（2560维）、Qwen3-Reranker-4B、原提示/温度0不变。

| 应用账本服务 | 每轮上限 | 两轮上限 |
|---|---:|---:|
| keyword LLM | 82 | 164 |
| embedding批 | 328 | 656 |
| Qdrant读取 | 656 | 1312 |
| Neo4j读取 | 820 | 1640 |
| PG计量 | 125952 | 251904 |
| 联合精排 | 41 | 82 |
| 答案模型 | 21 | 42 |

每腿PG1024是发现+答案累计信封，非各阶段1024；embedding每批最多32文本/64000字符。每个独立运行的total_cap也锁到一轮额度，因此两次之和不超过整批提案。预留≠实发，skip/unknown/拒绝分列；不把调用数写成人民币费用或Token上限，未测单价不估价。

## 最小只读评分映射

新collect_mapping.py只查固定gold的**27个唯一unit组合键**及其真实chunk/scope关系（同单位在多个题中复用），不是全库完整映射宣称。gold只提供评分目标，不进入发现/精排/答题输入。1条数据SELECT（上限20）＋已验身份守卫SQL另列；单只读REPEATABLE READ事务，无DDL、模型、图库/向量请求。

unit正文/HTML从既存解析产物复算SHA并核对目录长度；漏/重复/跨workspace/无链接/漂移拒绝整批映射，失败后保留诊断，不启动付费腿，不自动重试。代码仅经过离线测试，实际SQL执行与27/27采集尚未验证，先以本次单次采集确认；失败是停止条件，不能填造映射。没有作schema迁移。

## 已准备的入口

- run_round.py：新配置锚显式传给既有owning run_evaluation；默认CLI旧锚原样保留；--dry-run零后端。实际必须用户批准后带--round1或2、--authorized。
- collect_mapping.py：单次映射采集，亦要求批准后的--authorized；目录已有就拒绝，不覆盖历史。
- prepared_common.py：准备清单/源代码/环境SHA/模型参数验证，首轮证据清单核验与二轮停止条件。
- assessment：只使用通过的phase-4-scoring-readiness-r4/assess_two_rounds.py；人工结论绑定每个实际输出的SHA，不能预造。

真实目录为phase-4-formal-mapping-r1、phase-4-formal-fixed-round-1、phase-4-formal-fixed-round-2。运行须从项目根目录。prepared-binding不伪造身份观察，实际identity_before/after仍由每轮owning入口现场采集；不允许用锚替代观察。

## 通过不等于质量改善

fact-002缺单位、公开歧义、合成输出形态/覆盖仍是已知边界。两轮可能判Gate4不通过；不改gold/提示/模型迎合，不重试挑最好代次，不自动切融合。主agent逐轮审义并出分，失败/待审保留分母。

有序chunk召回、无序typed发现覆盖、unit证据召回分别报告，不能把它们拼成不存在的统一recall@20；单位级指标不等于细粒度引句命中。Gate4所需口径未证明则明确未通过/未验证，不用已有高召回替代答题正确性。时延无字段则unavailable，不用减法造精度。

低成本替代：不发这批付费请求，以既有基线+已确认改进/失败边界交付，注明全量新指标未验证，保留原默认路径。
