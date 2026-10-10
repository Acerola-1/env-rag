# 收尾离线材料裁决（2026-10-09）

**离线证据整理通过，以下主 agent 勘误为准；正式两轮评测尚未放行。下一组先完成零请求的评分准备。** 本轮不修改提交代次，不要求执行方重写已通过文档，不改生产代码与历史分数。

## 独立核验

123 行逐 key 保留 r3 原裁决的全部字段；246 腿矩阵与冻结矩阵逐行相同。有效上限核对：keyword 164、embedding 656、Qdrant 1312、Neo4j 1640、PG 251904、rerank 82、answer 42。27 份选定保护清单共 1206 条 SHA 均匹配，6 项来源锚不变；这是 reviewer 选定范围，不冒充独立复算提交方的全部 1342 条。未改源码，沿用通过的工程测试，不重复 526 项。

## 主 agent 勘误

1. 改后证据标签可重叠，9 现场与 9 离线之间重叠 6 行。互斥统计应为 **9 现场、3 仅离线、111 未验证**，合计 123；不能读成 18 条互斥验证。见 normalized-evidence-ledger.jsonl。
2. 22 条 PENDING 实际为 fact 正例 12、file-enum-004 三路 3、neg-002 三路 3、**neg-005/local 1**、neg-008 三路 3。方案误写 neg-007；它三路原判均 FAIL，保持。预算控制生效是局部安全观察，neg-008 整题仍 PENDING，不从分母消失。
3. 合成/neg-010 合计 21 行实际 **11 实发、10 未发**。总数正确但 syn-003/fusion 明细错误：model_calls_used=1、call.status=success，随后 incomplete_answer_coverage，不能按业务状态推断 HTTP 未发。逐行回执核对见 synthesis-call-audit.json。旧评分器 neg-010/pg 理由中的“未发”已有勘误，保留历史字节，新代账本按回执处理。
4. chunk 物理表是 **public.lightrag_doc_chunks**，不是 env_rag.lightrag_doc_chunks。chunk→unit 必须依据 **env_rag.unit_chunk_links JOIN source_units**，按 workspace/doc_id/snapshot 组合键；scope 另由 scope_units/scopes 建立。documents 可核对身份，但它与 chunks 单独不能给出 unit 映射。≤20 数据 SQL 仅提案，尚未授权执行；守卫另列，缺映射显式 pending。
5. **1024 是一腿发现+答案共用的累计 PG 信封**。编译工件的“双信封”文字不是实际可发额度；503808 为保守算术上界，被总 cap 251904 裁剪。不得给每个阶段另发 1024，现有预算闸门不改。

## 付费前仍缺的准备

新评分器尚未落地。r3 工具的 `_MANUAL`/`manual_review_for` 以 (qid,path) 固定套用 Round1 失败，`finalize_positive` 没有完整的新代人工 PASS 输入通道。只更换运行目录/锚会把新输出误判为旧失败。规则与人工结论应分开：保留规则；人工结论绑定被审的具体运行、轮、题、路径、输出 SHA，并核对响应/上下文 SHA。新输出无匹配人工审查时保留待审，不能借旧结论，也不能由 app complete 自动通过。

按 handoff-phase-4-scoring-readiness.md 在新目录做离线适配与正负例验证，历史工具/35 项冻结/旧裁决原样。无需新模型、DB 或网络请求，不做生产改进。通过后由主 agent 建正式评测配置代次，再给用户明确的两轮额度选择；本轮不发权限问题、不预授权246腿。

## 当前进度

Gate0–3、6.1 和三组工程改进保持通过；PG/local 有界实况闭合。仍在 Phase4 最后评测收尾，6.2–6.5 未勾选，默认融合未切。35/39 清单已勾选是约90%的清单比例；整体工作量粗估仍75–80%，未验证的全题质量不能按文档完成率视作完成。剩评分准备、固定版本两轮运行与人工/指标裁决、Gate4及最终交付。达不到门槛可保留基线与失败报告收尾，不强行切融合。

Reviewer：0 新服务/数据库请求、0 写库；本地文件读取与上述勘误为独立观测，提交方“零请求”的历史行为只能按现存工件支持，不能由 SHA 单独证明。
