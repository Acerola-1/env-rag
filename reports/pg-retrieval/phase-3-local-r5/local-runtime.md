# 5.2 真实 local 候选适配（第五轮，V1 有效向量覆盖补正后）

日期：2026-10-07。响应 `phase-3-local-review-r4/review.md` V1 与 `handoff-phase-3-5.2-fixes-r4.md`。前四轮交付保留于 `phase-3-local/`、`-r2/`、`-r3/`、`-r4/` 为历史。本轮仅修 V1 一处，不重做既有修复。

复跑入口（本轮实测 fact-002 单题，按交接要求）：

```
uv run env-rag-final lightrag-local --query-id fact-002 --report-dir reports/pg-retrieval/phase-3-local-r5
```

## V1：覆盖按有效向量映射判定，不按返回 point 数

- **根因**：此前 `vectors_returned` 实际统计原生 `retrieve` 返回的 point 条数。真实发布存储 `get_vectors_by_ids()` 会**丢弃 `point.vector is None` 的 point**，并按 payload 原始 chunk ID（`ID_FIELD`）把数据重新映射后交给选取器；VECTOR helper 只对请求 chunk 身份命中的向量计算相似度。因此"返回条数完整"不等于"请求 chunk 的有效向量完整"——point 无向量或原始身份不匹配时，发布包已回落 WEIGHT，适配器却仍标 vector-similarity。
- **修复**：新增 `_EffectiveChunkVectorObserver`（`src/env_rag_final/local_adapter.py`），在 chunks 存储的 `get_vectors_by_ids` 读取边界包装一次调用，记录**实际交给选取器的映射**并与请求 chunk 身份逐条对照，按选取阶段（entities/relations）分别记账：
  - `vectors_requested`（请求 chunk 身份数）、`vectors_effective`（命中且有可用维度向量的数）、`vectors_missing_total/sample`（请求了但映射中没有）、`vectors_mismatched_total/sample`（映射中出现但不在请求集合内）、`vectors_unusable_total/sample`（命中但向量为 None/维度不符）；
  - `points_returned_raw`：该窗口内原生 `retrieve` 成功的 point 条数——**仅作传输统计**，不再命名为向量数、不参与 `vector_backed`；
  - `retrieve_failed`：窗口内是否有原生 retrieve 失败；`complete`：请求集非空、missing/mismatched/unusable 全为 0（与发布 helper 的"任何不一致即回落 WEIGHT"语义一致）。
- **覆盖判定**：`vector_backed = 所有观测调用 complete`；任一请求 chunk 缺向量、原始身份不匹配、维度不可用、或从未观测到有效映射（空请求集）→ `chunk_pick=weight-fallback` + degraded，PG verified 不能抵消；embedding/qdrant 失败仍优先 `truncation-fallback`。
- **报告字段**：`sorting_sources.chunk_pick_vectors` 含 `vectors_requested/vectors_effective/missing_total/mismatched_total/unusable_total/points_returned_raw/vector_backed/observer_bound` 与逐阶段 `observed_calls`（含各自样本与 complete 标志）。

## 入口反例（tests/test_local_adapter_review_r4.py，3 例）

经正式 `fetch`、实际发布 Qdrant 读取/选取函数、假原生传输：

| 场景 | 发布包实际选择 | 现在适配器 | 结果 |
| --- | --- | --- | --- |
| 请求 ID 全返回、`point.vector=None` | 无有效向量 → WEIGHT | `vector_backed=False`、weight-fallback、degraded | 通过 |
| 请求 ID 全返回且有向量、payload 原始 ID=unrelated-chunk | 请求 chunk 无可用向量 → WEIGHT | `vector_backed=False`、weight-fallback、degraded | 通过 |
| 请求 ID 与原始身份正确、有效 2560d 向量 | VECTOR | `vector_backed=True`、vector-similarity | 通过 |

## 实测（fact-002 单题，r5 代次）

- identity before/after 均与冻结一致、`identity_drift=[]`；gold SHA 实读匹配 `1bf130077c21583a…`；`env_sha` 前后一致。
- 该题走实体+关系两阶段选取：entities `req=29/eff=29`、relations `req=3/eff=3`，`points_returned_raw=32` 与 `vectors_effective=32` 一致（真实数据下两者相等，正例）；missing/mismatched/unusable 全 0；`vector_backed=true`、`chunk_pick=vector-similarity`。
- 10/10 候选经 (workspace, chunk_id) 生产 PG 回读验证（workspace=default，单一 full_doc_id）；degraded_notes=0。
- 实际调用：LLM 1（keyword，0 answer）、embedding 3、Qdrant 3（entities query_points + chunks retrieve 分别记账，target 标注）、Neo4j 真实 `session.run` 5（组 1）、PG 只读 3；全部 success。
- `lightrag_llm_cache` 16,514 行不变；`hashing_kv=None`，0 缓存读写；0 生产初始化/写库/重建。
- 说明：本轮 fact-002 抽取到的 keyword 集与 r4 不同（LLM 抽词非确定性），故 `vectors_requested`（32）与 r4（282）不可直接比较；这不是行为回退——观测器只读取映射，不改变请求。其它三题无相关改动，沿用 r4 代次证据。

## 测试与检查

全套 **255 passed**（原 252 + r4 三例；r1/r2/r3 冻结套件 32/32 保持，r4 三例 3/3 通过；无删除/xfail/弱化）。Ruff check/format、OpenSpec strict、diff、凭据扫描通过。
