# 仅5.4正式入口衔接D1/D2，完成后停检查点

原C3与20项独立断言已通过，原315项保持；新增两项失败，报告phase-3-rerank-review-r3/review.md。不要重做原修复、不进入5.5/5.6/Gate3，不新增真实HTTP/模型调用。

## D1 使用已验证active snapshot，兼容真实输入结构

真实5.3 result的快照在pg.catalog_snapshot_id，没有根级catalog_snapshot_id。当前正式入口拿None，补关联被skip，人工派生记录无法替代owning入口修复。

在入口取前置guard已验证的catalog_active.snapshot_id，核验replay实际pg.catalog_snapshot_id及任何其它声明值一致后，给补关联使用同一个active值。缺失/冲突需按合同明确拒绝或有效来源证明，不能信任任意字段、也不能对已知active值静默skip。unit_kind JOIN、组合键、block/source_unit与table分类均保持。

冻结test_rerank_review_r3.py::test_real_fusion_shape_uses_verified_active_snapshot_for_enrichment，经production分支的fake HTTP+fake PG验证。再覆盖不符声明快照拒绝、空集合正确skip。使用实际已验收JSON字段布局，避免仅让自行增加根字段的fixture通过。

## D2 发布规范化修复轨迹

replayed_*与canonicalization_basis在局部verified字典已有，但经_rerank_inputs后被丢弃。将原doc/SHA/长度与规范新值、chunk身份、来源/依据保存到inputs或source_verification逐项repair记录，成功/失败终态均可追溯。当前行doc/SHA/长度始终规范化；记录实际变更，不因未改SHA就漏掉错误长度。

冻结test_rerank_review_r3.py::test_canonical_repair_evidence_is_published_not_only_kept_in_local_dict：同时错SHA/空doc，最终报告必须包含原SHA、原doc字段与非空修复依据（不是仅函数内存在）。不改原文件元数据来迎合，不恢复错误来源。

## 有界交付

原315项及新增2项全过；r1/r2/r3独立断言不弱化。格式化tests/test_rerank.py现有真实SHA断言，Ruff/format/OpenSpec strict/diff/凭据扫描与最终manifest一致。

**0新真实HTTP/模型/embedding调用，也无需新增只读PG核验**。997ms原响应与上轮12 table/29 block真实目录类型证据可沿用；本组只验证编排接线和证据发布，记录隔离入口证明，不把人工派生冒充正式入口运行。停5.4待主agent复审，5.5–5.6不进入。
