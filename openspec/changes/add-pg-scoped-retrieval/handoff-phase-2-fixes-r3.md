# Gate2 第三轮补正交接

先读 `reports/pg-retrieval/gate-2/review-r3/review.md`、`gold-review-v3.json`、`benchmark.json` 和 `tests/test_gate2_review_r3.py`。原13+11断言未变且24/24通过；152既有测试通过，新9项验收失败。4.1–4.3经独立证据通过，4.4–4.6未完成，仍停Gate2。

本轮仅补已存在的范围闭环、固定三类清单和质量合同，不扩展问题集或开始融合。

1. **B1（先修）**：`_expand_prose` 保留读取层缺失集合/partial/fail_stage，完成条件还需请求条款全部出现，不以“有一些引用正确的条目”覆盖缺失。真实 `4.1.1至4.1.7` 必须 partial/明确缺4.1.7。支持已承诺的“3章”语法，固定 prose001不能继续ambiguous。
2. **B2**：建立每题明确的答案投影合同；比较名称、内容/必要条件、值/单位/平均时间或子项，而非仅序号。表格物理行留作引用证据，污染物集合按问题去重；不得丢掉同序号不同平均时间/高度/浓度和负荷子项。正文无子编号、罗马类别、级别清单均应从确认的原文范围提取。不得把4.2问题回答为4.3/4.4且complete。现有词法/结构方法可继续使用；需要模型另行说明调用范围，本轮没有新的模型调用授权。
3. **B3**：benchmark 文件题实际调用完整 expand_docs；对 expected_doc_ids 和实际 document_enumeration/candidates 做集合比较并核查版本、来源和引用。候选发现的 recall 仍独立截断 top-k，不把完整枚举倒灌候选召回。必要时保存 discovery_candidates 与枚举输出两个字段，避免偷换指标。
4. **B4**：固定金标身份正确的一类6题要保留全部6题及失败行；ambiguous/partial/抽取失败计集合不正确，不给其候选记可信证据。stale/错来源/错workspace仍明确拒绝指标或使整轮无效；不得以仅剩可用题的 questions 数作Gate2分母。六题1对5失败必须1/6，不能1/1。
5. **B5**：gold verifier 校验完整已提交引句，不截80字放行。表格验证行、列、值和支持主张，不是仅ID存在。raw_grid上下文、answer expected_items、header/units/footnotes分开。table005材料已有全部32raw行，但答案应按题面投影（24控制项目及其浓度/负荷等子行的预处理值，另保留注释）。补syn001必要日期typed证据组、fact007前后时期相应表来源，保留syn002公开排序失败及重复6.1.2要求。31题交主agent审核冻结；不自行把gold持久改approved迎合分数。

保留原13、新11、本轮9验收断言，不删/skip/降低断言。若数据合同调整需适配调用形状，保留等价的行为要求并在报告逐项说明。先跑新9定位，修复后完整回归，再逐题跑真实31题、六文件分页和至少8个反例；每题保存完整输出及missing/extra/内容和引用错误，而不是只有status/候选数。源public/MinerU只读；来源变更和构建故障放隔离测试；未改索引派生无需重建。

交付 `phase-2/report-gate2-fixes-r3.md`、完整逐题runs、修订gold及其投影合同、反例执行断言和来源manifest。4.4–4.5按新证据可提交恢复勾选，4.6由主agent。停止于Gate2，不进入Phase3。
