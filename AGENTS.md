# AGENTS.md

## 正式运行态（始终适用）

- 知识数据只使用PG5432/rag、现有Qdrant/Neo4j及air/water/coastal技术目录，身份只使用远程IAM19100。唯一权威清单见[正式环境](docs/CURRENT-RUNTIME.md)；历史评审/评分/归档不得当作现用DSN或启动说明。
- 统一使用Agent的`deployment/run_separated_local.py start/status`；不重建已退役原库、评测容器或本地账号源。新测试只用空临时资源，完成后回收。

本文件是面向仓库协作者（人类与 AI）的项目事实与约定汇总。项目全貌见 [README.md](README.md)。

## 当前形态

- **当前网页入口是 8099**：`python -m env_rag_final.access`（登录、分库授权）。`src/env_rag_final/web/`（8091）是早期的无登录对照工具，启动还依赖仓库外的 LightRAG 源码 checkout，两者是不同时期、不同用途的应用。
- 演示账号的权威说明在根目录 [ACCOUNTS.md](ACCOUNTS.md)；正式本机口令与机器凭据清单是 `.local/remote-iam-live/credentials.md`（Markdown，账号由IAM管理，旧本地账号生成入口已退役）。凭据的读写逻辑统一在 `scripts/wa_credentials.py`，凭据格式以该模块渲染的 Markdown 表格为准。
- Gate 4 评测未通过、默认融合处于关闭状态，现有实验数据没有证明融合优于 local。`reports/` 与 `assets/` 中的结论都带时间戳，代表对应轮次的结果，引用时标注轮次即可与当前状态区分。

## 环境与命令

```bash
uv run env-rag-final doctor --connections            # PG/Qdrant/Neo4j 只读连通检查
PYTHONDONTWRITEBYTECODE=1 uv run pytest tests -q
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
```

Python 3.12；依赖由 uv 锁定在 `uv.lock`；LightRAG 依赖采用 PyPI 发布的 `lightrag-hku`（1.5.x），与隔壁的源码 checkout 相互独立。

## 数据与安全架构

- 正式 PG 的 `public`/`rag` 库与 MinerU 产物在架构上是**只读**的；写入范围限定在自有的 `env_rag` schema 和 air/water 等自有 workspace。全局 prune、删库、卷重建都在写入范围之外，现有工具也没有提供这类操作的入口。
- 查询路径不实例化 LightRAG 存储、不做存储初始化，对现有库只有读连接。
- `.env`、`.local/` 与生成的凭据都在版本库之外；历史审计产物中的凭据按 `.gitignore` 单独排除。
- 所有服务与网页仅监听 `127.0.0.1`；网关校验 Origin 拒绝跨站提交，源文件 API 采用白名单，不接受任意本机路径。
- LLM/embedding/rerank 调用都是计费的，测试套件默认离线（633 项零网络）；真实调用在专门的验收脚本中进行并留痕，调用次数有账本记录。
- 应答生成与答案缓存分属不同路径，评测产物不会作为答案缓存命中。

## 结果状态的含义

- `complete` 表示**已确认范围的清单完整**；`retrieved`/HTTP 200/`success` 只代表请求成功，与答案正确性无关。
- `stale/partial/ambiguous/missing` 状态下不进入答案模型；版本缺失时结果保留缺失状态；引用解析到来源的连续片段。
- 精排服务异常时序列保持原序并记录真实回执；枚举的完整集合不受 top-k 截断。
- 参考：[WORKSPACE-ACCESS.md](WORKSPACE-ACCESS.md) 与 `reports/pg-retrieval/` 中的状态机说明。

## 文件组织

- `assets/` 收存已结束探究线索的叙述文档（旧网页、PG 检索研究、维护记录），入口是 [assets/README.md](assets/README.md)。移动其中文档时引用路径同步更新，`src/env_rag_final/access/snapshot.py` 的 `PROTECTED_FILES` 是其中一处引用方。
- `reports/` 按轮次保存评测与验收证据，代次目录自组织，历史轮次保持原样；新克隆不包含全部本地审计缓存。
- OpenSpec：通过验收的变更位于 `openspec/changes/archive/`；`add-pg-scoped-retrieval` 因 6.2–6.5/Gate 4 尚未完成，仍在 `changes/` 下。
- `.local/` 是本机运行状态目录（注册表、口令清单、实例密钥、记录、入库账本），整个目录在版本库外。
- Python 运行带 `PYTHONDONTWRITEBYTECODE=1`，仓库不收录 `__pycache__` 和 `.DS_Store`。

## 提交约定

提交信息面向公开仓库，内容不含真实主机名、绝对路径或凭据；提交动作在使用者明确提出后进行。
