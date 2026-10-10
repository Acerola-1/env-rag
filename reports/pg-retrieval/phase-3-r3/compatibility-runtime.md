# 5.1 隔离兼容性运行时验证（第三轮，D1–D4 补正后）

日期：2026-10-06。本轮响应第二轮复审 D1–D4（`reports/pg-retrieval/phase-3-review-r2/review.md`、`handoff-phase-3-fixes-r2.md`），全部修复落在正式入口 `src/env_rag_final/compat_runtime.py`（rev 3），并由修复后的正式 CLI 完成隔离库完整重跑。首轮（C1–C5 前）与第二轮（C1–C5 后）报告/JSON 保留为历史，不混代。

复跑入口：

```
uv run python -m env_rag_final.compat_runtime --report-dir reports/pg-retrieval/phase-3-r3
uv run python -m env_rag_final.compat_runtime --cleanup-run-record reports/pg-retrieval/phase-3-r3/compat-run-record-<run_id>.json
```

本轮完整重跑结果：`compat-runtime-probes-20261006T185724.json`（= `compat-runtime-probes-latest.json`），run_id `compat-c747236f3cde`，scratch `lightrag_probe_de2f3b6ee7` (oid 145173)，`cleanup.dropped=true, ownership_verified=true`。0 次实际模型/embedding 服务调用（LLM/embedding 均为确定性 fixture；embedding fixture 函数仅本地 numpy 计算）。

## 0. 固定来源与生产身份（本轮前后实测一致）

- 八表计数 221/5709/279/16514/65527/221/221/119575（before 与 after 均采集、逐表相等）。
- 源指纹 before/after 均 `95f7791fd84171ab…`；catalog active run/snapshot `c15c741742394320`/`4919b3938ad93747`；search active `872d689343a9cbb6`；gold SHA `1bf130077c21583a…`；`.env` SHA before/after 相同（`e3bf75975fde9761…`）。
- 全部采集走只读连接（`default_transaction_read_only=on`）；正式库未实例化 LightRAG/ClientManager，未发生任何 DDL/DML。

## 1. D1 清理核验完整化：三重 OID + 无按名终止

`_verify_ownership` 现在要求 marker.secret==记录 secret、**marker.db_oid==记录 oid**、当前 pg_database oid==记录 oid 三者同时成立（缺一即 `ProbeAborted`，对应复审反例 marker.db_oid=999/current=42）。`cleanup_scratch` 移除了按库名 `pg_terminate_backend`：验证连接关闭后、任何破坏性语句前，`_recheck_oid_and_sessions` 从 admin 连接重新确认当前 OID 未变且无非本探针会话；`application_name` 常量不再作为本 run 身份使用（只用于会话分类），外来会话存在即拒绝而非终止。全部路径 0 次 `pg_terminate_backend`。

实弹验证（真实服务器，记录于本文档及执行日志）：

- 篡改库内 marker `db_oid` → `cleanup_scratch` 拒绝（`ownership marker mismatch`），库仍在、0 会话被终止；复原 marker 后真实清理成功（dropped, ownership_verified）。
- 附加外来会话（application_name=someone-else-cli）→ 拒绝（`1 foreign session(s) … refusing cleanup`），0 终止；外来会话退出后清理成功。

安全验收（假连接，无真实危险 SQL）：`tests/test_phase3_compat_review_r3.py` D1 组 5 项（marker OID/current OID/secret 任一不符拒绝、身份变化时 terminate 与 DROP 均未执行、外来会话拒绝、正常路径无 terminate）。

## 2. D2 前后身份守卫转化为完整拒绝

- `_identity_mismatch` 补上 **catalog run**（不只 snapshot）：run/snapshot/search/source/gold/env 任一与冻结值不符都拒绝。
- 新增 `_identity_drift`：post 对 before **逐字段比较**（八表计数、catalog run+snapshot、source fingerprint、search active、gold SHA、`.env` SHA）——even if the after 值仍合法，运行期间变化即失败。
- 预守卫失败不 acquire（无临时对象）；后置失败写 `guard_failure.stage="after"` 并非零退出，且清理照常执行。

实弹验证（真实 `run()` 编排 + 注入采集值）：catalog run 错误 → `pre-guard failed: catalog run not-… != frozen`（未创建任何临时库，leftover probe dbs=[]）；`.env` SHA 逐次漂移 → `post-guard failed: .env sha changed: original1 -> original2`；source 指纹变化但计数不变 → 预守卫拒绝（`source fingerprint mismatch`）。断言层验收见 r3 测试 D2 组 5 项（含 search active 途中切换由 drift 拒绝）。

## 3. D3 失败回收、独立报告与可用的恢复入口

- `run()` 的 finally 三步独立：①后置身份采集与比较、②`cleanup_scratch`（带所有权验证）、③失败报告写出。任何一步异常不吞掉后续步骤；清理失败记录 `cleanup.dropped=false + error`，非零退出。
- 后置采集抛错不再跳过清理/报告：异常记为 `after-capture-error` 阶段。实弹验证（真实 run + 注入 OSError）：`refused: post-guard capture failed: OSError: post-capture connection lost`，且 `guard_failure.stage=after-capture-error` 已写盘、`cleanup.dropped` 已执行、recovery 记录存在。
- **恢复入口真实可用**：每次 acquire 后立即写私有恢复记录 `compat-run-record-<run_id>.json`（0600，含 run_id/库名/OID/secret；公开报告不含 secret），`--cleanup-run-record` 读取该记录走完整 `_verify_ownership`+重验路径。验收测试覆盖"生成→读取→清理"往返（正确 secret 成功 DROP、错误 secret 拒绝）；实弹验证该记录在清理后重放按预期拒绝（DB 已不存在）。
- acquire 失败/工作阶段中途异常同样写失败报告；工作阶段异常（含探针合同违规）由 `stage_error` 记录为 `failure.stage="probe-stage"`。

