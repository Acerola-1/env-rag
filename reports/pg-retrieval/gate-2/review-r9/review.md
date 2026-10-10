# Gate 2 第九轮主 agent 复审（H1–H3补正后）

2026-10-06。**Gate 2仍未通过，仅剩H3非整数偏移的类型检查顺序。H1合法跨unit、H2缺源拒绝、H3空区间三项原反例均已通过。**4.1–4.3/4.5保持完成，4.4/4.6未完成。本轮不重新退回这些已通过修复。

## 独立验证

177既有测试全过；原49验收断言及金标SHA未改变。新增1项模型JSON→binding→verify调用链反例失败（覆盖字符串及null两种非整数偏移），完整结果 **177 passed / 1 failed**。

同一主agent冻结gold完整31题复跑：独立用实际unit→chunk映射复算证据 **56/59=0.9491525423728814**、文件 **23/23=1.0**；三类集合file/prose/table **6/6、5/6、5/6**。当前输出 **60正文及241表行引用**全部独立raw回读成立。8实际入口反例8/8、25分词探针全过，公开失败及固定分母保持。

模型测试使用完全模拟的httpx响应（两份fixture JSON），没有外部模型调用。正式PG只读，source/catalog/search及public八表冻结值前后不变；无数据库写入、无目录/索引重建。

## 唯一阻断 I1 [medium] 类型检查晚于减法，非整数JSON偏移抛TypeError

`src/env_rag_final/enumerate_/prose_enum.py:537–541`：

```python
lo, hi = rel_lo - off, rel_hi - off
if not (isinstance(lo, int) and isinstance(hi, int)):
    return None
```

字符串或null在第一行已经抛TypeError，不会到达类型检查并返回拒绝。报告声称“非整数偏移同样拒绝”，目前只对浮点数等可参与减法的类型成立。

这不是仅对私有_slice喂非法数据的测试：fixture走真实 `extract_items_with_model`，响应为合法JSON，primary/quote均有逐字原文支持，citation额外含 `unit_segments`。解析器未限制该字段类型，`bind_citations`为quote-only条目绑定正确owner跨度，但保留了额外segment；最终 `verify_citations`对segment的字符串/null偏移抛TypeError。模型响应边界可到达，因此不能依赖“所有上游偏移都由binding生成”。正确行为是上游model_failure拒绝，或verify返回unverified继而partial；不能让异常逃出这条抽取/引用验证链路。

**最小修复**：先检查rel_lo/rel_hi的原始类型，非法即return None，然后再做offset减法及既有0≤lo<hi≤len边界判断。owner/segments沿用共同_slice。示意：

```python
if type(rel_lo) is not int or type(rel_hi) is not int:
    return None
lo, hi = rel_lo - off, rel_hi - off
```

无需改变已经验收的引用重建、来源判断、偏移算法、路由或gold。新的测试接受安全的上游model_failure拒绝，也接受verify=False；没有要求改合法模型内容或调用实际模型。

## 来源与验收范围

source `95f7791f…`、catalog `4919b3938ad93747`、search `872d689343a9cbb6`、public八表221/5709/279/16514/65527/221/221/119575保持current及冻结值。本轮仅审修改的verify与模型JSON/绑定生产调用链；其余先前已验收实现保持。没有把隔离反例冒充当前31题的引用错误：当前固定题引用依然0错误。

证据：submitted-tests.txt、new-counterexamples.txt、test-results.txt；benchmark.json、benchmark-runs.jsonl（31行）、metrics-audit.json、citation-reread.json、counterexamples-full.json、tokenizer-probes.json、final-source.json、review-manifest.json、coverage-manifest.json。

新增 `tests/test_gate2_review_r9.py`，原49断言未删改。下一轮只修类型检查顺序，交接 `openspec/changes/add-pg-scoped-retrieval/handoff-phase-2-fixes-r9.md`。禁止为此扩大修改或重建索引。
