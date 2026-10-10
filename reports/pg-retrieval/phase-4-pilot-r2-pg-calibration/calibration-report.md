# 阶段 A：只读 PG 标定报告（pilot-r2-pg-calibration，2026-10-08）

按 `handoff-phase-4-6.2-pilot-r2.md` §A：3 题 × pg 单路径 = 3 腿，**零模型、零付费服务**（keyword/embedding/Qdrant/Neo4j/rerank/answer 全部 cap 0），PG 每腿信封 1024 / 整批 3072；预算文件与两份输出目录由主 agent 预置，命令逐字一致、单次运行、exit 0；未写库、未初始化、生产只读。

## 结果：放行门槛逐条满足（允许进入 B）

| 条件 | 实测 | 判定 |
|---|---|---|
| 三腿均有 answer 阶段记录 | 3/3 | ✅ |
| 无 budget_failure / 腿级或运行级 failure / 身份漂移 | 全 0；pre/post matches_frozen=true、drift=[] | ✅ |
| LLM/embedding/Qdrant/Neo4j/rerank/answer 实发均 0 | issued_total 仅 `pg:342`；answer_llm 未预留（无 --allow-model） | ✅ |
| 每腿 PG 累计 reserved 最大值 ≤ 512 | **89 / 109 / 144**（max 144，缓冲 ≥ 880） | ✅ |
| 拒绝事件 | 0（reserved==issued 全腿） | ✅ |

## 逐腿 PG 读数（累计，含组+语句双计口径不变）

| 腿 | reserved | issued | 答案阶段 | 业务终态（如实） |
|---|---:|---:|---|---|
| r1/pg/fact-002 | 89 | 89 | 到达 | **partial**（缺单位边界保持；1 项交付、13 项复核 0 问题） |
| r1/pg/prose-enum-001 | 109 | 109 | 到达 | **complete**（4 项、复核 0 问题） |
| r1/pg/syn-004 | 144 | 144 | 到达 | **partial / model_not_authorized**（标定的预期边界，非链路失败；8 项范围复核 0 问题） |

标定证明：同一条 pg 路径在信封 1024 下全程无拒绝地到达答案阶段并完成只读生成合同；B 阶段复跑中三条 pg 腿读数与标定**逐值一致**（89/109/144，确定性佐证）。

按交接：1024 是标定期有限上限，不是已测得需求；本批单腿峰值 176（B 内最大值）仍非外推依据。工件见本目录 `eval-runtime-*`、`legs/`、`inputs/`、`pilot-manifest.json`；敏感值扫描 0 命中。
