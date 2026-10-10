# 6.2 首批试跑执行交接（主agent，2026-10-08）

6.1已通过，Gate3保持。用户已明确确认DeepSeek恢复可用、允许恢复原来的DeepSeek，并要求准备交接交给执行agent。本交接安排之前提出的单轮9腿有界试跑，可直接执行，不再询问HY3切换或重复逐请求授权。运行后停主agent检查点，不自动扩为完整246腿评测。

## 已完成的配置准备

- `.env` 的QUERY_LLM_MODEL已从hy3恢复为deepseek-v4.1-flash；KEYWORD_LLM_MODEL与LLM_MODEL本来就是deepseek-v4.1-flash，保持。embedding/rerank、端点、凭据、提示与代码未改。
- 原6.1代码锚按字节归档为 `reports/pg-retrieval/phase-4/phase-4-config-anchor-6.1-approved-r4.json`；当前锚新模型代次为 `phase4-deepseek-restored-pilot-r1`。原Gate3锚及所有HY3/503历史运行保留，不混入本轮评测。
- 前后.env SHA、模型变更与新锚SHA记录于 `reports/pg-retrieval/phase-4/deepseek-restoration.json`（无凭据）；来源/gold/代码锚不变，零后端锚验证已通过。用户确认的服务恢复已采用，未额外健康探测。

执行agent首先核对配置锚/源码SHA与本交接一致，确认新输出目录未被完成代次占用，然后直接运行下列一次评测。实际源身份由入口现场只读采集并校验，不得回写expected去掩盖漂移。

## 有界试跑

冻结题号fact-002、prose-enum-001、syn-004；单轮，三路径pg/local/fusion，共9腿。fusion按已验收策略联合精排，另两路显式无精排，报告为系统对照。syn-004三路独立冷生成，最多3次答案调用，不复用syn6或旧答案。fact-002既有缺单位partial与合成/附录边界诚实保留，不预设complete。

预算配置：`reports/pg-retrieval/phase-4/pilot-budget-proposal.json`（沿用原文件名，本交接按此配置执行）。已通过owning dry-run，矩阵与上限见 `phase-4-6.1-review-r5/pilot-dry-run/`：

| 服务 | 单批执行的总上限 |
|---|---:|
| keyword LLM | 6 |
| embedding | 24批，每批≤32文本/64000字符 |
| Qdrant | 48 |
| Neo4j | 60 |
| PG计量读取 | 432（已批准排除口径保持，不声称全线SQL计量） |
| 联合精排 | 3 |
| 答案LLM | 3 |

仅一次9腿运行，完毕即停主agent审查；不追加请求/预算，不作编排或手工重试/额外健康探测。预算耗尽/单题失败按现行入口如实记录并处理其余已授权腿；运行级身份漂移按现行守卫拒绝。未知HTTP实发仍为unknown，不当成确定0或虚构账单金额。

执行命令（在env-rag-final根目录）：

```sh
.venv/bin/env-rag-final eval-run --round 1 --paths pg,local,fusion --query-id fact-002,prose-enum-001,syn-004 --allow-model --budgets reports/pg-retrieval/phase-4/pilot-budget-proposal.json --report-dir reports/pg-retrieval/phase-4-pilot-r1
```

输出目录必须是新代次，禁止覆盖完成代次。身份/model/prompt/code/预算保持同批固定，各路保存完整答案、来源、上下文、真实服务凭证与三态；来源区分正文与资料性附录。敏感值不落盘，正式PG/Qdrant/Neo4j/MinerU只读，不初始化或重建。

## 交付与停止点

交付9腿各自的新runtime、输入/精排/上下文/答案工件，附 `pilot-report.md` 与SHA manifest：逐题逐路记录真实候选、覆盖/降级/失败、引用回读、模型与来源身份、实际调用/预留/unknown和耗时；正文与资料性附录证据分列。syn-004人工检查两环境要素是否回答、附录句是否被错误升为规范要求，不能只以应用complete判语义正确。

只报告这9腿的链路与语义诊断，不能用3题代表31题总体指标，不能勾选6.2。完成这批即停主agent复审；不得追加重试/预算或自行执行完整246腿。配置与运行级身份拒绝保留终态、非零退出；单题partial/服务失败按已验收入口记录，不修gold、不改已验收代码来追求通过。若执行命令因代码缺陷无法运行，提交复现与终态即可，不现场扩大修改范围。

此次交接由用户自行交给执行agent，主agent不通过工具给其它聊天发消息。
