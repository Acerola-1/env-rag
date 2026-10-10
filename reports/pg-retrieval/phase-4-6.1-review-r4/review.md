# Phase 4 / 6.1 rev-3 复审（2026-10-08）

**6.1仍未通过；Gate3保持，6.2与网络评测未启动。** 只审S1/S2增量，其余已通过结论沿用。本轮不建立新配置锚。

提交450项独立通过（11.34s）；r1 20/r2 12/r3 7与自有28共67项通过。新冻结 `tests/test_evaluation_review_r4.py` 四项：3失败/1正例。全部验证为离线假I/O，0真实模型/embedding/rerank/DB请求、0写库。

## 仍需补正

1. **S1异常终态漏状态**：evaluation.py:1042–1050仅在异常时条件增加issued后raise。 owning catch保存failure，但只有正常stage返回才能将 `rerank_issuance` 写入record（1764）。无可读runtime的真实异常出口因此既没有unknown标志，也没有可区分的实发状态。测试 `[False]` 复现：issued不增加、失败终态的rerank_issuance缺失。保持“不猜实发次数”，同时把unknown明确写入当前题终态。
2. **S1在途凭证未绑定题号**：evaluation.py:997–1002检查service，却不检查 `failure_service_records.query_id`。只有another-question的HTTP凭证时当前题issued被记为1；测试 `[True]` 复现。应核对当前qid，外题凭证不作本题实发或零调用证明。已有已完成result的qid筛选与当前题真实401正例保持。
3. **S2温度声明未比较**：evaluation.py:1442–1457对五个预算逐项比较，却只对answer_temperature做非负int结构校验，未与实际0比较。锚temperature=1照样通过；其代码锚虽锁定实际payload为0，也不能证明锚的声明1相符。新增temperature=1拒绝反例失败；temperature=0完整正例通过。

## 保持通过

精排正常返回call字典计1、call=None计0和当前题已执行失败计1；关键词KEYWORD_LLM_MODEL优先/LLM_MODEL fallback冻结；必填空节拒绝；前轮预算/连接/终态/来源保真结论保持。本轮未扩大审查到其它模块。

字节审计：r1–r3冻结未改，17份Phase3冻结、27份历史运行/控制工件未改；answer/expand已批准兼容缝未改；CLI与前轮字节一致，rerank/fusion/local/compat与已验收代码锚一致；.env与HY3成功代次身份SHA一致，gold SHA一致。敏感值扫描0命中。246矩阵仍为186正例腿+60反例腿。

Ruff check/format、OpenSpec strict与diff通过。Reviewer仅新增冻结反例、复审证据与补正交接并追加tasks裁决；提交实现未改，真实锚未动。

执行交接：[handoff-phase-4-6.1-fixes-r4.md](/Users/acerola/Dev/Python/RAG/env-rag-final/openspec/changes/add-pg-scoped-retrieval/handoff-phase-4-6.1-fixes-r4.md)。仅闭合上述S1/S2接缝，不重做已通过部分。
