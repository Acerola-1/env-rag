# 5.1 隔离兼容性运行时验证（第四轮，E1–E3 补正后）

日期：2026-10-06。本轮响应第三轮复审 E1–E3（`reports/pg-retrieval/phase-3-review-r3/review.md`、`handoff-phase-3-fixes-r3.md`），全部修复落在正式入口 `src/env_rag_final/compat_runtime.py`（rev 4），并由修复后的正式 CLI 完成隔离库完整重跑。第三轮（rev 3/D1–D4）产物保留于 `phase-3-r3/` 为历史，不混代。

复跑入口：

```
uv run python -m env_rag_final.compat_runtime --report-dir reports/pg-retrieval/phase-3-r4
uv run python -m env_rag_final.compat_runtime --cleanup-run-record reports/pg-retrieval/phase-3-r4/compat-run-record-<run_id>.json
```

本轮完整重跑结果：`compat-runtime-probes-20261006T203207.json`（= `compat-runtime-probes-latest.json`），run_id `compat-6ac185c09ad6`，scratch `lightrag_probe_96eff0f17d`，`cleanup.dropped=true, ownership_verified=true`；`required_probe_contract.problems=[]`。0 次实际模型/embedding 服务调用（fixture 仅本地 numpy/异步桩）。

## 0. 固定来源与生产身份（本轮前后实测一致）

八表计数 221/5709/279/16514/65527/221/221/119575；源指纹 before/after 均 `95f7791fd84171ab…`；catalog active run/snapshot `c15c741742394320`/`4919b3938ad93747`；search active `872d689343a9cbb6`；gold SHA `1bf130077c21583a…`；`.env` SHA 前后相同。全部身份采集走只读连接；正式库未实例化 LightRAG/ClientManager。

## 1. E1 实际执行 DROP 的连接自查身份

`cleanup_scratch` 改为三连接时序：①marker 验证（scratch 库内 probe_ownership，三重 secret/db_oid/记录 OID 校验）→ ②precheck admin 连接（`_recheck_oid_and_sessions` 首次拒绝点：当前 OID 与外来会话）→ ③**实际执行 DROP 的 admin 连接自己重新读取 pg_database OID 与剩余会话**，紧接 DROP 之前、同一连接内完成；②与③之间或②之前的任何身份变化都会被③捕获并拒绝。三个连接均无 `pg_terminate_backend`。

实弹验证（真实服务器）：

- 篡改 marker `db_oid` → ①拒绝，库保留、会话数不变；修复 marker 后真实 DROP 成功。
- 外来会话（application_name 异于探针）→ precheck 拒绝（`1 foreign session(s) … refusing cleanup`），DROP 连接根本不会打开；外来会话退出后清理成功。
- 对不存在库的恢复重放 → 明确拒绝（`InvalidCatalogNameError`，不吞错）。

安全验收：复审反例 `test_identity_change_on_actual_drop_connection_is_refused`（verify/precheck=42、actual DROP 连接=999 → 拒绝且该连接 0 DROP/terminate）通过；r3 正例同步更新为三连接时序（drop 连接执行的 `DROP DATABASE` 语句之前必须有其自身对 `pg_database` 的读取记录）。

## 2. E2 资源边界完全包围创建、恢复记录与初始化

1. **部分 acquire 可恢复**：`_acquire_scratch` 在 CREATE DATABASE 成功、marker 建立失败时抛出携带 `partial_scratch`（database/secret/run_id/partial=true）的 `ProbeAborted`。`run()` 捕获后将部分身份纳入报告（`scratch` + `guard_failure.stage="acquire-partial"`），尝试清理并重新拒绝——已创建的库名不再丢失。实弹验证：注入"新库连接失败" → `partial_scratch` 保留库名与 secret，库确实已创建；本轮按归属证据手动回收并确认无残留。
2. **恢复记录写入失败不跳过回收**：`write_recovery_record` 调用移入资源边界内；OSError 被记录（`recovery_record_error`）但清理与失败报告照常执行，最终 run 以 `recovery record write failed: OSError` 非零拒绝（无 `finished_at`）。实弹验证：`cleanup_executed` 为本轮库名、失败报告已写盘（`failure.stage="recovery-record"`）。
3. **构造实例即登记**：`probe_workspace_identity` 中 LightRAG 实例在构造后、`initialize_storages()` 前即放入 `rags` 集合；initialize/ainsert 中途抛错时 finally 仍对其调用 `finalize_storages`。复审假实例反例（initialize 抛错 → 全部构造实例 finalized）通过。
4. **cleanup-only 失败独立持久化**：主 finally 中 cleanup 拒绝（如外来会话）而其余全部正常时，写 `guard_failure.stage="cleanup-error"` 到盘后才抛错；复审反例（cleanup 抛 ProbeAborted → 报告 `cleanup.dropped=false` 且无 `finished_at`）通过。
5. **恢复记录 0600 从创建生效**：`os.open(..., O_CREAT, 0o600)` 首写即私有（无 world-readable 窗口），写失败时删除半成品文件；实弹核验本轮记录权限 `0600`。

## 3. E3 必验字段真正纳入合同

`_enforce_probe_contract`（在 run 入口、全部探针之后执行）新增：

- `PGTableGraphStorage.repeated_initialize_same_pool` **必须为 True**（缺失/False → `contract failure`，整轮失败、无 `finished_at`、清理与失败报告照常）；
- 池生命周期三阶段计数纳入合同：`first_acquire=1/1`、`second_acquire_holding_ref=1/1`、`reacquire_after_full_release=2/2`，缺失或错误值即失败；
- `probe_cache_details.columns` 必须存在且含 `cache_type`。

报告中的 `required_probe_contract` 块现在列出 required 后端、`lifecycle_stages_required` 与 problems，区分"采集到的观察字段"与"强制验收条件"；本轮实际运行 `problems=[]`。AGE/PGVector 的缺扩展失败仍按精确归因（`ag_catalog` / `unknown type: public.vector`）作为允许的预期失败，不视为环境意外。

## 4. 其余结论（本轮重跑复核一致）

发布包行为矩阵、`(workspace, chunk_id)` 组合键、同 workspace doc-a/doc-b 版本并列（`aquery_data` 双版本返回）、public→physical 逐 chunk 映射（chunk_id+full_doc_id+content）、`get_by_ids` 缺失 `[None]`、cache 小写表 9 列 extract 阶段、正式只读策略（正式库仅 asyncpg 只读连接；Qdrant/Neo4j 归 5.2）均与第三轮一致，本轮 JSON 为准。

## 5. 测试与检查

- 全套 **216 passed**（原 208 + r4 复审 8 项中 6 项失败断言全部转为通过、2 项正例保持；无删除/xfail/弱化）。
- Ruff check/format 209 files 通过；OpenSpec strict、`git diff --check` 通过。
- 实弹拒绝路径证明（真实服务器、真实入口）：§1 三项、§2 四项；全程 0 会话被终止、0 外来对象被清理；结束后 leftover probe dbs=[]。
- 产物：`phase-3-r4/compatibility-runtime.md`、`compat-runtime-probes-latest.json`、`compat-manifest.json`、`compat-run-record-compat-6ac185c09ad6.json`（0600 私有恢复记录）。
