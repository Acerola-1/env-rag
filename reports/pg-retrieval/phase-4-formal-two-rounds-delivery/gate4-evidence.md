# Gate4 逐条证据建议（对照 design.md 验收最低标准表；门槛裁决权在主 agent）

固定版本两轮（phase4-fixed-improvements123-two-rounds-r2，DeepSeek，两轮机械裁决逐行一致）。数字均出自 delivery-round{1,2}.json 与 adjudication-initial.json，每题级明细可逐行回查。

| 指标 | 门槛 | 实测事实 | 建议 |
|---|---|---|---|
| 已确认文档身份/编号/版本定位 | 白名单正例 100% 正确，所有 unknown 明确 | file_enum PASS 5/6（pg/fusion，两轮同）；FAIL 题为 file-enum-004（引用 1 条未成立 + 集合缺项，如实 FAIL 未伪造）；fact-002 缺单位保持已知边界；unknown/self_code 无法确认处均显式空值交付 | **未达**（file-004 两轮 3 路复现；非 100%） |
| 已确认范围覆盖 | 正例 100% 范围单元被读取；全部反例无 false complete | unit 证据召回均值 pg 0.947 / local 0.960 / fusion 0.980（25 题分母）；正例 coverage complete 56/partial 31/ambiguous 6——partial/ambiguous 均如实非伪造；**反例 false complete：neg-005×3 两轮复现**（期望 ambiguous，交付跨 2 文档 complete），neg-003/004 complete 属其冻结期望内（neg-003 ok、neg-004 complete）不算违规 | **未达**（neg-005 false complete） |
| PG 候选证据 recall@20 | ≥0.90，记录漏掉的真实来源 | pg chunk@20 简单均值 0.9585（n=31，非官方聚合）；漏项明细已录（file-enum-004 pg union<1、syn 类个别）；fusion 0.9908、local usable@20 0.9516 | **达**（≥0.90，含漏项记录） |
| 三类 enum 集合完全正确率 | 各类别 ≥5/6，条目来源可验证 | pg 与 fusion：file 5/6、prose 5/6、table 5/6，两轮同，PASS 行均引用经独立重读；local：file 5、**prose 4/6**（prose-004/005 FAIL）、table 5 | pg/fusion **达**；local prose 未达 |
| 引用/混入违规 | 引用错误及违规混入为 0；缺失不得伪造 | 未成立引用 6 腿（file-enum-004×3、table-enum-003×3，各 1/2 条），掩码 3 行（数值碰撞 sanitizer，如实 gap 不假判）；跨 workspace/版本混入：0（两轮所有 FAIL 均含集合级 missing/extra 明细）；缺失处未伪造完整答案 | **未达**（引用错误 6>0；混入 0；伪造 0） |
| 融合增益 | 两轮 enum 均不低于 local；至少一类可复现修复案例；fact/synthesis 不下降 | enum：fusion≥local 两轮同（prose 5>4，其余 =5）；**可复现修复案例：prose-enum-004 local FAIL→fusion PASS 两轮**；fact PASS：pg/fusion 0（6 PENDING 载体待审+1 FAIL）、local 0（7 FAIL）——0→0 不下降；synthesis 三路两轮均 0（HTTP 实发 11/轮、合同全拒，开放质量问题）不下降 | **达**（按字面三项；synthesis 0 为全路径共同短板） |
| 延迟与降级 | 分阶段 p50/p95+样本量+降级次数 | discovery（fusion 含精排 inclusive）R1 2670/8044ms、R2 2552/7441ms（n=120）；total 4780/11533、4489/10606；answer_stage 1610/5860、1606/5572；answer_http（仅 model_calls==1，n=11/轮）4434/7811、4265/6600；expansion unavailable 无字段、未减法造数；精排 degraded 0；预算拒绝 3/轮=仅 neg-008 构造信封（单列，未冒充成员预算或整题通过） | **达**（报告口径） |

## 汇总建议

七项中四项达（其中两项为"达"于 pg/fusion 主路、local 一项未达），**三项未达：身份 100%、反例无 false complete、引用违规 0**。按交接"不达标保留基线与失败报告收尾，不自动开启改进组、不追加付费试跑、不切默认融合、不勾 6.2–6.5/Gate4"——建议 Gate4 判**未达标**，本批材料（含 69 行/轮待审清单与 SHA 绑定）交主 agent 人工核对与最终裁决；若主 agent 对 12 行 fact 载体与 synthesis 的语义抽审改变 FAIL/PENDING 归属，可在 adjudication-final 中用绑定记录复核，**FAIL 的 false complete 与引用违规属机械证据，不可被人工救**。
