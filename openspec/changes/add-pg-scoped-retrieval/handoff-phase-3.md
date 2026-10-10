# Phase 3 交接：先完成5.1隔离兼容检查点

本交接在主agent Gate2最终验收通过后生效。验收依据 `reports/pg-retrieval/gate-2/final-review/review.md`、`reports/pg-retrieval/phase-2/report.md`、tasks.md。Phase2固定gold和测试继续保留，不因融合路径更改期望或预算。

## 先做5.1，完成后停下提交主agent审查

现有发布依赖为lightrag-hku 1.5.7。Phase0已静态发现 `ClientManager.get_client()` 首次建池会执行check_tables/初始化DDL；声明aquery_data返回实际chunk IDs尚需运行时确认。下一步先证明正式只读接入办法，不立即把发布包初始化到现有库。

1. 核对锁定发布包、实际公开入口及存储配置。使用本项目安装的发布包，不引用LightRAG源码工作区，不自动升级依赖。
2. 使用独立临时数据库/独立测试存储验证首次建池、DDL/迁移、workspace作用域及重复初始化的行为。仅换workspace不足以隔离原库级DDL；只要存在库级写入，必须让连接指向独立临时库。原.env保持不改，用测试配置副本覆盖DSN，池/进程也隔离；临时对象仅能清理本任务创建的对象。
PG之外，可能写入的vector/graph/cache连接同样使用独立临时环境或明确fixture；原Qdrant/Neo4j只读，不让initialize_storages触及正式后端。

3. 在隔离环境放入最小受控样例，确认来源ID、实际chunk ID、文档归属、内容字段和公开查询返回结构。覆盖同ID跨workspace、不同版本、缺失chunk、cache字段；不能用显示引用编号猜真实chunk ID。
4. 如需embedding/LLM完成接口形态探针，优先使用明确标注的本地deterministic fixture。fixture只能证明相应接口/副作用，不能宣称真实LightRAG local语义检索通过；真实模型/embedding请求划归5.2，先列明必要调用与数据范围。
5. 确定正式只读策略：说明会触发写入的路径、正式库采用的已核验入口/适配方式、强制只读连接及失败行为；如发布接口本身无法做到正式只读，明确兼容缺口和最小备选，不通过改正式表或迁移现有库解决。

交付 `reports/pg-retrieval/phase-3/compatibility-runtime.md`、隔离测试manifest、最小复跑入口、调用/SQL副作用证据、ID映射样例、正式来源前后只读核对。5.1证据充分才勾选；5.2–5.6与Gate3保持未完成，停“兼容检查点”待主agent审查。

## 保留的来源与质量合同

workspace=default，catalog snapshot=`4919b3938ad93747`，source fingerprint=`95f7791fd84171ab727870fc5810d79b4327b0c4fa547d432951e0499a3808f8`，search active=`872d689343a9cbb6`。public八表基线221/5709/279/16514/65527/221/221/119575（doc_full/doc_chunks/doc_status/llm_cache/entity_chunks/full_entities/full_relations/relation_chunks）。读取前后身份不符则记录stale并停止，不迁移/修复正式原文库、MinerU或目录来迎合。

审核gold `reports/pg-retrieval/gate-2/review-r5/gold-approved.json` SHA=`1bf130077c21583a89c5ca14695694d9552c558a7d8dc5d45ff0d9f72cfd7a5e`；31正例/10反例期望，top-k=20。50既定验收反例保持。公开失败syn001/002排序、prose005/table003歧义保留，Phase1 requires_span保守状态保持。答案缓存16,514行不用于任何新质量评测。

5.1通过后才按既有OpenSpec安排真实local适配、两路按workspace/chunk ID去重、联合rerank、精排后完整scope展开。原检索分数不直接相加，枚举top-k仅发现，来源版本分别保留，认证/超时/缺证据等返回可见降级。Phase4再做无缓存污染的正式两轮对照；本交接不把Gate2通过当作融合质量已验证。
