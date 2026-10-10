# 5.3 第二轮复审：仅F3两个边界仍未通过

日期2026-10-07。F1/F2/F4已确认通过，F3的SHA拒绝与当前题local完成后回读失败路径已修。5.3保持未勾选，仅补正下面两个反例；5.1/5.2/Gate2保持通过，5.4–5.6/Gate3未进入。

## 已通过部分

- 原独立8项全过，既有test_fusion.py 11项保持；全套**274 passed / 2 failed**，仅新增两项失败。提交manifest七项SHA全部匹配。
- 主agent正式CLI使用 `--pg-only --query-id fact-002,neg-010`，退出0：fact-002可用1个chunk，其中两个物理片分别带原table_id/unit_id/citation；neg-010可用6个chunk、0拒绝，合法无自身编号的修改单归属被保留，严格自身编号反例仍通过。
- 正式运行identity before/after冻结匹配、无drift，正式八表/cache=16514不变；0模型/embedding调用、0数据库写入/初始化/重建。该运行仅核验PG-only融合编排，不声称重跑local或测量质量。
- Ruff/format、OpenSpec strict、diff检查通过；原始证据及各路径见formal-cli/，全套结果final-tests.txt，独立10项结果acceptance-tests.txt。

## F3-a gold解析仍在失败终态边界外

`src/env_rag_final/fusion.py:547`直接read_text/json.loads，之后的try只包含verify_gold_guard。损坏gold JSON因此直接抛JSONDecodeError，不写fusion-runtime-latest.json；“gold解析/SHA拒绝都写终态”的提交陈述仅对SHA拒绝成立。

独立入口test_malformed_gold_has_zero_call_failure_terminal确认：零后端调用，但报告不存在。必须将读取、解析、结构准备、SHA及配置校验纳入统一前置失败边界，保留真实错误类型/原因、明确零调用、无finished_at；不修改冻结gold。不是要求容忍损坏gold继续执行。

## F3-b 第二题local前失败仍借用第一题凭证

`fusion.py:766–771`在新题开始仅更新live.query_id/partial，不清空live.receipts。第一题local完成留下账本；第二题PG发现超时、尚未调用local，_collect_failure_receipts会优先返回第一题的旧receipts。

独立入口test_second_query_pg_failure_does_not_borrow_first_local_receipts确认：失败题为q-dual，终态凭证query_id仍为q-merge；第二题实际零local调用却取得第一题keyword LLM success。新题入口先创建/重置独立账本，再做任何可能失败的await。失败报告应属于当前题，第一题凭证留在它自己的完成结果中。

## 下一轮限定范围

仅F3-a/F3-b，固定tests/test_fusion_review_r2.py两项不得弱化；原274项保持。修复后用隔离入口测试/格式/OpenSpec即可，**无需任何真实模型请求、PG-only或语义整轮**，本轮真实正例证据可以沿用。交接handoff-phase-3-5.3-fixes-r2.md。主agent未修改实现或旧断言，只新增两个入口级验收与报告。
