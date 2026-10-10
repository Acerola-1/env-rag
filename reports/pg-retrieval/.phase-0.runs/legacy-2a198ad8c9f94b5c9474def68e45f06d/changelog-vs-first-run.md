# phase-0 报告差异说明（首轮历史副本 vs 补正后报告）

首轮报告保留在 `phase-0-first-run-historical/`（2026-10-04，run 无 run_id、manifest 仅 6 步）。
补正后报告在 `phase-0/`（2026-10-05，run_id=985f1d0f8653417c…，manifest 8 步）。
首轮副本只作历史参照，不再代表当前审计工具的输出。

## G0-1 指纹

- 首轮：`corpus_fingerprint = sha256(sorted doc_id list) + sha256(sorted doc_name list)`，
  只含名称，改内存 content_hash／chunks 后不变（见 gate-0/fingerprint-check.json）。
- 补正后：`source_snapshot_fingerprint`，组件含 PG doc_full 全字段（含 content）、
  doc_chunks 全字段（id／顺序／tokens／content／heading／sidecar）、doc_status、
  解析 blocks／tables 字节 SHA-256、分块参数，另附审计代码逐文件 SHA-256。
  灵敏度由 tests/test_audit_fixtures.py 的 14 项离线 fixture 验证（内容／顺序／引用／table／
  分块参数变化均改变指纹；未改动目录重跑一致）。两次复跑 composite 一致：95f7791fd84171ab…。

## G0-2 动态结论

- block 跨度：首轮写死"14 个 chunk"（water-126）；补正后由全库聚合实时计算，本次实测最大为
  **273**（water-145 WHO-UNICEF，与主 agent 独立核验一致）。
- 序号连续性、processed 行 chunks_count 一致性、meta 全 NULL：首轮为模板写死；补正后在
  `_inventory` 中逐行执行并生成 `consistency_checks`，结论文字按实测值分支。
- 重复定因：首轮写"内容完全相同"；补正后限定为**规范化合并正文**相等（本轮复算：raw merged
  text 与其 SHA-256 不同，规范化 MD5 相等，PDF 字节未比较），由 `_duplicate_pair_evidence`
  生成，fixture 覆盖两种分支。
- doc_full.content 与本地正文关系：新增实测记录——去除 `{{LRdoc}}` 前缀后 221/221 逐字符相等；
  Phase 1 比较原文必须先做该转换。
- compatibility.md：首轮是 JSON 包装的固定模板（inspect／三库声明未在生成时执行）；补正后为
  真 Markdown，每次运行实际执行接口存在性／docstring／源码扫描探针并附原始记录；三库 workspace
  现场取值标注为首轮历史观察，不再声称本次刚核实。
- run-manifest：补 run_id、全部 8 个交付步骤、失败阶段（status=failed_at:<step>）与审计代码指纹；
  报告改为 staging 目录采集、全部成功后一次性提交，失败不会把旧 manifest 与新文件混用。

## G0-3 目标身份

- 首轮 file-enum-002/003/004/005、syn-007 的 target_docs 为 `air-15…19`、`待枚举` 等省略说明；
  补正后全部展开为真实 workspace／doc_id／完整 doc_name（集合题另附匹配谓词与当前全部候选 ID）。
- 白名单校验从"仅 doc_full 存在"升级为"parsed 产物存在 **且** chunks 可读"；不满足的题移入
  `displaced_unresolved_targets` 并使 meets_minimum=false（fixture 验证）。当前 35 题全部通过、
  0 displaced；gold 全部保持 unreviewed。

## 计数与既有事实（未变化）

doc_full=221、chunks=5709、processed=221、failed=58（57 重复文件名＋1 重复内容，原始文档全部
processed）、引用覆盖 211 全／10 部分／1 无 chunk、哈希合同 221/221 匹配——与首轮及主 agent
独立核验一致；数据库全程只读。
