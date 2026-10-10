# 6.1 rev-3剩余补正：仅 S1 / S2（2026-10-08）

6.1未通过；Gate3保持，6.2与网络评测不启动。提交450项独立通过，冻结r1/r2/r3与自有矩阵共67项通过；冻结、已验收组件、.env、gold和历史未变。新冻结 `tests/test_evaluation_review_r4.py` 四项为3失败/1正例。本轮Reviewer零真实请求、零写库。

## S1：异常路径的状态落盘与当前题凭证

返回路径按call计数已通过，reserve闸门与实际401计1保持。只修异常路径：

- `_fusion_path` 抛错前需把本题的对账状态发布给 owning `run_evaluation`，最终失败腿与终态也必须带 `rerank_issuance`。不可读runtime必须显式 `unknown-no-receipt`；仅未增加issued不能代表确定0。已进入HTTP=executed，请求前明确拒绝=before-http-zero，三态均可追溯且保持原错误。
- `_rerank_runtime_receipt` 的在途 `failure_service_records` 必须核对 `query_id`。只有其它题的call不计入本题，也不能因为该runtime存在failure便推断本题HTTP前零调用；应为unknown。已完成result同样只认当前qid。全局明确pre-flight零调用拒绝仍可保留，但不得以任意failure充当当前题零调用证明。
- 返回与异常分支不双计；已有当前题HTTP执行后抛错计1正例保持。自有矩阵补当前题执行后异常与明确HTTP前拒绝的终态三态正例；不得靠全拒绝、吞异常或改旧断言达标。

新冻结两项 owning 入口反例：无runtime抛错→当前代码终态缺unknown；只有another-question在途call→当前代码误记issued=1。

## S2：温度值必须比较

必填结构、关键词冻结/fallback和空节拒绝已通过。仅补 `frozen_budgets.answer_temperature` 的值比较：实际答案payload固定0，锚声明1必须在任何后端接触前拒绝并指出temperature。代码SHA固定实际payload不能代替声明值与实际值的相等校验。锚为0的完整正例保持。无需改answer.py或提示。

只改evaluation.py上述接缝、自有tests与必要文档/工件。禁止重构其它通过部分；不改CLI/已验收组件/.env/gold/四版冻结/历史运行。真实配置锚仍旧，本轮不得回写当前值；6.1批准后主agent另建代次。0真实模型/embedding/rerank/DB请求、0写库，不进行健康探测。

验收：四版冻结与原450项保持；新四项全过并含正例；Ruff/format、OpenSpec strict、diff与敏感值扫描通过，工件可复算SHA。提交后停6.1主agent复审，不勾6.1、不进入6.2。
