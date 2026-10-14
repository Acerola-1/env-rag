# env-rag

环境知识库：230 份中外环境标准/公报 PDF（大气、水），提供两条互相独立又可组合的检索路径：

- **PG 文档与范围检索**：PostgreSQL + pgvector 上的关键词检索、元数据过滤，以及不依赖模型总结的**表格/条款完整清单枚举**（解决“表查全了没有”的问题）。
- **LightRAG 图检索**：`lightrag-hku`（PyPI 1.5.7）+ Qdrant 向量库 + Neo4j 图谱，支持 naive/local/global/hybrid/mix 模式，以及两路融合与精排的工程实现。

面向使用者的是一个**带登录和分库授权的网页网关**（8099）：按账号决定能查哪个知识库，支持选库查询、完整清单、基于证据生成回答（带引用，证据过期/范围歧义时停止生成）、来源全文与 PDF 下载、个人历史记录。

## 快速开始（macOS）

### 1. 准备依赖服务

Python 3.12，用 [uv](https://docs.astral.sh/uv/) 安装依赖；大文件走 Git LFS：

```bash
git lfs install
uv sync --locked
cp .env.example .env      # 然后填写自己的服务配置
```

后端三个存储运行在本机容器里（现场使用 Apple Container，其他机器可用 [deployment/docker-compose.workspaces.yml](deployment/docker-compose.workspaces.yml) 模板，未在本机以 Docker 验证）：

| 服务 | 默认地址 | 用途 |
| --- | --- | --- |
| PostgreSQL + pgvector | 127.0.0.1:5432 | 原文 chunks、目录与搜索索引（自有 `env_rag` schema） |
| Qdrant | http://127.0.0.1:6333 | 向量索引 |
| Neo4j | bolt://127.0.0.1:7687 | 知识图谱 |
| LLM 兼容端点 | http://127.0.0.1:8787/v1 | 生成/抽取模型（OpenAI 兼容协议） |
| Embedding/Rerank | https://api.siliconflow.cn | 需自行配置 API key |

应用本身是纯 Python 进程，与容器运行时无关——只要这些端口和库里数据就绪即可；但数据在容器卷内，没有后端就没有可检索内容。

### 2. 启动两个 LightRAG 实例与网关

```bash
container system start          # Apple Container 服务未运行时
container start lightrag-postgres lightrag-qdrant lightrag-neo4j

.venv/bin/python scripts/wa_instance_env.py   # 生成实例环境文件（本机）
bash scripts/wa_instances.sh start air
bash scripts/wa_instances.sh start water

.venv/bin/python -m env_rag_final.access --port 8099
```

### 3. 登录试用

浏览器打开 <http://127.0.0.1:8099>，账号口令见 **[ACCOUNTS.md](ACCOUNTS.md)**（例如 `water-reader` 只能查水库、`dual-reader` 两库都能查）。页面只绑定 127.0.0.1。

### 4. 自检与测试

```bash
uv run env-rag-final doctor --connections    # PG/Qdrant/Neo4j 只读连通检查
PYTHONDONTWRITEBYTECODE=1 uv run pytest tests -q
uv run ruff check src tests scripts
```

## 常用命令

```bash
# 纯 PG 完整清单（不需要模型、不需要 LightRAG，只需 .env 里 5 个 POSTGRES_*）
uv run env-rag-final ask --query '列出 GB8978-1996 表1的全部项目及限值'

# 注册表演示账号（生成/更新 credentials.md）
.venv/bin/python scripts/wa_bootstrap_registry.py

# 入库（可中断重跑，已完成的文档不重复计费）
uv run env-rag-final workspace-ingest --workspace air --dry-run
uv run env-rag-final workspace-catalog --workspace air
uv run env-rag-final workspace-index  --workspace air
```

全部命令见 `uv run env-rag-final --help`；历史评测期的命令语义表保存在 `reports/` 对应轮次目录。

## 仓库结构

| 路径 | 内容 |
| --- | --- |
| `src/env_rag_final/` | 应用代码：`access/`（8099 网关与网页）、`web/`（旧对照网页）、检索、枚举、入库、评测 |
| `datasets/` | 230 份 PDF 与 MinerU 解析产物（Git LFS）、固定金标、SHA 清单 |
| `deployment/` | Apple Container 实例脚本配置、Docker Compose 模板、注册表模板 |
| `scripts/` | workspace 引导、入库、验收与巡检脚本 |
| `docs/initialization/` | 当前有效的入库与发布边界说明 |
| `assets/` | **历史探究归档**：旧对照网页、PG 检索研究、整理记录（详见 [assets/README.md](assets/README.md)） |
| `reports/` | 各轮评测与验收证据（400MB+，逐轮自组织，勿手改） |
| `openspec/` | 规格驱动的变更计划；已完成的在 `openspec/changes/archive/` |
| `.local/` | 本机运行状态（不进 Git）：注册表、口令清单、实例密钥、记录、入库账本 |

## 网页入口说明（避免混淆）

本项目演化出两个网页：

| 入口 | 模块 | 认证 | 现状 |
| --- | --- | --- | --- |
| **8099 Knowledge API** | `env_rag_final.access` | 登录 + 分库授权 | **当前唯一推荐入口**，说明见 [WORKSPACE-ACCESS.md](WORKSPACE-ACCESS.md) |
| 8091 检索对照页 | `env_rag_final.web` | 无（本机评测工具） | 历史工具，启动还依赖隔壁的 LightRAG 源码 checkout；用法见 [assets/legacy-comparison-web/WEB_RAG.md](assets/legacy-comparison-web/WEB_RAG.md) |

## 数据与质量边界（重要）

- 数据库、向量、图谱、缓存、`.env` 和密钥**不入 Git**；数据库是运行时派生数据，重建不能保证逐字复现历史 LLM 图谱。入库/重建边界见 [docs/initialization/INGESTION.md](docs/initialization/INGESTION.md)，发布边界见 [docs/initialization/PUBLISHING.md](docs/initialization/PUBLISHING.md)。
- 权限是**应用层粗粒度知识库授权**，不是数据库强隔离（未启用 RLS）；演示账号仅限本机试用，正式部署必须替换全部凭据。
- 评测结论：固定金标为 31 正例 / 10 反例；**Gate 4 未通过，默认融合未启用**——工程可运行不代表检索质量已达标。完整证据在 `reports/pg-retrieval/`。
- 语料默认定位 `datasets/corpus/parsed`，可用环境变量 `ENV_RAG_PARSED_ROOT` 或 `ENV_RAG_DATA_DIR` 覆盖。

## 分支

`dev` 为开发分支，`main` 为稳定分支。命令名保留 `env-rag-final` 以兼容既有脚本。
