# 仅完成F3-a的前置异常终态覆盖

当前F3-b已通过；F1/F2/F4与原两轮独立断言保持。5.3只剩同一个前置边界覆盖缺口：try包住操作，except仍未覆盖结构/配置的KeyError、TypeError、ValueError。报告phase-3-fusion-review-r3/review.md。

在既有前置窗口内，让所有普通Exception拒绝都通过统一零调用失败终态，再保留原异常/cause拒绝。可以保留特殊类型的阶段分类，增加统一兜底；不要吞掉异常继续执行，也不要捕获KeyboardInterrupt/SystemExit之类BaseException。错误类型与原因须可审计，不输出配置凭据值。损坏输入和非数值维度不能因异常类型不在列举中而无报告。

冻结tests/test_fusion_review_r3.py三场景：缺questions→KeyError、questions=null→TypeError、非整数EMBEDDING_DIM→ValueError。各自零后端接触、终态call_records=[]、原类型可追溯、无finished_at。原276项与新增3项全部通过，r1/r2断言不弱化。

仅隔离入口验证，**不再真实PG-only/模型/embedding复跑**。保持rev2已通过正式正例，gold/.env/数据库/目录/索引不变。Ruff/format/OpenSpec strict/diff/凭据扫描；最终manifest列出当前SHA，停5.3待复审，不进入5.4–5.6/Gate3。
