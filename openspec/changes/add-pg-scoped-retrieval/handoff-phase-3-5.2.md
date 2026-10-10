# Phase 3 下一组：只做 5.2 真实 local 候选适配

5.1已通过主agent独立验收，依据 `reports/pg-retrieval/phase-3-review-r5/review.md` / review-manifest.json；tasks.md为当前状态。**下一组仅5.2，完成后停检查点复审；不做5.3融合、5.4精排、5.5展开/生成或5.6 Gate3。** 5.1 fixture的naive查询不算真实local通过。

## 先核对真实后端与安全接入

1. 原.env配置是PG KV/Status、Qdrant vector、Neo4J graph。只读查实际workspace/collection/namespace/label、向量维度与模型配置、来源字段和可用公开接口。PG普通图表为空，不能用它或fixture替换原语义后端宣称成功。
2. 正式PG不实例化ClientManager/任何LightRAG存储initialize；原Qdrant/Neo4j也不得让初始化创建集合、索引、约束或迁移。生产数据读取沿用READ ONLY+超时适配。核对发布包可用的公开扩展/接入点；若无法安全只读接入，明确具体缺口及可审查备选，不能改原库或复制fixture结果冒充。
3. 池/进程/测试DSN隔离；需要写入的临时cache/测试存储单独所有权保护。复用5.1安全合同，不能把故障注入monkeypatch当生产适配器。部分创建身份未知继续拒绝自动删除；人工恢复须额外确认创建归属。

## 实现和实际验证

- 实现调用发布包真实local证据路径的候选适配器。先列所需实际embedding/LLM调用、接口/模型、最小查询数据范围与次数；只执行必要调用，区分实际服务请求与fixture。查询输出保存证据，不进行答案生成或新的整轮评测。
- 从冻结白名单选择少量真实请求，覆盖常规候选、不同版本与缺失来源；记录query/mode/workspace/实际候选chunk_id/doc归属/content/路径/耗时及服务调用。若LLM非必要或未调用，记录原因；不要把cached/fixture结果算成实际调用。
- 每个可用候选按(workspace,chunk_id)在现有PG回读，核验文档归属与原文；reference_id不是来源身份，不能靠标题/相似文本猜chunk ID。缺失、跨workspace、不匹配明确拒绝/降级；不同版本来源不能被去重掉。
- 明确缓存读写路径，原public.lightrag_llm_cache 16,514行不得写入或作为旧答案替代真实验证。任何认证/超时/embedding维度/模型不一致、原图/向量引用失配都留原始失败与degraded，不自动升级、重索引或修原库。
- 验证真实调用路径的正常与失败行为，附必要入口测试和源码/配置指纹；接口有输出、真实请求成功、是否命中目标、来源回读正确是不同事实，分别记录，不用“测试通过”替代实际行为。

## 交付与保留合同

交付候选适配实现、最小复跑入口、local-runtime报告、实际请求/响应与候选JSONL、身份对应和失败/降级证据、前后只读来源/后端核对、测试与Ruff/OpenSpec strict/diff结果。凭据不落盘；实际语义质量若尚未形成评测，只列观测，不宣称Gate3通过。5.2证据完整后提交主agent复审，5.3–5.6不勾选。

source=`95f7791fd84171ab727870fc5810d79b4327b0c4fa547d432951e0499a3808f8`；catalog run/snapshot=`c15c741742394320`/`4919b3938ad93747`；search=`872d689343a9cbb6`；审核gold SHA=`1bf130077c21583a89c5ca14695694d9552c558a7d8dc5d45ff0d9f72cfd7a5e`。八表221/5709/279/16514/65527/221/221/119575，31正例/10负例期望、top-k20，原50及之后验收断言保留。既有公开失败与requires_span保守语义保留，不调整gold迎合新链路。
