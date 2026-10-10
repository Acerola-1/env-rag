# 5.3 补正（F1–F4，第五轮交接后）

日期：2026-10-07。响应 `phase-3-fusion-review/review.md` 与 `handoff-phase-3-5.3-fixes.md`。首轮提交（`phase-3-fusion/`）与其三题真实证据保留为历史；本轮仅修 F1–F4，不重复三题语义整轮、0 模型调用。

## F1 显式归属请求的合法允许集合

- `_allowed_docs(resolved, typed_targets, question)`：在显式"含修改单/相关文件/整合版"请求（与 PG 路由同一个 R1 谓词 `_attribution_requested`，自身编号显式排除）下，PG 已验证的 `doc_attribution` 目标（`citation_verified=true`、doc_id 存在）加入允许集合；`membership_basis`、原 citation 与快照保留在 `allowed_set_basis.verified_attributions` 与 typed 目标，**不伪造 self_code**。
- 普通标准/自身编号请求保持严格 code_exact 集合——新增正例 `test_self_code_request_never_relaxes_to_attribution`：即使 discovery 里出现归属目标也不放行（该反例暴露了首轮修复按 discovery 便放行的缺口，已按请求谓词独立判定）。
- 真实只读证据（neg-010，正式入口 PG-only）：GB 18466-2005 归属请求解析出主文档（self_code=GB18466）+ 两份无编号归属文档（doc-9bb1…、doc-b423…，basis 原样保留），6 usable / 0 拒绝——修复前两份归属文档全部被拒。

## F2 每条路径保留物理片身份与引用

- table_unit → chunk 路径保留 `unit_id`/`table_id` 与**原 citation 全文**（workspace/snapshot/doc/table/locator 等上游提供的字段原样带下）；typed 目标补齐 `scope_status`/`membership_basis`/`citation`。
- 真实证据（PG-only fact-002，`phase-3-fusion-r2/`）：同一 chunk（doc-b45c…-chunk-001）的两条 table_range_binding 路径分别携带 `tb-…-0001` 与 `tb-…-0002`、citation.kind=table_unit、snapshot=4919b393… 可分别辨认；typed_targets 同步保留片 ID。不猜页码/单位，不编造上游没有的 locator。

## F3 失败统一写入同一终态

- **gold 拒绝入前置失败边界**：`verify_gold_guard` 的 AdapterError 现在写 `failure.stage="gold-guard"` 的失败终态（零调用、无 finished_at）再抛；JSON 解析同理。
- **配置拒绝（F4）同样写终态**：`failure.stage="config-guard"` + 显式零调用账本（note 注明"config guard rejected before any backend read"）。
- **回读/合并失败保留当前题凭证**：`_fuse_one` 接收 `live` 发布引用——查询开始即发布 `query_id/partial` 阶段，local 完成即发布真实 receipts（call_records/by_service/groups）；外层 `_collect_failure_receipts` 优先取失败题的 live 凭证（partial 无凭证时记录阶段与说明），只回退到已完成结果中"自身 local 失败"的记录，**绝不借用前一题凭证**。
- 新增 `test_readback_failure_retains_completed_local_service_receipts` 通过（keyword LLM success 凭证入终态、identity_after 保留、无 finished_at）；新增 `test_multi_query_failure_receipts_belong_to_current_query`（第二题回读失败 → 终态凭证是第二题自己的账本）。

## F4 配置检查前置

- `verify_config_guard`（env 覆盖/未映射 workspace/模型/维度）对全部选定请求 workspace 的检查移到**任何后端接触之前**（先于 identity capture、先于任何 PG 读取/服务调用）；拒绝时写零调用失败终态。反例 `test_config_rejection_happens_before_backend_identity_reads` 通过（capture 计数=0、终态存在）。正常流程的 source/catalog/search/gold/env 前后守卫与原错误合同不变；`.env` 未被修改。

## 有界验证

- 独立验收 `tests/test_fusion_review_r1.py`：8/8（原 6 项含 1 正例 + 交接要求补充的 2 项：自身编号不放宽、多题失败凭证归属当前题）；原 `tests/test_fusion.py` 11/11 与全部既有断言未删/未弱化。
- 全套 **274 passed**（原 266 + 独立 6 + 补充 2）。Ruff check/format、OpenSpec strict、diff、凭据扫描通过。
- 真实入口证据（0 模型调用）：`phase-3-fusion-r2/`（PG-only fact-002，F2 片路径实证，identity 前后冻结一致无 drift）、`phase-3-fusion-r2-f1/`（PG-only neg-010，F1 归属允许集合实证）。

## 交付

`fusion.py` rev 2（`d5dc8570…`）、CLI 未变（`08753ee8…`）、`test_fusion_review_r1.py`（`9aff4a4b…`）、`test_fusion.py` 未变（`a89194b9…`）、r2/r2-f1 runtime JSON；本报告与 fusion-manifest.json（更新至 rev 2）。停 5.3 检查点待主agent复审；5.4–5.6/Gate3 未进入。
