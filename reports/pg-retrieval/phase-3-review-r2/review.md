# Phase 3 / 5.1 第二轮主 agent 复审

2026-10-06。**仍未通过 5.1，恢复未勾选；只补正 D1–D4，5.2–5.6 / Gate 3 不进入。Gate 2 保持通过。**

复审覆盖 compat_runtime.py 全文、第二轮报告/probes/manifest 和旧安全测试；OCR 只提供本地预览/规则，未调用外部审查模型。全量 workspace 清单中的前期文件不重新验收，逐项范围见 coverage.json。未修改应用实现、旧测试或提交证据；仅新增复审用例与报告、更新任务状态。

## 本轮确实完成的修正

- 唯一临时库、所有权表已加入，旧固定名入口不再盲目复用/清理；池持有引用与全释放后重建已分别记录。
- workspace 样例实际有 A/B processed 行和各自 60/99 内容，来源 ID 结论已更正；missing 从公开 get_by_ids 返回 None。
- 发布包原生 PGTableGraphStorage 已实测成功；cache 正确读取小写表与 extract 类型，未声称查询缓存已验证。
- 提交 manifest 中代码、报告、latest probes、gold 的四项 SHA 均与当前文件匹配。
- 新的内容级源指纹采集已实现；在有效采集 fixture 下，doc_full=222 确实触发 ProbeAborted（本轮新增正向验证通过）。

这些修正不等于拒绝/清理路径全部可靠。下列反例在当前正式 owning entry 上复现。

## D1 [P1] 清理核验不完整，仍在拒绝前执行会话终止

位置 compat_runtime.py:262–269、301–314。

`_verify_ownership` 读取了 marker.db_oid 却没有比较它，只比较 secret 与当前库 OID。反例：marker db_oid=999、run record/current OID=42、secret 相同，仍放行。三重标记中实际只验证了部分。

`cleanup_scratch` 完成一次校验并关闭连接后，在管理连接上先对库名执行 pg_terminate_backend，再核对当前 OID。反例模拟库身份在两次连接之间变化：函数最终抛 ProbeAborted，但已经执行会话终止。应用名也是全体运行共用的常量，不能证明会话属于本 run；所有实例已 finalize 后应当拒绝任何未知剩余会话，而不是先按库名全部终止。

要求：marker.db_oid、record OID、current OID 全部一致；任何实际破坏动作前重新确认归属。移除按库名批量终止；如确需清理自有会话，按本 run 记录的 PID/身份限定，外来会话和身份变化在任何终止/删除前拒绝。不要因旧 legacy helper 用例通过而跳过正式 cleanup_scratch 验证。

## D2 [P1] 前后身份采集未转化为完整守卫

位置 compat_runtime.py:151–172、827–867。

`_identity_mismatch` 没有比较 FROZEN.catalog_run_id；env_sha 仅检查不为 None。run 没有把 before/after SHA 做差异判定。

正式 run 入口反例：before 的 catalog run 错误、snapshot/其他字段正确，仍创建临时对象并成功；before/after env_sha 不同、两次文件都存在，仍成功。这与报告“任一不符都非零退出”不符。当前实测文件没有变化只是此次运行的事实，不证明该拒绝路径已经实现。

要求：开始检查冻结 run/snapshot/search/source/gold；结束逐字段比较开始值，包括原 `.env` SHA 和 catalog run。错误须在入口保留 guard_failure 并退出，开始即不符不得 acquire。

## D3 [P1] 后置守卫读取失败时跳过清理和报告，恢复入口也缺记录

位置 compat_runtime.py:837–866、885–889。

run 的 finally 先 await capture_production_identity，再进入 cleanup 的 try。只要后置核对因连接/读取/文件错误抛异常，cleanup 和 _write_report 都不会执行。入口反例使后置 capture 抛 OSError，复现无清理、无失败报告。工作阶段异常、后置采集正常时，原异常也会绕过 finally 后的写报告步骤。

