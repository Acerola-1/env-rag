# Phase 0 handoff

## Objective

首轮先收集工程可验证事实，执行 `tasks.md` 的 1.1–1.9；1.10 由主 agent 审查。
不开始第 2 组及后续实现。无需把整份语料重新复制或让用户手工收集数据库信息。

## Read First

按顺序阅读本 change 的 proposal.md、design.md、specs、tasks.md 和项目 README.md。
工作目录：`/Users/acerola/Dev/Python/RAG/env-rag-final`。
遵守仓库 AGENTS 指令：存在 `.codegraph/` 才优先用 CodeGraph；没有则不要自行索引。

## Inputs

- 本工程 `.env` 和 `.venv`／uv 锁定依赖。读取连接配置但不得打印或提交密钥。
- 已有 PG 中的 lightrag_doc_full、lightrag_doc_status、lightrag_doc_chunks 及其实际 schema。
- `/Users/acerola/Dev/Python/RAG/LightRAG/inputs/__parsed__` 的原始／blocks／tables 产物。
- 已安装 PyPI LightRAG 发布包及公开接口；旧源码项目仅用于理解已有产物，不能当成本工程运行依赖。
- design.md 的起点快照只是线索，全部关键计数和 ID 需要重新核验。

## Allowed Work

- 在本工程添加可复跑审计脚本、说明和 reports/pg-retrieval/phase-0/ 报告。
- 只读检查 PG 表、索引、配置、统计和原文映射；使用只读事务和合理超时。
- 离线检查已安装包接口与字段；小范围词项探针和身份／引用核验。
- 为真实评测提出题目、引用和待审核 gold，不伪造缺失样本。

## Boundaries

- 不写入现有数据库，不建表／索引，不重导入、不修 failed、不重新解析或向量化。
- 不连接现有库运行可能自动迁移的 LightRAG 存储初始化。
- 不调用付费 LLM、embedding、reranker，不安装新的运行依赖；这些在后续任务中明确实施。
- 不修改 LightRAG 源码、本工程运行配置或密钥，不读取无关私密资料。
- 不因为连不上数据库就只交泛化建议；保留本地可完成的产物、报告确切阻断及未验证项，不能冒充已完成审计。

## Deliverables

交付目录 `reports/pg-retrieval/phase-0/` 至少包含：

1. audit.md
2. inventory.jsonl
3. schema.json
4. mapping-samples.jsonl
5. compatibility.md
6. search-probes.json
7. sample-set.json
8. run-manifest.json

按 design.md 定义填充。文件要能直接被主 agent 读取和复核；机器可读文件使用明确状态，不能用空文件占位表示完成。
样本集为候选稿，gold 未审核必须标记；若资料不足以覆盖所有类别，列出缺口而不是换成合成题。
失败异常信息需脱敏，报告只说明必要的错误类型、阶段与影响，不能泄露 DSN 或 token。

## Acceptance

- 清单能解释目录、状态和 chunks 的不同计数口径，并给出缺失／异常记录的身份与依据。
- 映射样本包含两片同 chunk 表格、正文条款、跨 chunk 范围和异常关系；没有真实样本的项明确缺口。
- 每个结论注明已观察事实、推断或未验证；发布包 import 成功不等于检索兼容。
- 审计工具可复跑；记录语料变化，不能为了消除差异写库。
- `tasks.md` 只勾选已交付且有证据的 1.1–1.9 项。不要勾选 Gate 0 或后续任务。
- 最终向用户报告产物路径、关键发现、未解决项和建议进入的下一组任务，供主 agent 审查。

## Copyable Prompt

请在 /Users/acerola/Dev/Python/RAG/env-rag-final 执行 OpenSpec change `add-pg-scoped-retrieval` 的 Phase 0，只做 tasks.md 1.1–1.9。先阅读该 change 的 handoff-phase-0.md、design.md、specs 和 tasks.md，遵守只读数据库、隐藏凭据及无自动迁移边界。用现有环境核验 PG 与 MinerU 产物的身份、范围、缺失记录、block/table→chunk 多对多映射，以及 LightRAG 发布包的离线接口兼容信息。交付 reports/pg-retrieval/phase-0/ 中定义的八个报告和可复跑审计入口；真实问题与标准答案附来源及审核状态。完成后停在 Gate 0，报告证据与缺口，不创建辅助数据库对象、不实现检索或融合。
