# 5.2 真实 local 候选适配（第二轮，L1–L5 补正后）

日期：2026-10-07。响应 `phase-3-local-review/review.md` L1–L5 与 `handoff-phase-3-5.2-fixes.md`。适配器 `src/env_rag_final/local_adapter.py` 重写（rev 2），首轮交付保留于 `phase-3-local/` 为历史。

复跑入口：

```
uv run env-rag-final lightrag-local --query-id fact-001,fact-002,syn-001,neg-001 --report-dir reports/pg-retrieval/phase-3-local-r2
```

本轮实跑（run 目录 local-runtime-20261007T000150.json = latest）：identity before/after 均与冻结一致、`gold_sha_verified` 实际读取匹配；4 题 40 候选全部通过 (workspace, chunk_id) 生产 PG 回读验证；by_service 实际调用合计 LLM 4 次（keyword 提取，0 次 answer LLM）、embedding 13 次、Qdrant 4 组、Neo4j 1 组/题、PG 只读 9 次；`lightrag_llm_cache` 运行后仍 16,514 行。

## L1 只读接入（不再有任何生产写请求）

移除了对发布存储 `initialize()` 的一切调用——rev 1 声称"幂等 no-op"是错误的：Qdrant initialize 对已存在集合仍无条件调 `create_payload_index`，Neo4j initialize 仍发 `CREATE INDEX IF NOT EXISTS`，且含建集合/迁移/建库/DROP 重建分支。rev 2 改为：

- 经发布模块解析 `QdrantClient`（使测试替身可注入），自建原生连接后**只读校验**元数据：`collection_exists`（缺失 → AdapterError 拒绝，绝不创建）、`get_collection` 读维度（≠2560 拒绝）与 `workspace_id` payload index（缺失拒绝——initialize 将提交写请求的路径被预先阻断）；
- 发布 `QdrantVectorDBStorage`/`Neo4JStorage` 的读取方法通过直接注入连接对象复用（`_client`/`_initialized`/`_flush_lock`/`_driver`/`_DATABASE`），`initialize()` 永不执行；
- 派生集合名必须等于生产集合名（`lightrag_vdb_entities_qwen_qwen3_embedding_4b_2560d` / `…chunks…`），不匹配拒绝；
- 图 workspace 绑定后复核等于生产 `base` label。

L1 复审反例（实际安装的 Qdrant 存储类 + 假客户端、集合与索引已存在）现在通过：0 次 `create_payload_index`，0 个写 API。

## L2 发布包候选函数 + 真实端点 + 预算合同

- 生产路径使用发布包函数本体 `_find_related_text_unit_from_entities` / `_find_related_text_unit_from_relations`（接收只读 `ReadOnlyPGTextChunks` 与真实 chunks 集合；空图数据直接返回不触存储）。
- 边端点读取发布包真实字段 **`src_tgt`**（rev 1 误读 source/target 导致所有边折叠成 `edge:|` 的缺陷消除）；每个 chunk 保留全部实体/边来源路径，后到的边/实体不覆盖前者（复审两条边反例与来源路径反例通过）。
- 频次计数跨全部实体完成后才排序（release "先全量计数再排序"语义）。
- 预算合同：发现层 = release `related_chunk_number`（5）与 VECTOR/WEIGHT 选取；最终候选 = `chunk_top_k` 封顶（发现排序 ≠ 最终精排，精排归 5.4）。`_assemble_candidates` 作为**有边界的独立扩展**保留（来源映射 + 选择/预算合同，见代码注释），不宣称与发布包整体等价。

## L3 调用前守卫 + 真实身份采集

- 任何连接/服务请求前：`verify_config_guard` 拒绝 env 覆盖（`QDRANT_WORKSPACE`/`NEO4J_WORKSPACE`/`POSTGRES_WORKSPACE`）、未映射 PG workspace（唯一已核实映射 default↔'_'↔base，不泛化）、模型/维度不一致（`EMBEDDING_MODEL` 必须等于生产 Qwen3/2560，其他模型不得套旧集合名）。
- `run_frozen` 实际读取 gold 文件并比较冻结 SHA（错误 SHA → 任何 fetch 前拒绝）；采集实际 source/catalog run+snapshot/search/gold/env 与冻结比较（开始不符 → 不进入任何 fetch）；finally 后置漂移核对；未知 query_id 在任何调用前拒绝；失败写 `failure` 报告且 CLI 非零——硬编码 FROZEN 不再冒充实测身份。

## L4 服务边界证据

- 每个真实调用经 `ServiceBoundary` 记录 service/operation/status/耗时（`by_service` attempt/success/failure + 每调用 `call_records`）。
- 发布 VECTOR helper 吞 embedding 异常并返回截断列表——边界包装使失败落 `notes`/`degraded`，`sorting_sources.chunk_pick` 显式标记 `truncation-fallback`（正常路径为 `vector-similarity`）；不以 PG verified 抵消服务失败。
- 计数按实际执行定义：空 id 列表不开连接不计 `pg_readonly_queries`（空路径实测 0）；计数器每请求独立，不复用累计。
- 本轮 4 题：`by_service` LLM 4/4/0、embedding 13/13/0、PG 9 次全部成功；无失败记录。

## L5 资源生命周期

资源构造即登记；成功/失败/取消统一 finally：先校验待写队列为空（只读适配永不存在，若存在则拒绝 finalize 并记录，不引入生产写路径——原生 finalize 会 flush），再 `client.close()` / `driver.close()`；单项关闭失败记录后继续其余清理与报告。复审成功反例（三实例均回收）与半初始化路径通过。

## 实测结果（冻结子集 4 题）

| query_id | 目标 | 候选 | 验证 | 命中目标 | 排序来源 |
| --- | --- | --- | --- | --- | --- |
| fact-001 | 1 | 10 | 10/10 | 2 | vector-similarity |
| fact-002 | 1 | 10 | 10/10 | 10 | vector-similarity |
| syn-001 | 2 | 10 | 10/10 | 7（双版本均命中） | vector-similarity |
| neg-001 | 0（missing 期望） | 10 | 10/10 | 0 | vector-similarity |

neg-001 的语义候选仍可宽泛召回 2012/2026 相关证据——保留 missing 期望（counter 原样存于 JSONL），严格版本约束归融合/答案层（5.3+）。语义质量不做评测，Gate 3 未开启。

## 前后只读核对

八表 221/5709/279/16514/65527/221/221/119575、源指纹 `95f7791f…`、catalog/search、gold SHA、`.env` SHA 前后一致；`lightrag_llm_cache` 16,514 行不变；release RECORD 0 差异；0 answer LLM、0 缓存读写、0 DDL/DML。

## 测试与检查

全套 **238 passed**（复审 10 项独立验收全部转通过 + 提交 8 项按 rev 2 接缝适配，断言语义未弱化；另含既有全部断言）。Ruff、OpenSpec strict、`git diff --check` 通过；凭据不落盘。
