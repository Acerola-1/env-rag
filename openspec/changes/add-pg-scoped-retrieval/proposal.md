# Proposal

## Why

现有 LightRAG 路径能够发现语义相关证据，但 top-k chunks 无法证明文件清单、正文条目或跨页表格已经列全。本工程已有 PG 原文和 MinerU 产物，需要先验证它们的对应关系，再增加关键词定位、元数据过滤和完整范围读取，与 LightRAG 形成互补的两路检索。

## What Changes

- 先完成只读数据审计，固定可复用语料范围、文档身份、解析／分块快照和依赖兼容性；输出机器可读清单与核验报告。
- 在本工程管理的独立 PG schema 中建立文档、章节／条款、逻辑表格与原始 blocks／chunks 的定位目录，原文继续复用已有存储。
- 增加标准编号等精确条件检索、应用侧中文分词与 PG 原生全文检索、目标范围完整读取。
- 同时支持文件枚举、正文枚举、表格枚举；条目附来源，不确定或缺失范围显式报告。
- 接入 LightRAG 发布包的公开检索接口，统一 chunk 身份、联合精排，再展开枚举所需完整范围。
- 建立可复现的真实语料评测和反例测试，分别验证候选召回、范围覆盖、条目集合、版本／来源正确性与延迟。
- 分阶段推进：审计 → 结构定位和读取 → PG 全文检索 → 融合和评测。每阶段有输入、交付与进入下一阶段的证据门槛。

## Capabilities

### New Capabilities

- `corpus-evidence-catalog`: 可审计的语料范围、来源身份、版本快照及文档／章节／表格定位关系。
- `pg-scoped-retrieval`: PG 条件定位、中文关键词候选、完整范围读取及有证据的枚举结果。
- `retrieval-fusion`: LightRAG 与 PG 候选统一、联合精排、完整范围展开及失败可见性。
- `retrieval-evaluation`: 固定真实样本、无答案缓存污染的同请求上下文评测与验收报告。

### Modified Capabilities

无。本仓库此前没有 OpenSpec 主规格。

## Impact

- 本仓库 `src/env_rag_final/`、CLI、测试、评测工具，以及新建的应用辅助 PG schema；新增配置需同步无凭据的 `.env.example`。
- 复用 `/Users/acerola/Dev/Python/RAG/LightRAG/inputs/__parsed__` 和已有 PG 表。既有 LightRAG 表只读；新目录和索引通过显式迁移／构建命令维护。
- 中文分词依赖与词表在审计后的探针中确定并锁定；不新增 embedding 流程，不引入 ES，不修改 LightRAG 源码。
- 此次请求交付 OpenSpec 计划。创建计划不表示功能已实现，也不替用户派遣其他 agent。
