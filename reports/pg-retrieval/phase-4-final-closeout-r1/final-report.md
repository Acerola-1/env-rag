# env-rag-final 本次任务结案

**本次委托已结束，采用“保留基线＋失败报告”结案。Gate 4 不通过，默认融合路径不启用。** 工程实现、最后两轮真实评测和离线交付均已完成；这不表示问答质量达到既定门槛。按用户约定，不继续追加付费请求、重试或改进组。

## 已完成的交付

- 工程：目录/范围与原文映射、中文PG检索、只读local接入、候选融合、联合精排、范围展开与引用核验、固定配置评测和评分工具。沿用已验收源代码，无本轮源码或配置修改。
- 真实运行：评分专用映射27/27；两轮各123腿，共246。每轮31正例×3路径、10反例×3路径。绑定同一r2锚，前后及跨轮身份一致，所有服务应用账本均在上限内。
- 累计实发：关键词158、embedding402批、Qdrant402、Neo4j790、PG24911、联合精排76、答案HTTP22。预留与实发分列，不把调用次数当作人民币费用。结案阶段新增真实请求/数据库写入均为0。
- 工程质量：当前工作面Ruff/格式、uv锁定环境离线检查、OpenSpec strict、diff check通过；准备包14项测试通过。生产源码字节未变，不重跑526项工程基线或改动已冻结测试。

## 固定两轮的质量结果

两轮逐行状态一致。下表是已验评分器的初版逐题裁决，未审部分保留，不能当作最终完整正确率。

| 每轮分母 | PASS | FAIL | PENDING |
|---|---:|---:|---:|
| 正例93 | 44 | 37 | 12 |
| 反例30 | 10 | 14 | 6 |

PG与fusion的三类枚举机械集合结果各5/6；local的文件/表格各5/6、正文4/6。每轮18条合成正例均未满足完整交付合同；模型原始答复片段可能正确，但不能替代应用实际交付。fact载体待审、公开歧义、单位缺失等保留在逐题记录。

## 主agent最终裁决及核对范围

实际逐一检查了两轮neg-005的pg/local/fusion共6份答案终态，并与固定反例合同对照。题目问两份不同标准的表1是否为同一张表；冻结合同要求ambiguous，实际均声明complete并交付跨两份文档的38行。因此“全部反例无false complete”门槛已经被真实行为证伪，**Gate 4不通过**。该结论不推断底层表ID被串并，也不因引用真实而放行不对题的结果。

其余每轮18条PENDING未宣称全数人工审过，完整保留在unresolved-review-boundaries.json。这个负向门槛不可能被剩余人工PASS改变，因此不为消除所有PENDING继续追加工作。未生成伪造的全题adjudication-final或未来人工PASS记录，原initial文件保留。

对执行方报告另作三处口径订正（原报告不改）：

1. file-enum-004本轮记录的missing/extra均为空，不能称为“文件集合漏项”；问题是ambiguous且一条引用缺乏受SHA保护运行输入的独立背书。缺证据不自动等于文件身份错误。
2. table-enum-003的数值被既有脱敏逻辑碰撞遮盖，离线原行回读因此不能核实全部发布cells；不能把这类掩码全部称为原始引用伪造，也不据此补造数值。
3. scorer的chunk/usable recall@20实际衡量前20候选的**文档命中**；unit指标是映射单位覆盖，二者不等于支持具体断言的精细证据recall@20。不将文档高召回直接算作原设计“候选证据”门槛通过。fact仍有待审，不能用“已确认PASS都是0”证明整体fact质量不下降。

上述边界不会改变已确认的Gate 4失败。时延按已有实际字段、样本量与inclusive口径发布；独立展开时延无字段则unavailable，不相减造数，见results-and-timing.json。

## 交付索引与状态

- final-decision.json：本次结案与Gate 4结论。
- decisive-behaviour-review.json：6份决定性反例终态/固定题目/SHA与人工核对范围。
- results-and-timing.json：逐轮分类、分母和实际时延记录。
- unresolved-review-boundaries.json：36行跨轮待审项，不删分母、不伪判通过。
- ../phase-4-formal-two-rounds-delivery/summary.md：执行方两轮总账，口径订正以本报告为准。
- ../phase-4-formal-fixed-assessment-1/adjudication-initial.json与../phase-4-formal-fixed-assessment-2/adjudication-initial.json：原逐题裁决。
- ../phase-4-formal-fixed-round-1/与../phase-4-formal-fixed-round-2/：原始输入、请求/响应、答案和manifest。
- ../phase-4-formal-mapping-r2/：实际评分专用映射；仅评分附件，不进入发现或答案。

旧失败目录、历史评分/运行代次、gold、配置锚、.env、默认路径及数据库均保留。任务清单不将未满足的质量条件勾为通过；清单留白不是自动继续任务的授权。**本次任务在此结束；质量改进若以后要做，须另起明确的新范围。**
