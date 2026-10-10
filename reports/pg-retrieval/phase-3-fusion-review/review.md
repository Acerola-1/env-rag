# 5.3 首轮验收：未通过

2026-10-07。只验收候选融合，不进入联合精排/生成/Gate3。5.1、5.2、Gate2结论保持。5.3保持未勾选，仅补正下面四组；既有提交与真实三题证据保留。

## 已确认的部分

- 原提交266项测试全过；提交manifest七项SHA全部匹配，5.2适配器SHA保持 `0bbad9764856250085b5cefb90c9d56933bfd2f6e9ed5ed796fdd93bdf2da7e3`。
- 显式空discovery不回填、组合身份合并、跨workspace拒绝、原始分数不相加、不同版本独立保留、缺失版本跳过local、常规local超时降级、PG stale拒绝、逐阶段覆盖降级，既有入口测试通过。
- 主agent独立只读回读提交fact-002/syn-001全部19条usable：完整content、full_doc_id、content SHA **19/19相等**。实际source/catalog/search/gold/env前后匹配冻结、无drift，cache=16514；0模型调用、0写入/初始化/重建。详见read-only-probes.json。
- 不把以上发现行为作为质量指标或Gate3通过证据。

## 必须补正的四组

### F1 显式修改单归属被丢出允许集合

`fusion.py:90–103、278–283、286–300`仅从code_exact建立允许文档集合；PG已合法确认的doc_attribution被保存为typed目标，但其local chunk仍被标为“非已解析目标”。这是既有“含修改单/相关文件”路由的回退，不是要求宽泛放行正文引用。

入口反例test_explicit_related_route_allows_proven_amendment_without_self_code失败。真实只读请求“GB 18466-2005 含修改单的相关文件有哪些？”PG返回2份已证实归属文档，两份都不在当前fusion允许集合、均被拒绝。修复必须保留自身编号请求的严格集合与缺失版本规则，不伪造修改单self_code；保存归属依据与快照。

### F2 chunk路径缺少物理表片身份与引用

`fusion.py:151–177`把每个table_unit转成PG chunk路径时移除了unit_id/table_id及原citation。实际fact-002同一chunk的两条table_range_binding路径因此成为完全相同的字典，无法在路径本身判定来自哪个物理片。typed_targets另存片ID不能代替每条路径的来源绑定。

入口反例test_each_table_path_keeps_physical_unit_and_locator失败，两个片ID被降为{None}。保留每条原始定位身份和citation，存在locator时保留原值，不要求上游本来没有的locator；同时保留typed目标的快照、scope_status与已有membership_basis，不编造新的定位。

### F3 统一失败终态仍有两个缺口

`fusion.py:529`的failed_receipts从未接到正在执行的_fuse_one。local完成后PG正文回读失败，当前题out尚未返回，外层results为空，终态便错误记录零local凭证。test_readback_failure_retains_completed_local_service_receipts失败：实际已记录的keyword LLM success丢失。应在工作窗口持续保存当前题账本/部分结果，而不只收集成功返回或此前题目；当前题错误不能拿前一题凭证替代。

`fusion.py:486–504`的gold解析/校验不在失败写入边界。真实verify_gold_guard拒绝时无fusion-runtime-latest.json。test_gold_rejection_writes_failure_terminal_without_backend_calls失败。前置失败应明确零调用、原错误、无finished_at；已启动工作后的失败保留后置身份与真实凭证。

### F4 配置拒绝晚于后端读取

`fusion.py:507、534`先capture生产身份，再verify_config_guard。显式QDRANT_WORKSPACE覆盖已应在任何后端接触前拒绝，但入口反例test_config_rejection_happens_before_backend_identity_reads记录到了前后两次backend capture。把本地配置/每个请求workspace校验放到首次后端读取之前，拒绝时仍写可审计零调用失败终态；不修改正式.env。

## 测试与复跑范围

独立tests/test_fusion_review_r1.py共6项：**5失败/1正例通过**，全部经run_fusion入口，不调用真实后端。原tests/test_fusion.py及其余既有断言未修改。加入独立断言后的全套结果为**267 passed / 5 failed**，失败全部对应以上五个验收反例；Ruff/format、OpenSpec strict、diff检查通过，证据扫描0凭据泄漏。构造器只作纯赋值，不将人为注入的构造抛错列为生产阻断项。

下一轮仅修F1–F4并停5.3，交接见handoff-phase-3-5.3-fixes.md。失败报告/配置分支用入口隔离测试即可；路径修复用PG-only fact-002，归属修复用只读现有目录与入口反例。无需重复三题语义整轮或5.2模型请求，不改gold/依赖/目录/索引，不进入5.4–5.6。
