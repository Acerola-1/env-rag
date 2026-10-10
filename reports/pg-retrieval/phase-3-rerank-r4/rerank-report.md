# 5.4 联合精排（D1/D2 正式入口衔接补正，第四代次）

日期：2026-10-07。响应 `phase-3-rerank-review-r3/review.md` 与 `handoff-phase-3-5.4-fixes-r3.md`。前三代次保留为历史；C3 与派生映射（12 table/29 block）结论沿用。**本轮 0 新真实 HTTP/模型/embedding 调用、无新增只读 PG 核验**——只修编排接线与证据发布，不冒充正式入口运行。

## D1 使用已验证 active snapshot，兼容真实输入结构

- `_rerank_one` 的补关联快照改取**前置守卫已验证的 active 目录快照**（`report.identity_before.catalog_active.snapshot_id`，即 capture 比对冻结后的值），不再读任意根级字段。
- 回放声明值全部收集核对：真实 5.3 形状的 `pg.catalog_snapshot_id` 嵌套字段与任何根级声明值必须与 active 一致，**不符 → AdapterError 拒绝**（服务接触之前）；有声明值但 active 未知 → 拒绝（无来源证明不静默补全）。真实 5.3 JSON 无根级字段、只有 `pg` 嵌套——正式入口现在直接消费该真实布局，不再需要 fixture 加根字段才通过。
- 已知 active 值存在时补关联**绝不静默 skip**；空候选集合仍零目录读取（新增入口测试：冲突拒绝 + 空集合 skip，均经 production 分支 fake HTTP/fake PG 验证）。
- unit_kind JOIN、组合键、block/source_unit 与 table 分类保持不动。
- 冻结 `test_rerank_review_r3.py::test_real_fusion_shape_uses_verified_active_snapshot_for_enrichment` **通过**：真实嵌套形状下 catalog 读取发生、args[1]==已验证 active "s"、`actual-table-unit` 路径进入 ordered。

## D2 发布规范化修复轨迹

- `_verify_candidates_against_source`：doc/SHA/**长度**始终按当前生产行规范化（此前仅在 doc/SHA 差异分支内重算——仅长度错误也会被漏掉）；每个实际变更字段记入 `repair_fields`，原值 `replayed_doc_id`/`replayed_content_sha256`/`replayed_content_len` 与 `canonicalization_basis` 一起保留。
- `_rerank_inputs` 不再丢弃这些字段——**按 key 存在性**发布（原值为 `None` 的修复（如空 doc_id）同样是证据，必须出现在落盘记录里）。
- `_rerank_one` 的在途记录发布到 `live["partial"]`：查询中途抛错（绑定拒绝、补关联失败等）时失败终态仍携带该题已产生的 inputs/source_verification/repair 轨迹；每题开始先重置，绝不串题。
- 冻结 `test_canonical_repair_evidence_is_published_not_only_kept_in_local_dict` **通过**：同时错 SHA + 空 doc，终态报告可查到原 SHA 值与非空修复依据。

## 验证与检查

- 冻结 r3 2/2；r1 14/14、r2 6/6、矩阵 18/18（含新增 D1 冲突拒绝/空集合两个入口反例与交接要求的真实 SHA 断言格式化）——rerank 全系 **40/40**；全套 **319 passed**（原 315 + 本组新增 4 项矩阵断言，无删/弱化）。
- Ruff check/format（含 `tests/test_rerank.py` SHA 断言处，交接指出的格式点已修）、OpenSpec strict、diff、凭据扫描通过。r1/r2/r3 冻结文件 SHA 未变动（`3039068…`/`6673e0e…`/`9a337de…`）。
- 997ms 原始响应与上轮 12 table/29 block 类型证据沿用；未重跑检索/精排，未篡改旧运行。

## 交付

实现 `rerank.py` rev 4（`e2a8e089…`）、矩阵测试更新（`7edeaa62…`）；本目录仅存报告与 manifest（无新真实运行产物）。停 5.4 检查点待主agent复审；5.5/5.6/Gate3 未进入。
