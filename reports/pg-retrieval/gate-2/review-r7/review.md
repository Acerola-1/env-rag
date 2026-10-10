# Gate 2 第七轮主 agent 复审（F1 补正后）

2026-10-06。**Gate 2 仍未通过。普通正文真实偏移已验收通过；F1 的引用验证器仍有三项确定性反例，未满足完整 quote/裁切偏移/旧调用兼容合同。**4.1–4.3、4.5 保持完成，4.4/4.6 未完成。本轮不重新退回已通过的类别、发现快照、金标或索引。

## 已确认结果

171 既有测试通过（包括上一轮标题后空行、末尾99反例），原43项验收断言未修改。新3项反例全部失败：完整结果 **171 passed / 3 failed**。普通正文真实 body_start 计算正确，三个 expand 调用与一个 enum-prose CLI 调用已传入 units。

使用未改动的主 agent 审核副本 `review-r5/gold-approved.json`，完整重跑31题、8个真实入口反例（8/8），25个实际PG分词探针。独立复算发现召回 **56/59=0.9491525423728814**，文件发现 **23/23=1.0**；file/prose/table集合 **6/6、5/6、5/6**，分母、公开失败题保留。当前输出的 **60正文引用及241表行引用**全部按声明坐标/原始HTML行独立回读成立。未将枚举答案倒灌发现召回。

这些数字确认当前固定白名单表现；不能代替下面验证器边界的行为验收。没有因为新反例篡改金标、扣掉公开失败或扩大评测预算。

## G1 [high] 前60字相同仍放行，完整声明跨度核验尚未落实

`src/env_rag_final/enumerate_/prose_enum.py:531`：

```python
_norm(quote) in _norm(span) or _norm(span).startswith(_norm(quote)[:60])
```

后半句仍然是前缀放行。反例给出长度超过60的原文引句，声明的char跨度只覆盖前60字（整句在全文中确实存在），经真实 `bind_citations → verify_citations` 后仍verified=True。引句剩余内容与末尾限值99完全不在声明跨度中。上一轮交接明确要求完整引句受声明span支持，不能用全文存在性或截短前缀代替，这一要求仍未满足。

删除前缀豁免；合法跨单元引句通过所有有效声明segment按原始assembled顺序还原，验证完整quote。不能为了维持现有白名单通过而固定放行60/80/120字前缀。

## G2 [medium] raw unit偏移被直接用于已裁切的UnitText.text，合法requires_span引用被拒

同文件 `530、539`。`bind_citations` 已把 `span_offset_in_unit` 加到unit_rel起止；`UnitText.text` 本身只保留裁切后的片段。新验证器却直接用raw坐标切裁切后的文本，缺少 `unit_rel - span_offset_in_unit` 转换。正例经binding后，按真实raw单元回读完全等于quote，新验证器却False。

新测试使用既有UnitText/binding接口的合法requires_span正例，无特定文档ID或OCR值。另尝试在当前真实WHO大block取得编号子条款：原文没有当前reader支持的编号结构，此真实正例**未执行**，已保存在requires-span-live.json；不把隔离回归错误谎报为当前冻结31题或WHO请求的实库失败。当前真实WHO范围的保守拒绝不要求改变。

核验owner与每个segment时转换坐标并检查完整可读区间；不能用Python切片静默裁剪或错误空片段拒绝合法数据。无需重建目录。

## G3 [medium] 无units兼容路径已失去全文存在性检查

同文件 `521、528–548`。supported仅初始化为bool(quote)；没有units或找不到unit时，没有检查quote是否在text里，仍可True。反例 `text='门诊、病房'`、quote='停车场'、既有verified=True的旧两参数调用，最终仍True。执行报告声称退化为全文存在性检查，与代码实际不符；这也不是“不会把失败升级为通过”的安全退化。

恢复旧调用的完整quote全文存在性检查，并保留已False不升级、locator_missing/ambiguous拒绝。正式入口目前已传units，本项是接口兼容回归，不声称当前正式CLI有遗漏穿线。绑定了unit但其来源缺失时要拒绝或明确降级，不能仅凭非空quote通过。

## 验收范围与来源

只复审F1所属正文/展开/CLI引用链路，保留先前已验收的发现、目录、索引、金标。冻结源指纹 `95f7791f…`、catalog `4919b3938ad93747`、search `872d689343a9cbb6`、public八表221/5709/279/16514/65527/221/221/119575前后不变。只读连接；模型调用、数据库写入、目录/索引重建为0。

证据：submitted-tests.txt、new-counterexamples.txt、test-results.txt；benchmark.json及benchmark-runs.jsonl（31行）；metrics-audit.json、citation-reread.json、counterexamples-full.json、tokenizer-probes.json；requires-span-live.json、final-source.json、review-manifest.json、coverage-manifest.json。新测试 tests/test_gate2_review_r7.py，原测试/冻结金标SHA未改。

下一轮仅按 `openspec/changes/add-pg-scoped-retrieval/handoff-phase-2-fixes-r7.md` 修验证器三点，保持原43断言及新3断言行为强度。合法跨单位/quote-only模型路径由隔离行为验证，本轮及下一轮无需调用模型。
