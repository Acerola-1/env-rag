# Phase 2 最终报告：Gate 2通过

主agent验收日期：2026-10-06。tasks 4.1–4.6全部完成。唯一残留I1已修复并通过独立验证；下一步进入Phase3 tasks5.1隔离兼容检查点。正式验收原始记录见 `../gate-2/final-review/`。

## 实现及已验证行为

PG第二路检索使用应用侧受控分词与派生索引：jieba 0.42.1，索引用cut_for_search超集、查询用最大词，编号/版本和复合词受保护；现行受控词表104、停用词70、同义词组10。编号先定位，再限定元数据、按核心词AND检索、记录受控同义词/OOV/OR放宽。缺失编号/版本明确missing，不以其他候选替代；自身编号与引用/相关文件归属分开。

env_rag搜索账本、文档/chunk搜索表、加权tsvector与GIN是派生数据，现有public原文保持只读。构建身份包含源/目录/词表/分词器/清洗配方，构建守卫与原子发布已验收。活动索引再次读取为221文档/5709chunks。来源变化返回stale，不沿用旧定位。

top-k只限制发现；确认scope后读取全成员。三类枚举均返回完整/partial/ambiguous/stale及成员统计。文件完整分页与发现快照分开；空发现不以枚举答案回填召回。表格引用使用原始物理grid行坐标，保留表头/单位/脚注；正文绑定原始unit与真实跨度，处理标题空白、裁切offset、合法跨unit重建及quote-only定位。完整quote按声明范围核验；缺源、空span、错误位置、非整数JSON偏移拒绝或降级，既有False不升级。

模型解析/引用保护的反例使用本地fixture，本轮真实模型调用0。此前Gate1的小范围授权模型验证保留为历史，不当作本轮或未来融合质量证明。

## 冻结输入与金标

- workspace：default；source fingerprint：`95f7791fd84171ab727870fc5810d79b4327b0c4fa547d432951e0499a3808f8`。
- catalog run：`c15c741742394320`；snapshot：`4919b3938ad93747`；recipe：phase-1-v4-single-active-snapshot-prune。
- search active：`872d689343a9cbb6`；tokenizer：phase-2-v3-jieba-0.42.1-cfs-index；vocab SHA：`c3d0b6a6cf7d6af0758329bccea3bbbf432d73b20df4db42b768ae07446978cf`。
- 主agent审核副本：`../gate-2/review-r5/gold-approved.json`，version=gate2-source-gold-reviewed-2026-10-06-v1，SHA=`1bf130077c21583a89c5ca14695694d9552c558a7d8dc5d45ff0d9f72cfd7a5e`。
- 31正例（fact7/file6/prose6/table6/synthesis6）、10反例期望；111枚举期望已逐项原文审核。top-k=20，原题/期望/分母/SHA均未改变；原提交gold-candidates.json的unreviewed状态保留为历史，不用于正式计分。

## 独立最终指标

| 指标 | 结果 | 判定 |
|---|---|---|
| PG候选证据recall@20 | 56/59 = 0.9491525423728814 | ≥0.90，通过 |
| 文件发现召回 | 23/23 = 1.0 | 独立记录 |
| 明确编号/版本正例定位 | 28题30分支，30/30 | 100%，通过 |
| 文件enum集合exact | 6/6 | ≥5/6，通过 |
| 正文enum集合exact | 5/6 | ≥5/6，通过 |
| 表格enum集合exact | 5/6 | ≥5/6，通过 |
| 实际引用错误 | 60正文+241表行独立raw回读，0错误 | 通过 |
| 实际PG分词探针 | 25/25 | 通过 |
| 冻结负例实际入口 | 8/8 | 通过 |

召回只使用展开前发现列表（每题截前20再计分），独立从实际unit_chunk_links解析typed证据；集合比较使用完整枚举结果并检查内容、引用、coverage/fail_stage。歧义/partial答案不记exact，固定六题分母不缩水。所有31题完整运行保存在final-review/benchmark-runs.jsonl，失败/放宽/发现/展开及来源身份均保留。

## 最终回归与正式入口

178项测试全过，50项历轮独立验收断言文件未删改；I1字符串/null模型JSON→binding→verify反例通过，16组owner/segment起止的bool/str/null/float安全拒绝。Ruff检查/格式、OpenSpec严格校验、diff检查通过。

三次正式只读CLI输出：GB3838类别5项complete；GB8978表1 top-k=1仍13项complete；直接enum-prose请求3.1–3.4得到4条complete。完整参数与输出见final-review/cli-runs.json。此次未发起真实LLM、embedding或reranker请求。

public八表冻结计数逐一保持：doc_full221、doc_chunks5709、doc_status279、llm_cache16514、entity_chunks65527、full_entities221、full_relations221、relation_chunks119575。源/目录/搜索前后current，正式CLI结束后再次核对。所有本轮连接强制只读，无数据库写入、无目录/索引重建、无PDF重解析。

## 公开失败与下一阶段

syn-001必要前言日期组未进前20（2/3）、syn-002排序未中（0）；prose-005范围歧义、table-003结构歧义继续保留。达到既定门槛不代表所有题已正确回答，也不扩大WHO requires_span的保守结构合同。预算、词表或语料改变须重新核对/评测，不靠后续rerank掩盖PG未发现证据。

下一步按 `openspec/changes/add-pg-scoped-retrieval/handoff-phase-3.md` 先做5.1隔离兼容：发布包1.5.7首次ClientManager建池可能执行DDL/迁移，必须在独立临时库验证，不能直接初始化现有public库。完成兼容检查点后再安排真实local适配、联合rerank与完整scope生成，最后Phase4无缓存污染两轮对照；5.2–5.6/Gate3尚未验收。

## 证据目录

最终主agent报告、完整bench及独立复算、代码/版本审计、原文引用回读、负例、正式CLI、分词探针、来源manifest与审查覆盖均在 `reports/pg-retrieval/gate-2/final-review/`。原各轮提交、补正和退回报告保持历史，不能用旧状态替代本最终报告。
