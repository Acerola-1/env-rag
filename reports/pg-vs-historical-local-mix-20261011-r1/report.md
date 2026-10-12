# 历史 local/mix 核对与当前 PG 复测

## 结论

1. 当初的计划确实以 local/mix 差距不大的评测为背景，第二路定位为元数据、版本、完整范围读取，避免重复 mix 的普通向量检索。OpenSpec design §7 明确 local/PG/融合为主对照，mix 为可选参考。
2. 历史最终冷生成（50 题，其中 17 枚举）RAGAS 四项均值 local=0.847、mix=0.858；平均延迟 local=11.27s、mix=11.75s。这是单轮观测，不能证明统计打平或稳定优势。原报告末尾 0.841/0.854 与 JSON/总表不一致，以 JSON 四项均值为准。
3. “很多枚举两路都没解决”不获该固定题集支持。按旧指标，local 的缺口是 enum-05/15；mix 是 enum-09/15；唯一交集是 enum-15。enum-09 的 NH4+“铵离子/铵根”是同义词误判。GB8978 表1在最终冷生成两路均13/13，不能继续使用更早 mix=0/13 来证明当前共同缺口。旧指标只查期望项命中，不核全量 extra/引用/规范含义；不把这些命中数当全题精确正确率。
4. enum-15 旧题本身错误：它问附件 I 第1节“表2”的四项目标值；PDF 第32页及解析 caption 均证明四项目标值在 Table 3，Table 2 是另一张限值表。旧题/金标不改动，另出勘误；该题不能作为正确前提下 local/mix 同时漏项的干净证据。当初审计遗漏此表号错误，本轮明确更正。
5. 当前 PG 没有补上这道原题：网页请求 HTTP400（正文+表格范围冲突），零后端/模型调用。只读底层诊断也发现英文文档/表格路径缺口；即使明确文件、以辅助问题分别指定表2或更正的表3，枚举均 ambiguous、0项。没有成功结果可发布，未把手工读出的正确四项冒充PG答案。

## 核对的计划和历史证据

- openspec/changes/add-pg-scoped-retrieval/proposal.md：top-k相关片段不证明列全。
- openspec/changes/add-pg-scoped-retrieval/design.md §5/6/7：完整范围、联合精排、local主基线及mix可选参考。
- LightRAG/runs/ragas/RESULT_v2_local_vs_mix_20260929.md：较早无有效精排基线，含旧失败说明。
- LightRAG/runs/ragas/RESULT_final_rerank_cold_20261004.md 与两路 v2fresh JSON/answers：最终冷生成基线；答案缓存命中轮已排除。
- historical-enumeration-matrix.json：17题按原问题逐项对齐，疑似失败单独人工核对，不换题。

## 实测和诊断分列

| 实验 | 输入 | 结果 | 口径 |
|---|---|---|---|
| 当前网页PG | 旧enum-15原文；无options；top_k20；生成开启 | HTTP400，“同时出现正文与表格范围，请拆成两次提问” | 原题未完成，不重试 |
| 底层关键词发现 | 同一原问题，run_query正式函数，生产只读 | status=ok，但20候选内没有目标doc | 发现候选不等于回答成功 |
| 辅助明确文件 | 删除第1节、指定原PDF、表2 | ambiguous，no logical table 表2，0项 | 手工澄清，不能算原题成功 |
| 辅助更正表号 | 同PDF、附件I表3 | ambiguous，no logical table 表3，0项 | 更正题目、明确文件，仍失败 |
| 原PDF独立核对 | 第31–32页及原tables.json | 四目标值在Table3 | 人工来源核对，不是PG发布答案 |

## 当前PG缺口的定位

- Question.prepare 把“第1节”和“表2”看作两个独立目标，禁止组合；未把它解析为一个表格的层级地址。
- 该欧盟文件有29个物理table units，目标表原始HTML完整；标题登记为2024/2881，自身GB/HJ类编号为空。上述中文原问题的关键词发现没有选中它。
- 目录仅有 front-matter ambiguous scope，尚无该文档的英文Annex/Section范围。
- enumerate_/tables.py 的表号caption识别为中文“表N”，不识别原始“Table N”。物理table_seq=4与原文Table3不是同一字段，不能拿片序号替代原文表号。
- 因此当前问题同时涉及自然语言层级定位、英文目录/表号支持。原始内容已存在，不需要重新解析或embedding；但这次仅核对和测试，没有改实现。

## 保真与边界

- 历史local/mix是2026-10-04归档，PG是本轮当前版本；模型提示、精排策略和版本并非统一冻结，不能将此复测当同条件三路性能评测。
- 当前生产只读诊断前后 matches_frozen=true、identity_drift=[]；没有DDL、目录/索引重建、embedding、精排、答案模型调用。原题HTTP前拒绝。
- 历史六份关键输入SHA复验全等，源PDF与gold不改。此次只新增独立报告目录。
- 下一步若要修这个范围，应另建题号正确的案例（保留旧gold，不能原地改历史指标），同时补英文Table/Annex/Section支持，再比较当前mix、PG和PG+mix。不能用中文GB强项的局部成功替代这一缺口。
