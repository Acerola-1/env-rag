# 固定版本正式两轮——执行与离线评分交付（2026-10-09，停主 agent 裁决）

用户方案 1 授权的最后一批：一次只读映射采集 + 两轮各 123 腿 + 离线评分，全部按 `handoff-phase-4-formal-two-rounds-r2.md` 完成。**无重试、无追加点、无预算/配置/代码变更**；原 `phase-4-formal-mapping-r1` 失败现场与 r1 准备包逐字节保留。

## 批次完成事实

- **映射采集（r2，唯一一次）**：27/27 单元全部采得（14 block + 13 table，chunk 链接与内容 SHA 齐），守卫前后身份一致且 matches_frozen；1 条数据 SQL（上限 20）、0 模型、0 写库。产物 `phase-4-formal-mapping-r2/`（capture-manifest 已验证绑定）。
- **两轮运行均一次成功**：`phase-4-formal-fixed-round-1/2` 各 123 腿完整、前后身份==冻结、跨轮身份相等、硬腿失败 0、精排 degraded 0。拒绝每轮 3 条=仅 neg-008 构造信封（预期观察单列）。
- **账本 vs 授权上限（两轮合计，应用账本口径）**：keyword 158/164、embedding 402/656、Qdrant 402/1312、Neo4j 790/1640、PG 24911/251904（单腿峰 178≤512 审查线）、精排 76/82（38+38 executed）、答案模型实发 22/42（每轮预留 21=帽、实发 11；10 条腿 incomplete_conditions HTTP 前 skip，与历史基线同型）。reserved==issued 除 answer_llm 的合规 skip。
- **离线评分**：r4 评分器 + r2 锚 + 同一 mapping-r2，两轮各 123 行，manifest 覆盖 805 工件，初版裁决落 `phase-4-formal-fixed-assessment-1/2/adjudication-initial.json`。

## 机械结果（两轮逐行完全一致——固定版本跨轮稳定性的直接证据）

- 正例 93：**44 PASS / 37 FAIL / 12 PENDING**；反例 30：**10 PASS / 14 FAIL / 6 PENDING**。
- enum 集合完全正确（每类 6 题）：pg 与 fusion 均 **file 5/6、prose 5/6、table 5/6**；local file 5、**prose 4**、table 5。
- fact：0 PASS——pg/fusion 各 6 题 PENDING（载体 evidence_gap 待人工）、1 题 FAIL；local 7 FAIL。synthesis：0/18 全 FAIL（每轮 11 次 HTTP 实发后按合同拒——开放的质量问题，不是服务失败）。
- 引用：6 腿存在未成立引用（file-enum-004×3、table-enum-003×3 各 1/2 条），另 table-enum-003 有 2 处数值碰撞掩码；缺失结果均如实 FAIL/PENDING，未伪造。
- 覆盖分布（正例）：complete 56 / partial 31 / ambiguous 6；反例 false complete：neg-005×3（期望 ambiguous，交付跨 2 文档 complete）两轮复现。
- 召回（每题简单均值·非官方聚合，分母 31）：pg chunk@20 **0.9585**、typed/union 文档覆盖 1.0；fusion chunk@20 0.9908、typed 1.0；local usable@20 0.9516（missed：file-enum-004=0、syn-004=0.5）。unit 证据召回（新映射）：pg 0.947、local 0.960、fusion 0.980（25 题均值，missed 明细在 delivery-round*.json）。
- 时延（n=120）：discovery_ms（fusion 含精排 inclusive）R1 p50 2670/p95 8044、R2 p50 2552/p95 7441；total_ms R1 4780/11533、R2 4489/10606；答案阶段 answer_stage_ms 1610/5860 与 1606/5572；**真实 HTTP 口径** answer_http_ms（n=11/轮）R1 p50 4434/p95 7811、R2 4265/6600。展开阶段无字段=unavailable，不做减法。

## Gate4 逐条状态建议（详见 gate4-evidence.md；门槛裁决权在主 agent）

按 design.md 七项：第 3、6、7 项**达到/可报**；第 1、2、4（local）、5 项**未达标**。综合建议：**Gate4 不通过**，按交接走"保留基线 + 失败报告"收尾，不切默认融合、不再追加付费试跑。

## 待主 agent 人工核对清单（本方不代拟结论）

`review-list-round{1,2}.json` 共 69 行/轮：18 行 PENDING（fact 载体 12 + neg-002×2 + neg-008×2 + 其余）逐行绑定了 answer-runtime SHA 与 raw_response SHA（可填 records 直接复跑评分出 adjudication-final，初版不覆盖）；44 行机械 PASS 标 `recommend_main_agent_spot_audit`（其中 synthesis 无 PASS 行；file/table 的 10 行建议抽审）；`failure-attribution-round{1,2}.json` 37 行 FAIL 含原因摘录。附录A 与规范正文的证据分列已在行级字段中保留。

## 工件

delivery-round{1,2}.json（全部聚合数字）、review-list/failure-attribution×2、本文件、gate4-evidence.md、sensitive-scan.json（真实密钥 0 命中）、sha-list.json、manifest 最后写。四个新目录（mapping-r2、round-1/2、assessment-1/2、delivery）之外未写任何路径；所有历史目录/源码/gold/.env/锚复核零漂移（全库清单复算见交付记录）。
