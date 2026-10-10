# Phase 3 / 5.1 首轮补正交接

主 agent 2026-10-06 独立验收：**5.1 未通过，只补正此项；5.2–5.6 / Gate 3 不进入。** Gate 2、冻结 gold、来源目录和搜索索引保持。完整依据为 `reports/pg-retrieval/phase-3-review/review.md`；独立探针 JSON / 可复跑代码同目录，已完成后清理自有临时库。不要运行当前提交的无所有权 `--cleanup`；旧固定库不是主 agent 本轮创建，未清理。

## C1–C5 必须落实到实际入口

1. **C1 所有权与隔离**：唯一临时库/目录，验证 run/库名/OID/所有权标记；外来同名库不得复用、迁移或清理；外来活动会话拒绝，不盲目终止。运行用独立进程与测试 DSN，校验 ClientManager 实際连接目标，finally finalize 所有实例与池、恢复环境。三项安全验收文件前两项必须通过。
2. **C2 workspace 和 ID 合同**：去掉 POSTGRES_WORKSPACE 误覆盖，断言两 workspace 实际生效及 processed；相同文件名、不同内容、相同 chunk ID 的公开查询各自正确，组合键不混源。增加同 workspace 不同版本文件并列保存；缺失 chunk 从公开读入口返回明确不存在。记录实际行/状态/请求结果，不能只写成功 note。
3. **C3 后端矩阵**：实装发布包原生 PGTableGraphStorage 需纳入独立库测试（不初始化正式图）；PGGraphStorage 的 AGE 失败 / PGVectorStorage 的 vector 失败不能泛化。CM None/Nano/Qdrant enable_vector=False，LightRAG 默认 Nano；正式类名配置是 PG KV/Status、Qdrant vector、Neo4J graph，PG 两张 graph 表为空。来源未知保持未知，不用表数推断旧管线。修正文档与代码说明，不改正式库、不装扩展、不升级依赖。5.2 真实语义链路仍待验证，不以 fixture 替代。
4. **C4 副作用 / cache 采集**：分别记录持有池引用与全部释放后重建；重复 initialize 的实际行为；正确小写表名下的字段与按阶段 cache_type。插入 extract cache 不等于 query cache。AGE/vector 失败也加入可复跑入口；成功/失败结论必须来自实际采集。
5. **C5 冻结身份前后守卫**：开始/结束只读核对八表计数、源指纹、catalog/search active、gold SHA、`.env` SHA；不符非零退出并保存失败报告，不打印成功。第三项安全验收必须通过，另补开始即 stale、内容变化但计数不变、途中 active 变化等入口反例。

允许使用独立审查脚本作为实现参考，不能直接把主 agent JSON 复制为执行 agent 修复后的运行证据。新提交须由修复后的正式入口完成真实隔离库完整运行（仅 fixture，无正式模型调用），采集成功及拒绝路径，证明正式库前后不变；临时对象清理有归属证据。原报告/JSON 明确保留为首轮历史，新证据单独命名或有完整代次归档，不混代覆盖。

## 复验和交付

保留全部原178项测试和新增3项安全断言；新增真实问题的入口级反例，不仅测试 helper。运行全套、Ruff、OpenSpec strict 和 diff check；交付 compatibility-runtime.md、新 probes/manifest、必要运行日志、所有权及来源守卫拒绝证据。5.1 证据完整后提交待主 agent 复审，5.2–5.6 未勾选。

冻结值沿用 handoff-phase-3.md：source 95f7791fd84171ab727870fc5810d79b4327b0c4fa547d432951e0499a3808f8、catalog 4919b3938ad93747 / run c15c741742394320、search 872d689343a9cbb6；审核 gold SHA 1bf130077c21583a89c5ca14695694d9552c558a7d8dc5d45ff0d9f72cfd7a5e。既有8表冻结值、50验收断言及公开失败题保留。
