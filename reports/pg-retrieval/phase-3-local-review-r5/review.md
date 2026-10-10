# 5.2 第五轮独立验收：通过

日期：2026-10-07。**5.2通过，真实local只读候选检查点完成；下一组仅5.3。5.4–5.6/Gate3未完成，5.1/Gate2保持通过。**

本轮只审查V1有效向量映射观测及必要读取/选择调用链，没有修改应用实现、原测试、冻结gold或依赖。OCR只做本地预览/规则解析；逐文件范围及历史阶段跳过理由见coverage.json。

## 通过依据

1. **代码与证据匹配**：提交五项SHA全部匹配；前三轮及r4向量套件四份独立验收文件未改。安装lightrag-hku==1.5.7的172项Python文件与RECORD匹配，0差异；5.1实现SHA未变。
2. **255项测试通过**：r4三场景3/3（无向量、原始身份不匹配都明确weight-fallback/degraded；正确2560d向量正例保持）。前期异步图请求、失败终态服务记录、close失败不flush、部分构造回收、身份漂移等断言继续通过，无删除/xfail/弱化。
3. **观测实际映射**：_EffectiveChunkVectorObserver包装实际get_vectors_by_ids结果，按请求chunk身份计missing/mismatched/unusable与有效数，分entities/relations阶段记录；返回原始映射，不改请求或选择算法。原生point数量只作传输统计，不能给有效向量完整性背书。
4. **主agent正式CLI单题独立复跑**：命令`env-rag-final lightrag-local --query-id fact-002 --report-dir .../phase-3-local-review-r5/formal-cli`退出0。实体阶段28/28、关系阶段2/2有效向量，missing/mismatched/unusable均0，observer_bound=true、vector_backed=true、vector-similarity；无degraded/errors。10/10候选按(workspace,chunk_id)PG回读verified，实体/边来源保留。root再用独立只读SQL回读10条，核对workspace/doc归属、ID前缀、file_path与原文摘要并保存内容SHA，10/10一致，见source-reread.json。
5. **实际服务次数与守卫**：keyword LLM1、embedding3、Qdrant3、Neo4j底层读取5、PG SELECT3，全部成功；helper分组另外记录，不冒充底层请求。0答案生成、hashing_kv=None、不使用原答案cache。正式运行before/after冻结匹配且无漂移，gold SHA实读一致；原八表与内容指纹/catalog/search/env不变，llm_cache仍16,514。
6. **正式运行后只读核查**：原生客户端读取Qdrant/Neo4j元数据，Qdrant5709/65526/119574点/2560d、Neo4j base66069节点/121819关系符合冻结记录；PG/source/catalog/search/gold/env前后核对无漂移。没有初始化、迁移、写库、重建或会话终止。
7. **检查与凭据**：Ruff check/format、OpenSpec strict、diff通过；报告、终端日志、JSON/JSONL、交接材料凭据扫描无泄漏。没有重复四题整轮模型请求。

## 实测边界

root该题目标文档命中为9/10，来源验证为10/10；这是两项不同观测。5.2没有规定单题语义命中率门槛，不据此批准或否定质量改进；其它编号/版本候选是否可用于请求，将由5.3现有PG硬约束过滤。不得把来源verified写成全数目标命中。

root本次28+2与执行agent29+3不同，关键词服务非确定性可改变发现集合；两次都逐实际映射验证覆盖。没有修改gold或为了匹配数字重复请求。原r4其它三题的跨版本/缺失版本候选观测沿用，前期来源和降级断言保留。

5.2只接受发布包实际候选读取、必要服务调用、来源映射、只读/守卫、故障降级与回收合同。**融合去重/约束、联合精排、范围展开后的生成及正式冷生成对照仍未验收。** neg-001的local可以发现邻近版本，答案层missing期望不变。

## 下一步

按`openspec/changes/add-pg-scoped-retrieval/handoff-phase-3-5.3.md`只做两路候选归一化、身份去重、来源路径保留及明确编号/版本约束。先入口级合同测试，再少量真实合并请求，完成后停5.3检查点；不提前运行rerank、答案生成或整轮评测。

正式证据在formal-cli/、live-inventory.json，当前接受状态与SHA、测试/服务/检查证据详见review-manifest.json。历轮退回报告保留为历史，以本报告为当前5.2结论。
