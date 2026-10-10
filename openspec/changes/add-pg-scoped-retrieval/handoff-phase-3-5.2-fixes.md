# 5.2 首轮补正交接：只修 L1–L5

当前结论：5.2未通过，见 `reports/pg-retrieval/phase-3-local-review/review.md`。5.1/Gate2保持通过；**不进入5.3–5.6/Gate3，不升级依赖，不改冻结gold，不修原库或重建图/向量。** 当前 tests/test_local_adapter_review.py 为9失败/1通过，原228项继续通过。不要删除、xfail、弱化断言或只用更换stub消除正式入口缺陷。

## 按此顺序补正

1. **L1 正式只读接入优先**：Qdrant initialize已存在集合仍发create_payload_index，Neo4j仍发CREATE INDEX；移除生产ensure/migrate路径。实现仅连接+只读元数据验证+读取方法的适配，验证既有资源无任何写API/DDL，缺资源/不兼容拒绝且不创建。不能以故障注入monkeypatch作为生产策略；不能以计数不变证明没有写请求。纠正实现/报告中no-op陈述。
2. **L2 候选与来源**：发布包边端点是src_tgt，当前source/target造成所有边覆盖成“|”。保留每条边与每个chunk的全部实体/边来源。安装包_find_related_text_unit_from_entities可直接接只读存储，无需完整LightRAGinitialize；检查并复用真实候选函数/扩展点，必要差异明确描述及行为验证。全量频次计数后排序，预算约定明确；不得把复制算法宣称同发布包等价。真实运行不再出现edge:|，两条以上不同边不会覆盖丢失。
3. **L3 身份/配置守卫**：未知PG workspace不能固定映射到原向量“_”/图“base”；建立显式映射并拒绝不支持值及env覆盖冲突。请求的模型与model_name/集合/实际维度一致，其他模型不得套旧Qwen名继续查。在任何服务调用前核验gold/config/模型/映射，frozen入口采集实际source/catalog run+snapshot/search/gold/env并比较；后置守卫包在统一资源/报告边界。变化/采集失败非零、可见终态，不能只输出常量FROZEN。
4. **L4 降级/证据合同**：实际发布包VECTOR helper会吞embedding异常并简单截断；包住真实服务边界留故障状态并显式degraded/排序来源，不要只捕helper外部异常。缺向量/认证/超时/维度不符同样显式失败或降级。准确计数实际attempt/success/failure，定义query/group/HTTP口径；空实体/空PG读取无虚增，同adapter两次请求不混计数。未知query_id前置拒绝，错误和守卫失败有统一报告及非零CLI；保存必要请求/响应、模型配置指纹与耗时，凭据不落盘。
5. **L5 生命周期**：构造即登记资源；成功、初始化部分失败、检索失败、取消均关闭自有Qdrant/Neo4j连接，关闭异常不跳过其它清理/post-guard/报告。Qdrant原生finalize会flush，不可为关闭引入生产写路径；只读close-only或明确不可写队列保证。

## 复验和交付

- 先跑十项独立验收反例确认失败，再修实现；全部旧测试保持。新增必要入口级失败断言，包含缺资源零写、半初始化回收、运行中身份漂移、服务失败可见以及query_id拒绝。测试不是实际服务成功的替代。
- **L1安全修复后**，同一冻结子集fact-001/fact-002/syn-001/neg-001最小真实运行。列必要embedding/keyword调用及次数，再执行；0答案LLM、hashing_kv=None、不读写原答案cache。重复调用须有实际理由，不做整轮质量评测。
- 每个可用候选以(workspace,chunk_id)生产PG回读核验，保留ID/content指纹、doc归属、实体/真实边端点、排序方法与耗时；缺失/错归属明确拒绝，不去重掉不同版本或路径。neg-001可宽泛发现相关版本，保留missing答案期望，5.3才做融合的严格约束。
- 前后只读核验八表+内容source/catalog/search/gold/env、Qdrant/Neo4j资源元数据及配置身份；**计数一致与无写请求分开证明**。报告明确真实成功、fixture拒绝、未验证语义质量三者。
- 保存新运行JSON/JSONL、失败终态、服务请求/响应/耗时、manifest SHA、资源回收证据；原交付保留为历史。Ruff/OpenSpec strict/diff及凭据扫描通过后，仅5.2提交复审，不勾选5.3以后。

冻结身份仍为source=`95f7791fd84171ab727870fc5810d79b4327b0c4fa547d432951e0499a3808f8`；catalog=`c15c741742394320`/`4919b3938ad93747`；search=`872d689343a9cbb6`；gold=`1bf130077c21583a89c5ca14695694d9552c558a7d8dc5d45ff0d9f72cfd7a5e`。八表221/5709/279/16514/65527/221/221/119575，vector“_”、graph“base”、PG“default”只是已核实的当前映射，不允许泛化到任意workspace。
