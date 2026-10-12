# 工作区整理与提交核验

本轮整理只处理应用工作区，不修改已有数据库、语料、模型配置或隔壁 LightRAG checkout。

## 保留

- 网页应用、前端选择逻辑及其回归测试。
- DESIGN、UX 合同、网页使用说明和 PG 技术汇报。
- 历史验收汇总、截图、对照报告和原始证据；已有 `reports/pg-retrieval/` 保持原样。
- `.env`、本机数据库状态、历史预算及日常问答计量均保留。

## 整理

- 历史网页 GOAL 提示移入 `docs/handoffs/GOAL_RAG_COMPARISON_WEB.md`。
- 枚举后续方案移入 `docs/retrieval/ENUMERATION_NEXT_STEPS.md`。
- 原始网页 runtime 创建可恢复压缩归档及逐文件 SHA-256 清单；本机原目录保留并忽略，不直接提交可变状态。
- 根目录临时 `premium-audit.json` 移入忽略的 `.local/workspace-cleanup-20261012/`；`premium-ui.json` 是有效审计配置，保留。
- 删除可再生成的 Python／pytest／ruff 缓存和 `.DS_Store`，保留 `.venv`。
- `.env.example` 的两处向量存储类名修正为发布包实际提供的 `QdrantVectorDBStorage`；没有更换模型或修改 `.env`。
- 历史报告保留原始空白字节，由 `.gitattributes` 排除其空白格式告警。

## 当前基线核验

- Python 完整回归：580 项通过；唯一未通过项是沙箱不允许临时本机端口监听。该项在允许监听的环境下单独复验通过，合计 581 项通过。
- 前端选择：6 项通过。
- Ruff 检查通过；101 个 Python 文件格式检查通过。
- 新提交文件核对本机配置中的五类实际凭据，无命中；凭据本身不写入报告。
- 没有执行模型调用、入库、数据库迁移或知识库拆分。本提交是现有成果的基线整理，workspace 功能由后续独立 OpenSpec 实施。

源码与配置核对显示主模型、关键词模型、查询模型均为 `deepseek-v4.1-flash`；用户确认沿用。Embedding 为 `Qwen/Qwen3-Embedding-4B`，维度 2560；reranker 为 `Qwen/Qwen3-Reranker-4B`。这里只核对配置，未把模型服务可用性算作本轮已验证。
