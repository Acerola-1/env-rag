# 5.4 联合精排（C1–C3 补正后，第三代次：派生元数据）

日期：2026-10-07。响应 `phase-3-rerank-review-r2/review.md` 与 `handoff-phase-3-5.4-fixes-r2.md`。前两代次（`phase-3-rerank/`、`phase-3-rerank-r2/`）保留为历史。**本轮 0 新模型/embedding/reranker 调用、无新 HTTP**：元数据修复后对已验收的 997ms/HTTP 200 原始响应做派生映射，不冒充新响应。

## C1 规范来源身份与正确请求

- **canonical 元数据**：`_verify_candidates_against_source` 在正文逐字节核实后，从当前生产行**重算** `content_sha256`/`content_len` 并把 `doc_id` 回填为真实 `full_doc_id`；回放原值保留在 `replayed_*` 字段、修复依据记录在 `canonicalization_basis`。错误 SHA/空 doc_id 不再以 verified 元数据原样发布（修复而非仅拒绝）。
- **题目绑定**：`_rerank_one` 开头校验回放 entry 的 `query`/`workspace` 与冻结题目一致，不一致抛 AdapterError 拒绝——其它问题/编号版本条件的候选绝不因"当前库冻结"进入本题评分；缺失字段拒绝而非默认相等。
- **旧矩阵 fixture 修正**：`_usable` 记录**真实可复算正文 SHA**（不再是 `sha-{order}` 占位）；`_fused` 带规范 `query`/`workspace`；显式 fake PG 行明确注册。所有原顺序/两版本/来源/降级断言保留。

## C2 按实际单元类型补关联

- `_enrich_table_paths` 重写：`unit_chunk_links JOIN source_units`（workspace/snapshot/doc/unit 组合键）取真实 `unit_kind`——**只有 table 才创建 `table_unit`/`table_id`**；block 及其它类型用 `source_unit`/`unit_kind` 关联语义，正文 block 不再伪装表格。
- **固定 active snapshot**：快照缺失直接跳过并记录（跨代次扫描分支已移除）。
- 关联一律标注 `enrichment_basis`：这是**关联补全**，不是新 PG 检索命中或请求范围确认；不靠 tb 前缀猜类型。
- **历史更正**：首轮宣称"41 条表片补齐"有误——独立只读核验（本轮复跑一致）实际 **12 table + 29 block**。修复后派生映射 `table_unit=12`、`source_unit=29`，可独立按类型核对。

## C3 净化覆盖所有写盘路径

- **先净化后截断**：`_call_rerank` 的错误正文/非 JSON/异常消息全部先 `_sanitize_evidence` 再 `[:300]/[:200]`——secret 跨截断边界不再留下未净化前缀。
- **终态统一净化**：`_write_terminal` 在唯一写盘点对**整个 report**（含前置/身份/failure detail 与任意嵌入证据）执行净化；配置 key/password/token 与敏感字段不进入任何公开报告，真实错误类型/状态与非敏感原因保留。
- **占位值碰撞修复**：`_sanitize_evidence` 改为**最长优先**替换；测试 fixture 的一字符占位凭据（"v"/"k"）换成足够长且不与正文/ID 冲突的合成值（交接明确允许），来源正文/SHA 核验语义不变。
- **生产分支真实测试**：C2 类型修复经 owning 入口的 explicit fake PG（block/table 各一）验证——`test_block_link_not_fabricated_as_table_fragment` 通过，不靠 transport 分支跳过。

## 验证

- 冻结 `tests/test_rerank_review_r2.py` **6/6**；r1 独立 14/14、原矩阵 16/16（fixture 按交接允许改为真实 SHA/规范绑定，断言未删弱化）；全套 **315 passed**。
- **派生映射**（无新 HTTP）：从已验收 997ms 原始响应独立重推排序，与发布 ordered 逐项一致；输入正文 SHA 不变；`phase-3-rerank-r3/rerank-derived-metadata.json` 保留派生依据与历史更正（41 误标 → 12 table/29 block）。旧 runtime 原样保留。
- Ruff/format、OpenSpec strict、diff、凭据扫描通过；0 写库/初始化/重建（仅只读目录查询）。

## 交付物（phase-3-rerank-r3/）

`rerank-derived-metadata.json`（派生映射+依据+历史更正）、`rerank-inputs.jsonl`（正文 SHA 不变的 10 输入）、`rerank-report.md`（本文件）、`rerank-manifest.json`（SHA 索引）。停 5.4 检查点待主agent复审；5.5/5.6/Gate3 未进入。
