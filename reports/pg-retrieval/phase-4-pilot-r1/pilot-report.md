# Phase 4 首批试跑报告（pilot-r1，2026-10-08）

按 `handoff-phase-4-6.2-pilot.md`：单轮、3 题（fact-002 / prose-enum-001 / syn-004）× 3 路径（pg / local / fusion）= **9 腿，仅一次运行，完毕即停**。命令逐字使用交接指定形式，预算 `pilot-budget-proposal.json`，输出新代次目录。CLI exit 0；未追加重试/预算/健康探测；写库 0，生产 PG/Qdrant/Neo4j/MinerU 全程只读。

**本批结论：链路真实性验证成功，但 9 腿全部按现行合同如实记为预算失败（per-question pg 信封 24 不足）。无任何答案生成，syn-004 人工语义检查与 fact-002 partial 语义核对在本批无法进行（无答案工件，不虚构）。不勾选 6.2；3 题不代表 31 题指标。**

## 1. 运行级守卫

- 分发前零后端锚校验 PASS（`validate_phase4_anchor`，代次 `phase4-deepseek-restored-pilot-r1`：模型/端点/维度/提示 SHA/代码锚/参数预算含 answer_temperature=0 逐值比较/env 守卫）。交接 manifest 所列工件 SHA（锚两份、预算、恢复记录、交接本体）逐一复核匹配；`.env` SHA = 恢复记录 after 值。
- 运行级身份：pre `matches_frozen=True`，post `matches_frozen=True`、drift=[]；`finished_at` 存在（未发生运行级拒绝）。expected 未回写。
- 复用守卫：目录为新代次（运行前不存在）。

## 2. 真实服务凭证（终态 `budget_snapshot_end`，预留==实发，全部在批准上限内）

| 服务 | 实发（=预留） | 批准上限 | 结果 |
|---|---:|---:|---|
| keyword LLM（DeepSeek） | **3** | 6 | 3/3 全部成功——**恢复后的 DeepSeek 通道实测可用** |
| embedding（Qwen3-4B 批） | **8** | 24 | 8/8 成功（单批均 ≤32 文本/64000 字符） |
| Qdrant | **8** | 48 | 8/8 成功 |
| Neo4j | **15** | 60 | 15/15 成功 |
| PG 计量读取 | **216** | 432 | 每腿恰好封在 24 后拒绝（见 §3） |
| 联合精排 | **0** | 3 | fusion 腿死于发现，从未进入精排 |
| 答案 LLM | **0**（仅 syn-004/local 预留 1） | 3 | 全部在 HTTP 前被信封拒绝；无真实模型调用发生 |

`refusal_count=15`；所有拒绝事件 `issued:0`——零超限发出、零借用、`unknown` 未出现于精排（精排从未进入）。逐腿 issued==reserved（`quotas_just_sufficient` 语义在无答案路径下同样成立）。

## 3. 逐腿结果与根因

九腿全部记录 `budget_failure(stage=swallowed-refusal)`——预算异常被各已验收入口自己的统一终态捕获后，由编排层按"本题账本拒绝事件增量"显式检出（R2 合同在生产形态下首次实战生效），未出现无标记 complete：

- **pg ×3、fusion ×3**：`run_fusion` 在发现阶段自身 SQL 即撞上每腿 24 语句信封（终态 `fusion-runtime-latest.json`：`fuse` stage 拒绝，BudgetExhausted 原文、zero calls）。精排与答案阶段未进入；未写 inputs（尚无融合结果可发布）。
- **local ×3**：发现**完整成功**——真实 DeepSeek 抽词 1 次、embedding 2–3 批、Qdrant 2–3 查、Neo4j 5 run、10 候选全部经生产 `SourceAdapter` 全文回读（usable=10、refused=0、degraded=[]），`chunk_pick=vector-similarity`、向量覆盖观察逐条真实（fact-002 例：32 请求=32 有效，points_returned_raw 仅传输统计）；发现+回读+双计恰好用满 24 → answer 阶段第一条守卫 SQL 被拒（answer 终态：`identity-capture` 拒绝、model_calls_used=None 即未发生）。inputs 三题已落（fusion.json + 显式 absent 精排报告），答案未生成。

根因不是故障而是**预算标定**：`per_question.pg=24` 沿用离线期默认，而生产单腿真实 SQL 量（catalog 检索+展开 / 10 候选逐条回读+组语句双计）≥24。`pilot-budget-proposal.json` 的轮/总上限（432）足以容纳多腿，但信封在请求前就封住了单腿。按交接"不追加预算"，本批保持原样并如实呈现；**扩批前需主 agent 重定每腿 pg 信封（或显式声明双计口径下的等效值）**。

## 4. syn-004 / fact-002 人工语义检查

**本批阻塞**：三路均未产出答案，无 claims/引用可读。交接要求的"两环境要素是否回答、附录句是否被误升为规范"检查待信封重定后的下一批进行；不以任何 fixture/离线结果冒充真实答案语义。

## 5. 工件索引（`reports/pg-retrieval/phase-4-pilot-r1/`）

- `eval-runtime-{stamp}.json` / `eval-runtime-latest.json`（终态：逐腿记录、账本事件、`budget_coverage_declaration`、identity_before/after）
- `legs/r1/{pg,local,fusion}/{qid}/`：各入口真实终态（fusion 失败终端 ×6；local 含 `answer/answer-runtime-latest.json` 失败终端；`inputs` 引用见下）
- `inputs/local/{qid}-fusion.json`（真实候选全文+完整出处：`reached_via`/`similarity_order`/`source_type`/`file_path`，score=null 未伪造）、`inputs/local/{qid}-rerank.json`（显式 absent 声明）
- `pilot-budget-proposal.json` 引用件与 `deepseek-restoration.json` 的 SHA 关系见交接 manifest。
- 敏感值扫描：本目录全部 JSON/MD 对 `.env` 密钥/口令/DSN 形式 0 命中（凭证仅以计数与状态落盘）。

## 6. 保持的通过证据（本批实际证明到的部分）

1. DeepSeek 关键词通道恢复可用：3/3 真实成功（用户报告的服务恢复由此获得链路实证，非推断）。
2. embedding/Qdrant/Neo4j 生产只读路径 100% 成功，服务边界记录、向量覆盖观察、weight/vector 区分逐条真实。
3. 预算三合同实战成立：请求前硬封（零超限）、拒绝事件可审计、被入口吞掉的预算异常经账本增量检出并显式降级——九腿无一误标 complete。
4. 身份守卫与冷生成合同：同批 pre/post 无漂移；未复用 syn6/旧答案（answer 阶段未达，不存在复用面）。

停止点：交主 agent 复审；6.2 未勾选，未扩批，未追加重试/预算。
