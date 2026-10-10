# Phase 3 / 5.1 第四轮主 agent 复审

2026-10-06。**正常正式 CLI 已独立复跑成功，但部分创建失败路径仍未满足既定资源/证据合同，5.1 暂不通过；仅补正 F1–F2。** Gate 2 保持通过，5.2–5.6 / Gate 3 不进入。

提交为 `phase-3-r4/`（rev4），不与历史报告混用。代码、报告、probes、gold、r4 测试五项提交 SHA 全部匹配。全文复审正式实现、r4 交付物及验收测试，OCR 仅提供本地预览/规则，不调用外部模型；详细范围见 coverage.json。未改应用实现、原测试断言或提交证据。

## 本轮确认通过的修正和运行

- 实际 DROP 连接自己读取 OID/会话；三连接身份变化反例通过；不存在按库名终止会话的语句。
- initialize 前登记实例、恢复文件首写0600、普通 cleanup-only 失败落盘、同池/生命周期/cache字段门控均已实现；前轮6失败及2正例全部通过。
- 主 agent 运行最终正式 CLI，输出到 `phase-3-review-r4/formal-cli/`，没有覆盖执行 agent 的交付：run=`compat-d191627fe5e9`，scratch=`lightrag_probe_0fd498c573`，ownership_verified 后清理成功。
- 该运行的 backend/lifecycle/cache 合同 problems=[]；before/after 八表计数、内容源指纹、catalog run/snapshot、search、gold SHA、原 `.env` SHA 逐字段一致；没有 guard_failure，正常 finished_at。private record权限0600。
- 正式库仅作只读身份采集，所有 LightRAG 初始化在自有临时库；没有实际 LLM/embedding 服务调用。本轮验证接口/副作用，不宣称真实 local 语义链路已完成。

## F1 [P1] OID 查询本身失败时，部分创建身份再次被覆盖掉

位置 compat_runtime.py:299–321（_acquire_scratch）。

若连接新库成功，但 `row = await conn.fetchrow(...)` 在赋值前抛 OSError/数据库异常，except 中 `row["oid"] if row is not None else None` 又访问尚未赋值的 row，产生 **UnboundLocalError**。原有 ProbeAborted/partial_scratch 根本不会成功构造；run 收到普通异常、没有已创建库身份，无法按承诺记录/恢复该临时库。

这与前一轮“新库 connect 失败”是同一资源边界的另一处真实 await 失败，不要求扩展新业务。新增 `test_oid_lookup_error_does_not_mask_partial_creation_identity` 已复现。

要求：在可能抛错的 await 前初始化局部状态，所有 CREATE 后故障都保留已知库名/run/OID/创建阶段；未知 OID 明确 unknown，不掩盖原始异常，不误称 ownership 已验证。保留原有 marker/实际 OID 的严格清理拒绝规则。

## F2 [P2] 部分失败分支绕开统一终态，成功清理后报告仍是不完整初始快照

位置 compat_runtime.py:1229–1268（run partial 分支）。

该分支先 `_write_failure('acquire-partial', ...)`，然后才把 scratch/recovery_record 加入 report；若 cleanup 成功，虽然内存加入了 cleanup 结果，却没有再次写报告就抛错。实际落盘仍是早期快照，没有库身份、恢复记录路径或清理终态。只有 cleanup 拒绝的分支再次写盘。

同一 partial 分支在通用 finally 前直接 raise，没有 `capture_production_identity(...,'after')`，也没记录后置采集失败，绕过前面已约定的开始/结束身份合同。

新增 owning-entry 用例分别复现终态缺失和 post-guard 未执行；正例证明 partial cleanup 拒绝时仍能落盘。补正应把 partial acquisition 作为同一工作阶段的失败状态，复用统一后置采集/安全回收/失败报告出口，不再增加一个平行终结分支。

本轮不要求在 marker/OID 不完整时强制 DROP。严格所有权检查目前不会允许缺 marker/OID 的自动清理，这是安全拒绝；保留它，清楚记录 retained、known/unknown identity 及后续可验证恢复方法。手动处置与正式 cleanup 成功必须分别陈述。执行 agent r4 报告已说明部分样例由人工回收，不能据此宣称自动恢复已成功。

## 验证和交付

- 提交基线 **216 passed** 复现；新增 `tests/test_phase3_compat_review_r5.py` 4项：**3失败 / 1通过**；全套 **217 passed / 3 failed**。旧断言未改，新失败用例保留，不删除/xfail。
- 新用例仅假连接/阶段故障注入，不执行真实 CREATE/DROP，不读模型服务。输出 acceptance-tests.txt / all-tests.txt。
- 正常正式 CLI 的完整实际证据和退出0日志保留在 formal-cli/；该成功不能替代上述故障路径验收。
- Ruff、format（211 files）、OpenSpec strict、diff通过；提交SHA、公开文件凭据扫描、正常运行身份对照见 review-manifest.json。私有恢复记录不纳入公开报告正文。

5.1 恢复未勾选。下一位 agent 只按 `handoff-phase-3-fixes-r4.md` 修 F1–F2，再提交同一检查点；保持正常 CLI、已修前轮断言及冻结 gold/source/catalog/search 不变。
