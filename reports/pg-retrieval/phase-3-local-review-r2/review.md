# 5.2 第二轮独立验收：未通过，收敛为 M1–M3

日期：2026-10-07。只审查 L1–L5 本轮修改及必要调用链。**5.2仍未通过；下一组只修M1–M3，5.3–5.6/Gate3不进入。5.1与Gate2保持通过。**

## 证据与已修复部分

- 提交五项 SHA 与当前文件匹配；首轮独立十项验收文件 SHA 未变，10/10通过。原238项完整通过。本轮新增8项：7失败/1通过；完整结果239 passed/7 failed，详见 acceptance-tests.txt / all-tests.txt。没有删除、弱化旧断言或修改应用实现。
- 发布存储 initialize 已从生产接入移除；既有集合读取元数据、模型/映射前置校验、真实 src_tgt 边端点、最终候选预算及发布包候选函数接入已可确认。正常真实类绑定反例中两个客户端均关闭，不再把首轮的“正常路径不关闭”作为未修结论。
- OCR仅本地预览与规则解析，未调用外部评审模型。范围与逐文件跳过理由见coverage.json；不重新验收前期阶段。
- 主agent现场只读核对：八表221/5709/279/16514/65527/221/221/119575、内容指纹、catalog run/snapshot、search、gold、env前后无漂移，冻结匹配。Qdrant5709/65526/119574点、2560d与Neo4j base66069节点/121819关系符合提交记录。原生客户端只读查询，没有initialize、写库或实际模型请求，见live-inventory.json。
- Ruff/format、OpenSpec strict、diff检查通过。尚有入口反例失败，因此没有重复执行真实模型子集；本轮0 embedding/LLM请求、0答案生成、0目录/索引重建。

## M1 / P1：后置守卫没有比较 before/after，失败终态未持久化

对应原L3/L4，位置：`local_adapter.py:1143–1179`，调用的`compat_runtime._identity_mismatch`只检查env存在性。

后置逻辑仅检查post.matches_frozen。该匹配函数不比较env字节SHA，且run_frozen没有调用前后漂移比较。**只有env_sha从before变化为after、其余冻结字段完全相同的正式入口用例仍成功返回**。这违反本轮“finally后置drift核对”的陈述；真实一次未漂移不能替代变化时的拒绝行为。

fetch失败时，代码先_write_failure，再执行finally采集post；之后直接raise，没有把加入identity_after/identity_after_error的report再次写盘。**独立入口反例中post确实执行，latest失败文件却没有identity_after**。已有成功结果和失败服务边界记录也没有进入统一失败输出，不能据当前失败报告核查运行终态。

修复：比较完整实际before/after（source、计数、catalog run+snapshot、search、gold、env），所有post采集/漂移错误可见。统一终态在post和清理后写盘再拒绝；保留工作失败、post失败及已完成请求/失败调用记录，不覆盖原错误，也不写finished_at。未知query_id与本地gold/config校验尽量先于不必要的后端读取，保留原前置拒绝合同。

## M2 / P1：服务边界未覆盖真实Qdrant，降级标签错误且复用时混账

对应原L4，位置：`local_adapter.py:537–541`、628–708、782–799、1002–1016。

1. **每请求独立的陈述未成立**：boundary和service_call_counters只在__init__建立，fetch没有重置。相同adapter两次正常请求，第二次by_service.neo4j.attempt=2，第一次=1；第二次call_records也含第一次记录。正式fetch反例失败。
2. **Qdrant无实际调用凭证**：实际安装的Qdrant读取方法+假原生客户端确实执行query_points/retrieve，但call_records无一条service=qdrant。qdrant_queries仍在assembly逻辑外围加1。提交真实运行的by_service也没有qdrant；flat embedding/LLM/Neo4j都为0，与其自身by_service计数相矛盾。Neo4j/PG的外层helper分组与实际底层读取混在同一聚合中，须定义并区分group与实际request/SQL。
3. **缺向量仍标vector-similarity**：真实发布helper因retrieve返回空向量而WEIGHT兜底，候选PG验证可以通过，但fetch只检查embedding失败，仍把sorting_sources.chunk_pick设为vector-similarity。独立正式入口反例失败。
4. **Qdrant超时继续无失败凭证**：实际Qdrant.get_vectors_by_ids内部吞TimeoutError返回空集合；目前embedding边界捕获不到，call_records仍无qdrant失败，独立正式入口反例失败。不能把PG verified当服务成功或向量排序成功。

修复：每次fetch独立账本；在真实底层读取/模型边界记录attempt/success/failure/耗时与必要去凭据请求、结果摘要，分组统计另列。不依赖已吞异常的helper返回值推断成功；记录每个选择阶段的vector/WEIGHT/truncation/empty/error原因并正确聚合，所有缺向量/读取错误明确degraded。CLI显示采用同一实际计数来源，不能一处13次、另一处0次。

另外，assembly先执行一次VECTOR，然后release entity/relation函数再执行各自选取，提交13次embedding包含重复发现选择。来源追踪可以从source_id构建，不必为追踪重复请求模型。请在本组一起移除不必要选择调用或给出必要性，优先让生产选择由release函数完成；预算及来源保留不变。它是原L4“只执行必要调用”的落实，不要求另做质量评测。

## M3 / P2：binding内部部分创建没有资源边界

对应原L5，位置：`local_adapter.py:390–407`、fetch资源登记574–588。

原生QdrantClient先创建，随后构造storage；只有binding完整返回才登记到fetch的resources。**实际发布类构造在client创建后抛错的正式fetch反例中，已创建client未关闭**。部分元数据形状读取失败也位于显式close分支之外。已有正常清理通过，不能证明部分创建回收。

修复：binding从客户端成功创建起立即拥有try/finally或上下文边界；在元数据/构造/锁绑定任何失败时close，成功后明确转移到fetch。后续资源失败仍关闭前面的资源。生产清理真正close-only；当前在client.close之后又调用发布storage.finalize，虽然正常空队列未观察到写入，该finalize仍含flush逻辑，应移除生产flush接入，待写队列非空也要拒绝flush并关闭连接，不能continue跳过close。

## 边界与下一步

本轮是原L3/L4/L5未完整落实的反例，不是推进到融合或追加语义质量门槛。首轮L1/L2主要问题已修，不要求重复实现。提交40/40 PG候选验证保留为执行agent观测；root本轮没有重新生成这些候选或批准新增质量指标。neg-001允许发现相邻版本，但保留missing答案期望。

补正交接：`openspec/changes/add-pg-scoped-retrieval/handoff-phase-3-5.2-fixes-r2.md`。先保留并跑这8项和原10项，再一次修M1–M3；安全与失败反例通过后只做必要真实请求，提交统一终态、底层调用证据及只读前后核对，停5.2复审。
