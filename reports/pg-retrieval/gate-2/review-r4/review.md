# Gate 2 第四轮复审（2026-10-06）

**仍未通过 Gate 2。4.1–4.3 保持通过；4.4–4.6 未完成，继续在 Phase 2 补正，不进入融合。**

提交的161项测试确实全过，原13+11+9三个验收文件的SHA与第三轮主agent存档一致。本轮新7项独立行为验收全部失败；完整结果为161 passed / 7 failed。主agent未修改检索/评分实现、旧验收断言、真实gold状态或数据库。

## 已确认修好的部分

- 4.1.1–4.1.7实库请求现在partial，missing明确列4.1.7；“3章”请求四个术语complete；第4.3节不再重复展开。
- 原先的错名称/错值、丢同序号子行、同号换内容反例已拒绝；文件题实际进入完整枚举，六文件程序集合检查全部相等（2/5/5/7/3/1）。固定普通失败行的分母也保留。
- 当前提交gold的原文/网格来源重新回读：prose引句全句子串成立，表格引句的已引用完整单元格与原始网格相符；syn001新增前言日期组和fact007表2物理片来源已补。不能据此推断验证器能拒绝所有错误输入。
- 搜索索引/目录/源指纹保持current、未重建。分词25个样本实际重跑通过。167条真实物理表行引用全部在原始grid回读相等。

## C1 [P1] 新正文兜底绕过引用绑定，且静默截400字

`src/env_rag_final/search/expand.py` 的无子条款分支发生在 bind_citations/verify_citations 和 unverified 计算**之后**。新造的item直接设置 citation_verified=True，没有再次绑定或校验。

独立实库及正式CLI的prose006现在给出正确的4.2内容，却同时输出：

- coverage=complete、citation_verified=True；
- citation只有char_start/char_end/quote，没有workspace/doc_id/snapshot_id/unit_id/原文locator；
- char_start=0，却把标题去掉后的正文当quote；坐标亦未调整；
- text硬截body[:400]，预算/告警/partial均未体现。

167表行+11正文引句共178条回读中，**这1条无身份引用不合格**（citation-reread.json）。另一个正式编排入口隔离反例：超过400字的无子条款普通正文被截掉尾项，却仍complete。既有读取预算足够，不构成允许截断的理由。

修复顺序必须是：确定答案文本与原始偏移 → 绑定全部引用 → 独立验证 → 重算unverified → 完成判定；若预算不足则明确partial。不能手造verified旗标。

## C2 [P1] 投影评分仍放过额外错行和未完成文件枚举

`search/eval.py` 的matched_names消费分支无条件应用到**完整cells模式**，而它只该用于明确的名称投影。期望`[1,总汞,0.05]`，产出正确行再加`[99,总汞,999]`，额外错行因同名被消费，仍exact_match=True。真实表001/005使用完整cells期望，因此这不是未使用的评分路径。

文件评分只读取候选，没有把document_enumeration的coverage/fail_stage/members状态传入incomplete判断。独立正式benchmark入口反例中，文件读取返回partial/budget_exhausted、只处理1/2成员，但候选碰巧与gold相等，仍exact_match=True。普通partial必须保留分母并计失败，不能只比较ID就声称答案完全正确。

验收：full-row额外同名错误行、partial文件枚举两个反例。

## C3 [P1] 完整枚举覆盖了discovery recall候选

`_expand_documents`继续替换result.candidates；`SearchResult.to_dict()`没有保留独立discovery列表。`run_benchmark`改为expand_docs后仍从doc.candidates截top-k算两种recall。完整枚举输出因此倒灌到候选发现指标，与上轮交接的明确要求相反。

正式benchmark隔离反例：发现阶段零候选，完整枚举找到d并答对集合，当前却把evidence recall计成1.0。正确行为是“集合正确、发现recall=0”。需分别保存预算内发现候选及完整枚举答案，或明确分两阶段执行；禁止丢掉已修好的B3文件枚举。

