# 新代人工审查记录合同（rules vs human conclusions 分离）

## 为什么旧 `_MANUAL` 不能用于新运行

r3 的 `_MANUAL`/`manual_review_for` 按 `(qid,path)` 固定套用 Round-1 人工结论；
新运行同一题同一路径的输出 SHA 不同，若照套就是把历史人工 FAIL/PASS 当新证据。
主 agent 勘误（phase-4-finalization-offline-review/review.md）点名此为付费两轮前
必须修复的误判通道。**新代里 Round-1 人工表只在显式兼容模式生效**；
生成模式（`--run-dir --round --anchor`）零继承：无匹配记录的语义项=PENDING，
机械决定性 FAIL 保持 FAIL，正确机械 PASS 保持 PASS（仍受抽审）。

## 记录格式（`--records` 附件）

```json
{ "schema": "manual-review-records/r1",
  "records": [ {
    "round": 1, "qid": "syn-002", "path": "pg",
    "answer_runtime_sha256": "<被审 answer-runtime-latest.json 的逐字节 SHA>",
    "response_evidence_sha256": "<sha256( utf-8( json.dumps(model.raw_response, sort_keys=True, ensure_ascii=False) ) )>",  或  "response_evidence": "absent",
    "reviewer": "主 agent / 具名审查人",
    "verdict": "PASS | FAIL | PENDING",
    "reason": "整题结论与依据",
    "checked_items": ["subject","value","unit","time_or_grade","verbatim_source", …]
} ] }
```

## 校验与安全性（全部由评分器强制执行）

- **绑定即校验**：round/qid/path 对不上、runtime SHA 不等、"absent"与实际响应不符、
  缺 response 绑定又非 absent——**拒绝并非零退出**（写净化诊断、不产裁决文件），
  而不是静默忽略；第二轮绝不接受第一轮键的记录。
- **PASS 只能解语义/载体缺口**：仅机械终判为 PENDING（evidence_gap/内容复核/
  隔离合同等）的行可被 PASS 记录解决，且记录必须列出该缺口要求的已核项
  （fact 载体=`subject/value/unit/time_or_grade/verbatim_source` 五项；
  引用元数据缺口=`doc_name_evidence`；gold 投影=`gold_projection`；
  掩码=`masked_cells_reread`）。
- **PASS 不能救**：已证实的出处错/数值错/缺项/引用未验证/覆盖不全（机械 FAIL）、
  以及"raw 模型对而应用 0 交付"——行保持 FAIL，冲突公开记 `manual_pass_refused`。
- **FAIL 记录**：决定性覆盖（含反例行为合同之上的语义 FAIL，如 neg-010 型
  "真实条款不答替代关系"由新记录重新裁）。
- **PENDING 记录**：可把机械 PASS 降回 PENDING（人工更严永远允许），不能升格。
- fact 散文载体不因格式自动对/自动错；附录 A 与规范正文分列；gold 不改、
  不迎合答案。
- 账本三态不受人工影响：HTTP 实发只认本题真实 call 凭证（reserved≠issued；
  `incomplete_answer_coverage` 可发生在成功 HTTP 之后=发过；无凭证不猜零，
  ledger 不可读=统一拒绝路径）。

## 22 条旧待审清单（订正口径引用，不改历史终判）

按主 agent 勘误：fact 正例 **12**、file-enum-004 三路 **3**、neg-002 三路 **3**、
**neg-005/local 1**、neg-008 三路 **3**。（我方 finalization 方案误写 neg-007——
neg-007 三路原判 FAIL，保持不翻案；neg-008 预算闸门是局部安全观察，整题仍
PENDING 不从分母消失。历史文件不回改，订正以本引用为准。）

## 审查人员与流程

未来两轮的人工审查由主 agent 侧完成并落上述记录文件（评分器只消费绑定记录）；
执行方不代拟任何未来结论（本组亦未预造：测试用记录全部是合成/已存工件副本，
文件名含 `fixture` 标记）。
