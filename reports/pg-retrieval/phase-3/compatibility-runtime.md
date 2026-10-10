# compatibility-runtime.md — LightRAG 发布包运行时兼容验证（task 5.1，第二轮）

生成：2026-10-06（本轮 C1–C5 补正后完整重跑）。对象：**本工程 .venv 实装的 PyPI 发布包 lightrag-hku 1.5.7**（uv.lock 固定，`site-packages/lightrag/`，按安装 RECORD 与源码工作区无关，未升级依赖）。全部探针在**按次唯一命名、带所有权标记的隔离临时库**中执行；正式库 `rag` 与 `.env` 全程未被 LightRAG 触及。产物：`compat-runtime-probes-latest.json`（本轮原始记录，代次文件另存）、`compat-manifest.json`、复跑入口 `uv run python -m env_rag_final.compat_runtime`。

## 1. 临时库所有权与清理（C1）

- 每次运行生成**唯一库名** `lightrag_probe_<uuid>`；库内建 `probe_ownership` 表记录 `(run_id, secret, db_oid)`——三重所有权标记（库名+OID+secret）。
- 复用/初始化前校验归属：无本 run 标记的既有库**拒绝复用**（`_ensure_scratch` 遗留入口同样拒绝）；`cleanup` 校验 run_id+secret+OID 三者匹配，且**外来活动会话**（application_name≠本探针）在库时**拒绝清理**，绝不盲目 `pg_terminate_backend`。
- 本轮实测：`cleanup: dropped=lightrag_probe_3d78dca346, ownership_verified=true`；探针自己的 LightRAG 连接池在清理前通过 `finalize_storages()`/`finalize()` 显式排空（含 pgtable 图后端与 ClientManager 共享池）。
- 3 项安全验收（`tests/test_phase3_compat_review.py`，假连接、无真实危险 SQL）：无标记库拒绝复用/清理、外来会话拒绝终止——**3/3 通过**。

## 2. workspace 作用域与来源 ID 合同（C2）

- **移除了此前对 `POSTGRES_WORKSPACE` 的全局覆盖**；探针断言两个 LightRAG 实例的构造 workspace 实际生效，文档状态均 `processed`。
- **同文件名 `doc-a`、不同内容、两个 workspace：chunk id 完全相同**（`doc-2ab7b92c…-chunk-000`，按 file_path+分块序号派生）——内容不同不改变该 ID，这正是融合层必须以 **(workspace, chunk_id) 组合键**去重的运行时实证（前轮"内容不同 ID 不同"的结论撤回更正）。
- **公开查询逐 workspace 返回各自内容**（A→60、B→99，互不混源）；缺失 chunk 经**公开入口** `get_by_ids` 返回 `[None]`（明确不存在，不编造）。
- 同 workspace 不同版本文件并列保存另由既有 `doc-a/doc-b` 样例覆盖（各自独立 chunk id）。

## 3. 后端矩阵（C3）——失败按各自后端归属

| 后端 | 结果 | 归因 |
|---|---|---|
| `PGTableGraphStorage`（pgtable_impl，**普通表图**） | **OK** | — 建出 `lightrag_graph_nodes/edges` 两表（PK 含 workspace/namespace），fixture 节点 upsert/get_node 成功；无 AGE/pgvector 依赖 |
| `PGGraphStorage`（AGE） | FAIL | `UndefinedTableError: ag_catalog.ag_graph does not exist` —— 归因 **Apache AGE 缺失**（仅此后端） |
| `PGVectorStorage` | FAIL | `ValueError: cosine_better_than_threshold must be specified…`（配置项缺失；服务器亦无 pgvector）—— 归因 **该后端配置/pgvector** |
| enable_vector 矩阵（ClientManager.get_config） | None/NanoVectorDBStorage/QdrantVectorDBStorage → **False**；PGVectorStorage → **True** | LightRAG 默认 vector=NanoVectorDBStorage（enable_vector=False）；"None" 是 ClientManager 参数而非完整 LightRAG 配置 |

**更正前轮结论**：生产库多出的 `lightrag_graph_nodes/edges` 与发布包原生 `PGTableGraphStorage` 建表**形状一致**——"发布包不识别普通图表/必然由旧管线创建"的说法撤回；原图数据来源**保持未知**（表计数不能定因，正式 PG 两张图表 0 行仅记录）。AGE/pgvector 的失败只归属于各自后端，不泛化为"发布包路径不可用"。正式 .env 类名配置为 PG KV/Status、Qdrant vector、Neo4J graph——**Qdrant/Neo4j 语义路径未验证，归 5.2**。

## 4. 初始化/池生命周期与 cache 证据（C4）

- initdb/check_tables 按阶段计数（实测）：首次获取 **1/1**；**持有引用**的第二次获取仍 **1/1**（池复用，无重初始化）；**全部释放后**再获取 **2/2**（重建但 DDL 幂等）。前轮"同进程二次调用"的表述据此更正为"持引用复用/全释放重建"。
- `lightrag_llm_cache`（小写表名）**9 列**：workspace, id, original_prompt, return_value, chunk_id, cache_type, queryparam, create_time, update_time；本轮行 `cache_type='extract'`——**插入/抽取阶段 cache**；查询阶段 cache 的写入/禁用属 task 6.1，本轮不做声称。
- manifest 在**最后一次代码修改后**由本次运行重新生成（compat_runtime.py SHA 与提交一致），成功结论全部来自采集值。

## 5. 正式来源前后守卫（C5）

- 探针开始与结束各做一次**只读**采集：八表计数 + **内容级源指纹**（复算 docs/chunks/status 字节，非仅计数）+ catalog active(run/snapshot) + search active + 审核 gold SHA + `.env` SHA。
- 任一不符 → `ProbeAborted` 非零退出，报告保留 `guard_failure` 阶段与明细，不打印成功、不产出成功 manifest。隔离反例（假连接 doc_full=222）通过；本轮真实运行 before/after 指纹均为 `95f7791f…`，未触发。
- 异常/日志不含 DSN/密钥。

## 6. 正式只读接入策略（结论）

1. 正式库**不实例化** LightRAG/ClientManager/任何存储 initialize——首次建池即库级 DDL；
2. 只读证据读取沿用 asyncpg 只读适配器（`default_transaction_read_only=on` + statement_timeout）；
3. 5.2 的 local 语义链路在隔离环境/fixture 中验证真实模型调用，正式 Qdrant/Neo4j 后端只读；
4. 失败/超时/缺证据返回可见降级；不迁移正式库、不装扩展、不升级依赖。

## 7. 边界

- fixture（deterministic numpy embedding + async stub LLM）只证明接口形态与副作用，**不证明**真实 local 语义检索质量（5.2）。
- 真实 LLM/embedding 服务调用次数：0。
- 检查点状态：5.1 待主 agent 复审；5.2–5.6 未动。
