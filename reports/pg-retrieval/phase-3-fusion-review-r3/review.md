# 5.3 第三轮：仅F3-a的异常类型覆盖尚未完成

2026-10-07。F3-b新题账本同步重置已修；F3-a损坏JSON、文件OSError、SHA/配置AdapterError及unknown id的终态路径已修，前两轮10项独立验收保持通过。F1/F2/F4、5.1/5.2/Gate2均保持已通过结论。5.3暂不勾选，5.4–5.6/Gate3不进入。

本轮只核验前置边界与账本，没有真实PG/模型请求，沿用第二轮正式PG-only正例。

## 唯一剩余问题

`fusion.py:566–609`把前置操作放进try，但except只有_PreflightRejection、JSONDecodeError、AdapterError、OSError。提交所称“无论异常类型都先写终态”尚不成立：

- gold缺questions字段：结构准备抛KeyError，无报告。
- gold.questions为null：结构准备抛TypeError，无报告。
- EMBEDDING_DIM不能转为整数：原verify_config_guard抛ValueError，无报告。

三项均经run_fusion正式入口复现，确认零后端capture，但fusion-runtime-latest.json不存在。这三类都是前轮交接已经明确要求的“gold结构准备/输入与配置异常”，不是新的功能要求或审查扩展。

冻结断言tests/test_fusion_review_r3.py中的参数化三场景。修复应保留原始异常类型/原因或cause、明确零调用、无finished_at；不能修改gold/.env或宽容坏输入继续执行。

## 结论与下一轮

前276项保持通过；新增3项失败，即**276 passed / 3 failed**。原r1/r2冻结文件SHA与上轮manifest相等，提交r3全部SHA匹配；Ruff/format、OpenSpec strict、diff检查通过。本轮未修改实现或旧断言。

仅补完整的前置异常终态，不重做账本/归属/表片。下一轮只需要隔离入口测试，不需要PG-only、模型/embedding或语义整轮。交接handoff-phase-3-5.3-fixes-r3.md。
