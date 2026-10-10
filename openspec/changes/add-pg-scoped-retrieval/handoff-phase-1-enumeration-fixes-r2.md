# Gate 1 第二轮补正交接

先读 reports/pg-retrieval/gate-1/re-review/review.md、replay-live.json、replay-offline.json和replay.py。

PG现已可连接：主agent实测public八表计数前后一致、源指纹冻结值一致、active仍v4。无需重建或迁移现有存储。Gate0、结构检查点和3.1保留通过，3.2–3.5仍未完成，3.6保持未勾选，不进入Phase2。

## 执行顺序

1. **R1/R6：先修正式正文编排及合同。**读取结果与答案结果分开；CLI先绑定原文引用、核验目标项目/缺失集合，再定coverage，source指纹非空。禁止warning包含items/extraction就允许空complete。按实际生产入口复跑GB18466 第3章3.1–3.4（当前退出1），不存在9.9.9必须非complete（当前退出0且空complete）。三个CLI连接强制只读，SourceAdapter构造用合法连接参数；model错误写fail_stage，提取后再次来源检查。
2. **R2：修表格坐标及回读。**保留原始片内grid行坐标，删表头不重编号。每项独立重新读取对应table_id及坐标，比较cells/支持范围；表1全部13项必须通过，不能只验证fragment_index<2。覆盖缺第一片/允许partial读取第二片，元数据索引不能压缩错位。最终输出保留header/units/footnotes。
3. **R3：按请求定位大块。**CLI/API将目标条款或子范围传到reader，不能自动取第一数字条款。全scope必须读完实际全范围，不能第一子条款代表全scope；局部未定位明确partial/ambiguous。保存unit原始char offset，绑定引用时考虑裁切偏移；最长重复条款更新起止坐标同时保持与text一致。只允许有原文边界证明的fallback，parsed_root/locator按参数使用。
4. **R4：窗口与workspace。**正式表格入口读取后检查live source和active；正文检查包围模型/抽取，不能只包reader。文件入口检查live source，不能仅依赖目录token；同workspace传到count/page/active。token覆盖全部输出字段；无源指纹/不支持workspace明确拒绝。用隔离连接/守卫模拟变化，不写public来制造反例。
5. **R5：项目支持关系。**“停车场”配真实“门诊、病房”引句必须被拒绝或标未核验，不得verified。明确场所名词可以按任务结构做确定性匹配；通用claim没有验证依据不能complete。schema/type异常、空引句、引用不支持项、transport/JSON失败通过正式编排传播model_failure，不只测试helper。保存完整模型输入输出及日志，不含密钥。
6. **R7：证据由正式入口产生。**按实际格式交付JSONL，保存本轮CLI命令参数/题目/双快照/范围/项目/引用回读/失败。记录表1、表2、GB18466定义与4.1.1–4.1.5、完整4.1、GB3095第4章、年报/公报/GB3095版本分页，明确已验收集合。保留局部3.2场所gold的开放边界和原文，不重新批量审核35题。旧报告留档，当前摘要只写本轮已执行证据。

## 必须重跑的真实与隔离验收

- 实际console CLI正文3.1–3.4成功；不存在9.9.9非complete，明确缺失集合；model路径同样由正式CLI/编排绑定引用并检查失败。
- 表1输出13项且每项raw grid回读cells相等；多级表头/续片/合并格/缺片坐标正确。
- requires_span：真实WHO大block局部请求及未定位反例；构造同unit含7.1/7.5/7.6请求7.5，必须返回7.5并引用原始offset，或明确无法证明而partial，不能7.1 complete。
- 读取中、最后一页、提取/模型期间来源或active变化 → stale；另workspace不能查询default后标另workspace。
- 不受真实引句支持的项目非verified；缺身份、空/错误版本、缺定位、待抽取空结果不得complete。
- 原有已通过的必要测试保留；新增测试调用正式CLI/编排并断言实际目标内容/坐标/状态。Ruff check和format、OpenSpec strict、diff check都执行并记录。

public和MinerU只读，优先只修消费代码；不改已验收目录配方。修复后仅勾选有新证据的3.2–3.5，3.6留主agent。不要仅因新增测试通过就提前写“全部补正完成”。
