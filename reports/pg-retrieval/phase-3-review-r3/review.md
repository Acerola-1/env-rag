# Phase 3 / 5.1 第三轮主 agent 复审

日期：2026-10-06。**5.1 仍未通过；只补正 E1–E3，5.2–5.6 / Gate 3 不进入。Gate 2 保持通过。**

本轮提交实际在 `reports/pg-retrieval/phase-3-r3/`，该目录与前两轮报告区分；没有把历史 phase-3/ 的 rev2 证据当作当前交付。当前源码与 r3 报告、probes、gold、r3 测试共五项 manifest SHA 全部匹配。

审查全文 compat_runtime.py、r3 交付物以及 r2/r3 验收测试。沿用 open-code-review-delegate，OCR 仅提供本地预览和规则，无外部审查模型调用。范围清单及前期文件跳过理由见 coverage.json。未修改应用实现、旧断言或提交证据；新增审查用例、报告与交接，更新任务状态。

## 已确认的修正

- marker.secret / marker.db_oid / current OID 的三重检查已实现；按库名批量终止会话已删除。D1 前两个连接的拒绝行为确实修复。
- pre 校验冻结 catalog run、post 与 pre 比较 env/source/目录/搜索/gold 等字段已实现；后置采集异常仍执行 cleanup 并留 guard_failure，该正例本轮继续通过。
- PGVector 已提供完整配置并到达实际 codec 兼容失败；同 workspace 的 doc-a/doc-b、公开 chunk→物理行对应已补。节点往返与后端 FAIL 归因门控已加入。
- 私有恢复记录生成/读取机制已可用；工作阶段和后置采集异常的处理已有实质改进。
- 原 **208/208 测试通过**；r2 原八项用例的关键拒绝/清理/报告断言保持，stub/假连接修改适配新路径，没有发现删除或 xfail。

仍有以下正式入口边界未处理，不能用上述正常/部分异常路径通过代替。

## E1 [P1] 最后执行 DROP 的连接仍未核验当前库身份

位置：compat_runtime.py:397–408（cleanup_scratch）。

`_recheck_oid_and_sessions` 开独立 admin 连接核验后就关闭；cleanup_scratch 又新建第三条连接直接 DROP。数据库身份在第二条连接关闭后变化，最后一条连接完全不会读取当前 OID/会话。反例：verify=42、recheck=42、actual DROP 连接所见 OID=999；当前代码执行 DROP，未抛 ProbeAborted。

这不是要求杜绝一切服务器并发，而是此前要求的“任何破坏语句前从实际执行连接确认”仍未落到执行 DROP 的连接上。请在同一实际执行连接内、DROP 前核验 recorded/current OID 和剩余会话，不再核验后关闭连接再另开 DROP。任何不符不得有 DROP/terminate，仍只处理已证明归属的库。

## E2 [P1] 资源边界未完全包围创建、恢复记录和初始化

位置：compat_runtime.py:254–296、902–916、1130–1147、1185–1204。

四个入口反例均复现：

1. `_acquire_scratch` CREATE DATABASE 成功后，连接新库失败：函数丢失库名/OID等部分创建身份，run 只有 acquire-error 文本，既无清理也无可恢复库身份。请求处理“acquire 中途失败”尚未落实。
2. acquire 成功后 `write_recovery_record` 抛 OSError：它位于资源 finally 之外，run 直接退出，无 cleanup/失败报告。恢复文件写入失败恰是需要回收已创建库的路径，不能以尚无恢复记录为由跳过。
3. workspace 的 LightRAG 对象在 initialize/ainsert 成功后才放入 rags。initialize 中途抛错时，该已构造且可能持资源的对象不在 finally 集合中，finalize 未调用。新增假实例反例证明该调用路径漏回收。
4. 后置身份正常、工作阶段正常，但 cleanup 因外来会话拒绝：report 内存写了 cleanup.dropped=False，随后抛错，任何失败报告都没写盘（写报告分支只有 guard/stage_error）。记录“cleanup_error 不吞掉”与交付失败证据是两件事。

要求：从第一次创建开始保存可核验的部分归属和阶段，并纳入统一回收；恢复记录写入放在已有资源 finally 内；构造实例后、initialize 前登记；所有 cleanup-only 错误也独立持久化失败结果。不能清理的对象保留可验证恢复身份与拒绝理由，不能操作外来对象。文件系统本身不能写时可报告明确的写入失败，但仍要尝试安全回收，不允许先前写失败跳过回收。

恢复记录应按私有文件处理：在创建时即设 0600（当前先 write 后 chmod），放在不会误提交/公开打包的位置或明确忽略；本次审查不把其 secret 内容带入报告。进程环境恢复仍遵循前轮交接，正式 CLI 用独立进程。

## E3 [P2] 重复 initialize 结果为 False 仍被成功合同接受

位置：compat_runtime.py:777–819（_enforce_probe_contract）。

probe 已记录 `repeated_initialize_same_pool`，但合同不检查它；将真实生产者返回结果设为 False，正式 run 仍写 finished_at、成功返回。当前报告/汇报声称“同池”为强制成功合同的一部分，实际只是观察字段。

要求：该字段必须明确 True，缺失/False 进入 contract failure，cleanup 和失败报告仍执行。同样核实声称“必验”的生命周期/缓存等字段是否实际被检验，报告区分采集事实与强制验收条件，避免成功 note 掩盖错误值。修复后保持明确允许的 AGE/PGVector 缺扩展失败，不把环境不兼容当整体意外失败。

## 复跑与结果

- 新增 `tests/test_phase3_compat_review_r4.py` 共8项：**6失败 / 2通过**；完整结果 **210 passed / 6 failed**。两项正例证明已修复的后置采集错误处理与内容源 pre-guard 仍有效。旧测试未改，新失败断言不删除/xfail。
- 新失败走 run / cleanup_scratch / probe_workspace_identity 正式路径，使用假连接/故障注入，无真实 DROP 外来库、无会话终止、无模型请求。具体输出 acceptance-tests.txt / all-tests.txt。
- 主 agent 独立安全入口再次在随机且有 OID/所有权标记的自有库完成运行，复验 wheel RECORD、池、workspace ID、图/vector/AGE 行为；正式 PG 只读。证据 independent-runtime.json：正式八表计数、source/catalog/search 前后未变、`.env` 字节 SHA 未变，自有库 ownership_verified 后已清理；0 实际 LLM/embedding 调用。
- 鉴于 E1 和 E2 仍存在，未执行提交正式 CLI 的真实 destructive cleanup。独立入口结果只验证环境和接口，不冒充当前提交清理路径通过。
- Ruff、format、OpenSpec strict、diff及凭据扫描见 review-manifest.json/check文件。

下一位 agent 仅处理 `openspec/changes/add-pg-scoped-retrieval/handoff-phase-3-fixes-r3.md`，完成后提交同一 5.1 检查点。保留 r3 原始代次、固定金标和 Phase0–2 通过状态。
