# 四腿fresh local实况裁决（2026-10-09）

**本批通过。** 分母为3正例+1反例；改进组1–3的PG/local有界现场核验完成。Gate3/6.1保持，完整第二轮及6.2/6.3/Gate4继续暂停，默认策略不切换。

Reviewer仅离线读取原始终态、发现输入、请求账本与原解析文件；0真实网络/数据库/模型/embedding/rerank请求、0数据库写入，无源码/历史/.env/gold/旧锚/冻结变更。已验收代码未变，不重复526工程全套。

## 独立验收

复算入口`verify_offline.py`：本批23项manifest匹配，各eval/answer身份before==after，来源/目录run+snapshot/search/gold/env/八表与批准期望一致，finished_at存在，无运行级或腿级failure。外部驱动/锚/预算及6项已验收源码SHA匹配。

账本按每条reserved/issued事件和每腿服务凭证交叉重数：keyword LLM4、embedding11、Qdrant数据调用11、Neo4j读取20、PG包装缝计量439；预留/实发相等、拒绝0。关键词call均为keyword_extraction/success，各腿vector-similarity与有效向量完整覆盖记录一致，无degraded/refused_candidates。答案模型与精排0。

这些数字按既有账本覆盖声明解释：Qdrant query_points/retrieve、Neo4j实际session.run和PG包装缝计量，不是穷尽所有网络传输。准备期集合元数据核对、连接/关闭、运行级身份读取等已声明排除项另列；PG仍有组+SQL保守双计。

| 腿 | 实际交付及独立核对 | 现场噪声证据 |
|---|---|---|
| prose-enum-001 | 3.1–3.4恰4项，术语与gold对应，4条完整文本按raw unit声明跨度切片后仅去首尾空白逐字相等 | GB8978及9bb1确在本次usable中，分别进入rejected/unresolved、flags有原因，均不在最终items |
| prose-enum-006 | 4.2恰1项、48字符，完整raw跨度相等且此题文本确与gold正文相等 | 2026兄弟版本、HJ2.2及另一unknown文档确在发现中；均排除/未确认，最终仅2012目标 |
| neg-004 | 恰13行，seq1–13，完整cells与表1固定期望相等；13/13按绑定物理片raw grid行号回读相等，确为两片 | GB18466确在发现中、以canonical编号不符明确排除；引用真实未被拿来授权外来表格 |
| file-enum-005 | 当前目录3份集合与gold零差，2份self_code仍None；引用非空snapshot并经owning目录复读verified/reverified，guard stable | pg.search_id空串、targets_resolved/typed_targets空、discovery_only/targets_confirmed=False如实保持；没有把local发现自报成范围 |

四腿当前输入中的每个usable正文长度/SHA匹配，工作区正确，完整路径留存；发现输入未携带已确认目标字段。目标确认与噪声拒绝是本次真实发布形态的观察，Reviewer不是用fixture补造噪声。5条全文raw跨度及13表行的独立核验在`offline-verification.json`。

25份明确选定保护清单1180条零漂移；原六份已恢复终态SHA保持。执行方1316条全库扫描作为其提交记录保留，不冒充Reviewer核验相同全库数量。模型/提示/源码/语料保持原期望。

## 当前进度与收尾边界

正式清单39项已勾35项（约90%）；剩余6.2两轮同配置对照、6.3质量/时延与降级汇总、6.4 Gate4裁决、6.5最终检查和证据交付。最后四项工作量较重，按最终可交付粗估约75–80%，这不是质量分数或工时保证。

当前在**Phase4真实评测与改进后的验收收尾**：评测入口、三组有界工程改进及PG/local样本现场复验完成；改后版本的全白名单两轮结果尚不存在，旧首轮与改后单轮不能合称同配置两轮。fusion整合后的完整质量与合成/待审题仍需最终报告。

下一组只按`handoff-phase-4-finalization-offline.md`做纯离线收尾准备：剩余问题对照账、评分新代方案、固定版本两轮矩阵/预算及结束条件，不追加真实请求、不改代码/提示/评分规则。避免继续零散付费试跑；提交后再由主agent决定最小必要工程或正式评测。

Gate4如未达标，按既定设计保留已验证基线、失败报告及默认策略，仍完成实际结果的最终交付；不得为了宣称融合达标无限增加修复或替换困难题。
