# 历史资产（assets）

这里归档**已结束的探究线索**留下的叙述性文档：日常开发不再依赖，但记录了当时试过什么、如何验收、结论是什么，供日后回溯。当前系统的使用说明在仓库根目录的 [README.md](../README.md)，入库与发布边界在 [docs/initialization/](../docs/initialization/)；逐轮运行证据与报告仍在 [reports/](../reports/)，不在此处。

## 目录

| 目录 | 探究线索 | 关键文档 |
| --- | --- | --- |
| `legacy-comparison-web/` | 早期的本机检索对照网页（8091，无登录的评测/对照工具，已被带登录的 8099 网关取代） | WEB_RAG.md（使用与验收结算）、DESIGN.md / UX-CONTRACT.md（设计与交互合同）、premium-ui.json（UI 审计配置）、GOAL_RAG_COMPARISON_WEB.md（当时的 GOAL 交接提示） |
| `pg-retrieval/` | PostgreSQL 结构化检索、范围枚举与 LightRAG 对照评测（含 Gate 4 未通过、默认融合未启用的结论） | ENUMERATION.md（枚举增强入口说明）、PG-RETRIEVAL-BRIEFING.md（技术汇报）、ENUMERATION_NEXT_STEPS.md（后续方案） |
| `maintenance/` | 历次工作区整理记录 | WORKSPACE-CLEANUP-20261012.md |

## 归档约定

- 只移入，不删改结论；文档内指向 `reports/` 的证据链接仍有效。
- 归档文档中的旧路径（如 `docs/handoffs/`）以文首注记或文档内说明为准。
- 新的已结束探究线索可新建子目录，并在本表追加一行。
