# 5.4 联合精排（对合并候选的一次真实 reranker 调用）

日期：2026-10-07。响应 `handoff-phase-3-5.4.md`（5.3 已由 `phase-3-fusion-review-r4/review.md` 验收通过）。仅实施 5.4；5.5 展开/生成、5.6 Gate3、Phase4 整轮对照未进入。

复跑入口：

```
uv run env-rag-final rerank-candidates --query-id fact-002 \
  --fused-report reports/pg-retrieval/phase-3-fusion/fusion-runtime-latest.json \
  --report-dir reports/pg-retrieval/phase-3-rerank
```

## 实现（`src/env_rag_final/rerank.py` + CLI `rerank-candidates`）

- **输入合同**： owning 编排入口取 5.3 融合结果的**全部 usable 合并集合**（同一 `query_id`、含两路路径、doc 归属、`content_sha256`、读回完整原文），一次请求发给精排服务——不分别精排 PG/local 后拼接、不只精排 local、不用展示摘要代替正文。输入带稳定 `input_index` 与 `(workspace, chunk_id)`；typed doc/scope/table 目标独立保留、不伪装成 chunk 文本。无读回正文的条目记 skip、绝不冒充。
- **服务合同（已核实）**：SiliconFlow `POST {host}/v1/rerank`（Cohere 风格）：请求 `{model, query, documents, return_documents:false}`，响应 `{id, results:[{index, relevance_score}], meta.tokens}`。配置复用 `RERANK_BINDING_HOST/RERANK_BINDING_API_KEY/RERANK_MODEL`（Qwen/Qwen3-Reranker-4B），不改 .env、不换端点；HOST 已含完整端点路径时直接使用（本轮实测曾因重复拼接 `/v1/rerank` 得 404，已修正为按 host 形态判断并记录 `url_path_used`）。
- **响应验证**：覆盖全部输入 index 且无重复/越界/缺失；分数必须有限数值（bool/string/NaN/Inf 拒绝）；按 `(−score, input_index)` 稳定排序（同分保原输入顺序）；排序结果经**响应 index** 映射回输入身份，不做正文相同匹配——同正文不同版本保持两个来源。
- **失败合同**：网络超时/401/403/非 2xx/非 JSON/结构错误分别记录真实状态码、耗时、错误类型与净化响应证据（不泄漏 headers/key）；失败按原融合顺序显式 `degraded` 回退，`rerank_score=None`、不伪造分数；不允许借用上一题响应（每题独立 call receipt）。
- **skip 合同**：空集合 / fused `missing`/`stale` 记 skip 原因并保持 **0 调用**——rerank 不升级任何不可信结果；身份前后守卫沿用 5.3（capture + drift），工作错误统一终态。
- **预算**：输入上限 40；超限显式拒绝并记录（不静默截断后谎称完整）。本阶段不按 top-k 丢弃、不展开、不生成。

## 验收矩阵（tests/test_rerank.py，16 项，全 fixture 无真实服务）

1. 两路合并输入**只发一次**联合请求，服务收到全部输入的完整原文；分数真实改变顺序；路径/来源保留（index 映射验证）。
2. 同正文两版本不误合并——按响应 index 各自回到正确版本（doc A/B 互异）。
3. 401 / 超时 / HTTP 500 均有真实失败凭证（status_code/error/elapsed）与原序 degraded 回退、0 伪造分数。
4. 重复 index、缺失 index、越界 index、bool/string/NaN/Inf 分数、无 results 数组、非 JSON——全部安全拒绝，完整集合不被静默缩减。
5. missing 状态 skip 且 0 调用；第二题失败凭证独立（第一题 `ok`、第二题 `degraded` 各自 call receipt）；40+ 输入超预算显式拒绝。

## 真实调用（一次，fact-002 合并候选回放）

- 输入：`phase-3-fusion/fusion-runtime-latest.json` 的 fact-002 usable（10 条，主agent已独立全文 PG 回读的历史输入；本轮未重跑 keyword/embedding/local）。冻结身份核对通过后才发送。
- 结果：HTTP 200、863ms、documents_sent=10、chars_sent=16441、results_len=10；identity before/after 冻结匹配、无 drift；gold SHA 实读匹配。
- 排序：10/10 按 index 映射回身份；top 分数 0.999318 → 最低 0.170743，单调递减；分数来自真实响应（`rerank_score`），原始 pg/local 分数保持独立口径未混合。路径与 `content_sha256` 逐项保留。
- 0 答案 LLM、0 缓存写入、0 写库/初始化/重建；llm_cache 16,514 不变。
- 过程记录：首次真实调用因 URL 重复拼接得 HTTP 404（失败凭证完整保留：degraded、无伪分数），修正拼接逻辑后重试成功——失败与成功两次凭证均在 `rerank-runtime-*.json` 历史文件中可审计。

## 交付物

`rerank-inputs.jsonl`（10 行：input_index/workspace/chunk_id/doc_id/SHA/路径）、`rerank-runs.jsonl`（真实调用凭证 + 排序映射）、`rerank-runtime-latest.json`（全证据，含守卫）、`rerank-report.md`（本文件）、`rerank-manifest.json`（SHA 索引）。

## 边界

本轮只做一次有界联合精排与可审计排序输出，不宣称检索/答案质量提升；5.5 范围展开与生成、5.6 Gate3 未进入。
