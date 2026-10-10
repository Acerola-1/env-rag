# 五腿PG实况裁决（2026-10-09）

**本批通过，有限缓冲门槛满足。** 改进组1–3、Gate3/6.1保持；本批不是第二轮，不满足6.2/6.3/Gate4完成条件，不切默认融合。

Reviewer仅离线读取工件与原解析产物，0网络/数据库/模型/embedding/rerank请求、0数据库写入；未改源码、历史工件、gold、旧锚、.env或冻结测试。代码与已验收SHA相同，不重复526工程全套。

## 独立核对

可复算入口`verify_offline.py`：提交42项manifest逐字匹配；eval及各answer的前后身份一致，source/catalog run+snapshot/search/gold/env/八表计数与期望一致，运行有完成终态，无腿级或运行级failure。9项驱动/锚/预算/已验收源码外部锚匹配。

账本逐事件重数：仅pg/reserved和pg/issued，均556，拒绝0；逐腿91/111/128/118/108，峰值128≤512，均在1024/腿和5120/批范围内。5个answer运行的model_calls_used均0。账本口径继续是已声明包装缝的计量，运行级身份采集、建连/关闭等排除项另列，不宣称所有线传输均在556中。

| 题目 | 实际交付 | Reviewer独立内容核对 |
|---|---|---|
| file-enum-002 | 5份 | doc_id集合与gold完全相等，名称年份2021–2025；文件名哈希身份、非空workspace/snapshot/doc引用一致 |
| file-enum-005 | 3份 | 原标准+两份修改单集合与gold相等；两份self_code仍None，attribution真；并集3/3，base1、相关证据2、guard stable，目录复读verified/reverified |
| prose-enum-002 | 4.1.1、4.1.2 | 各自目标doc与条款正确，完整文本按raw unit声明跨度切片后仅去首尾空白逐字相等，4.1.2为128字符 |
| prose-enum-003 | 4.3.1–4.3.4 | 恰四条，全部按raw unit坐标完整回读；4.3.4为53字符，无表1–5 HTML尾巴 |
| prose-enum-006 | 4.2 | 恰一条，48字符与raw跨度相等、所需正文与gold一致，不混4.3/4.4或无关表格 |

7条正文全量回读通过，所需gold正文全部出现在对应条款，不是仅凭生产端verified布尔判过。文件当前目录行的现场独立复读由已验收answer入口完成，Reviewer不再次查库；名称/hash/gold集合与身份链另做离线核对。

文件并集读取不依赖search层的结论沿用已验收源码SHA与守卫调用链、离线读取计量证据；本批通用PG账本未逐SQL标表，不能据此宣称整个PG发现链路也不读取搜索索引。local fresh发现上的混入/空search_id修复仍未由本批验证。

## 报告措辞订正（非阻断）

提交称“所有正文与gold正文逐字一致”过宽，提交自己的`text_norm_matches_gold_body`也显示002和003多项false。所需正文均完整，但交付还包含来源条款编号、原文句号；4.1.2保留了来源页眉`GB 18466 — 2005`。Reviewer核对的是**完整交付与声明坐标的原文一致、正确条款覆盖全部必要内容**；不把这些条目算作“完整字符串等于gold body”。006的48字符确为同一正文字符串。此处不修改已验收实现或gold，也不要求为报告措辞返工；本裁决为当前准确口径。

23份明确选定保护清单共1141条零漂移，旧六份终态仍与原manifest SHA相等。执行方1277条全库扫描作为其提交记录保留，不冒充Reviewer重新核验了同一全库数量。原源/提示/模型/config与历史评分保护保持。

## 下一步

批准**一次四腿fresh local有界复验**，具体按`handoff-phase-4-improvements123-local-validation.md`。只查此前三个混入/漏项案例与file005/local完整集合，不开fusion、精排或合成。上限keyword4、embedding16、Qdrant32、Neo4j40、PG4096，rerank/答案模型0；费用未估算单价，实际次数以账本为准，不把预留当实发。

另建local专属新锚/预算，旧PG锚和所有旧代次不变；驱动先调用原完整validator和附加代码锚检查，再调用未改的owning `run_evaluation`，无旧答案/候选注入。已执行4行矩阵dry-run，backend_fetches0。实际请求本轮未执行，由执行agent按交接执行一次后停主agent实况验收。若发现不足或守卫/预算/服务失败，保留真实非complete，不换模型、不补PG、不追加重试或额度。完整第二轮继续暂停。
