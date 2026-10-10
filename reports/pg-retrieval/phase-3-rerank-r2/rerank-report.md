# 5.4 联合精排（R1–R4 补正后，第二代次）

日期：2026-10-07。响应 `phase-3-rerank-review/review.md` 与 `handoff-phase-3-5.4-fixes.md`。首轮交付（`phase-3-rerank/`，含 200 成功与 404 失败两次历史凭证）保留；本轮集中补正 R1–R4，新代次 `phase-3-rerank-r2/`。不重跑 keyword/embedding/local 检索整轮。

## R1 输入可验证且集合完整

- **回放身份绑定**：`_verify_replay_binding` 将回放报告的 `identity_after`（source_fingerprint/catalog snapshot/search/gold）与**当下**生产身份采集逐字段比较，不符即拒绝整个回放——任意文件不因"当前库冻结"而被信任。
- **逐候选来源核验**：`_verify_candidates_against_source` 以 (workspace, chunk_id) 只读回读**当下**生产 PG 行：行存在、workspace 一致、`verified=True`、doc 归属与生产 `full_doc_id` 一致、回放正文与生产内容**逐字节相等**（篡改正文后重算 SHA 不等于来源证明）。任一问题拒绝整题，被拒候选不能从其它路径回流。
- **缺正文不缩减**：任一候选缺读回正文 → 整题显式 degraded（列出缺正文 chunk），余下集合绝不静默过滤后仍报 ok。
- 全部条目仍走**同一个联合请求**；端点/模型配置不变，不改 .env/gold/目录/索引。
- 本轮实测：10/10 候选 source_verification 全部通过、problems=[]。

## R2 成功与回退同一份完整来源

- typed doc/scope/table 目标独立保留在输出的 `typed_targets`（真实回放 3 个），不作为伪 chunk 送精排。
- `_fallback_ordered`：HTTP 失败/响应非法的回退项与成功项保留**同一份**完整身份（workspace/chunk_id/doc_id/content_sha256/全部 paths），仅 `rerank_score=None`、顺序为原融合序。
- **表片路径补齐**：`_enrich_table_paths` 按 `env_rag.unit_chunk_links` 真实目录映射为回放候选补齐 unit_id/table_id/citation（新增itive、原路径原样保留、basis 字段注明"回放先于 5.3-F2 修复"），不猜任何 id/locator。本轮实测补齐 41 条（含 tb-…-0001/0002/0003 三个物理片）。

## R3 完整失败边界与每题凭证

- 继承 5.3 统一前置出口：gold 读取/JSON/结构、unknown id、config（含 **RERANK_BINDING_API_KEY 缺失拒绝**——绝不发 Bearer None）、SHA、fused 读取/解析全部在零接触失败终态边界内；任意普通 Exception 兜底写终态并原样 raise（BaseException 不捕、异常不吞）。
- **live 凭证**：HTTP 交换完成即发布当前题真实 call receipt 到 `live`；超大分数等响应验证崩溃不再丢失已发生的调用凭证。新题开始先重置 live（query_id/call 清空）再接触任何服务。
- **分数验证安全化**：`_finite_score` 对 10**400 这类超限整数 OverflowError 安全拒绝；`_validate_response_safe` 兜住任何验证内部异常转为显式拒绝原因；非法分数（即便 HTTP 200）按原序 degraded 回退、0 伪分数。

## R4 原始证据与净化

- **原始响应落盘**：`call.raw_response` 保存净化后的实际 `{id, results:[{index, relevance_score, …}], meta}`——独立重推排序（按 −score/index 排序映射回身份）与发布 `ordered` **逐项一致**（本轮已独立验证），id+count 不能替代分数凭证。
- **凭据净化**：`_sanitize_evidence` 在任何证据落盘前递归清洗已配置 key/password/token/secret 与 Authorization 等敏感字段（401 回显 key 的响应正文→`<redacted>`）；失败证据保留状态/错误类型/非敏感原因。
- 每题记录模型、url_path_used、documents_sent/chars_sent、elapsed_ms、验证/skip/degraded 状态；HTTP 200 不等于精排成功——非法响应仍拒绝。
- CLI 精排分支格式已修（ruff format 通过）。

## 验证

- 独立反例 `tests/test_rerank_review_r1.py` **14/14**；原矩阵 `tests/test_rerank.py` 16/16 语义保持（fixture 按交接允许更新为可复算正文 SHA + 显式 fake 只读 PG 行，未删/未弱化任何顺序/来源保留断言）；全套 **309 passed**。Ruff/format、OpenSpec strict、diff、凭据扫描通过。
- **真实重跑一次**（新代次，fact-002 固定 10 候选回放）：HTTP 200、997ms、10/10 输入；source_verification 10/10；净化原始响应保存且独立重推排序一致；identity 前后冻结一致、无 drift。首次 200/404 历史保留在 `phase-3-rerank/`，新代次单独记录、不冒充旧响应。
- 0 答案 LLM、0 缓存写入、0 写库/初始化/重建（来源回读与目录映射均只读）。

## 交付物（phase-3-rerank-r2/）

`rerank-runtime-latest.json`（全证据含 raw_response）、`rerank-inputs.jsonl`（10 行）、`rerank-runs.jsonl`（真实调用凭证+排序）、`rerank-report.md`（本文件）、`rerank-manifest.json`（SHA 索引）。停 5.4 检查点待主agent复审；5.5/5.6/Gate3 未进入。