## 4. D4 必验探针成功合同 + 缺项补齐

- `_enforce_probe_contract` 在正式 `run()` 入口强制：`PGTableGraphStorage` 必须 OK 且有建表与节点往返；`PGGraphStorage`/`PGVectorStorage` 必须 FAIL 且 `attributed_to` 精确等于预期（AGE `ag_catalog` 缺失；pgvector `unknown type: public.vector`）；缺 key/缺字段/意外 OK/错归属 → 整轮失败（`required probe contract violated`），报告记录 failure、无 `finished_at`，清理仍完成。
- **PGVector 探针补全最小配置**（`vector_db_storage_cls_kwargs.cosine_better_than_threshold=0.2`，`vector_storage="PGVectorStorage"`；pgvector python 包本就是项目声明依赖 `pgvector>=0.4,<1`，未新增依赖）：现在真正到达池引导（CREATE EXTENSION vector 在隔离库失败）→ `register_vector` codec → `unknown type: public.vector`，与复审独立探针一致。这是扩展兼容性失败本身，不再是构造参数错误。
- **同 workspace 版本并列**：`ws_probe_same` 内 doc-a/doc-b 并存（chunk id `doc-2ab7b92c…` / `doc-c87b8a57…` 不同、内容不同、状态 processed），`aquery_data("总磷限值")` 同时返回两个版本内容。
- **公开→物理对照**：逐 workspace 记录 `public_to_physical_mapping`——每个 `aquery_data` 返回 chunk 的 chunk_id+full_doc_id+content 与 `lightrag_doc_chunks` 行逐项比对（本轮 2/2 映射成立），不再只存内容前缀。
- **同实例重复 initialize**：`PGTableGraphStorage` 二次 `initialize()` 复用同一池（`repeated_initialize_same_pool: true`），DDL 幂等重跑、无新 get_client。
- 报告只陈述本轮实际样例：三个 workspace（ws_probe_a/b/same）各自 processed；此前"包含外来会话的旧测试"表述已更正——旧 C1 假连接测试只覆盖固定名复用/固定名 cleanup/计数变化，外来会话拒绝本轮由真实路径（r3 测试 + 实弹）证明。

## 5. 发布包行为矩阵（本轮实测，隔离库）

| 后端 | 结果 | 归因 | 证据 |
| --- | --- | --- | --- |
| PGTableGraphStorage（发布包原生普通表图） | OK | — | 建 `lightrag_graph_nodes/edges`（PK 含 workspace/namespace），节点 upsert/get_node 往返成功；重复 initialize 复用同池 |
| PGGraphStorage | FAIL | Apache AGE missing（`ag_catalog.ag_graph` UndefinedTableError） | 已到达 AGE 检查阶段 |
| PGVectorStorage | FAIL | pgvector 扩展缺失（`unknown type: public.vector`） | 已到达扩展+codec 阶段（完整最小配置） |
| enable_vector (CM 参数 None/Nano/Qdrant/PG) | False/False/False/True | — | `get_config` 实测；LightRAG 默认 vector=NanoVectorDBStorage |

其余结论沿用前两轮（仍以本轮重跑复核为准）：首次建池 initdb/check_tables=1/1、持引用复用 1/1、全释放重建 2/2；`(workspace, chunk_id)` 组合键（同文件名 doc-a 跨 workspace 同 chunk id 不同内容）；公开 `get_by_ids` 缺失返回 `[None]`；`lightrag_llm_cache` 小写表 9 列、本轮 cache_type 仅 extract（插入阶段；查询缓存归 6.1）；正式库两张 graph 表 0 行、来源保持 UNKNOWN（表数不能定因），5.2 验证真实 Neo4j/Qdrant 语义路径。

## 6. 正式只读策略（不变）

正式库从不实例化 LightRAG/ClientManager（首建池即库级 DDL）；正式访问仅 asyncpg 只读连接（`default_transaction_read_only=on`）做身份采集。所有 LightRAG/存储初始化指向 per-run 唯一 scratch DSN；`POSTGRES_WORKSPACE` 全局覆盖持续清除（C2），workspace 由构造参数显式传入并断言生效。Qdrant/Neo4j 本轮未初始化。

## 7. 测试与检查

- 全套 **208 passed**（原 181 + r2 8 项 + r3 新增 19 项；r2 的 6 项失败断言全部转为通过，无删除/xfail/弱化——r2 文件仅修正 stub 与假连接行为以匹配 rev 3 正式路径，断言语义保持）。
- r3 新增 19 项：D1 组 5（marker OID/current OID/secret、无 terminate、外来会话）、D2 组 5（env 漂移、catalog run 预守卫、source 变计数不变、search 途中切换、后置采集错）、D4 组 6（必验 FAIL、AGE 意外 OK、PGVector 构造级失败、缺 key、正常路径、恢复记录先于探针）、D3 组 3（恢复记录往返、错 secret 拒绝、失败运行仍留恢复记录）。
- Ruff check/format 203 files 通过；OpenSpec strict 通过；无凭据出现在报告/JSON（恢复记录仅含本 run 私有材料，0600 权限）。
- 实弹拒绝路径证明（真实服务器、真实入口、非 fixture）：见 §1/§2/§3/§4 各"实弹验证"段；全程 0 会话被终止、0 外来对象被清理，结束后 leftover probe dbs=[]。