`--cleanup-run-record` 需要 scratch_secret，但 `_write_report` 产出的 record 删除了 secret，也没有另外保存恢复记录；用其实际输出调用 cleanup_only 会 KeyError。出错留下临时库时，没有交付可用的恢复入口。

要求：清理、环境恢复和失败证据写出各自独立 finally；采集失败也记录明确阶段，不能让它跳过自有资源回收。失败时不发布成功结果，记录 cleanup 是否完成/为何拒绝。提供与公开 CLI 配套的私有权限恢复记录，或其他可验证归属的恢复办法，不把恢复密钥混入公开报告。处理首次 acquire 部分失败、初始化中途失败的资源归属；确保实例在 initialize/ainsert 出错前也被登记并最终释放。

## D4 [P2] 探针失败仍可总体成功，部分报告事实没有本轮样例

位置 compat_runtime.py:482–614、718–743、842–867；compatibility-runtime.md §1/2/3。

backend_matrix 将 PGTableGraphStorage 异常存为 FAIL 后继续，run 未检查关键探针结果。入口反例让该必验普通图后端 FAIL，仍返回 finished_at/success。这不能用于复跑验收。

PGVector 当前探针实际因缺 cosine_better_than_threshold 构造失败，尚未到达 initdb/register_vector；不能拿这个结果证明本轮验证了无 pgvector 的运行时失败。独立安全探针补足配置后复现 unknown type: public.vector，修复后的正式入口仍须能自行复跑此项。

报告称同 workspace 的 doc-a/doc-b 已覆盖，但当前代码/最新 JSON 只有两个 workspace 各一个 doc-a；没有 doc-b 或并列版本运行。aquery 只保存内容前缀，未保存并比较公开返回 chunk_id/full_doc_id 与实际行，来源合同证据仍不完整。报告还把三项旧测试写成“包含外来会话”，实际它们只测固定名复用、固定名 cleanup、计数变化。

要求：必验探针定义明确成功合同，FAIL/缺字段/错误预期异常均令整轮失败并写证据；允许的 AGE/PGVector 失败必须在到达目标阶段后按类型/原因确认。补同 workspace 不同版本文件并列、逐 workspace 完整公开 chunk ID/内容/文档归属对照、同实例重复 initialize 采集；报告只陈述本轮实际样例。不要把 C1–C5 说明字符串当成断言。

## 测试及独立运行

- 提交基线 **181/181 通过**。本轮新增 8 项：**6 失败 / 2 通过**，完整结果 **183 passed / 6 failed**，见 all-tests.txt。旧断言未改，新失败断言保留。
- 旧计数测试确实因 **AttributeError** 通过，未触发 ProbeAborted、未写 production_untouched；审查记录 old-count-test-audit.json。新命名异常用例用有效身份采集验证真正的计数守卫通过，避免把 fixture 异常当作业务拒绝。
- 新用例 `tests/test_phase3_compat_review_r2.py` 走 run / cleanup_scratch / _verify_ownership 正式路径，以假连接/采集替身触发边界；0 次真实危险操作。C1旧测试只走遗留函数，不覆盖主入口清理路径。
- 主 agent 使用独立安全入口运行唯一自有隔离库（不是当前有缺陷的 cleanup）：wheel RECORD 172 文件无差异；两个 workspace 同 ID/不同内容、普通 PG 图读写成功、AGE/vector 原因已复现，见 independent-runtime.json。正式 PG 八表计数、source/catalog/search 前后不变，`.env` SHA 不变，自有临时库 ownership_verified 后清理；0 实际模型/embedding 请求。
- 当前 cleanup 和异常处理仍有安全缺口，因此没有直接运行提交入口的真实 destructive cleanup。待 D1/D3 修复后再做其正式 CLI 的整轮重跑；本轮独立运行不冒充提交入口已验收。
- Ruff/format（201 files）、OpenSpec strict、diff 检查通过；报告凭据扫描见 review-manifest.json。

下一位 agent 只执行 `openspec/changes/add-pg-scoped-retrieval/handoff-phase-3-fixes-r2.md`，完成后停 5.1 检查点复审。审核 gold、Phase 0–2 来源与既有验收断言保持。
