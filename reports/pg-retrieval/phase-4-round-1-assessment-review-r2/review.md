# 离线评分 r2 增量复审（主 agent，2026-10-08）

**仍未通过评分验收，第二轮继续暂停。** Gate3、6.1与第一轮执行证据保持。上轮冻结17项、自带10项、历史6项共33项独立通过；原运行809项、原评分9项、新评分4项清单全部匹配。已完成的表格extra、fact凑词、citation workspace/名字、typed discovery、人工合成落盘等修复保持，不返工生产链路。

剩余问题集中为R1–R3。新增18项冻结矩阵：**14失败、4正例通过**。矩阵只读既有工件、复制内存对象或在临时目录构造坏输入；0网络/模型/数据库请求、0写库，无生产代码或提交目录修改。新脚本仅在临时输出目录复跑，与提交adjudication字节一致；原始blocks/tables全量字节指纹与Gate0冻结组件一致，未发现本轮来源漂移。

## R1：声明本身尚未完整受来源约束（P1）

- `_prose_spec` 只为dict金标提取编号；字符串金标仍把编号当普通文本。真实prose-enum-001/pg的第一项clause改成9.9.9，仍PASS。上轮修复只覆盖了另一种金标形状。
- 保留真实quote，给答案text追加“停车场允许无条件排放污水。”，仍PASS。验证quote存在不等于验证所交付声明。
- table/prose的item.doc_id与citation.doc_id矛盾，仍PASS；prose目标范围用两者OR，也让矛盾归属通过。需要对完整声明身份做一致性检查。
- **真实当前错误**：prose-enum-003/pg的4.3.4交付20,636字符，quote仅120字符。citation的unit_segments按声明顺序重建，并不包含该完整text，评分仍PASS。并非要求text必须等于短quote：合法长条款可从原始声明跨度完整回读。prose-enum-001与002的原始正确项正例保持；不能为了过新矩阵全拒正文。

R1影响当前“36通过”的可信度，不能只修复制后的反例而不重新核对真实长正文。完整逐字来源与条款/文档身份应分别检查，局部gold内容命中不能掩盖交付文本中的无来源尾文。

## R2：反例的安全观测被当成完整行为通过（P1）

`finalize_counter` 把missing/partial/ambiguous/isolation归为同一“保守拒绝侧”：零交付、非complete就PASS。连runtime=failure、no_answer_artifact的腿也可被判missing行为PASS。这不能证明冻结预期行为完成。

主agent明确本轮裁决政策，补正无需再猜测：

| 当前证据 | 整题裁决 | 可保留的局部观测 |
|---|---|---|
| neg-001/006 PG、fusion显式missing并未替代版本 | 保持有证据支持的PASS | 缺失版本不替代 |
| neg-001/006 local仅partial、条件不足，无明确missing答复 | FAIL冻结行为合同 | 未乱答/无false complete |
| neg-002三路零交付，只有本腿隔离观测 | PENDING隔离合同 | 本腿未见外workspace；不是对抗证明 |
| neg-007三路partial，而冻结要求ambiguous | FAIL冻结行为合同 | 保守拒绝，不编造表号 |
| neg-008只在PG守卫耗尽，未到成员/字符展开 | PENDING该展开预算反例 | 请求前额度闸门工作正常，可单独PASS这项控制 |
| neg-009三路expected ok但零交付 | FAIL整题未回答 | 不构成内容丢失或版本乱答的证据 |
| neg-010 PG/local零交付 | FAIL整题未回答 | 各自的model_failure/条件不足保留 |
| neg-010 fusion四条真实4.1句 | FAIL整题未回答 | 真片段来源仍保留；未回答“修改单能否替代原标准”关系 |

neg-010/fusion四句是原标准排放、消毒、禁排和脱氯条款，没有回答替代关系。此项现由主agent完成语义裁决，不再留“over-answer疑点”。neg-003、neg-004 PG/fusion真实正确行为保持；neg-004 local及neg-005 PG/fusion已知失败保持。

**“未发生不安全交付”与“满足被测行为”需分字段。** 因而当前20 PASS/3 FAIL/7待审不认可为反例整题得分；也不因此否定预算控制工程验收。expected只用于事后判定，仍不得干预运行路由或改gold。

## R3：输入拒绝边界仍不完整（P2）

- `verify_inputs` 用`if post and ...`检查后置身份。删除identity_after，保留finished_at和全部前置字段，仍返回ok=True。完成标志不能替代实际post身份，后置证据必须存在并一致。
- 损坏manifest JSON直接在verify_inputs抛出，main未写input-rejection.json。已正常非零且未发布裁决，但不满足统一拒绝诊断合同。给verify_inputs及其前置读/解析异常一个统一净化边界即可，不需要新线上验证。

## 裁决与下一步

typed发现分段、撤回旧三项均值及18条合成FAIL落盘的方向正确，保留；文档级覆盖不能升级为typed证据召回。当前36/42/15和20/3/7仅是未通过工具的暂存结果，不发布成功率或融合增益。第二轮不会修好这些评分漏判，暂不继续付费采样。

按`handoff-phase-4-offline-assessment-fixes-r2.md`在独立assessment-r3代次，仅修离线R1–R3并复算真实行。两轮冻结矩阵和历史工件原样保留，不修改生产代码、提示、gold或配置；不重跑工程全套测试，不勾6.2/6.3/Gate4。
