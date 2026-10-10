# 5.4 第三轮：C3通过，剩两个正式入口衔接缺口

2026-10-07。5.4保持未勾选，5.1–5.3/Gate2保持，5.5/5.6/Gate3不进入。原20项独立反例与全套315项通过；新增两个入口反例失败，即315 passed / 2 failed。本轮0真实后端/模型调用，未改实现或旧断言。

## 已确认

- 九项提交SHA匹配，r2冻结验收文件SHA保持。规范化输出的doc/SHA修复、不同题目拒绝、source_units.unit_kind JOIN、block/table分别标记、先净化后截断与整个终态净化，已在此前约定场景通过。
- 原997ms原始响应继续有效；派生metadata的10个(input_index,chunk_id,score)与已验收排序相同，输入SHA不变。利用上一轮主agent只读类型结果独立比对，派生新增关联12 table_unit/29 source_unit类型正确。历史文件没有被当作新HTTP响应。
- C3已通过；原先模拟key全文、跨边界前缀、前置错误终态反例保持，实际配置值扫描0泄漏。

## D1 正式5.3结果形状导致补关联被跳过（C2）

真实已验收 `phase-3-fusion/fusion-runtime-latest.json` 的result字段为 `pg.catalog_snapshot_id=4919b3938ad93747`，**没有根级catalog_snapshot_id**。当前 `_rerank_one` 只把 `fused_result.get("catalog_snapshot_id")` 传给_enrich_table_paths，正式回放因此得到None并跳过补关联；人工派生12/29不能证明此入口已经修复。

独立test_real_fusion_shape_uses_verified_active_snapshot_for_enrichment复制真实嵌套形状，经生产分支（HTTP与PG替身）运行：catalog读取未发生，缺失表片路径仍未补齐。应取前置守卫已验证的active snapshot，核对真实pg字段及任何声明值一致，再调用补关联；不能信任任意根级字段，也不能默默跳过一个实际已知的active snapshot。

## D2 规范化原值/依据只在局部字典，未落盘（C1）

_verify_candidates_against_source确实创建replayed_doc_id、replayed_content_sha256、canonicalization_basis，但_rerank_inputs重新组装时仅复制固定字段，将这三项丢弃；source_verification只记计数/问题，终态没有修复记录。因此提交“原值保留、依据落盘”目前只对函数内部成立。

独立test_canonical_repair_evidence_is_published_not_only_kept_in_local_dict同时提供错SHA与空doc，规范化的最终身份正确，但落盘报告找不到原SHA或修复依据。必须在inputs或source_verification的逐项repair记录保留原值/新值、chunk身份与依据，并让成功/失败终态都可追溯。长度也应总是按实际行规范化，不能仅在doc/SHA变化分支重算。

## 检查与下一轮

Ruff check/OpenSpec strict/diff通过；Ruff format当前在tests/test_rerank.py真实SHA断言处未通过，补格式即可，非新增功能组。

下一轮仅D1/D2，固定tests/test_rerank_review_r3.py两项保持，原315项不弱化。使用真实输入JSON形状与owning生产分支替身验证，不做模型/HTTP/PG-only复跑；997ms原始响应与12/29类型证据沿用，不篡改旧运行。交接handoff-phase-3-5.4-fixes-r3.md。
