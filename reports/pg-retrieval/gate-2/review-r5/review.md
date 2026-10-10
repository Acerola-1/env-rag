# Gate 2 第五轮复审（2026-10-06）

**Gate 2 未通过；4.1–4.3保持通过，4.5源金标审核冻结现已完成，4.4/4.6仍未完成。下一轮只修两个具体实现问题，不改目录、不删失败题、不进入融合。**

原13+11+9+7共40个独立验收反例已通过；提交时全套168 passed。本轮新增两个入口反例后为168 passed / 2 failed。检索实现、旧验收断言和执行agent提交gold的标签未由主agent修改。

## 已确认的进展

- 兜底正文全文、标题后偏移与来源绑定已经修好；真实prose006的引句和坐标可独立回读，没有400字静默截断。
- 完整cells模式不再吞额外同名错行，文件partial/fail_stage也进入评分。表格gold不再接受编造尾值；prose003完整四条要求已补，旧关键词反例拒绝。
- 正常非空的discovery快照与完整枚举输出已分离；六文件完整枚举正确。
- scope3的水域五类现在能够发现并切分，OCR原号没有被伪改。prose005与table003的歧义保持公开失败，不要求强行消除。
- 新词表身份已对应实际active search `872d689343a9cbb6`，check_search_stale=current，221原文/5709chunks及源指纹/目录未变，25个PG词项探针重跑通过；本轮没有重建或模型调用。

## D1 [P1] 类别条目的坐标仍相对于去标题后的body

位置：`src/env_rag_final/search/expand.py:875`、911、1039。

_split_category_sentences接收body和assembled_text，却用body内的m.start/m.end直接作为assembled_text的char_start/char_end。标题已在fallback分支被移除；类别分支没有像正确的兜底分支那样加回body起点。后续bind_citations把错误global坐标当真，verify_citations只确认quote存在于全文，无法发现位置错了。

独立真实回读prose004的五条引用：**五条起点均未加标题偏移**；前四条完整引句不在声明span内。第一项声明unit_rel_start=30/end=51，回读为`标，按功能高低依次划分为五类：\nI 类 主`，引用却是`\nI 类 主要适用于源头水、国家自然保护区`。这些条目仍claimed_verified=True、coverage=complete。

本轮167表行+16正文引用共183条独立回读：167表行全部正确、11条正文正确、5条类别坐标不合格。引用错误为0的门槛尚未满足。实际查找引句在全文存在，不能替代位置核验。

修复：以body在原始assembled_text中的真实起点映射类别span（含标题/空白/UnitText.span_offset）；然后走同一bind/verify管线。最终核验声明span的文本与quote，而非仅全文子串。新的三类别普通原文编排测试可复现，不依赖GB3838 ID或OCR特殊值。

验收反例：`test_category_split_uses_original_assembled_coordinates`。真实证据：citation-reread.json、replay.json中的prose004。

## D2 [P1] 明确空discovery快照仍被or回填

位置：`src/env_rag_final/search/eval.py:501`。

当前逻辑是“过滤discovery列表 **or** 过滤candidates列表”。明确的[]快照会触发后者；后者只排除document_enumeration，不排除枚举后新加入的doc_attribution。

正式benchmark入口隔离反例：discovery=[]，枚举后归属候选d答对集合，当前却将discovery_candidates_total记为1、给recall满分。既有C3反例只有document_enumeration标记，故能通过，但没有覆盖这条归属路径。

修复：有明确快照时，[]就是0，绝不回填。若兼容尚未捕获的旧调用，区分None/缺字段与显式[]，并在每个真实查询返回路径保存发现快照；禁止按“非空性”决定来源。真实发现阶段的doc_attribution仍可以参与recall，不能把这个标签一律删除来掩盖问题。

验收反例：`test_empty_discovery_is_not_backfilled_by_post_enumeration_attribution`。集合应true，而发现数及两口径recall均为0。

## 4.5 已完成：31题源金标与10反例期望冻结

主agent重新逐题核对引句/原始网格和完整期望，并对111个枚举期望项目执行原文支持检查。八项真实入口反例保存完整结果和独立断言，8/8通过：缺失版本/裸编号/全角版本、混合版本缺失、自身编号不混引用文档、两片表1完整、表2缺base歧义、无编号且不能确认的请求保持歧义。

**审核副本为 gold-approved.json**，version=`gate2-source-gold-reviewed-2026-10-06-v1`；31题gold_review_status=approved，10个反例期望reviewed。执行agent的gold-candidates.json仍保留原提交及unreviewed标签。数据批准不代表当前实现或指标通过。

- prose004保留I/Ⅰ/Ⅰ/N/V原OCR号，并单列依据已审核的I/II/III/IV/V规范类别映射；不能把原文错误号悄悄当作规范编号。类别顺序与内容有来源依据。
- prose003四条要求、syn001过渡日期、fact007前后两表来源、table005全部30数据行及24控制项目/表头/脚注仍保留。
- syn001/002的真实候选遗漏，以及prose005/table003的公开失败均未移出题集。
- 冻结数据SHA、原提交SHA、来源/目录/词表/索引身份、审核记录与原文支持检查分别见gold-freeze-manifest.json、gold-review-v5.json。下一轮benchmark明确指定审核副本，不自行改gold适配实现。

## 当前质量判断

| 类别 | 程序集合检查 | 加入独立引用核验后的合格集合 |
|---|---:|---:|
| file_enum | 6/6 | 6/6 |
| prose_enum | 5/6 | **4/6**（004坐标不合格；005保留失败） |
| table_enum | 5/6 | 5/6（003保留失败） |

因此仅看EXACT旗标已经达标，但正文合格集合与引用错误门槛仍未达标。本轮记录的候选证据计数为56/59=0.9491525；在D2修复并重跑前不批准为Gate2正式指标。质量观察见quality-observation.json，固定分母和失败行均保留。源金标冻结后也不能盲信citation_verified。

## 验证及边界

- 26次生产检索、31题benchmark、25个PG词项探针、8项额外真实入口反例；原168测试通过，新2项验收失败。Ruff/OpenSpec严格/diff检查通过，旧40验收文件SHA不变。
- public八表冻结计数221/5709/279/16514/65527/221/221/119575；源指纹95f7791fd84171ab727870fc5810d79b4327b0c4fa547d432951e0499a3808f8，catalog4919b3938ad93747保持不变。当前search为按新词表合法构建的872d689343a9cbb6，验收期间未变。
- 数据库全程只读，无模型调用、索引重建、迁移、原PDF操作。仅添加审核副本/测试/报告并更新阶段状态。
- 下一步见handoff-phase-2-fixes-r5.md。验收边界固定为D1坐标、D2快照来源与原31题/8反例复跑，保留4.1–4.3/4.5已完成成果。

审查覆盖统计：{"total_files": 184, "reviewed_files": 6, "skipped_files": 178, "coverage_rate": 0.03260869565217391}；全部preview条目均有review/skip及理由，额外人工审查另记于账本。
