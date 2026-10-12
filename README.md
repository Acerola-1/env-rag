# env-rag

环境知识库检索工程：LightRAG local、PostgreSQL 结构化检索及融合对照。当前项目已完成两轮固定评测，以基线和失败报告收尾，**Gate 4 未通过，默认融合未启用**；工程可运行不代表质量已达标。详见 `reports/pg-retrieval/phase-4-final-closeout-r1/final-report.md`（实际收尾目录见 reports）。

## 仓库与数据

- `src/env_rag_final/`：应用、检索、范围枚举、答案与评测代码。
- `datasets/corpus/parsed/`：230 份 PDF 以及 MinerU JSON、blocks、tables、图片等原始解析产物；按文件 SHA 校验复制，原来源目录保留。
- `datasets/evaluation/`：固定金标与单位映射；`datasets/manifest.json` 记录语料字节和 SHA。
- `tests/`：工程回归；`reports/`、`openspec/`：历史证据、设计和交接记录。历史报告里的旧绝对路径仅是当时的审计信息。
- 数据库、向量、图谱、缓存、`.env` 和密钥 **不入 Git**。数据库是运行时派生数据；入库与重建方式见 [部署与入库说明](docs/initialization/INGESTION.md)。

当前网页使用见 [WEB_RAG.md](WEB_RAG.md)；历史网页 GOAL 提示和枚举后续方案分别归入 [交接资料](docs/handoffs/GOAL_RAG_COMPARISON_WEB.md)、[检索方案](docs/retrieval/ENUMERATION_NEXT_STEPS.md)。本机历史网页运行记录有 [可恢复归档](reports/archives/README.md)，工作区整理说明见 [维护记录](docs/maintenance/WORKSPACE-CLEANUP-20261012.md)。

大文件使用 Git LFS，首次克隆请先安装 Git LFS，再运行：

```bash
git clone https://github.com/Acerola-1/env-rag.git
cd env-rag
git lfs pull
python3 scripts/verify_dataset.py
uv sync --locked
cp .env.example .env
# 填写自己的数据库和模型服务配置
uv run env-rag-final doctor
uv run env-rag-final ask --help
PYTHONDONTWRITEBYTECODE=1 uv run pytest tests -q
```

语料默认定位本仓库的 `datasets/corpus/parsed`，不再读取另一个 LightRAG checkout。可用进程环境变量 `ENV_RAG_PARSED_ROOT` 或 `ENV_RAG_DATA_DIR` 显式覆盖。独立文件布局不等于内置数据库：运行检索仍需配置 PG；local 还需 Qdrant、Neo4j 与模型服务。

开发使用 `dev`，稳定功能合入 `main`；本次初始化两分支指向同一版本。命令保留 `env-rag-final` 名称，兼容既有脚本。

## 历史运行说明

下面保留此前各检查点的使用说明，质量结论以最终收尾报告为准。

## 开始使用

```bash
uv sync --locked
uv run env-rag-final doctor
uv run env-rag-final doctor --connections
uv run ruff check src tests
```

Python 使用 3.12。正式依赖为 PyPI 的 `lightrag-hku`，没有引用本地源码。
`uv.lock` 固定本次安装版本。更新发布包使用 `uv lock --upgrade-package lightrag-hku`，
然后 `uv sync --locked` 并验证公开接口和数据库兼容性。

## 配置与来源

本地 `.env` 由 `.env.example` 创建并填写自己的服务配置；不依赖另一仓库的配置文件。
保留生成 LLM、keyword/query 模型、embedding、reranker、PG、Qdrant 和 Neo4j 配置。
`.env` 被 Git 忽略；`.env.example` 仅保留配置项和无凭据示例。
复制的连接指向现有数据库。doctor 只检查读取与认证，不创建或迁移 LightRAG 数据。
已验证一次小范围正文模型抽取及真实local的keyword/embedding服务和只读来源接入；两路候选融合与联合精排已通过验收；答案链路已在 5.5 以真实回放、真实只读展开与回读完成工程验收，syn6真实合成与环境要素识别核对通过（此前三次503保持历史，四次HY3仅一次应用complete；质量稳定性尚未评测）。

