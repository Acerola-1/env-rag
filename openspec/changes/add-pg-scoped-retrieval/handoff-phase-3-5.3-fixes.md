# 仅补正5.3：F1–F4，完成后停检查点

主agent首轮验收未通过。报告reports/pg-retrieval/phase-3-fusion-review/review.md；独立tests/test_fusion_review_r1.py为冻结验收断言（5失败、1正例），原266项通过。提交19条候选完整正文独立PG回读相等、冻结身份无漂移，5.2实现保持验收状态。

## F1 请求的合法归属集合

- 显式“含修改单/相关文件/整合版”时，PG已验证的doc_attribution目标应按其实际名称/标题证据进入本请求允许集合，允许对应local来源；保留membership_basis、原citation与快照，不伪造self_code。
- 普通标准问题/“自身编号”仍只许code_exact，自身编号不存在仍missing，不让邻近年份或正文提及替代。已解析双版本保留，缺一分支仍missing并保留已找到证据。
- 真实已只读确认：GB18466-2005显式相关请求产生两份合法归属文档，当前约束拒绝两份；不需要调用模型来重现或证明。

## F2 每条路径保留来源定位

- table_unit映射chunk后，路径保留unit_id/table_id、原citation（workspace/snapshot/doc/table/chunk关联），上游提供locator就原样保留。
- 同chunk连接两片时两条PG路径必须可分别辨认，而非两个完全一样的摘要字典。typed_targets保留已有citation/scope_status/membership_basis等证据字段。
- 不猜页码、单位或引用，不改变PG范围发现/完整枚举合同。

## F3 所有失败写入同一终态

- 持续保存当前题部分结果和服务账本。local完成后PG回读/合并阶段抛错，失败报告必须仍含当前题已发生的真实服务凭证、原错误、后置身份；不得以“尚未返回out”为由记零调用，或借用前一题失败凭证。
- gold读取/JSON解析/SHA拒绝纳入前置失败终态，注明真实零调用，无finished_at。错误原因不被后置/写报告错误覆盖；现有身份漂移、post采集失败分支保持。

## F4 前置配置检查

- verify_config_guard与所有选定请求workspace检查必须先于capture生产身份/任何后端读或服务调用；环境覆盖/模型维度/未映射workspace拒绝时零后端接触，并写失败终态。
- 配置正常的流程保持source/catalog/search/gold/env前后守卫及原始错误合同。禁止修改.env来迎合检查。

## 有界验证与交付

1. 先跑独立6项确认5个失败，再一次修四组。原验收断言不得删除/弱化/xfail；补充“自身编号不放宽”、多题失败凭证属于当前题、前后漂移与原错误并存的入口正反例。
2. 原266项及独立6项全部通过。格式/Ruff/OpenSpec strict/diff/凭据扫描。
3. 正式PG-only fact-002证明两条表片路径各带真实来源；归属集合可用真实只读PG发现+约束判定或正式入口stub（模型路径已有5.2证据）。**不要求新的模型/embedding请求，不重复三题整轮。**
4. 保存本轮报告/manifest/正式入口证据，分清原提交与本轮。5.3提交待主agent勾选；5.4–5.6/Gate3不进入。source/catalog/search/gold/env与正式八表仍只读不变。
