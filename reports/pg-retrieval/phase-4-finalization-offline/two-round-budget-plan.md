# 固定改后版本两轮计划与预算提案（dry-run 编译校对）

矩阵经未改 owning 入口 `eval-run --dry-run --rounds 2` 编译到本目录
`two-round-dry-run/execution-matrix.json`（246 行=41 题×3 路径×2 轮，正例
186/反例 60 分列；与已冻结 6.1 矩阵逐行相等）。**backend_fetches=0，
本组未发任何真实请求。** 预算提案为 `two-round-budget-proposal.json`
（信封=已验收两批复验批次的现行值：keyword 1、embedding 4、Qdrant 8、
Neo4j 10、PG 1024/腿），非网络授权。**

## 编译上界 vs 交接提案

| 服务 | 交接提案 | dry-run 编译（effective_bound） | 差异说明 |
|---|---:|---:|---|
| keyword LLM | ≤164 | 164 | 一致（164 条 local/fusion 腿各 1） |
| embedding | ≤656 批 | 656 | 一致（164 腿×4 信封，含保守双计） |
| Qdrant | ≤1312 | 1312 | 一致（164×8） |
| Neo4j | ≤1640 | 1640 | 一致（164×10） |
| PG | 每腿 1024 / 两轮 ≤251904 | envelope 503808、total cap 251904、effective **251904** | 信封×2（发现+答案各自可满 1024）是保守文案；总帽 251904=246 腿×1024 生效 |
| 精排 | ≤82 | 82 | 一致（仅 fusion 腿 41×2） |
| 答案模型 | 正例≤36+反例≤6（总≤42） | 42 | 一致；正例 synthesis 6 题×3 路×2 轮=36、反例路由≤6 |

对已冻结 6.1 `budget-upper-bounds.json` 的差：PG effective 3936→251904，
**这是信封标定的差异而非规则变化**（旧编译按每腿 PG 24×2=48；现行按已验收
批次实发峰值现场证据钉 1024/腿，与 1024 相容且未放大 top-k/上下文）。其余
服务编译值与 6.1 完全一致。

## 实际执行时的强制分列（沿用已验收合同，不改排除项/守卫）

- reserved / issued / refusal 三态分列，预留不当实发；refusal 零实发。
- 单腿 PG 峰值 >512 或出现 budget_failure/腿级 failure/身份漂移 → 保留真实
  下界与拒绝原因停主 agent，不自行提额。
- answer 缺前置条件时 allow_model=False 只读运行，HTTP 0 计 0、skip 分列。
- 无未经测量的费用单价估算；实际请求数以账本为准。

## 成本较低的备选收尾路径（若两轮显示不达标）

保留已验收基线（round-1 + 改进组 1–3 + PG/local 有界现场证据），交付
Gate 4 未通过的审查与失败报告，不强行启用默认融合、不追加付费试跑。
若为此需要少量改工程/评分接口或时延采集，先列具体根因、最小边界与正负
验收交主 agent 裁决，本组未动任何代码。
