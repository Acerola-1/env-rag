# 固定版本正式两轮交接 r2（修正采集 SQL 后继续原授权批次）

评分准备r4保持通过。用户方案1的最后两轮授权延续，实际付费运行尚未启动。本交接仅授权 SQL 修正后的新准备代次：一次替代只读映射采集，成功后原定两轮各一次，额度不变。原交接与准备包仍作为历史保存，请只使用此 r2 入口。

## 一次批次、固定输入

31正例+10反例×pg/local/fusion×两轮=246腿，两个独立run-dir。code/model/prompt/gold/环境字节保持同一新锚；已恢复DeepSeek，禁止换HY3/静默换模型。调用上限见prep/README：两轮keyword164、embedding656批、Qdrant1312、Neo4j1640、PG251904（每腿1024累计）、rerank82、answer42。每轮预算锁为这些值的一半；答案正例36+反例至多6。额度是已验应用账本口径，不填未经测量收费价格。

不增额、不额外健康探测、不重试/重跑挑样本、不改源码/提示/gold/旧锚/历史。此前改前全量round1不能拼进本次固定版本两轮。只允许恢复.env对应原有PG/Qdrant/Neo4j开发容器，卷不变、无initialize/建库/迁移；如需容器操作沿既有container规程。任何源/配置漂移保留拒绝证据停主agent，不现场回写锚。

## 步骤一：核对修正版并采集评分专用映射（原授权延续）

先验证preparation-manifest.json所有SHA及当前源谱系，目标三个真实目录必须不存在。干跑可执行：

```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python reports/pg-retrieval/phase-4-formal-two-rounds-prep-r2/run_round.py --dry-run
```

该命令只读配置与编译矩阵，不查询数据库。

仅允许在新目录 phase-4-formal-mapping-r2 只读执行一次；原 phase-4-formal-mapping-r1 保留，不清位、不覆盖。执行：

```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python reports/pg-retrieval/phase-4-formal-two-rounds-prep-r2/collect_mapping.py --authorized
```

只采固定gold27个unique unit评分键的真实关联，1数据SQL（最大20）＋守卫另列，0模型、0写库。gold目标不传给发现或答案，仅进入评分附件。完整27/27、unit内容SHA/长度与既存产物相符、前后身份一致，mapping/capture-manifest落新目录；代码的fixture/SQL静态审查不冒充实况，实际成功由本步验证。任一失败停主agent、不得付费跑后续、不得填数据/追加探测。

## 步骤二：首轮一次运行

```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python reports/pg-retrieval/phase-4-formal-two-rounds-prep-r2/run_round.py --round 1 --authorized
```

既有owning入口现场前后守卫、冷发现/精排/答案，不读旧runtime答案。输出phase-4-formal-fixed-round-1，保留全部123腿、原始服务凭证/上下文/response。失败/partial/ambiguous/missing是业务结果，不删除；hard leg failure、意外budget_failure、漂移或PG单腿峰值>512则停止，不启动二轮。neg-008原构造信封拒绝是预期观察，单列，不假装成员预算路径或整题能力通过。

首轮结束后离线做敏感扫描与逐文件SHA，写pilot-manifest.json（files字典必须覆盖实际评分消费的所有工件，含eval-runtime-latest）；读当前账本校验reserved/issued/unknown/caps，材料完整才可二轮。不触碰原输出值、不将模型拒绝改成功。

## 步骤三：二轮一次运行

在同锚、同source/catalog/search/gold/env且首轮身份/账本/证据完整时：

```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python reports/pg-retrieval/phase-4-formal-two-rounds-prep-r2/run_round.py --round 2 --authorized
```

独立目录phase-4-formal-fixed-round-2；不以同轮恢复/补题替代冷生成。按两个单轮帽复算整体上限；已有目录拒绝重复。发生失败同样停，无重试。

## 步骤四：同工件离线评分与人工审查

分别绑定run/round/new config-anchor/各轮pilot-manifest，使用已验r4评分器、单次mapping.json附件，输出到全新评分目录。示例（先mkdir新目录，round2替换对应路径与数字）：

```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python reports/pg-retrieval/phase-4-scoring-readiness-r4/assess_two_rounds.py --run-dir reports/pg-retrieval/phase-4-formal-fixed-round-1 --round 1 --anchor reports/pg-retrieval/phase-4-formal-two-rounds-prep-r2/config-anchor.json --manifest pilot-manifest.json --mapping reports/pg-retrieval/phase-4-formal-mapping-r2/mapping.json --out reports/pg-retrieval/phase-4-formal-fixed-assessment-1/adjudication-initial.json
```

未审语义保持PENDING，已证失败不能被人工救；所有合成/载体等须主agent基于实际交付人工核对，附录A和规范正文分列。执行方只列待审清单及实际输出，不代拟“未来已正确”结论。主agent提供绑定输出/response SHA的records后再落新adjudication-final，初版不覆盖；规则/字段/gold不变，无网络。

每轮93正例+30反例独立分母、按类别和路径记录集合expected/produced/missing/extra/citation/版本，拒绝与完整答案的行为分列。chunk@20、typed/doc覆盖、unit证据召回各自口径/分母，不能伪造全局统一@20；缺口仍待审，Gate4门槛未证则不通过。时延按可测字段p50/p95与样本数；发现inclusive/精排真实HTTP/展开unavailable/生成HTTP与复合阶段分列，不能相减补字段。

## 交付与停止点

两轮原工件、manifest与账户实际调用账本、逐轮待审与裁决、事实失败报告、时延、Gate4逐条证据建议交主agent最终裁决。受影响代码测试保持；源码未动不重复526。工作面Ruff/strict/diff/锁定环境、敏感扫描与历史保护复核，manifest最后写。

不自行勾6.2–6.5/Gate4、不切默认融合。主agent根据结果可认定未达标，保留基线与失败报告完成交付；不得再追加付费试跑。这是用户选择的最后一批。达标完成验收，不达标保留基线与失败报告收尾，不自动发起改进组或追加付费测试。采集中断同样保留未完成事实，停主agent，不能自行重试。

## 本次修正与纪律裁决

原采集报 UndefinedColumnError，前后守卫一致、付费调用0，属于主agent准备脚本缺陷，不归因执行或服务。SQL 和产物定位统一使用 doc_full.doc_name，其他 SQL 结构/范围/只读合同不变；线上成功仍待新单次采集确认。既往 nc TCP 握手属于交接外存活检查，记录为流程偏差，不要求补测或撤销现有证据；以后不做额外探测。不得把 doc_status.file_path 等字段与 doc_full 混淆。

首轮/二轮真实目录继续为 formal-fixed-round-1/2（均未启动），但 prepared-binding.generation 必须为新锚 phase4-fixed-improvements123-two-rounds-r2；映射引用统一改 r2。正式评分命令绑定本 r2 anchor。本次准备无新真实请求，执行方完成后交主agent评分与语义裁决。
