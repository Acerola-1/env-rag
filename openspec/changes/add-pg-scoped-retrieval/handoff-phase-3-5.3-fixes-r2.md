# 仅5.3/F3的两个失败边界；完成后停检查点

F1/F2/F4已通过；前轮8项、既有266项均通过，root正式PG-only fact-002/neg-010成功、冻结无漂移。报告phase-3-fusion-review-r2/review.md。**不要重做已通过的归属/表片修复，不做5.4–5.6，不重复真实服务请求。**

## F3-a 完整的前置失败出口

目前gold.read_text/json.loads仍在try外。把gold读取、JSON解析/结构准备、SHA拒绝以及配置/请求校验纳入前置失败终态边界；各失败保留原始异常类型和原因、明确零后端/模型调用、无finished_at。拒绝损坏输入，禁止修改正式gold/.env或伪造身份来通过。

冻结独立断言：tests/test_fusion_review_r2.py::test_malformed_gold_has_zero_call_failure_terminal。同时保持SHA拒绝、unknown id、环境覆盖/未映射workspace在后端前拒绝；输入/配置异常不能因异常类型不为AdapterError而再次漏出无报告路径。

## F3-b 新题先重置账本

新题入口只更新live.query_id/partial却保留前题receipts。必须在任何新题后端接触/await之前创建或完整重置当前题账本；当前题local尚未执行时，失败服务凭证明确为空且query_id为当前题，前题凭证保留在前题结果。当前题local已完成后的失败仍保留它自己的真实凭证；两个方向均不得回退使用前题账本。

冻结独立断言：tests/test_fusion_review_r2.py::test_second_query_pg_failure_does_not_borrow_first_local_receipts；前轮第二题local完成后失败的正例保持。

## 验证与交付

- 先复现两失败，再集中修复；原274项与新增2项全部通过，独立断言不得删除/弱化/xfail。
- 整理失败终态证据（损坏JSON、第二题PG发现失败、第二题local完成后失败），隔离fixture不接真实服务。
- Ruff/format/OpenSpec strict/diff/凭据扫描；manifest在最终修改后生成。
- 0新模型/embedding调用，**无需重新PG-only复跑**；保持已验收真实正例证据、冻结source/catalog/search/gold/env与原始语义提交。
- 仅5.3提交主agent复审；5.4精排/5.5生成/5.6Gate3仍不进入。
