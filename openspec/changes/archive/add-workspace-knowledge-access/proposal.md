# Proposal

## Why

现有 PG 目录、检索索引和范围读取已经支持 workspace，但问答入口、网页、LightRAG 适配映射及运行记录仍限制为 default。需要以大气／水资料交付一套实际可用的知识库授权示例，允许不同企业／角色访问不同资料集合，并支持以后通过配置新增知识库。

## What Changes

- 建立 Knowledge API：先认证主体，再从服务器配置计算允许的 workspace；角色与知识库分开管理。
- 交付 air、water 两个固定 workspace 的独立 LightRAG 服务实例，共用现有 PostgreSQL、Qdrant、Neo4j 服务；PG 检索保留一个服务，按授权 workspace 查询。
- 将已有 PG 查询、完整范围展开、LightRAG 各模式及组合查询接入显式 workspace 上下文；可选一个或全部已授权知识库。
- 用仓库 PDF／MinerU 产物构建可追踪的分类及分片清单，先完成小样本试入库，再完成冻结清单中的大气／水资料导入及派生目录／索引构建。已有 default 数据保留。
- 网页提供最小登录、已授权知识库选择、查询、生成、引用和文件读取；历史记录、导出、下载和缓存执行相同权限检查。
- 提供可重复启动／停止的两个实例与网关部署、配置模板、幂等导入命令、必要回归和真实验收脚本；新增第三个 workspace 不修改核心检索代码。
- 沿用 `deepseek-v4.1-flash`、现有 Qwen embedding 和 reranker 配置，记录真实服务回执，不更换 HY3。

## Capabilities

### New Capabilities

- `workspace-access-control`: 主体认证、企业／角色到 workspace 的授权，以及所有知识读取入口的统一权限边界。
- `workspace-retrieval`: 单／多 workspace 下的 PG、LightRAG 与组合检索、来源身份及范围完整性。
- `workspace-ingestion`: 分类与分片清单、独立知识库入库、重复资料、派生索引及更新生命周期。
- `workspace-deployment`: 两个固定 workspace 实例、共享存储、运行配置和可扩展知识库注册。
- `workspace-query-ui`: 已授权知识库选择、查询状态、引用和记录访问的网页交互。

### Modified Capabilities

无。`openspec list --specs` 当前没有主规格；已有 `add-pg-scoped-retrieval` 是未归档变更，本次引用其完整范围与来源核验合同，不修改或冒充它已归档。

## Impact

- 主要涉及 `src/env_rag_final/{ask,cli,local_adapter,fusion,catalog,search,web}/` 的入口、运行配置和服务接入，以及新增 Knowledge API／授权模块、导入工具、测试和 `deployment/` 文件。
- PG 原文表、向量库、图谱增加本轮专属 workspace 的数据；`env_rag` 派生表按 workspace 维护。不得搬迁、改名、清空已有 default 数据。
- 复用仓库 `datasets/corpus/parsed/`。网页当前还依赖邻接 LightRAG checkout，实施时必须明确实际版本／来源与容器可用路径，不能把本地定制接口当成 PyPI 默认接口。
- 本轮不建设账号管理后台、收费系统、企业组织树、文档级 ACL、数据库 RLS、MCP 管理平台或通用权限规则引擎；不要求把 Qdrant／Neo4j 迁到 PG，不重做检索质量评测。
- 本次交付是计划和 GOAL 提示词；所有实施任务初始未完成。后续执行按 design、tasks、acceptance 和 GOAL 约束自主推进。
