# 5.2 真实 local 候选适配（第三轮，M1–M3 补正后）

日期：2026-10-07。响应 `phase-3-local-review-r2/review.md` M1–M3 与 `handoff-phase-3-5.2-fixes-r2.md`。第二/首轮交付保留于 `phase-3-local-r2/`、`phase-3-local/` 为历史。

复跑入口：

```
uv run env-rag-final lightrag-local --query-id fact-001,fact-002,syn-001,neg-001 --report-dir reports/pg-retrieval/phase-3-local-r3
```

## M1 统一身份与失败终态

- 后置守卫不再只查 `matches_frozen`：新增 `_identity_drift` 逐字段比较 before/after（八表计数、source 指纹、catalog run+snapshot、search、gold SHA、**`.env` 字节 SHA**）。仅 env_sha 漂移、其余完全相同的入口用例现在拒绝（`identity-after-drift`）。
- 终态统一：`run_frozen` 有唯一 `_write_terminal()`；fetch 失败/post 采集失败/漂移/mismatch 都在 **post-guard 之后**写盘——报告包含 `identity_after`（或 `identity_after_error`）、`identity_drift`、`failure.stage/detail`、已完成 results、失败时的服务记录；无 `finished_at`；原始错误不被覆盖。复审反例（fetch 抛 TimeoutError → latest 报告含 `failure.stage=fetch` 且 `identity_after` 存在）通过。
- 本地未知 query_id 与 gold SHA 校验移到任何后端读取/服务调用之前。

## M2 真实服务证据 / 正确降级 / 每请求独立

- **每 fetch 新账本**：`fetch()` 开头重建 `ServiceBoundary` 与计数器；同一 adapter 连续两次请求的 `by_service`/`call_records` 完全独立（复审反例通过）。
- **Qdrant 真实凭证**：原生客户端经 `_RecordingQdrantClient` 包装，`query_points`/`retrieve` 每次真实调用记录 attempt/success/failure/耗时/结果摘要（`{"points": n}`/`{"items": n}`）——包括发布 helper 内部吞掉的超时（先在边界记录再被吞）。`by_service.qdrant` 与 flat `qdrant_queries` 同源。
- **Neo4j 真实读取**：driver 经 `_RecordingNeo4jDriver` 包装记录每次 `session.run`（底层图读取）；helper `get_node_data` 归入 `groups.neo4j`，与实际请求分列不混。
- **降级正确**：embedding/Qdrant 失败 → `truncation-fallback`；读取成功但无向量/空结果 → `weight-fallback`（不再标 `vector-similarity`）；正常向量排序才标 `vector-similarity`。复审缺向量与超时反例通过；PG verified 不再抵消服务失败。
- **去重复选择**：`_assemble_candidates(select=False)` 在生产路径只做来源追踪（真实 src_tgt/source_id，不请求向量）；实际选择由发布函数完成——embedding 从 13 次降至 9 次（每查询 2 次：entities 查询向量 + chunks 检索向量 + keyword 无 embedding）。`select=True` 默认路径保留首轮复审契约（吞异常检测）。

## M3 部分构造回收 + 只 close 清理

- `bind_qdrant_readonly` 从客户端创建即建立完整 try 边界：storage 构造、namespace 校验、`collection_exists`/`get_collection`、锁绑定任一失败都 close 客户端后再抛（复审 storage 构造抛错反例通过）。`bind_neo4j_readonly` 同样；测试替身不创建真实 driver。
- 生产清理**只 close**：`client.close()`/`driver.close()`；不再调用会 flush 的发布 `finalize`（仅对无 client/driver 的非原生绑定回退 finalize）。待写队列非空 → 记录拒绝 flush 但**仍然 close**（不 continue 漏连接）。单项失败不跳过其余回收。

## 实测（冻结子集 rerun，r3 代次）

- identity before/after 均与冻结一致、无 drift；gold SHA 实读匹配。
- 4 题 40/40 候选经 (workspace, chunk_id) 生产 PG 回读验证；fact-002 命中 10/10、syn-001 双版本 7/10、neg-001 保留 missing 期望（counter 原样存于 JSONL）。
- 每查询实际调用：LLM 1（keyword，0 answer）、embedding 2、Qdrant 2（query_points+retrieve 各记账）、Neo4j 5 次 session.run（组 1）、PG 只读 2 + helper 组 2；合计 LLM 4、embedding 9、Qdrant 9、PG 9，全部 success。
- `lightrag_llm_cache` 16,514 行不变；0 answer LLM、0 缓存读写。

## 测试与检查

全套 **246 passed**（r2 复审 8 项 7 失败全部转通过；r1 复审 10 项与提交 8 项保持；无删除/弱化）。Ruff、OpenSpec strict、diff、凭据扫描通过（报告/JSONL 无凭据，仅模型名与主机）。
