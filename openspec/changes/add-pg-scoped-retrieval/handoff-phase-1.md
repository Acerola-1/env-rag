# Phase 1 handoff

## Objective

Gate 0 已由主 agent 复审通过。首个实现批次只做 tasks.md 的 2.1–2.6：自有目录、稳定原文读取、元数据、结构映射及幂等构建。交付后停在结构目录检查点，供主 agent 检查，再安排第 3 组的三类枚举闭环。

## Read first

- proposal.md、design.md、四份 specs、tasks.md。
- reports/pg-retrieval/gate-0/review.md 的 Re-review result 与 re-review-evidence.json。
- reports/pg-retrieval/phase-0/ 当前发布报告，以及审计入口的 snapshot.py。
- 工作目录 /Users/acerola/Dev/Python/RAG/env-rag-final；本工程使用 uv 锁定发布包，不改 LightRAG 源码。

## Frozen inputs

- 来源 snapshot：95f7791fd84171ab727870fc5810d79b4327b0c4fa547d432951e0499a3808f8。
- PG workspace=default，221 份有 chunks 文档、5709 chunks；58 failed 排除。water-58 是规范化内容重复，未入库，不能当作可读文档。
- 实际文档身份从 inventory 获取，不重新按文件名计算生产 ID；文件名推导规则只是当前审计结果。
- 原文有 {{LRdoc}} 标记，转换规则需显式且可验证；PG 哈希与解析正文／PDF 哈希不可混认。
- 审核 sample-set 目标所附 snapshot_id；gold 尚未审核，不能报告问答质量已通过。
- 273-chunk block、14 个空 sidecar、10 份部分引用都保留为真实困难样本；ID 引用完整不等于正文范围完整。

## Work and boundaries

1. 实现显式自有 schema 迁移、对象列表、重复运行与回退策略。实施前重新检查 env_rag 名称与来源快照；只操作本应用明确拥有的对象，已有 public.lightrag_* 只读。测试使用隔离应用 schema，不将测试记录写入既有语料。
2. 实现实际 workspace／doc_id／chunk_id 的只读适配器、有序读取和稳定分页。缺失／重复顺序／跨 workspace／来源改变均有明确错误或状态，不用 max(order)+1 推断总量。
3. 建立 documents 和可追溯元数据：自身编号与引用编号分开，日期类型分开，标题不能直接使用通用封面行，无法确定保留 unknown。
4. 建 source_units 和多对多 unit_chunk_links，保留原始 locator、覆盖状态及匹配依据。表定位使用内联完整 table ID 与 tables.json，不能伪造 sidecar 的 table ref。
5. 建章节／条款 scopes 及精确边界。尤其验证大 block 中的小条款不能被整个 block 的 273 个 chunk 引用替代；不能仅凭 chunk.heading／子串存在就标完整范围。
6. 实现来源指纹、build 幂等性、引用校验和原子发布。来源改变时 stale，不把旧目录指向新原文；本阶段不承诺存储历史原文。
7. 不重新解析、向量化、修 failed、不调用 LightRAG 存储初始化。不安装分词器、不建全文索引、不接模型／reranker，均属后续任务。

## Deliverables and acceptance

- 实现代码、显式迁移与构建／读取命令、必要配置模板、操作和回退说明。
- reports/pg-retrieval/phase-1/structure-report.md、build-manifest.json 和真实文档／单元／映射／范围样本；指向实际应用 build 和来源 snapshot。
- 真实样本含 GB 8978、GB 18466、一个大 block 与空 sidecar／部分引用案例；无法确认关系标 partial／ambiguous。
- 隔离测试证明重复迁移／构建安全，构建失败不替换旧 build，跨 workspace 拒绝，来源变动 stale；现场验证原 public 表计数与来源摘要未被更改。
- Ruff、受影响测试、OpenSpec 严格校验、diff 检查通过。只勾选有证据的 2.1–2.6，第 3 组和 Gate 1 不提前勾选。

## Copyable prompt

请在 /Users/acerola/Dev/Python/RAG/env-rag-final 按 OpenSpec change add-pg-scoped-retrieval 执行 Phase 1 的 tasks 2.1–2.6。先阅读 handoff-phase-1.md、Gate 0 复审结论、design.md 和 specs。实现自有目录迁移、只读原文适配器、可追溯元数据、block/table↔chunk 多对多映射、章节条款 scopes、幂等构建与来源快照校验。已有 public.lightrag_* 保持只读，仅操作本应用拥有的辅助对象。保留所有 partial／ambiguous／stale 边界，不启动全文检索、模型调用或融合。交付隔离测试、真实结构样本、构建报告和回退说明，完成后停在结构检查点，交由主 agent 检查。
