# Phase 0 correction handoff

## Objective

Gate 0 暂不通过。先阅读 reports/pg-retrieval/gate-0/review.md 和独立核验结果，补正 G0-1／G0-2／G0-3。只修审计工具、测试、报告与必要文档，不执行 Phase 1，不建 schema／索引，不改现有数据，不运行有迁移副作用的 LightRAG 存储初始化。

## Work and acceptance

1. 将名称 fingerprint 升级为来源快照摘要：PG 原文、chunks（ID、顺序、正文、heading／sidecar）、解析 blocks／tables、分块参数。使用固定只读快照，检测本地产物读取变化，补充审计代码指纹。
2. 删除写死的实时结论。273／14 矛盾、序号、meta、状态数量及重复定因由记录生成；重复限定为已验证的规范化正文等值，不宣称原 merged text 或 PDF 字节相同。
3. compatibility 真正执行离线接口／源码检查并保存证据。Qdrant／Neo4j 若不采集则标未验证或有依据的历史观察，不每次改时间后继续声称刚核实三库一致。
4. target_docs 展开为真实文档身份和快照；覆盖校验检查产物与 chunks。省略 ID／待枚举说明不作为 locator，gold 保持 unreviewed，不提前计算指标。
5. 输出真正 compatibility Markdown；manifest 覆盖全部交付步骤，记录失败阶段和统一 run ID。失败不能把旧 manifest 与新文件当作同一次成功运行。
6. 添加离线 fixture 测试：来源内容／分块／引用／table 变化改变摘要，报告随统计变化，未解析 target 不通过白名单，失败运行不混用成功报告。禁止修改现有语料或数据库。
7. 补正后只读复跑，保留前次报告为明确历史副本，说明差异。Ruff、相关测试与 OpenSpec 严格校验通过后，只恢复有证据的 1.5／1.6／1.8／1.9，1.10 留给主 agent。

## Copyable Prompt

请在 /Users/acerola/Dev/Python/RAG/env-rag-final 修复 OpenSpec change add-pg-scoped-retrieval 的 Gate 0 问题。阅读 reports/pg-retrieval/gate-0/review.md 和 openspec/changes/add-pg-scoped-retrieval/handoff-phase-0-fixes.md，完成 G0-1／G0-2／G0-3 的审计补正与 fixture 测试，保存可复跑报告。数据库保持只读，不进入 Phase 1，不创建 env_rag，不修改或初始化现有 LightRAG 存储；gold 保持未审核。完成后交回差异和证据，停在 Gate 0，1.10 留给主 agent 复审。
