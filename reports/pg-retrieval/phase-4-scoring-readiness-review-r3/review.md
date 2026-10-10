# 评分准备 r3 复审（2026-10-09）

**原衔接27项通过保持，仍有一处严格校验作用域未覆盖后续读取；本轮暂不放行正式付费评测。** 不返工硬失败判定、typed身份保留、独立诊断或八表锚结构。

独立复跑：原17+新10共27/27；历史35/35；自有22/22。新增小矩阵3项（完整owning入口）：**2失败、1正例通过**。源码/历史不修改，不重复526工程全套；全部输入是合成终态+既存工件副本，0真实服务/DB请求。

## 唯一剩余衔接

生成模式main把`_STRICT_BIND=True`只包围`_score_legs`，在finally里立刻关回False。**随后**才调用`recall_report`和`typed_evidence_recall`，它们经`_fusion_segments`/`pre_expansion_docs`/`local_discovery_identities`读取真实fusion/local工件。这些函数虽调用`_bind_leg_identity`，但此时开关已关闭，缺少必填qid/workspace就被当成裸接口探针放过。

独立反例（均有合法manifest SHA，明确status=ok）：

- fusion发现结果删除query_id：实际main仍发布123行裁决，而应输入拒绝。
- local发现结果删除workspace：实际main仍发布裁决，而应拒绝。
- 保留完整qid/workspace的零发现正例：仍正确输出零召回，且入口返回后_STRICT_BIND=False。

所以答案结果的必填检查已修对，但不能宣称正式fusion/local消费同样闭合。`test_scoring_review_r3.py`固定这一处生命周期与正确正例，原始结果pytest-independent-r3.txt。

## 下一步限界

仅handoff-phase-4-scoring-readiness-fixes-r3.md：在全新r4评分副本，把严格绑定作用域包围整个正式生成消费过程（含recall/typed），成功与任何异常后恢复裸接口状态。原27、35冻结不动，新3项不动；必要的非冻结fixture只补合法身份，不弱化零发现/分母断言。

本轮不建正式锚、不问额度、不启动任何评测批、不改生产组件/gold/旧目录。6.2–6.5、Gate4、默认路径保持。其余已通过结论与预算提案保留，避免扩大修改。

保护复核：33份选定清单1298条与6项来源锚无漂移，before/after登记匹配（不冒充全部1434条）。严格校验/diff/reviewer专项ruff格式通过，新增工件按实际配置敏感值扫描0命中；OCR无LLM，preview每项reviewed/skipped登记见ocr-coverage.json。
