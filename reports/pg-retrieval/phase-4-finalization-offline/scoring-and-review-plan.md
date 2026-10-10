# 新代评分与人工审查方案（本组仅设计，不实施）

输入均为已验收工件；本组 0 网络/DB/模型请求。

## 1. 保持不变的规则

- 已验收 r3 评分器（`phase-4-round-1-assessment-r3/assess_round1.py`）的评分规则、35 项冻结矩阵与来源/坐标完整性守卫逐字保持。它对改后源码的 SHA 拒绝是**正确行为**：不加豁免、不放宽 R1 声明跨度、不改反例行为合同或分母规则。
- gold（`1bf13007…`）、`expected_status` 仅事后裁决、从不决定路由——全部沿用。

## 2. 新代评分代次如何绑定

对未来两轮真实运行（改后代码代次），另建 `phase-4-round-{2,3}-assessment-r{N}/` 评分代次，代次清单必须显式绑定四样东西，缺一拒绝运行：

1. **运行目录**：两轮各自的 eval-runtime/legs 工件路径与 SHA 清单（新代运行目录，绝不读 round-1 旧答案充当新轮输出）；
2. **代码谱系**：本轮批准锚的 `evaluation_code_anchors` + 被测 answer/rerank/fusion/local/compat SHA，全部从锚文件重读比对磁盘，不手填；
3. **输入 manifest**：每题每路径的 fusion/rerank 输入工件 SHA 与运行终态互指（沿用 `replay_sources` 交叉校验形状）；
4. **固定 gold**：`gold-approved.json` 内容 SHA 与 pre/post 身份（source/catalog/search/counts/env）逐项相等，任何漂移在非零终态前拒绝。

终判仍为**每轮 123 行**（93 正例 + 30 反例），两轮分别出分、分母分列，不做跨轮合并平均；`final_status` 决定性 FAIL 优先于掩码 pending 的规则保持。参数化的只有**运行来源目录与批准锚文件路径**两个入口（沿用 `ENV_RAG_ASSESSMENT_SCRIPT` 选择模式）；集合、正文支持、反例行为、分母规则一律不动。

## 3. 旧 PENDING 的人工裁决缺口（22 行）

机器清单 `pending-review-gaps.json`。改前 15 正例 PENDING + 7 反例 PENDING 全部保留为"未裁决"，进入新代评分时仍需人工处理，处理路径：

- **fact 载体口径（12 行）**：需人工逐题定"表格事实以散文句子交付"是否满足 gold 行投影；裁决依据=原文引用+声明跨度，不看交付形式是否"像对"。可定标后一次性套全部分类，不做逐题特判。
- **file-enum-004 引用元数据缺口（3 行）**：归属文档缺 doc_name（元数据 gap≠内容错误）。人工决定：判 pending 保留，或在新两轮中依据改后目录复读证据（answer 入口已逐条绑定快照）直接裁决。
- **反例 gold 投影（3 行）+ 状态审查（1 行）**：neg-002（观测≠对抗证明）、neg-007（partial≠ambiguous）、neg-008（额度闸门观测）——需要人工按冻结行为合同对"实际行为"出语义裁决；无法裁决的仍保留 pending 并报告分母/范围，**不伪判 pass**。
- **neg-008 预算构造 3 行**：计入 G4-7 降级/预算观测，不计能力失败（口径不变）。

## 4. typed evidence recall 与映射采集提案（本组不采集）

typed recall 只能取**发现候选**（typed_targets + chunks），禁止从展开成功反灌（file-005 教训：3 份真实发现≠0）。离线缺 chunk→unit 完整映射，代次内无法算。提案（待主 agent 批准后才执行一次）：

- 形式：一个受既有前后守卫约束的**只读映射采集**运行——单连接、`default_transaction_read_only=on`、只 SELECT `env_rag.lightrag_doc_chunks`（5709 行）与目录 documents 行，落盘 `chunk_id→(doc_id,unit 标识)` 映射工件；
- 预算：PG 数据语句 ≤20（分页 LIMIT 2000）、模型/embedding/向量 0；前后身份核验同现有合同；
- 用途：仅供新代评分把 typed 候选绑定到可审单元；不回填任何发现召回数字。

## 5. 时延字段可用性（新两轮报告口径）

| 阶段 | 可用字段 | 口径 |
|---|---|---|
| 发现（discovery） | `timings.discovery_ms` | fusion 路为 **inclusive 含精排**，exclusive 只能近似并列标注（round-1 主 agent 订正保持） |
| 精排 | rerank receipts 逐调用 elapsed | 仅 executed 凭证计时；before-http-zero/unknown 不计时 |
| 展开 | 无独立字段 | 如实 **unavailable**——不得用 total−其余 的减法造精确展开耗时 |
| 生成 | answer `latency_ms` | 复合阶段（含复读/守卫）；有 HTTP 凭证才算模型耗时，`model_status=incomplete_conditions` 的行是 0 调用非 0 秒交付 |
| 端到端 | `timings.total_ms` | p50/p95 按腿样本量分列报告；墙钟与逐腿和为不同口径不互推 |

样本量：每轮每路径 41（正例 31/反例 10 分列）；并行度=当前串行 owning 入口；缓存条件=零答案缓存+冷生成（锚合同）。未测字段全部显式 `untested/unavailable`，无历史 SLO 不承诺固定秒数。
