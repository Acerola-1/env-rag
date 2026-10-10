# Gate2 第四轮补正交接

先读gate-2/review-r4/review.md、gold-review-v4.json、scope-cause-and-final-source.json、citation-reread.json和tests/test_gate2_review_r4.py。原13+11+9断言文件SHA未变、161既有测试通过；本轮7个新反例失败。4.1–4.3保持通过，4.4–4.6未完成。

仅继续Phase2；不重建目录、不改public/MinerU、不进入融合。正文004/005的现有scope已confirmed且小块完整可读，无需另请求改Phase1结构。

1. **C1先修**：无子条款正文答案必须通过同一bind/verify流程，包含非空workspace/doc/snapshot/unit/原文locator、正确unit相对偏移。去标题后按实际偏移绑定，最后才计算unverified/coverage。移除400字静默切断；全文在读取预算内应完整输出，超预算明确partial。真实prose006引用必须能独立回读，不能造verified=True。
2. **C2**：完整cells投影不适用“同名子行全部消费”。额外同名错值行必须extra/不exact；只在显式name projection下消费合法同项目证据子行。document_enumeration的coverage/fail_stage/总量处理量实际进入文件质量判定，partial/ambiguous不能因候选刚好相等而exact。
3. **C3**：真实保留discovery_candidates（预算内排名、身份及路径），与enumeration_answer_items/完整范围输出分开。recall只看发现列表，集合指标只看完整答案；没有发现候选、枚举答对时两者应分别0与true。可以分两次运行，但记录同一来源/参数身份；不能用完整枚举倒灌召回，也不能撤回B3文件题进入完整枚举。
4. **C4**：表格typed quote/expected支持关系按真实行号/列投影和完整cell核对，移除反向子串放行。现有colspan在raw材料中可能展开重复单元格，允许显式有依据的列投影；不得允许真实行后追加编造值。所有gold目标和完整主张自动回读，不只验证样例首行。
5. **C5质量闭环**：固定prose004/005从候选证据/标题/问题含义确认已有scope（3水域功能分类、4.1标准分级），处理没有题面编号的枚举，不硬编码题ID/docID/scopeID。类别/级别与数字条款分开定义投影；类别OCR原号与经过依据审核的规范号映射需保留。prose003 gold附完整四条要求或必要主张，不能短前缀/编号得全对。prose006正确语义+合格引用。保留syn001/syn002实际排序失败和table003结构歧义，不强行改变gold或confirmed状态。至少正文5/6合格集合、引用错误0，且质量/recall评测合同正确后才提交Gate2。

保留全部既有33验收行为及本轮7，不删/skip/降低断言。若分阶段API改变需适配fixture，可补完整身份/新的调用形状，保持原反例语义和强度并逐项解释。先复现7项，再修复、全套回归、逐题真实31题和正式CLI；每题保留发现候选/范围/答案/投影/缺失多项/引用核验，计分gold交主agent审核冻结。

报告数值按实际文件重算：当前程序prose4/6，其中006引用无身份；不能一处3/6另一处列4道EXACT。table005是30数据行/24控制项目；header/footnotes继续上下文保留。反例日志需完整运行结果和独立行为断言，不以status/候选数替代答案或引用验收。

交付phase-2/report-gate2-fixes-r4.md、完整逐题原始runs、projection及typed gold、反例断言、source/search manifest和检查结果。未改变分词/清洗/索引派生则不重建索引。停Gate2复审，4.6由主agent；本轮没有新的模型调用授权，需要额外模型验证时先说明具体范围。
