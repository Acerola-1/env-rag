# 5.6 下一检查点：一次有界真实合成（主agent另行安排）

**当前裁决（2026-10-07）**：本次有界执行与失败回执验收通过；5.1–5.5工程结论保持。真实合成成功及人工回答核对仍缺失，5.6/Gate3不勾选，Phase4不进入。本次一次请求额度已用，不自动第四次重试；当前无新增应用代码返工项。 以下安排为已执行交接历史，当前不得据此继续请求。见 phase-3-real-validation-review/review.md。

文档材料已由主agent补正，见phase-3-review/review.md。5.5实现通过；提示已仅加一句C1一致性要求、64专属矩阵通过。**5.6/Gate3/Phase4未完成**。

执行前参考syn-prep-syn004.json的完整messages/context及syn004-source-citations.json的8条离线定位。所有材料是准备证据，不是新运行回执。若由执行agent接手，必须有用户/主agent明确的实际请求指示，不得因本交接自行调用服务。

若获安排：

- 仅syn-004，固定PG-only fusion输入与已验收rerank报告（该题rerank-absent如实标记），创建新报告代次；不重复keyword/embedding/local/rerank，不运行31题对照。
- 通过正式answer入口做前置身份、源/目录/search/gold/input SHA核对，完整范围与引用回读；实际context需与准备材料相符，若有漂移/缺项拒绝，不能手工替换成预备上下文。
- 至多一次答案请求，预算和--allow-model按原合同；成功/HTTP错误/非法JSON/验证拒绝全部保存。任何失败不循环重试，不伪造分数/引用，不删历史503。
- 看call.status、model.status、coverage和引用，不拿CLI退出0或Answer OK认定答案成功；连接/守卫异常才应抛出非零。
- 真实答案要人工核对GB3838与GB3095的环境要素陈述是否被各自连续原文支持。应用目前仅两版本槽不足以自动证明定性语义。现有GB3095块带附录A需保留来源边界说明，不把附录要求归为第7章要求。
- 更新phase3报告/真实运行新SHA与检查清单，停主agentGate3裁决；执行者不得自行勾5.6或进入Phase4。

真实服务仍不可用时保留失败和未验证状态即可，不安排重复重试、健康探针或新的检索轮。
