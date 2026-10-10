# 改进组1–3后：五腿PG只读实况与预算核验

改进组3 F1工程复审通过，改进组1/2保持。**可直接执行本交接，无需再问授权；范围仅五腿PG、零模型/零付费服务、只读来源。** 不跑完整第二轮，不新增local/fusion发现、精排或答案模型请求，不重试、不追加额度、不做健康探测/初始化/建索引/迁移。

## 新代配置与运行入口

主agent另建新锚`reports/pg-retrieval/phase-4/phase-4-config-anchor-improvements123-pg-r1.json`，明确登记已验收代码变更；旧锚及历史代次原样保留。source/catalog/search/gold/模型/提示/参数身份保持原期望，**并未现场重新采集**，实际运行仍须前后守卫核实，不得用锚冒充现场观察。DeepSeek保持用户恢复后的配置，但本批不调用它。

新预算`reports/pg-retrieval/phase-4/improvements123-pg-validation-budget.json`：PG每腿1024、整批5120；keyword/embedding/Qdrant/Neo4j/rerank/answer所有总cap=0，单批限制原样。1024是有限护栏，不是已测需求。运行级身份采集仍按既有账本排除口径单列，不声称所有PG线传输都在5120中。

标准CLI目前只读取旧默认锚，因此本次使用review目录内小驱动器：先对新锚执行**既有**`validate_phase4_anchor`及附加代码SHA检查，再进入**既有**`run_evaluation` owning入口；没有patch源码/账本，没有现场回写expected，也不跳过守卫。已做零后端dry-run；完整工程526、冻结42/35已验证，无需为这个文档组再全跑一遍。

先核对本轮review清单/新锚/预算/驱动SHA，然后仅执行一次：

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python reports/pg-retrieval/phase-4-improvement-3-review-r2/run_pg_validation.py --report-dir reports/pg-retrieval/phase-4-improvements123-pg-validation-r1
```

目录不存在或未用过才运行；失败保留终态，不复用已完成目录。源码/.env/gold/旧锚/历史/冻结均不修改。若服务不可连接、守卫不符或额度拒绝，记录并停，不修复容器/更换配置绕过。

## 五腿与必须核对的实况

| 题目/路径 | 本次目的 |
|---|---|
| file-enum-005/pg | 目录base+related完整三份，未知self_code不伪造；每条目录快照与独立回读、最终发布集合守卫有证据 |
| file-enum-002/pg | 年报完整五份，现行基础分页及最终复读不丢项 |
| prose-enum-002/pg | 条款边界排除无关独立表格尾巴，完整声明与坐标回读相等；4.1.2既有离线128字观察现场核实 |
| prose-enum-003/pg | 恰四条，4.3.4既有离线53字观察现场核实，不夹表1–5 HTML |
| prose-enum-006/pg | 4.2整体条款保持，既有离线48字观察现场核实、不读兄弟条款/无关表尾 |

原问题/候选由本批PG发现，gold只作事后missing/extra/内容核对，不注入答案。现场若与离线数值不同须查原始正文与坐标并如实记录，不能按固定长度切文本。每条正文须按声明的raw unit跨度完整逐字回读；表格内属于条款的内容仍按已验收规则保留。

本批**不能**证明local路径混入修复已在fresh local发现上验证，或local空search_id已在现场完整枚举；这两项已有离线owning证据保持，未来再安排有界local验证。本批也不构成31题指标、融合增益或第二轮。

## 发布与预算报告

- 五腿均到answer阶段；逐腿app coverage和独立内容/集合裁决分列，complete不替代正确性。
- 逐腿PG reserved/issued/拒绝、累计峰值、守卫复读可观测计量；预留不当实发。非PG服务实发必须全0。
- 若无budget_failure/腿级failure/身份漂移且单腿PG峰值≤512，可报告“有限缓冲门槛满足”，**仍不自动启动local/fusion或整轮**。否则保留真实下界、具体拒绝原因，不自行提额。
- 来源/目录/索引/gold/env前后身份，全文/范围/引用、时延样本量及账本排除口径；当前run原始终态，敏感扫描，新的SHA清单。

六份旧报告覆盖事件已由主agent从残留临时原件按原manifest SHA逐字恢复；覆盖版在review目录保留，双方历史报告不回写。以后任何驱动OUT必须先核对是本轮新目录。

提交后停主agent实况验收，6.2/6.3/Gate4不勾选，默认策略不切换。零付费核验结束后再决定local有界试验与后续质量改进；本交接不预授权第二轮/123/246腿。
