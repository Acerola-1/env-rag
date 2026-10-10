# 5.3 两路候选融合（合并 / 身份去重 / 版本约束）

日期：2026-10-07。响应 `handoff-phase-3-5.3.md`（5.2 已由 `phase-3-local-review-r5/review.md` 验收通过）。本轮只做 5.3：候选归一化合并、来源身份去重、路径保留与明确编号/版本约束；不做 5.4 联合 rerank、5.5 展开/生成、5.6 Gate3。

复跑入口：

```
uv run env-rag-final fuse-candidates --query-id fact-002,syn-001,neg-001 --report-dir reports/pg-retrieval/phase-3-fusion
uv run env-rag-final fuse-candidates --query-id neg-001 --pg-only --report-dir <dir>   # PG-only 开关
```

## 实现（`src/env_rag_final/fusion.py` + CLI `fuse-candidates`）

- **两路来源**：PG 路径用 `search.query.run_query(expand=False)`，其输入**只取 `discovery_candidates`**（预算内发现快照）——显式 `[]` 即权威零发现（回填探针测试证明枚举答案不进入融合）；`None` 作明确兼容处理并记 note。local 路径复用 5.2 的 `LocalCandidateAdapter.fetch`（只读、同一套身份守卫）。两路共享同一请求身份（gold question + workspace）。
- **类型不混**：只有真实 chunk 身份（keyword `chunk_row`、经真实 `unit_chunk_links` 的 table 绑定 chunk_ids）进入 chunk 候选；doc/scope/table 定位保留为有类型的独立目标（`typed_targets`），绝不猜 `chunk-000`/标题/前 80 字。
- **身份去重与路径保留**：chunk 候选按 `(workspace, chunk_id)` 合并；每条路径的原始口径分数原样保留（`pg_ts_rank` / `local_selection_order`，无分数的记 `none`/`unknown`），**不相加、不转换、不伪造余弦/联合分**；同一身份两路命中只合并候选、路径全留。跨 workspace 相同 `chunk_id` 显式拒绝（不混源）；跨路径 doc 归属冲突记 `conflict` 并整体拒绝，不二选一。
- **版本约束**：从 PG 路由 trace 提取 requested/resolved 目标集；local 候选必须属于**已解析**目标文档（`_apply_doc_constraint` 标记、合并时传播到条目），未解析目标的邻近版本一票拒绝；全部目标缺失时**跳过 local 调用**（零模型调用）。缺失目标保持 `missing`（已找到证据保留、不替代）。多版本按分支集合允许各自目标，跨版本不丢。
- **只读回读**：所有 usable 候选经生产 PG `(workspace, chunk_id)` 回读，校验 full_doc_id 归属并读**完整原文**（`content_sha256` 为读回正文的 SHA；`content_head` 不再当全文）。未 verified 的 local 候选、归属冲突、跨 workspace 条目一律不进 usable。
- **降级合同**：local 失败且 PG 可用 → 显式 `pg-only-degraded`，保留真实错误与失败 adapter 的调用凭证；PG stale/身份漂移 → `stale` 拒绝，local 输出不能升级；降级判定同时核对 local 的**逐阶段完整性记录**（`stage_completeness`），全局排序标签或单个布尔值不单独采信。
- **预算**：usable 上限 40/查询；截断记录规则与未保留 id 列表，状态转 `partial`，不标 complete。
- **守卫与终态**：source/catalog/search/gold/env 前后采集比较 + `identity_drift`；失败统一终态（含 `failure_service_records`）；正式 PG/Qdrant/Neo4j 不初始化、不迁移、不写入。

## 实测（真实请求：fact-002 / syn-001 / neg-001）

- identity before/after 冻结匹配、`identity_drift=[]`、gold SHA 实读匹配；八表计数不变（`lightrag_llm_cache` 16,514）。
- **fact-002**（GB 8978-1996 表1 总汞）：status=ok；目标解析 1/1；PG 发现 4 条（3 chunk），local 运行；usable 10、rejected 0；其中 1 条 chunk **两路合并**（pg_ts_rank=0.00220183… 与 local 选择序 0 并存、不求和）；local 逐阶段完整（entities 29/29、relations 3/3）。
- **syn-001**（GB 3095-2012 vs 2026）：status=ok；**双版本目标各自解析**（docs 2012→doc-257d…、2026→doc-4c88…）；usable 9（两版本都保留，含“同内容不同版本不合并丢失”的实体基础）；**3 条邻近版本被拒绝**（doc-8bd9…/c963…/eb0a… 非任何已解析目标）。
- **neg-001**（GB 3095-1996 缺失版本）：status=missing；目标解析 0/1；**local 调用被跳过**（skipped_reason 记录，邻近版本不可替代）；usable 0。
- 服务调用（真实）：LLM 2（keyword，0 answer）、embedding 5、Qdrant 5、Neo4j 10、PG 只读（含 JSON 记账的 SQL 次数）；neg-001 零模型调用。0 初始化/写库/重建。
- **PG-only 开关实跑**（`--pg-only`）：neg-001 真实运行 status=missing、usable=0、0 模型调用（`phase-3-fusion-smoke/`，仅作开关端到端证据；主结果为 `phase-3-fusion/`）。
- 交付物：`fusion-candidates.jsonl`（3 行，逐题 usable/rejected/路径/完整原文/预算）、`fusion-runtime-latest.json`（全证据）。

## 入口级测试（tests/test_fusion.py，11 项）

两路同一 chunk 合并且路径齐全（分数口径各异不求和）；不同 workspace 同 chunk_id 拒绝不混源；同内容不同版本双保留；明确版本不存在而 local 有邻近版本仍 missing 且 local 跳过；2012/2026 比较缺一目标不替代、已解析证据保留；未 verified/归属冲突拒绝；local 超时 → PG-only 降级带凭证且 PG 候选仍可用；PG stale 拒绝且 local 不运行；doc/scope 目标保持类型、显式空 discovery 不被枚举回填；PG-only 开关跳过 local；不完整阶段记录上报 degraded。全部经正式 `run_fusion` 入口。

## 测试与检查

全套 **266 passed**（原 255 + 11 项融合入口测试；无删除/弱化）。Ruff check/format、OpenSpec strict、diff、凭据扫描通过。`--pg-only` 开关与回退说明见 fusion.py 模块 docstring 与本报告。

## 边界

本阶段只做可审计的合并/发现顺序与约束，**不产生联合 rerank 分数、不生成答案**（5.4/5.5 未进入）。syn-001 的跨版本差异、neg-001 的 missing 期望为发现层行为，语义质量与 Gate 3 未验证。
