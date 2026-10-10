# Phase 3 / 5.1 第二轮补正交接

5.1 第二轮仍未通过；**只修 D1–D4，再提交同一检查点，5.2–5.6/Gate3不进入。** Gate2继续通过。详见 `reports/pg-retrieval/phase-3-review-r2/review.md` 与对应失败用例。原 C1–C5 交接边界继续适用。

1. **D1 正式清理入口**：检查 marker.db_oid==record.oid==current_oid；在任何会话终止/删除前核验。不要按库名批量终止；实例已经 finalize 后存在未知会话则拒绝。共用 application_name 不是本 run 身份，旧 helper 的测试不代表 cleanup_scratch 已安全。
2. **D2 身份守卫**：pre 核对冻结 catalog run，post 与 pre 比较完整身份尤其 env_sha/run_id。错误前置不得 acquire；错误后置写 guard_failure 并非零退出。保留 doc count/内容/source/snapshot/search/gold 拒绝语义。
3. **D3 失败回收与报告**：后置 capture 抛错也独立执行安全 cleanup、环境恢复及失败报告写入。工作阶段失败同样留证，不能仅正常路径写出。提供 `--cleanup-run-record` 真正可读的恢复记录/机制，私有权限记录所有权材料；测试实际生成→读取恢复入口。登记初始化尚未完成的实例并在 finally 释放，不吞掉清理失败。
4. **D4 探针合同和缺项**：必验后端 FAIL 不允许总体 success；PGVector 提供完整最小配置，实际走到扩展兼容失败才算此探针。补同 workspace 不同版本文件、完整公开 chunk_id↔数据库文档/内容映射、同实例重复 initialize；允许的兼容失败分类型确认。报告只列本轮真实采集的事实/测试，取消不存在的 doc-b 和外来会话测试声称。

保留原181测试及本轮8项断言；本轮2正例必须继续通过，6失败须修好，不改为xfail或删减。另补 source变化但计数不变、后置search/目录切换、initialize/ainsert 中途异常、失败阶段报告、真实恢复入口及外来会话拒绝用例，走 owning entry。

D1/D3安全缺口修复后才运行修复后的正式 CLI 完整隔离探针（fixture即可，无实际模型服务），从最终代码产生新 manifest/新代次证据。正式库/原.env只读核对，原Qdrant/Neo4j不初始化；不升级依赖、不迁移正式库。全套、Ruff、OpenSpec strict、diff通过后提交，仍停5.1待主agent。

冻结源/目录/搜索/gold沿用 handoff-phase-3.md；主agent本轮独立运行 current，未更改。原失败报告和JSON保留为历史，不拿独立审查JSON代替修复后正式入口运行证据。