复用语料位置：本仓库 `datasets/corpus/parsed/`。
优先复用已有 PG chunks 与 MinerU 的 raw/blocks/tables，不重新解析 PDF。

## Phase 3 运行说明（5.6 交付，2026-10-07）

以下命令逐一与 `src/env_rag_final/cli.py` 的 argparse 定义核对（本组仅离线核对，未执行任何有网络的命令）。每条注明**是否会真实调用模型/embedding/精排**——默认示例均不触发答案模型，不能误读为 0 调用以外的含义。

| 命令 | 真实调用属性 |
| --- | --- |
| `uv run env-rag-final doctor [--connections]` | 只读：依赖导入、配置计数与（可选）数据库连通检查；0 写入、0 模型 |
| `uv run env-rag-final search-query --query … [--code GB3095-2012 --strict-code] [--top-k 20] [--expand] [--expand-docs]` | **只读 PG**：关键词/元数据发现与完整范围展开；0 模型、0 embedding |
| `uv run env-rag-final enum-table --doc-id … --table-number 1 [--chapter-scope …]` / `enum-prose --doc-id … --scope-id … [--clause-wanted 3.1,3.2] [--with-model]` / `enum-docs --predicate … --page-size …` | **只读目录+sidecar 回读**；`enum-prose --with-model` 显式发起正文抽取模型请求（默认 0） |
| `uv run env-rag-final lightrag-local --query-id fact-002` | **真实 local**：keyword LLM 抽取、embedding、Qdrant/Neo4j 只读检索、PG 按 (workspace, chunk_id) 回读正文；答案模型 0、答案缓存 0 读写 |
| `uv run env-rag-final fuse-candidates --query-id fact-002,syn-001,neg-001 [--report-dir …]` | **两路**：local 路真实发生 keyword/embedding/Qdrant/Neo4j 调用；PG 路只读。加 **`--pg-only` 则完全跳过 local（0 模型/0 embedding）**——5.5 回放链路的输入即为显式 PG-only 运行 |
| `uv run env-rag-final rerank-candidates --query-id fact-002 [--fused-report <fusion-runtime.json>] [--report-dir …]` | **真实精排一次**：POST 配置端点 `/v1/rerank`；key 缺失直接拒绝（绝不 "Bearer None"）；401/超时/非2xx/异常分数→degraded 保原序、0 伪分数；>40 输入显式拒绝 |
| `uv run env-rag-final answer --query-id … [--fused-report … --rerank-report …] [--report-dir …] [--allow-model]` | 回放已验收融合/精排代次（入口记录文件SHA、前置身份采集后核对代次；范围读取及服务请求前拒绝不符代次）+ **只读**展开/独立回读；fact/file/prose/table 0 答案模型；synthesis **默认 0 调用**（`model_not_authorized`，报 incomplete），**仅 `--allow-model` 授权至多 1 次答案模型请求** |

失败与回退语义：

- **PG/目录 stale**：来源指纹、active run/snapshot 与冻结值不符时命令显式拒绝或标记 stale；回放报告代次与当前活体采集不符在**前置身份采集之后、范围读取/服务请求之前**拒绝（终态含原因）。
- **缺版本**：比较题缺一版本 → `missing`/`incomplete_conditions`（0 调用），绝不以邻居版本或 gold 替代；`--pg-only` 输入空集为权威零发现，枚举不回补。
- **local 失败**：local 路失败/超时不阻断 PG 路，可用 `--pg-only` 显式降级；degraded 记录真实原因，不冒充成功。
- **精排失败**：认证/超时/异常分数 → 原序 degraded + 真实回执（含 404/863ms/997ms 历史可对照）；精排顺序**仅是范围优先级**，完整成员展开永不被 top-k 截断。
- **答案层**：歧义/缺片/缺单位/预算截断/条件不可定位 → ambiguous/partial/incomplete，生成成功**不升级** complete；正文 claim 仅接受来源连续逐字片段（应用侧仅年份前缀/标点装饰），无法证明的改写 `model_failure`；`answer` 连接/身份守卫/运行级异常写失败终态并非零退出；已记录的 `model_failure/partial/ambiguous` 可以正常返回且退出码为0，必须检查 coverage、model.status 与实际服务凭证（不能以 Answer OK/HTTP200 当答案成功）。
- **来源与 schema 边界不变**：正式 PG `rag` 与 MinerU 产物只读；写入仅限自有 `env_rag` schema；不实例化 LightRAG 存储连接现有库；`.env` 不改、凭据不落盘。

