# 5.2 真实 local 候选适配（第四轮，N1–N3 补正后）

日期：2026-10-07。响应 `phase-3-local-review-r3/review.md` N1–N3 与 `handoff-phase-3-5.2-fixes-r3.md`。前三轮交付保留于 `phase-3-local/`、`-r2/`、`-r3/` 为历史。

复跑入口：

```
uv run env-rag-final lightrag-local --query-id fact-001,fact-002,syn-001,neg-001 --report-dir reports/pg-retrieval/phase-3-local-r4
```

## N1 异步图查询记账 + 分阶段向量支持

- **Neo4j 包装 await 后记录**：`_RecordingNeo4jDriver` 不再同步调用 `session.run` 后立即记 success（那只记到协程创建）。现在在真实的 `await session.run(...)` 完成之后才写 success（耗时包含执行等待）；await 期间抛出的异常在同一边界记 failure 后再抛。复审异步失败反例（真实发布 `get_nodes_batch` + 异步假 driver，TimeoutError）现在得到 failure 凭证且无错误 success；成功正例保持。
- **chunk 向量支持按集合/阶段判定**：不再对全部 Qdrant 成功记录做 `any`。每条 Qdrant 凭证带 `target`（entities/chunks 集合）；排序来源只依据 **chunks 集合的 retrieve 覆盖**：`vectors_requested` vs `vectors_returned`，只有完整覆盖（req>0 且 ret>=req）才算 vector-backed。entities 的 `query_points` 命中不能替 chunks 背书——复审反例（实体检索非空 + chunks retrieve 空集合）现在输出 `weight-fallback` 且 degraded 非空。`sorting_sources.chunk_pick_vectors` 记录 expected_chunks/retrieve 次数/请求数/返回数/backed。

## N2 失败终态携带失败请求的服务凭证

`run_frozen` 捕获 fetch 异常时序列化**失败 adapter 的真实账本**：`failure_service_records = {query_id, call_records, group_records, by_service, groups}`（如 llm/failure 的 TimeoutError 记录原样进入终态）；前置拒绝（无 adapter/账本）显式记录零调用并注明原因，不伪造。复审反例（keyword 服务 TimeoutError → 终态含 llm/failure 凭证且 identity_after 存在）通过；统一 writer/无 finished_at/原错误不覆盖保持。

## N3 部分图绑定回收 + close 失败禁止 flush 回退

- **Neo4j 绑定**：storage 构造**先于** driver 获取——构造失败时完全不获取 driver（复审断言允许零获取）。获取后的赋值链为纯属性赋值（不可失败），已获取的 driver 总是交给 fetch 的所有权回收边界，无 create_task/fire-and-forget 路径。
- **close 失败与 flush 回退**：清理按**是否拥有原生 handle**（`_client`/`_driver` 是否为本次创建）判定，而非按 close 是否成功。原生 handle 资源只走 `client.close()`/`driver.close()`——即使 close 抛错也**绝不**回退到含 flush 的发布 `finalize`（复审反例：close 失败 + finalize 禁止探针 → 0 次 finalize、degraded 可见）。仅无原生 handle 的测试替身走其 finalize（无生产连接、无 flush 能力）。待写队列非空记录拒绝但对象仍 close；单项失败不跳过其余回收/post/终态。

## 实测（冻结子集，r4 代次）

- identity before/after 均与冻结一致、无 drift；gold SHA 实读匹配。
- 4 题 40/40 候选经 (workspace, chunk_id) 生产 PG 回读验证；每查询 `chunk_pick_vectors` 完整覆盖（fact-001 220/220、fact-002 282/282、syn-001 20/20、neg-001 19/19）且排序来源 vector-similarity 有凭证支撑。
- 实际调用：每查询 LLM 1（keyword，0 answer）、embedding 2–3、Qdrant 2–3（entities query_points + chunks retrieve 分别记账）、Neo4j 真实 session.run（组单列）、PG 只读；合计 LLM 4、embedding 10、Qdrant 10、PG 10，全部 success。
- `lightrag_llm_cache` 16,514 行不变；0 answer LLM、0 缓存读写。
- 关于上轮报告"每查询 2 次 embedding"的表述：实际为 2–3 次（fact-002 因关系选取多一次），本轮按真实日志修正。

## 测试与检查

全套 **252 passed**（r3 复审 6 项 5 失败全部转通过；r1/r2 复审与提交套件保持；无删除/弱化）。Ruff、OpenSpec strict、diff、凭据扫描通过。
