# 改进组2工程复审（2026-10-08）

**四条已知混入已修复；本组仍未通过，仅补归属证据与无编号范围证据两组接缝。** 497工程、提交18项+改进组1冻结12项、评分冻结35项独立通过。四条实施后回放与提交对账一致（4/1/13/13、外来0），源码/历史清单核对无漂移。Reviewer0网络/数据库/模型请求/写库，未改提交实现或旧冻结。

新冻结6项：5失败、1正例。所有反例均通过真实run_answer入口、fake只读目录/原始blocks，验证最终发布；不使用真实服务，也不修改gold。

## A 归属通道没有消费绑定的上游证据（P1）

`answer._confirm_scope_identities`在self_code为空时，判断依据是候选的非空membership_basis，或任一路径discovery=doc_attribution。未核对原5.3 typed目标、allowed_set_basis、citation身份/快照与请求关系。

两种构造独立复现：给与GB9001无关且canonical self_code未知的外来文件，仅加discovery标签，或仅加一句membership字符串。问题包含“含修改单”，原文/引用都真实，但**外来文档仍进入allowed和答案**。这不是已验证归属；提交正例fixture的“cover attribution recorded by 5.3 route”字符串不能独立证明来自5.3。

同一接缝还会反向丢失合法目标：构造真实5.3形状的typed doc_attribution、catalog_row citation（workspace/snapshot/doc一致）与allowed_set_basis.verified_attributions；该合法unknown-self-code目标没有usable chunk。当前只从candidates_by_doc找归属，于是**合法上游目标被排除**，违反已确认目标不受发现top-k限制的完整读取合同。

两面应一起修：归属来自完整、请求绑定的上游证据并经当前目录核对，不能来源于任意路径标签，也不能要求必须有chunk候选。普通/自身编号请求仍严格。合法原5.3修改单通道不能全拒。

## B 无编号分支仍把发现重新当确认（P1）

resolved汇总先包含全部typed doc_id；无代码时elif resolved直接接受。给纯local发现输入（discovery_only=True、targets_confirmed=False）加旧typed discovery=local，或把发现文档放入targets_resolved，提出“第4章规定哪些要求”，两形态都**发布complete及外来文档正文**。

这复用了已诊断的发现晋升路径：字段非空不等于可信元数据/逻辑范围。应区分真实的、可回读验证的scope/元数据确认与旧发现标签；前者保持，无依据的后者必须保守零答案项，不以全拒无编号查询修复。

## 保持

普通编号canonical门、四条原输入修复、空local不是全库missing、多目标/文件分页、改进组1全文引用与既有冻结保持。无需修file-005、改提示、重跑检索或更换模型。

交接：`handoff-phase-4-improvement-2-fixes-r1.md`。原18自有测试的归属正例可补真实上游证据fixture，保留正例断言；新的6项冻结不能修改。第二轮暂停，6.2/6.3/Gate4不勾选，旧质量分数不回写。
