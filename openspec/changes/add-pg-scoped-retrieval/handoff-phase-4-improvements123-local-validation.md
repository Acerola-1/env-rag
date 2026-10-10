# 四腿local有界实况复验（2026-10-09）

五腿PG批已由主agent离线独立实况验收通过，PG计量峰值128≤512、有限缓冲门槛满足。**可直接按本交接执行一次四腿fresh local试验，无需再次询问逐项授权。** 这次确有关键词模型和embedding调用，数量上限如下；不包含答案模型、精排、fusion、第二轮或整批扩展。

## 范围与上限

只运行local单一路径、单轮、以下四题：

| 题目 | 本轮应独立核验 |
|---|---|
| prose-enum-001 | 原17项混入应收敛为目标标准3.1–3.4四项，无他文档13项；完整声明/raw坐标逐项回读 |
| prose-enum-006 | 目标GB3095-2012的4.2一项，排除他文档12项和兄弟条款；目标正文48字符是此前观察，不用固定长度切文本 |
| neg-004 | 目标GB8978表1的13项/13原始行，其它文档31项不得混入；真实引用不替代目标归属/集合正确性 |
| file-enum-005 | 原问题含修改单：当前目录完整三份，empty search_id如实保持；两份unknown self_code不伪造，最终并集3/3与非空snapshot/目录复读一致 |

**这是3正例+1反例的有界验收，分母分列，不是31题质量指标。** 四题fresh发现不保证必命中：如果发现不足，要如实发布保守状态并指出缺口，不能用gold/PG/历史答案补候选、强塞targets_resolved或自报范围确认。

预算文件`reports/pg-retrieval/phase-4/improvements123-local-validation-budget.json`：

| 计量服务 | 每腿 | 全批 |
|---|---:|---:|
| keyword LLM | 1 | 4 |
| embedding | 4批 | 16批 |
| Qdrant | 8 | 32 |
| Neo4j | 10 | 40 |
| PG | 1024 | 4096 |
| rerank / answer LLM | 禁止 | 0 |

embedding单批最多32文本/64000字符，模型与2560维不变；现行预留/实发/拒绝及组+SQL保守双计、排除口径保持。无需未经测量的价格估算。额度拒绝/服务失败或模型抽词差异全部按合同落档，不临时提额、不补问模型、不作手工/编排追加重试或健康探测。

## 配置与一次运行

local专属新锚`phase-4-config-anchor-improvements123-local-r1.json`由主agent备好；旧PG锚/默认锚/历史配置均不改。DeepSeek恢复后的keyword配置不换，答案模型虽然在配置中仍不授权调用。source/catalog/search/gold/env及代码/提示期望保持，前后实际守卫照常核实，不能据新锚宣称已现场观察。

驱动`reports/pg-retrieval/phase-4-improvements123-pg-validation-review/run_local_validation.py`先对新锚执行原`validate_phase4_anchor`及附加代码SHA核对，再进入未改的`run_evaluation`总入口。四行dry-run已经backend_fetches0；不用重跑未改的526工程全套。

核对review-manifest中的锚/预算/驱动/交接SHA与受保护代码，然后只执行一次：

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python reports/pg-retrieval/phase-4-improvements123-pg-validation-review/run_local_validation.py --report-dir reports/pg-retrieval/phase-4-improvements123-local-validation-r1
```

必须是新目录。既有连接/服务若停机，仅按已验收规程恢复原有开发栈，不重建卷、不运行存储initialize/DDL。PG仍为项目`lightrag-postgres`/5432，勿切到其它项目15432库；.env不改。不新增探测调用。

## 证据与裁决

1. 保存fresh关键词回执、真实vector选择/降级凭证、完整chunk组合身份和PG全文回读、所有发现路径。发现/目标确认/被排除项/展开/答案分列。若本次发现碰巧没有噪声，不能声称现场观察到了主动排除噪声；可保留已验收构造证据。
2. 所有已确认目标必须经现行canonical门，版本按题面，未知编号仅走已验收双向归属证据；不能把local发现自报成确认范围。file005目录并集与检索top-k/search_id解耦，发现召回不回填。
3. 对正文按完整声明的raw单元跨度、表格按raw grid行坐标、文件按目录身份/实际snapshot独立核验；gold仅事后比missing/extra及内容。app complete、范围完整、集合正确和引用真实分别列，不拿一个代替其它。
4. 预算账本逐腿/逐服务reserved与issued及拒绝分列，答案模型/精排必须0。前后身份漂移或非零腿失败保留终态，运行级错误非零；服务层成功不折算答案正确。
5. 新目录交付报告、4腿原始终态/输入/回执、逐项裁决、账本、保护清单与敏感扫描。PG批的措辞勘误沿用主agent裁决：全文与声明源相等不等于全文与gold body字符串相等；条款号/来源页眉要如实记录。

代码/.env/gold/旧锚/冻结/历史目录一字不动。任何旧脚本OUT先核对本轮新目录，不能覆盖已保护报告。若有失败，保留失败，不删题、不挑成功代次、不改评分工具迎合。

**四腿完成即停主agent实况验收。** 本交接不自动放行fusion、有答案模型的合成改进、第二轮123/246腿或6.2/6.3/Gate4，不切默认路径。
