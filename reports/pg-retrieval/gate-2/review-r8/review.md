# Gate 2 第八轮主 agent 复审（G1–G3 补正后）

2026-10-06。**Gate 2仍未通过。上一轮的前60字豁免、裁切偏移换算、旧接口无原文引句三项原反例均已通过；同一验证器的合法跨unit、缺失来源、空segment边界仍失败。**4.1–4.3/4.5完成，4.4/4.6未完成。没有重开已验收的查询路由、普通正文偏移、目录、金标或索引。

## 独立验证

174既有测试通过，原46项验收断言文件SHA未改变。新增3项反例全部失败：**174 passed / 3 failed**。新测试 `tests/test_gate2_review_r8.py` 直接经过真实 `bind_citations → verify_citations`，无文档ID/OCR特值或模型调用。

同一主agent冻结gold（SHA不变）完整31题复跑：独立真实链接复算证据 **56/59 = 0.9491525423728814**，文件 **23/23 = 1.0**；file/prose/table集合 **6/6、5/6、5/6**。60正文引用及241表行引用全部按当前原文声明跨度/原始HTML行独立回读成立。8项真实入口反例8/8，25分词探针全过，公开排序/歧义失败及固定分母保留。

这些确认当前固定白名单表现；下面三项是历轮交接已经要求的验证器边界，不是新检索功能或新的质量门槛。

## H1 [medium] 合法跨unit引句被primary owner判断短路

`src/env_rag_final/enumerate_/prose_enum.py:545、565–568`。

先执行“完整quote必须在主owner片段中”，再以该supported为条件重建segments。真正跨两个unit的完整quote不可能全部落在主owner，于是supported=False，合法segment重建永远不执行。反例两份真实UnitText、有正确assembled坐标、binding产生两个有效segments，整条quote就是两片正文的拼接，却被verify=False。

结构有效性与quote覆盖要分别判断：先验证owner/全部segment来源、坐标与非空区间；存在segments则按assembled顺序重建后独立判断完整quote覆盖；无segments才判断owner单片覆盖。不能用主owner单片“不含完整quote”阻止合法跨单元重建。

## H2 [high] 数值绑定引用缺少source unit时仍True

同文件 `531–532、569`。

带unit_id和合法数值unit_rel的引用进入首个if；by_id找不到unit时，`if u is not None`直接跳过，没有else将supported=False。后面的elif只覆盖没进入数值分支的引用，不能补救。反例先用有效unit绑定引用，再调用verify时不给该来源（空units列表），仍因quote在assembled全文中而True。与提交报告“绑定unit但来源不可用拒绝”不符，也违背此前G3。

所有声明unit引用都必须先检查来源是否可用；numeric或quote-only字段不应决定缺源是否拒绝。裸两参数、没有绑定unit的旧接口仍可依全文检查，但已绑定来源缺失不得回落为全文存在性。

## H3 [medium] 额外segment的零长度区间仍放行

同文件 `561` 只检查`slo > shi`，未拒绝`slo == shi`。追加一个起止相同的空segment时，空串拼接不会影响完整quote，最终仍True。反例主owner本身正确、同时声明一个合法片段和一个空片段；期待拒绝空引用，实际放行。这是历轮明确的“空区间拒绝”边界。

统一owner和segment的区间验证：起止整数、offset换算后0≤lo<hi≤可读文本长度。空segment不能静默丢弃。

## 来源与范围

只读连接，source `95f7791f…`、catalog `4919b3938ad93747`、search `872d689343a9cbb6`及public八表计数221/5709/279/16514/65527/221/221/119575前后不变。无模型、无数据写入、无目录/索引重建。

本轮只审查改变的verify实现及binding接口/旧验收测试；此前完整入口CLI穿线与其他已验收实现保留，不重复全项目审查。逐文件reviewed/skipped及理由见coverage-manifest.json。三个新增反例为确定性接口行为测试，不谎称是当前固定31题的引用错误；当前31题引用仍为0错误。

证据：submitted-tests.txt、new-counterexamples.txt、test-results.txt；benchmark.json及benchmark-runs.jsonl（31行）；metrics-audit.json、citation-reread.json、counterexamples-full.json、tokenizer-probes.json、final-source.json、review-manifest.json。补正仅限 `handoff-phase-2-fixes-r8.md` 的判断顺序和两处缺失条件，无需调召回、改gold或重建。