Gate 3 条件逐条状态与证据见 `reports/pg-retrieval/phase-3/gate3-checklist.json`；一次必要真实合成请求的无凭据准备材料（请求已执行、第三次503）见 `reports/pg-retrieval/phase-3/syn-prep-syn004.json`。

## 后续实现边界

- LightRAG 路径通过依赖公开接口实现；local 暂作默认，mix 保留对照。
- 第二路验证 PG 关键词检索、元数据过滤和章节/表格完整读取；尚未引入 ES。
- 按 workspace/chunk ID 去重，联合精排，保留枚举所需完整证据。
- 评测绕过答案缓存并保存同一次生成请求的完整上下文。
- 不修改依赖源码，不把旧项目的定制能力当成发布包已经具备的能力。

初始化时本地源码版本为 1.5.8，PyPI 最新发布包为 1.5.7；二者不能视为完全一致。
未来接入现有存储之前需要核对 schema、workspace 和 MinerU 格式兼容性。

## 初始化验证（2026-10-04）

- PyPI LightRAG 1.5.7 与所有声明的客户端导入成功。
- uv 锁文件已生成；Ruff 检查和格式检查通过。
- PG `SELECT 1`、Qdrant 读取集合列表、Neo4j `RETURN 1` 通过。
- 尚未验证模型推理、已有 chunk 读取、MinerU 适配及两路融合。

## OpenSpec 计划

知识库权限与双实例的变更见 [add-workspace-knowledge-access](openspec/changes/add-workspace-knowledge-access/proposal.md)，实施边界、44 项任务及固定验收在同目录；交给 Z Code 的完整提示见 [GOAL-ZCODE.md](openspec/changes/add-workspace-knowledge-access/GOAL-ZCODE.md)。**本轮已实施并完成真实验收**，沿用当前 DeepSeek／embedding／reranker 配置。

### workspace 权限功能（已交付）

交付 `air`／`water` 两个固定 workspace 的 LightRAG 实例（共享现有 PG／Qdrant／Neo4j）、一个先认证后授权的 Knowledge API 网关与网页。启动、登录、入库、新增库、恢复与回滚说明见 [WORKSPACE-ACCESS.md](WORKSPACE-ACCESS.md)；本轮证据与报告见 `reports/workspace-access/wa-20261012-r1/`。

```bash
bash scripts/wa_instances.sh start            # 两个 LightRAG 实例
.venv/bin/python -m env_rag_final.access --port 8099   # 网关（唯一客户端入口）
.venv/bin/env-rag-final workspace-ingest --workspace air --dry-run
.venv/bin/env-rag-final workspace-catalog --workspace air
.venv/bin/env-rag-final workspace-index   --workspace air
```

workspace、主体与角色授权都在 `.local/workspace-access/registry.json`（模板 `deployment/workspaces.example.json`）；凭据只存在本机 `.local/` 下，不入 Git。新增第三个知识库只需改注册表、启动实例并入库，已由 `scripts/wa_third_workspace.py` 实测证明核心检索代码零改动。

变更：[add-pg-scoped-retrieval](openspec/changes/add-pg-scoped-retrieval/)。proposal定义范围、design定义门槛、tasks跟踪证据。Phase0–3及Gate3已验收；Phase4交接就绪，新增真实对照评测未执行。

固定金标：[审核副本](reports/pg-retrieval/gate-2/review-r5/gold-approved.json)，31正例/10反例期望，top-k=20，保持原题、期望及公开失败。源/词表/配方变化仍按stale合同处理。

阶段证据保存在reports/pg-retrieval/各阶段与审查目录；历轮退回/补正报告保留为历史。审计以完整代次发布，同级.<目录名>.runs与.<目录名>.failures保存历史代次及失败诊断，不逐文件混合覆盖。
