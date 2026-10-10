# Gate 2 第六轮主 agent 复审（D1–D2 补正后）

日期：2026-10-06。**Gate 2 仍未通过。D2 通过；D1 类别分支及当前白名单引用通过，但普通正文兜底仍存在相同类型的坐标错误，且位置核验未实现。**4.1–4.3、4.5 保持完成；4.4、4.6 未完成。仅剩以下一个阻断，不扩大到模型、索引、融合或目录重建。

## 独立验证结果

- 170 项既有测试全过；原 40 项与上一轮新增 2 项的文件 SHA 均未变化。新增 1 个普通 Markdown 正文入口反例失败，最终 **170 passed / 1 failed**。
- 使用主 agent 冻结的 `review-r5/gold-approved.json`（SHA 未变）重跑完整 31 题，题目、期望、分母与公开失败题均未改变。
- 独立从原始发现快照与 PG 真实 unit→chunk 映射复算：证据 **56/59 = 0.9491525423728814**，文件发现 **23/23 = 1.0**。所有 31 个正常生产返回均捕获发现快照；明确空快照反例通过，未用展开答案回填召回。
- 集合结果：file **6/6**、prose **5/6**、table **5/6**。本轮实际输出的 **60 条正文引用、241 条表行引用**全部独立回读通过（正文整条 quote 在声明 raw unit span 起点，所有跨单元 segment 坐标合法；表行与当前原始 HTML 完整 grid 行等值）。241 包括 fact/synthesis 的额外展开引用，不只是六道表格题的 167 行。
- 26 次生产查询、31 题 benchmark、8 项额外真实入口反例（8/8），及两次正式只读 CLI（GB3838 五类、GB8978 top-k=1 仍展开 13 项）完成；25 个分词探针全过。无模型调用，无缓存答案复用。
- 源指纹 `95f7791f…`、catalog `4919b3938ad93747`、search `872d689343a9cbb6` 前后保持 current。public 八表计数保持 221/5709/279/16514/65527/221/221/119575。本轮连接强制只读，数据库写入、目录/索引重建均为 0。

这些结果确认了执行 agent 的本轮白名单指标；不能据此把普通正文仍会错误标记为 complete 的路径判为合格。

## 唯一阻断 F1：正文兜底仍用标题长度推算真实偏移，验证器未检查声明位置

位置：`src/env_rag_final/search/expand.py:1015–1042`；`src/env_rag_final/enumerate_/prose_enum.py:497–507`。

类别分支已用 `assembled_text.find(body)` 正确映射坐标，但相邻的 `scope_body_no_subclauses` 分支仍对正文执行 `.strip()` 后，以 `heading_len` 作为起点。标题后多一个空行或正文前有缩进时，被 strip 掉的字符没有计入偏移，末尾也随之少读。`bind_citations` 接受这些偏移；`verify_citations` 仍只做 `quote in text`，所以错误 span 也能被标记 verified/complete。这正是上一轮交接要求的“verify 最后检查声明 span 支持 quote，不能只查 quote 在全文”尚未完成的部分。

隔离反例（示例数值仅用于测试，不是语料事实）：

```text
## 4.2 标准分级

一类区适用一级浓度限值 10，二类区适用二级浓度限值 99
```

真实 `_expand_prose` 入口输出 `coverage_status=complete`、`citation_verified=True`，quote 以 `99` 结尾；按 `unit_rel_start:unit_rel_end` 回读的原文却只到 `9`。这是数值字符丢失，不只是标点差异。新增 `tests/test_gate2_review_r6.py` 通过正式展开/绑定/验证管线复现；可返回正确跨度 complete，也可因引用不成立返回 partial/unverified，不能维持错误 complete。

修复：普通正文和类别分支使用统一的真实 body 起点，保留原始 assembled 坐标，再按 UnitText 的 span_offset 映射回 raw unit。引用验证必须检查声明 span 确实支持完整 quote（并验证边界/单元归属），不能用全文存在性代替位置支持。保留合法跨单元及 quote-only 路径；找不到真实位置时降级，不能伪造。

## 已验收部分与保留边界

D1 类别五条真实坐标及 anchor 优先归属经 60 条实际正文回读确认；D2 None/[] 语义、原零发现/枚举答对反例与当前 31 题发现快照确认通过，不再退回。公开失败 syn-001/syn-002 的排序遗漏、prose-005/table-003 的歧义按原合同保留，分母未缩小。本轮不要求修复这些公开失败，也不修改 Phase 1 状态或金标。

## 证据

`test-results.txt`（170 既有通过）、`test-results-with-counterexample.txt`（170/1）、`new-counterexamples.txt`；`replay.json`、`benchmark.json`、`benchmark-runs.jsonl`（31 行）；`metrics-audit.json`、`citation-reread.json`；`counterexamples-full.json`、`cli-runs.json`、`tokenizer-probes.json`；`final-source.json`、`review-manifest.json`、`coverage-manifest.json`。

只复审 D1–D2 和所属调用链；旧已验收的目录/索引构建实现不重复全库审查。文件覆盖与逐项跳过理由见 coverage-manifest.json。下一轮补正单：`openspec/changes/add-pg-scoped-retrieval/handoff-phase-2-fixes-r6.md`。
