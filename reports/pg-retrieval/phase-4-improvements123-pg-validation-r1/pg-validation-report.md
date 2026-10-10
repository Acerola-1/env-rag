# 五腿 PG 只读实况与预算核验（2026-10-09T02:32:13Z）

按 `handoff-phase-4-improvements123-pg-validation.md` 执行：一次有界真实 PG 只读运行，零模型/零付费服务，第二轮保持暂停，不勾 6.2/6.3/Gate4，不切默认融合。

## 运行材料与执行

- 驱动/新锚/预算/交接/代码 SHA 逐一核对与 review-manifest 相等后才执行（核对输出见对话记录）：driver `0a94cc00…`、anchor `1d540f4c…`、budget `4a7bfe11…`、expand `7ce0a67c…`、doc_enum `495efb96…`、answer `98328f7f…`、query `25bed96d…`、evaluation `a42d5c68…`。
- 环境恢复（不修配置）：`container system start` 拉起既有 apiserver 后 `container start lightrag-postgres`；未新建容器、未改 .env、未做额外探测（健康探测交由运行内前后守卫）。
- 按交接命令仅执行一次：`run_pg_validation.py --report-dir reports/pg-retrieval/phase-4-improvements123-pg-validation-r1`（目录全新）。控制台记录在 `console.log`，EXIT=0。
- 未跑 pytest：交接注明工程 526/冻结 42/35 已验证；代码 SHA 与已验收锚完全一致。

## 前后身份守卫（现场核实，非锚转述）

identity_before == identity_after：source `95f7791f…`、catalog `c15c741742394320/4919b3938ad93747`、search active `872d689343a9cbb6`、gold `1bf13007…`、env `e3bf7597…`、八表计数 221/5709/279/16514/65527/221/221/119575、problems 空、matches_frozen true。与锚登记期望逐项相等；锚未冒充现场观察。

## 五腿结果

| 题目 | coverage | status | gold 事后核对 | 模型 | PG 实发 | 拒绝 | answer 时延 |
|---|---|---|---|---|---|---|---|
| file-enum-002 | complete | ok | missing 0 / extra 0 | 0 | 91 | 拒绝 0 | 2081ms |
| file-enum-005 | complete | ok | missing 0 / extra 0 | 0 | 111 | 拒绝 0 | 4447ms |
| prose-enum-002 | complete | ok | 2/2 | 0 | 128 | 拒绝 0 | 5465ms |
| prose-enum-003 | complete | ok | 4/4 | 0 | 118 | 拒绝 0 | 3353ms |
| prose-enum-006 | complete | ok | 1/1 | 0 | 108 | 拒绝 0 | 3587ms |

- file-enum-005/pg：base 1 + 同快照归属扫描 related_matches 3 / 证据 2 / 新增 2，并集 3/3，missing/extra 0；两份修改单 self_code 保持未知（None，警告登记），未伪造；`publication_guard=stable`、read_token 在场，每条 citation_verified+reverified 均真，引用绑定快照 4919b3938ad93747。搜索层读取 0（并集来自目录层）。
- file-enum-002/pg：年报 5/5 完整，年份 2021–2025 与 gold expected_versions 精确一致；现行基础分页 5/5 复读不丢项。
- prose-enum-002/pg：4.1.1/4.1.2 两项完整声明，坐标独立复读相等（reverified）；4.1.2 现长 128 字与既有离线观察一致（含原文单位内的标准号尾行，无表格尾巴）；无兄弟条款/无关表尾混入。
- prose-enum-003/pg：恰 4 条，4.3.4 现长 53 字与离线观察一致；无表 1–5 HTML。
- prose-enum-006/pg：4.2 整体条款 48 字与离线观察一致，尾止于“见表 1和表 2。”，无表尾。
- gold 仅事后核对集合/内容，未参与任何输入生成；答案条目文本为逐字原文（编号前缀/句号属原文），与 gold 正文逐字一致（比对口径见 `leg-verdicts.json` 的 items 字段）。

## 预算账本

- PG：reserved=issued（批 5120 帽内）总量 556；单腿 91/111/128/118/108 全 ≤1024 帽；拒绝 0。
- keyword/embedding/Qdrant/Neo4j/rerank/answer 事件为 0：账本 service_events 只有 pg 一类（reserved/issued），实发全 0。
- 时延样本 5（answer 2.1–5.5s，腿总 5.4–8.0s）；运行级身份采集按既有排除口径单列（not_billed 声明保留原文）。

## 门槛判定

无 budget_failure、无腿级 failure、无身份漂移，单腿 PG 峰值最大 128 ≤ 512：**有限缓冲门槛满足**。按交接仍不自动启动 local/fusion 或整轮；本批不构成 31 题指标、融合增益或第二轮，也不证明 local 混入修复/空 search_id 已在现场复验（离线 owning 证据保持，后续单独有界安排）。

## 覆盖事件披露

本轮目录全新，无覆盖旧代写入；`phase-4-improvement-3` 六份历史终态已由主 agent 按原 SHA 恢复（见 review-r2 `history-recovery.json`），本轮保护复算确认零漂移。
