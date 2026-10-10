# 6.2 PG预算标定与同范围复跑（主agent，2026-10-08）

pilot-r1证据验收：31项SHA匹配，9腿均因PG信封24停止；关键词3/3、embedding8/8、Qdrant8/8、Neo4j15/15成功，local30候选内容/身份工件核对通过；精排与答案均未实际发出。预算拦截通过，端到端与语义尚未验证。24由主agent设定偏低，不是执行agent未遵守交接，也不要求重构已验收代码。

6.1/Gate3保持，6.2不勾选。本交接可直接执行以下两阶段，无需重复授权DeepSeek或逐条请求。完整246腿仍不在本交接范围。

## 口径与护栏

现行源码从begin_question到finally只有**一个累计PG信封**，发现、来源回读、精排守卫、答案守卫/范围读取共享，不能把discovery与answer当作两个独立24额度。local另有组+SQL保守双计；不改账本、不取消守卫、不改已验收组件。

新PG护栏设为**每腿1024**，是标定期有限上限，**不是已测得的需求或性能保证**。先零模型实测，再决定是否进入已限定的9腿。dry-run中的PG×2文案是既有保守编译口径，不授予第二个信封；总cap取实际累计上限。标定与复跑分别新预算/新目录，绝不覆盖r1。

## A：只读PG标定，3腿，零模型与付费服务

```sh
.venv/bin/env-rag-final eval-run --round 1 --paths pg --query-id fact-002,prose-enum-001,syn-004 --budgets reports/pg-retrieval/phase-4/pilot-r2-pg-calibration-budget.json --report-dir reports/pg-retrieval/phase-4-pilot-r2-pg-calibration
```

**不要加--allow-model。** keyword/embedding/Qdrant/Neo4j/rerank/answer总cap全部0；PG每腿1024，整批3072。源码/模型/来源/gold/提示/当前锚不变；运行级身份读取按既有排除口径另列，不声称所有PG线传输都在3072内。

从真实账本按round/path/qid统计PG reserved/issued，给出每腿累计读数、最终答案阶段是否到达、范围/回读情况。若既有工件足以区分发现与答案SQL则分列，否则保留累计值，**不改代码插桩**。syn-004因未授权答案模型而incomplete/model_not_authorized是本标定的预期边界，不等于链路失败；fact-002缺单位partial保持。

**进入B的条件全部满足**：三腿均有answer阶段记录；无budget_failure、运行级/腿级failure或身份漂移；LLM/embedding/Qdrant/Neo4j/rerank实发均0；每腿PG累计reserved最大值≤512（为额外local/精排/候选差异保留至少512缓冲）。不要求答案complete来放行，不能删除保守partial。

任一条件不满足，保留工件并停主agent复审，**不得执行B、追加额度或重试A**。1024若仍不够就报告下界，不能自升无界。

## B：同3题×3路，单次9腿

A通过条件后直接执行一次：

```sh
.venv/bin/env-rag-final eval-run --round 1 --paths pg,local,fusion --query-id fact-002,prose-enum-001,syn-004 --allow-model --budgets reports/pg-retrieval/phase-4/pilot-r2-budget.json --report-dir reports/pg-retrieval/phase-4-pilot-r2
```

仅PG cap改变为每腿1024、整批9216；**其它服务保持r1原上限**：keyword6、embedding24批（每批32文本/64000字符）、Qdrant48、Neo4j60、rerank3、answer3；批次完成即停，不作编排/手工追加重试或健康探测。已有单题失败隔离与预算增量合同保持，被吞拒绝也必须显式budget_failure/partial。

所有答案均为本轮冷生成，不用r1或Gate3答案填入。来源候选保持三路独立，fresh discovery不冒充回放；正文/资料性附录分列。syn-004人工核对两环境要素是否被真正回答、附录是否被误升为规范要求；fact-002单位缺源partial不因希望得到complete而补造。服务失败与业务partial分开报告。

## 交付与边界

保留r1及其31项manifest原样。分别交付A标定报告与B试跑报告（若B跳过则写具体门槛失败原因）、新runtime/输入/精排/答案、逐腿PG读数、预留/实发差异与服务凭证、SHA manifest、来源/config前后守卫与敏感值扫描。**reserved不等于issued**：r1答案曾预留1却实发0，必须如实区分；拒绝事件0只说明该次拒绝未转发，不抹除此前已发生调用。

不写生产PG/Qdrant/Neo4j/MinerU；不修改.env/锚/源码/冻结/gold/历史，不运行初始化/索引构建。不为这次预算文件调整重跑全套454测试；先做必要离线配置验证/dry-run，再执行已限定步骤。最终9腿即使成功也不代表31题指标、不勾6.2、不自行扩批，提交主agent验收。
