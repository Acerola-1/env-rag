# 第一轮离线评分复审（主 agent，2026-10-08）

**评分交付未通过，第二轮继续暂停。** 第一轮执行证据、Gate 3、6.1 的通过结论保持；本次退回的是新增离线评分器与裁决整合，不是重新验收生产链路。不勾 6.2/6.3/Gate 4，不切换默认路径。

本轮 reviewer 0 网络、0 模型/数据库请求、0 写库；没有修改生产代码、提交评分目录、gold、锚、原运行代次或旧测试。提交的 6 项测试通过，9 项评分清单和原运行 809 项清单全部复算一致。新冻结矩阵 17 项：**12 失败、5 正例通过**，见 `pytest-r1.txt`。3 条完整真实交付（table/prose/file）、fact-002 正确 partial 片段、零发现不回填均保留，拒收不是全局性。

## A1：集合投影漏判编号与多项（P1）

`assess_round1.py:400` 的正文匹配只读 `text`，没有把条款编号纳入匹配。复制 prose-enum-002/pg，把第一项 `clause` 改成 `9.9.9`，文本和真实引句不变，仍 `pass_mechanical` 且引用全真。

`assess_round1.py:278` 的 `seq_name` 分支只把命中 gold 的行加入 got，未命中的行直接消失。复制 table-enum-004/pg，加一行该表原始 grid 的真实表头（source 回读通过），仍 `pass_mechanical`，`extra_rows=0`。源行真实不能证明它属于被问条目集合。

## A2：fact 正文分支跳过来源核验与被问关系（P1）

`assess_round1.py:490` 在 `others and all(prose_bound)` 时直接按 coverage 放行，不检查 `all_citations_verified`。绑定 token 还由固定 cell 下标推导，fact-005 实际检查“臭气浓度/无量纲/10/30”，没有要求问题所问二级的 20/30 关系。构造“臭气浓度 无量纲 10 30”配不存在的 unit 和虚假引句，结果 **`all_citations_verified=False` 但 `pass_mechanical`**。需要证明主体/平均时间/级别/日期/数值/单位关系，而不是凑齐若干字符串。

## A3：引用来源身份与 metadata 未独立核验（P1）

复制真实 table/prose/file 三类通过项，仅把 `citation.workspace` 改为 foreign，均仍 `pass_mechanical`、verified=True。反例 neg-003 的行为分支也会忽略未证来源，仍 `behaviour_ok_mechanical`。

`assess_round1.py:157` 的 catalog 引用只检查自报 doc_id 相等和 doc_name 非空。file-enum-001 的 citation 改成“完全伪造的文件名.pdf”，仍 verified=True。反向地，合法归属文档的 citation 缺冗余 doc_name 就自动 pending，亦不是来源证明规则。必须用受身份守卫保护的独立既有文件/映射证据核对 workspace、doc、快照、元数据；不足才 pending，不能用答案自己为自己背书。

## A4：输入完整性没有成为评分前的拒绝门（P1）

`main()` 在评分、召回后才把 `verify_inputs()` 的布尔结果附到输出，并不拒绝失配。独立测试把期望 gold SHA 改成错误值，仍进入 score_row 并写 adjudication，正常返回。交接要求是先校验再评分；失败须非零、不得发布可信判定。测试仅改进程内常量、输出临时目录，未改 gold 或历史文件。

## A5：漏掉真正的 typed discovery，现有召回均值不能采信（P1）

`assess_round1.py:618` 只从 fusion 的 chunk `candidates` 读取 PG/fusion 文档。已验收 `fusion._normalize_pg` 明确从 **展开前 discovery_candidates** 分出 typed_targets 和 chunks；typed_targets 是真实发现，不是答案回填。

file-enum-005/pg 的运行记录为 `discovery_captured=True, discovery_total=3, chunks=0`，typed_targets 是原标准和两份合法相关文件，而 scorer 给 doc recall=0。该题有三份真实 PG 发现，不能描述为“PG 漏文件、fusion 补到”。这会改变路径对照结论。

补正时保留 typed 与 chunk 类型、workspace、发现出处。拆分后的列表若缺全局发现顺序，不得拼接后冒充同一 top-20；可以分列明确命名的 chunk 排名口径和 typed 发现覆盖，确实无法恢复的 @20 标 pending。禁止借 targets_resolved、枚举答案或精排回填；显式零发现正例必须保持。

## A6：整体裁决与细项缺口、人工结论需要分层落盘（P2）

table-enum-003/pg、fusion 的真实 coverage 已是 **ambiguous**，按冻结整题 exact 合同已经失败；两格掩码只令相应引用细项 pending，不能把整题改成 pending_artifact_masking。应同时记录整题 FAIL 和局部证据 unknown。

报告已人工判定 18 个正例 synthesis 整题失败，但 adjudication 中仍全部 `synthesis_pending_human_review`，没有同口径最终裁决。“39 PASS/16 FAIL/38 待审”只是有缺陷机械器的旧输出，不能作为已审基线。将人工结论、具体理由、支撑定位加入 canonical rows，汇总从这些行产生。

另有两处明确报告错误：18 个正例 synthesis 中实际 **9 行 HTTP**；另 **2 行是 neg-010**，合计全轮 11。§6 的“15 条拒绝”是旧试点数字，第一轮是 **3 条**（neg-008 三路）。10 条 answer 预留/实发差额的修正正确，保留。

## 保持的结论与下一步

file-enum-005/local 漏两份、neg-004/local 混入31项、neg-005/pg+fusion 不符冻结行为合同的证据仍成立。否决评分器不把这些真失败变成 unknown，也不把 neg-005 描述成已证明底层表身份串并。

请按新的 **A1–A6 一次性补正交接** 在独立 assessment-r2 代次修离线工具和报告，保留原目录与原始回执。只运行新评分工具必要矩阵和离线复算；不重跑454项工程验收、不发新付费请求。第二轮与改进生产链路的决定留待可信评分通过以后。

交接：`openspec/changes/add-pg-scoped-retrieval/handoff-phase-4-offline-assessment-fixes-r1.md`。
