# Phase 1 structure correction handoff

## Scope

结构检查点暂不通过。阅读 reports/pg-retrieval/phase-1-review/review.md、三个反例 JSON 与 live-verification.json，修复 S1–S7；对应 tasks 2.1–2.6。第 3 组枚举闭环暂不开始。

已有 public.lightrag_* 和 MinerU 产物保持只读。本应用 schema 可以做显式迁移和新配方构建；回退或清理只能作用于明确归本应用所有的对象，保留当前构建和失败证据。禁止对真实 public 对象运行反例删除／写入。

## Order and evidence

1. 先修应用 schema 所有权：schema 参数一致、验证标识符、禁止 public／系统及未知 schema，回退执行前核验归属。隔离迁移和回退验证真正使用独立应用 schema，不仅检查 SQL 字符串。
2. 修范围层级与保守状态：GB 3095 第4章包含4.1／4.2，叶范围排除相邻章节；内嵌条款未定位时持久化约束，不能只返回大 block warning。GB 18466 的4.1.1–4.1.6同一 block 情况保留。
3. 修元数据：GB 18466 的标题，不把“依据 GB…”当自身编号；位置、引句、置信度可追溯，未知与冲突保留。对实际文档抽样复核，不仅验证特定正例。
4. 修映射和适配器：HTML table 的真实完整 id 属性，多 workspace 同 ID，稳定分页与来源变动 stale。所有关系仍不得仅凭 ID 引用升级为全文覆盖。
5. 修构建：前后指纹包围派生，发布前核验消费来源；配方变更产生新 build；run 保存 snapshot 关联；失败重试与并发发布有数据约束和隔离数据库验证，link→chunk归属也核验。
6. 用与 catalog 源码对应的新配方重建自有目录，验证旧源内容指纹与 public 表计数保持不变，旧 active 被正常退役且新 active 唯一。请勿使用旧“源不变就跳过”路径冒充已修复目录。
7. 保留旧报告为历史，生成新的结构报告、manifest 与样本；记录实际测试数量、代码／配方版本、源指纹、已知 partial／ambiguous 和失败案例，不把 fixture 或计数验证扩展成未实测结论。

只勾选已经修复并有证据的 2.1–2.6。完成后停在结构检查点，供主 agent 复审；不要勾选第 3 组或 Gate 1。

## Copyable prompt

请在 /Users/acerola/Dev/Python/RAG/env-rag-final 按 OpenSpec add-pg-scoped-retrieval 修复 Phase 1 结构审查 S1–S7。先读 reports/pg-retrieval/phase-1-review/review.md 和 handoff-phase-1-fixes.md，修所有权保护、范围层级、元数据、真实表格映射、workspace／分页快照以及构建配方、来源守卫和并发发布。只操作应用拥有的辅助 schema，public 原文与 MinerU 产物保持只读。补行为反例及隔离数据库测试，以新配方重建目录并生成可复核报告；完成后停在结构检查点，第3组不开始。
