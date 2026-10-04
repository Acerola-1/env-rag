# env-rag-final

独立的环境知识库 RAG 工程。目前只完成 Git、uv、依赖、配置和只读连通性检查。
检索、两路融合、枚举补全、评测尚未实现。

## 开始使用

```bash
uv sync --locked
uv run env-rag-final doctor
uv run env-rag-final doctor --connections
uv run ruff check .
```

Python 使用 3.12。正式依赖为 PyPI 的 `lightrag-hku`，没有引用本地源码。
`uv.lock` 固定本次安装版本。更新发布包使用 `uv lock --upgrade-package lightrag-hku`，
然后 `uv sync --locked` 并验证公开接口和数据库兼容性。

## 配置与来源

本地 `.env` 从 `/Users/acerola/Dev/Python/RAG/LightRAG/.env` 原样复制，追加本工程配置。
保留生成 LLM、keyword/query 模型、embedding、reranker、PG、Qdrant 和 Neo4j 配置。
`.env` 被 Git 忽略；`.env.example` 仅保留配置项和无凭据示例。
复制的连接指向现有数据库。doctor 只检查读取与认证，不创建或迁移 LightRAG 数据。
没有验证 LLM/embedding/reranker 的实际推理调用。

复用语料位置：`/Users/acerola/Dev/Python/RAG/LightRAG/inputs/__parsed__`。
优先复用已有 PG chunks 与 MinerU 的 raw/blocks/tables，不重新解析 PDF。

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
