# 5.1 第三轮补正：E1–E3

主 agent 复审仍未通过。**只修 E1–E3，再停5.1检查点；不进入5.2–5.6/Gate3。** Gate2保持通过。详细复现为 phase-3-review-r3/review.md 与 tests/test_phase3_compat_review_r4.py（8项，6失败/2通过）。

1. **E1**：核验和 DROP 使用同一实际 admin 连接；DROP前确认记录/current OID、会话。不得校验后关连接再新建一条无检查的 DROP 连接。新的第三连接身份变化反例必须拒绝且0 DROP/terminate。
2. **E2**：统一资源回收覆盖部分 acquire、恢复记录写入、实例 initialize/ainsert、cleanup-only 失败。CREATE后连接新库失败保留可验证部分归属；恢复记录写入失败不跳过cleanup；构造实例即登记；cleanup拒绝也单独写失败证据并保留可用恢复信息。不得吞掉失败或清理外来对象。恢复文件从创建时即0600，并避免公开提交/打包。恢复进程环境；正式探针在独立进程。四项反例均在 owning entry 验证。
3. **E3**：强制 repeated_initialize_same_pool=True；缺失/False是失败，不允许finished_at。区分报告中的采集事实与实际合同检查，检查声称必验的字段不要仅写成功字符串。

保留原208项及新增8项测试和断言，修复6失败，2正例继续通过；不要改弱/删减/xfail。完成Ruff/OpenSpec strict/diff检查。E1/E2安全缺口修好后由最终正式CLI完成一轮真实自有隔离库成功与拒绝路径复跑，从最终代码生成新报告/JSON/manifest；记录创建/恢复/cleanup-only拒绝等边界及实际归属，不能以独立审查JSON代替。

正式库/原.env只读，原Qdrant/Neo4j不初始化；不装扩展、不升级依赖、不迁移原库、目录或索引。gold与既定源/目录/搜索冻结值沿用handoff-phase-3.md。修复后提交主agent复审，5.1是否通过仍由复审决定。
