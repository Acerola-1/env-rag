# env-rag-final

最新验收（2026-10-06）：Gate2第九轮复审仍未通过，只有非整数偏移类型检查顺序残留（177既有通过、新1失败）；原H1–H3反例、固定31题指标和实际引用回读通过。见[主agent报告](reports/pg-retrieval/gate-2/review-r9/review.md)及[单点补正单](openspec/changes/add-pg-scoped-retrieval/handoff-phase-2-fixes-r9.md)。以下旧状态为历史。

最新验收（2026-10-06）：Gate2第八轮仍未通过，仅引用验证器3个既定边界失败（174既有通过）。固定31题指标复现，源/目录/索引不变；4.4/4.6待验收。见[主agent报告](reports/pg-retrieval/gate-2/review-r8/review.md)及[最小补正单](openspec/changes/add-pg-scoped-retrieval/handoff-phase-2-fixes-r8.md)。以下为历史。

最新验收（2026-10-06）：Gate 2第七轮复审仍未通过。普通正文偏移已修；仅引用验证器3个反例失败（171既有通过）。冻结31题指标复现、源/目录/索引未变；4.4/4.6待验收。详见[主agent报告](reports/pg-retrieval/gate-2/review-r7/review.md)及[验证器补正单](openspec/changes/add-pg-scoped-retrieval/handoff-phase-2-fixes-r7.md)。以下旧状态为历史。

最新验收（2026-10-06）：Gate 2 第六轮复审仍未通过，仅剩普通正文兜底空行偏移及声明位置验证；D2、类别坐标和冻结31题指标已独立复现。170既有测试通过、新1反例失败；4.1–4.3/4.5完成，4.4/4.6待验收。见 [主agent报告](reports/pg-retrieval/gate-2/review-r6/review.md) 与 [单项补正交接](openspec/changes/add-pg-scoped-retrieval/handoff-phase-2-fixes-r6.md)。原报告保留为历史。

独立的环境知识库 RAG 工程。Gate0、v4结构目录与Gate1三类枚举已通过验收。已验证固定真实范围的表格、正文、文件清单及可回读引用；源库保持只读。
中文关键词检索的分词、索引与候选路由（4.1–4.3）已通过独立验收；Gate2整体未通过，类别引用坐标和空发现快照待补正；31题源金标已由主agent审核冻结。最新审查见 `reports/pg-retrieval/gate-2/review-r5/review.md`；两路融合及正式质量对照尚未实现。

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
已验证一次小范围正文模型抽取；embedding/reranker与LightRAG融合运行兼容性尚未验证。

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

## OpenSpec 计划

变更：`openspec/changes/add-pg-scoped-retrieval/`。
`proposal.md` 定义范围，`design.md` 定义阶段与验收门槛，`tasks.md` 跟踪执行证据。
首轮给执行 agent 的任务见 `handoff-phase-0.md`：先只读审计，交付数据合同和映射报告，
由主 agent 完成 Gate 0 审查后再实施目录、完整范围检索、中文全文检索与融合。
Phase0、结构目录与三类枚举已通过阶段验收；全文候选检索、融合和质量对照尚未完成。
Gate 0 首轮及复审记录见 reports/pg-retrieval/gate-0/review.md；下一位 agent 先执行
openspec/changes/add-pg-scoped-retrieval/handoff-phase-2-fixes-r5.md；原40反例均已通过，本轮新增2反例见 tests/test_gate2_review_r5.py；主agent金标审核副本为 reports/pg-retrieval/gate-2/review-r5/gold-approved.json，最新审查见 reports/pg-retrieval/gate-2/review-r5/review.md。
结构检查及v4复审证据见 reports/pg-retrieval/phase-1-review/review.md；3.6 Gate1已完成。
审计报告以完整代次发布，当前目录是指向成功代次的链接；历史代次和失败诊断分别保存在
同级 .<目录名>.runs 与 .<目录名>.failures 中，不逐文件混合覆盖。
