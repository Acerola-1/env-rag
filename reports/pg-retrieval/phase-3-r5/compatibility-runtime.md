# 5.1 隔离兼容性运行时验证（第五轮，F1–F2 补正后）

日期：2026-10-06。本轮响应第四轮复审 F1–F2（`reports/pg-retrieval/phase-3-review-r4/review.md`、`handoff-phase-3-fixes-r4.md`），修复落在正式入口 `src/env_rag_final/compat_runtime.py`（rev 5），并由修复后的正式 CLI 完成隔离库完整重跑。第四轮（rev 4/E1–E3）产物保留于 `phase-3-r4/` 为历史，不混代。

复跑入口：

```
uv run python -m env_rag_final.compat_runtime --report-dir reports/pg-retrieval/phase-3-r5
uv run python -m env_rag_final.compat_runtime --cleanup-run-record reports/pg-retrieval/phase-3-r5/compat-run-record-<run_id>.json
```

本轮完整重跑结果：`compat-runtime-probes-latest.json`（时间戳版 20261006T*），run_id `compat-f17917f2f455`，scratch `lightrag_probe_0033d69b98`，`cleanup.dropped=true, ownership_verified=true`，`required_probe_contract.problems=[]`。0 次实际模型/embedding 服务调用（fixture 仅本地 numpy/异步桩）。

## 0. 固定来源与生产身份（本轮前后实测一致）

八表计数 221/5709/279/16514/65527/221/221/119575；源指纹 before/after 均 `95f7791fd84171ab…`；catalog active run/snapshot `c15c741742394320`/`4919b3938ad93747`；search active `872d689343a9cbb6`；gold SHA `1bf130077c21583a…`；`.env` SHA 前后相同。正式库仅只读身份采集；所有 LightRAG 初始化在自有隔离库。

## 1. F1 OID 读取失败不再掩盖部分创建身份

`_acquire_scratch` 中 `row` 在第一个可能抛错的 await 之前初始化为 `None`；CREATE DATABASE 之后任何一步失败（连接、OID 查询、marker 建表/插入）都构造携带 `partial_scratch` 的 `ProbeAborted`，其中 `oid` 为 `None` 且 `oid_known=false`（明确 unknown，不冒充已验证）、`stage` 标注失败阶段（`connect-after-create` / `marker-setup`）、原始异常通过 `raise … from exc` 保留——不再出现 UnboundLocalError 覆盖原故障。所有权校验未放宽：marker/OID 不完整时 `_verify_ownership` 仍拒绝自动 DROP（安全拒绝），恢复走"以保留 secret 补建 marker → 三重校验通过 → 正式 cleanup"的可验证路径。

实弹验证（真实服务器，注入首个 OID 读取 OSError）：`refused with partial_scratch`，库名/secret 保留、`oid=null`、`oid_known=false`、`stage=marker-setup`，原始 `OSError` 文本完整；库确认已创建；以保留 secret 补建 marker 后走正式 `cleanup_scratch` 成功 DROP（`recovered_and_dropped=true`）。复审反例 `test_oid_lookup_error_does_not_mask_partial_creation_identity` 通过。

## 2. F2 部分创建失败走统一终态出口

移除了 partial 分支的提前 raise 平行出口：partial 获取被登记为本 run 的工作阶段失败（`stage_error`），继续流入与其它失败**同一条** finally——①后置身份采集（`capture_production_identity(...,'after')`，采集失败也记录 `identity_after_error`）、②安全回收（严格所有权校验的 `cleanup_scratch`，marker/OID 不完整按设计拒绝并记录 retained）、③失败报告终态落盘（`failure.stage="acquire-partial"`，含库身份、恢复记录路径或恢复失败、cleanup 成功/拒绝及阶段）。cleanup 拒绝时 `guard_failure.stage="cleanup-error"` 独立落盘，与 acquire-partial 并存可见。

复审三个 owning-entry 用例全部通过：partial 清理成功 → 终态报告含 `scratch.database`/`cleanup.ownership_verified=true`/无 `finished_at`；partial 运行仍执行 `capture:after`；partial 清理拒绝 → `cleanup.dropped=false` + `cleanup-error` 可见。本轮无 partial 情形（正常路径 `problems=[]`），上述为注入验证。

## 3. 正常路径完整重跑（本轮实际采集）

发布包行为矩阵（PGTableGraphStorage OK+同池重复 initialize、AGE/PGVector 按精确归因 FAIL）、`(workspace, chunk_id)` 组合键、同 workspace doc-a/doc-b 版本并列、public→physical 逐 chunk 映射、`get_by_ids` 缺失 `[None]`、cache 小写表 9 列 extract 阶段、池生命周期 1/1→1/1→2/2、`required_probe_contract` 全部强制项（同池/生命周期/cache_type）——结论与第四轮一致，以本轮 JSON 为准。恢复记录权限实弹核验 0600。

## 4. 测试与检查

- 全套 **220 passed**（原 216 + r5 复审 4 项：3 失败断言全部转为通过、1 正例保持；无删除/xfail/弱化）。
- Ruff check/format 213 files 通过；OpenSpec strict、`git diff --check` 通过。
- 实弹：F1 注入路径 + 正常 CLI 重跑；全程 0 会话被终止、0 外来对象被清理，结束后 leftover probe dbs=[]。
- 产物：`phase-3-r5/compatibility-runtime.md`、`compat-runtime-probes-latest.json`、`compat-manifest.json`、`compat-run-record-compat-f17917f2f455.json`（0600 私有恢复记录）。
