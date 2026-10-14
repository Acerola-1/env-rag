# 入库与重建边界

仓库保留原 PDF、MinerU 清洗产物和入库依赖（uv.lock 锁定 lightrag-hku），不分发 PG/Qdrant/Neo4j 数据库镜像。现有库的历史编号、chunk、图谱均由原 LightRAG 管线生成；清空库后重建不能保证逐字复现历史 LLM 图谱或相同快照，历史评测锚不能直接用于新库。

## 已有库

复制 .env.example 为 .env 并配置服务。先运行 `uv run env-rag-final doctor --connections`。应用 SourceAdapter 对 public 原文表只读；派生结构目录/搜索索引仅写自有 env_rag schema：

```bash
uv run env-rag-final audit --help
uv run env-rag-final catalog-migrate --help
uv run env-rag-final catalog-build --help
uv run env-rag-final search-build --help
```

新语料的入库顺序是先审计、确定新的来源指纹，再按上述入口参数显式构建；来源指纹按新语料内容生成，历史指纹与冻结锚不参与新语料构建。各迁移/构建实现位于 src/env_rag_final/catalog 与 search。

## 新库的原始语料导入

原文、chunks、embedding 和图谱的生成由锁定发布包 LightRAG 的入库管线负责，应用没有把旧数据库备份作为输入。LightRAG 的公开 `ainsert`/`apipeline_enqueue_documents` 与 `apipeline_process_enqueue_documents` 实现随 uv.lock 安装；PDF 解析与 sidecar 生成由其文件入库管线处理。复用现存 MinerU 产物时使用该版本支持的解析/sidecar 配置；merged text 不保留表格身份，单凭它构不成完整迁移。

本次仓库初始化未运行重新入库（会产生数据库写入及模型/embedding 费用），也未验证全新空库一键重建。当前保证的是语料文件和应用依赖自包含；运行数据库由部署者准备。已有生产数据的入库身份合同与解析字段证据见 reports/pg-retrieval/phase-0/audit.md，不需上传数据库内容。
