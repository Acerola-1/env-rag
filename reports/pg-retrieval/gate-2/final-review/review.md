# Gate 2 最终验收：通过

日期：2026-10-06。主agent独立复审I1类型检查顺序，并对同一审核金标、生产入口及真实来源复跑后，**Gate 2通过，tasks 4.1–4.6全部完成**。下一步只进入Phase3 tasks5.1隔离兼容检查点；5.2–5.6与Gate3未验收。

## 既定质量门槛全部满足

| 项目 | 门槛 | 独立最终结果 |
|---|---|---|
| PG候选证据recall@20 | ≥0.90 | 56/59 = 0.9491525423728814 |
| 文件发现召回 | 分开记录 | 23/23 = 1.0 |
| 明确编号/版本定位 | 100% | 28道明确编号题、30次code/version分支，30/30正确 |
| 文件enum集合 | ≥5/6 | 6/6 EXACT |
| 正文enum集合 | ≥5/6 | 5/6 EXACT |
| 表格enum集合 | ≥5/6 | 5/6 EXACT |
| 实际引用错误 | 0 | 60正文+241物理表行逐条独立回读，0错误 |
| 分词探针 | 全部正确 | 25/25 |
| 真实负例入口 | 按冻结期望 | 8/8 |

审核副本仍为review-r5/gold-approved.json（31正例/10负例期望），SHA不变。预算top-k=20，使用展开前的发现快照计召回，空快照不回填；集合比较读取完整枚举输出。题目/期望/分母未更换，歧义失败保留在三类enum的各6题分母。

## I1与既有反例通过

178项测试全过，50项历轮验收反例文件SHA全部保持。共享_slice先检查原始偏移是否真正int（bool也拒绝），再减span_offset与做边界判断。字符串/null的模型JSON→binding→verify模拟链路安全拒绝，不再抛TypeError；额外16组owner/segment起止坐标的bool/str/null/float检查均安全拒绝。

已验收的合法跨unit重建、缺源拒绝、空segment拒绝、whole quote支持、requires_span偏移、quote-only定位、既有False不升级、locator错误拒绝与空discovery合同未退化。两份模拟模型响应只用于本地fixture，实际模型请求为0。

三个正式只读CLI入口均成功：GB3838类别5项complete；GB8978表1 top-k=1仍完整13项；直接enum-prose列3.1–3.4四条complete，全部引用verified，并独立回读5/13/4条来源引用通过。完整输出与参数在cli-runs.json、cli-checks.json、cli-citation-reread.json。

## 来源及派生索引保持稳定

public八表计数221/5709/279/16514/65527/221/221/119575与冻结值一致。源指纹95f7791fd84171ab727870fc5810d79b4327b0c4fa547d432951e0499a3808f8，catalog snapshot4919b3938ad93747，search active872d689343a9cbb6前后current。活动搜索行数再次读取为documents221/chunks5709。

本轮PG连接强制只读；public/MinerU/env_rag均未写入，目录/索引重建为0；真实模型调用0。Ruff检查/格式、OpenSpec严格校验、diff检查通过。原审查报告与旧任务状态保留为历史，最终主报告为phase-2/report.md。

## 保留公开失败及验收边界

syn-001前言日期证据未进top20（2/3组），syn-002排序未命中（0组），prose-005范围歧义、table-003结构歧义保留。通过是在固定语料、审核题与预算内达到既定门槛，并非所有问题都已正确回答。Phase1 requires_span保守状态未被放宽；未来语料、词表或配方改变仍按stale/重建合同处理。

本验收确认PG第二路和受控范围展开；LightRAG发布包运行时只读兼容、真实local适配、联合rerank与最终生成质量仍由Phase3/4验证，不以Gate2通过替代。

## 原始证据和审查覆盖

- test-results.txt、initial-hashes.json、guard-probes.json。
- benchmark.json、benchmark-runs.jsonl（31行）、metrics-audit.json、code-audit.json。
- citation-reread.json、counterexamples-full.json、tokenizer-probes.json。
- cli-runs.json、cli-checks.json、cli-citation-reread.json、final-source.json、review-manifest.json、coverage-manifest.json。

本轮聚焦唯一变化的_slice与已要求边界，保留历轮完整审查。OCR预览的每个文件均有reviewed/skipped及原因；不会把全部历史报告/已验收代码宣称为本轮重新全审。Phase3交接见openspec/changes/add-pg-scoped-retrieval/handoff-phase-3.md。
