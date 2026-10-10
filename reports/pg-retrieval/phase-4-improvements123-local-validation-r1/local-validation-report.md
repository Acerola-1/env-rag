# 四腿 fresh local 有界实况复验（2026-10-09T03:24:05Z）

按 `handoff-phase-4-improvements123-local-validation.md` 执行：一次四腿 local 单路径单轮运行。真实 keyword/embedding/Qdrant/Neo4j/PG 只读请求，答案模型与精排为 0。第二轮、fusion、6.2/6.3/Gate4、默认路径全部不动。分母=3 正例+1 反例分列，不是 31 题指标。

## 材料与执行

- review-manifest 15 项与六受保护代码锚逐字节核对相等（driver f04a27b9、local 锚 038e8b60、预算 5e6f456f、handoff 64ae148f）后才执行；目标目录全新；EXIT=0，控制台在 `console.log`。
- 环境恢复按既有规程：apiserver/lightrag-postgres 已在（5432），本轮另启 `lightrag-qdrant`、`lightrag-neo4j`；集合清单只读核对确认为 qwen3-embedding-4b-2560d 三集后才运行。未新建容器/卷、未跑 initialize/DDL、未改 .env、无额外探测。

## 前后身份守卫（现场观察）

identity_before == identity_after：source `95f7791f…`、catalog `c15c741742394320/4919b3938ad93747`、search `872d689343a9cbb6`、gold/env、八表计数逐项与期望相等、problems 空、matches_frozen true。锚期望未冒充现场，守卫照常核实。

## 新鲜发现证据链（四腿公共）

- keyword 抽取回执 4/4 success（1528–2033ms，82–101 字符），embedding 全部 [*,2560]，Qdrant query_points/retrieve、Neo4j session.run 全 success 落 receipts。
- 每腿 usable 10（budget limit 40、kept 10、truncated 空），`pg.search_id` 保持 ""（如实，未回填）；发现层 `targets_confirmed=false`+discovery_only——不自报确认范围，全部经答案层 canonical 门（catalog 行身份经守卫 workspace+快照连接读取）。
- 本轮真实观察到的门控排除（带原因记录在 flags）：prose-001 的 GB8978 文档（编号不符分支）与 9bb1（目录 self_code 未知、不凭文件名冒认）被排除；prose-006 的 GB3095-2026 兄弟版本被排除；neg-004 的 GB18466 噪声被排除；以上均非用 gold/PG/历史补造，是本轮 fresh 发现+现查目录行的实况。

## 逐腿裁决（app coverage / 集合内容 / 引用回读分列；gold 仅事后核对）

| 腿 | coverage | 集合与内容 | 模型/精排 |
|---|---|---|---|
| prose-enum-001 | complete | 目标 GB18466 3.1–3.4 恰 4 项（原 17 项混入不复现）；gold 术语名全部包含于交付正文；完整声明按 raw 跨度逐项回读 verified+reverified | 0/0 |
| prose-enum-006 | complete | 恰 1 项 4.2（48 字符与 gold 正文同一字符串）；2026/HJ2.2 噪声未入答 | 0/0 |
| neg-004（反例） | complete | GB8978 表1 两物理片合并 13 项/13 原始行、seq1–13 连续，全部逐行 raw grid 复读；未出现 5/10 项假 complete | 0/0 |
| file-enum-005 | complete | 并集 3/3=gold（base1+related 匹配 3/证据 2/新增 2），guard stable、目录复读 verified/reverified；两份修改单 self_code 保持未知未伪造；`search_id=""` 如实保持、与 top-k 解耦 | 0/0 |

措辞口径沿用 PG 批主 agent 订正：以上"回读相等"指**交付全文与其声明 raw 源跨度逐字相等**，不宣称交付字符串等于 gold body（交付含条款编号前缀与原文句号；prose-006 恰为同一字符串属巧合级一致）。

## 预算账本（预留/实发/拒绝分列）

批合计 reserved==issued：llm 4/4、embedding 11/16、qdrant 11/32、neo4j 20/40、pg 439/4096；拒绝 0；rerank/answer_llm 无任何事件（0）。逐腿明细在 `leg-verdicts.json`（含组+SQL 保守双计与 not_billed 排除口径原文）。四腿均 real_entry、时延样本 4（answer 3.3–7.0s、腿总 7.4–9.8s）。

## 边界

本批不证明：fusion 混入、有答案模型的合成、第二轮；不宣称发现必命中（本轮命中系 fresh 实况，非构造）。历史文件零写入、零覆盖事件；全库清单复算见 sha-list/manifest 之后记录。