代码/报告声称“discovery独立”不能替代实际字段与调用链证据。0.949仍是执行agent的机制自检；本轮不把任何未冻结或混入完整枚举的结果当作Gate2指标。

## C4 [P1] 表格gold仍有反向子串放行

`search/gold.py:1372`使用`head in row or row in head`。只要quote含一个真实行，它后面追加编造的限值/说明也会通过；例如真实`1 | 总汞 | 0.05` + `| 原文不存在的附加限值999`，verify_typed_targets返回空错误集。

这与已经修好的正文80字漏洞是同一主张支持要求。表格应按声明的列投影、完整单元格值、真实行号核对；允许有依据的列投影/colspan表达，不允许字符子串或“真实行在编造长句里”作为验证。

## C5 [P1] 固定题仍未满足质量门槛，失败归因需要修正

独立31题运行的程序集合检查是：**file 6/6、table 5/6、prose 4/6**。报告写prose3/6，同时又列001/002/003与006均EXACT，数字自相矛盾；其中006又是C1的真实不合格引用，不能认可为合格答案。所有gold仍unreviewed，本轮没有计算正式门槛指标。

### 004/005不是Phase1 requires_span/大块结构问题

两题自然请求的trace都为auto_targets=[]、expansions=[]，尚未调用读取。主agent只读核验：

| 固定题 | 目录scope | 结构状态 | 成员长度 | requires_span | 直接原文读取 |
|---|---|---|---|---|---|
| prose004 | GB3838 scope3 | confirmed | 363字 | false | complete 1/1 |
| prose005 | GB14554 scope4.1 | confirmed | 225字 | false | complete 1/1 |

显式传入上述scope后两题都实际进入正文读取/输出。缺口在Phase2：没有根据候选来源/标题/题意确认范围，且罗马类别与中文级别的答案投影尚未闭环。不要改建目录或宽松覆盖结构状态来修这两题；可以在已授权Phase2内完成。不能给固定题硬编码doc_id、scope_id或gold答案。

### prose003的gold仍只检查前缀

当前expected分别是“4.3.1 同一排放口”“4.3.2 工业污水”“4.3.3 污染物最高允许年排放总量”“4.3.4”。保留这些短词，把四条要求全部改成相反内容，现有评分仍exact=True。新反例直接使用当前提交gold验证了这一点。题面要列全部要求，gold须含完整要求或明确的必要主张（混合污水附录A、负荷附录B、年总量附录C、放射性污水另执行GB8703），不以关键词/编号代替内容。

31题及10反例期望重新逐项审查见gold-review-v4.json；保持计分gold未冻结。table005实际是**30数据行/24控制项目**，不是报告所称24数据行；表头和脚注分离的修复成立，全部浓度/负荷子行仍要保留。table003保守ambiguous可以作为失败保留，达到表类5/6并不要求强行解除结构歧义。

## 证据与操作边界

- 本轮26次生产检索重跑、31题benchmark、25个PG词项探针；2个scope直接读取和2个显式scope请求；2次正式CLI复跑。
- 7项新增验收均在实际编排/评分/验证入口复现，未调用模型；161既有测试通过。Ruff/OpenSpec严格/diff检查通过。
- public八表221/5709/279/16514/65527/221/221/119575，源指纹95f7791fd84171ab727870fc5810d79b4327b0c4fa547d432951e0499a3808f8、catalog4919b3938ad93747、search e3cb2a39dee53d9d未变。
- 检索源码、原gold标签、原33断言均未改；新测试保持失败，不skip/xfail。OCR只加载文件/规则；逐文件review/skip账本见coverage-manifest.json。
- 下一步按handoff-phase-2-fixes-r4.md在Phase2完成C1–C5；4.1–4.3继续保留已通过结论，4.4–4.6不放行。

审查覆盖统计：{"total_files": 164, "reviewed_files": 6, "skipped_files": 158, "coverage_rate": 0.036585365853658534}；全部preview条目均有review/skip及理由，额外人工审查另记于账本。
