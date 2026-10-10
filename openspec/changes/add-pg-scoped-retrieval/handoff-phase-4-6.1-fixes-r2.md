# 6.1 rev-1复审补正：R1–R4（2026-10-08）

6.1未通过，Gate3保持，6.2不启动。原420项与冻结r1 20项全过且冻结SHA未改；新增冻结 `tests/test_evaluation_review_r2.py` 共12项，9失败/3正例。仅读文件/假I/O，Reviewer0真实请求/写库。

按 `phase-4-6.1-review-r2/review.md` 与comments.json仅补R1生产async-with图session/CLI自有PG连接预算，R2预留≠实际发出及发布helper吞预算异常后的明示partial，R3完整CLI配置锚/预算类型与post AdapterError终态，R4local全部原始来源与选择顺序。现有Candidate全文、真正融合精排、反例题型/微预算、唯一目录、净化、原漂移和选择矩阵通过结论保持。

## 必须覆盖的生产形态

- 测真实 `async with driver.session()` 的进入后session和原来的直接session.run，两条路径各只有一个预算/issued记录；额度刚好正例不要拒绝。
- 不传conn（CLI实际形式）时answer/fusion/rerank/SourceAdapter自行连接的I/O仍可受控；禁止为测试必须传conn而生产静默放行。保留只读事务/timeout/借用与自有close语义。声明guard/事务控制语句如何计量，与实际代码一致，预算前置控制不能漏真实数据SQL。
- 区分reservations、实际issued、服务成功/失败。模型因缺条件/预算在HTTP前skip计0 issued，实际执行失败仍计1。阶段前后读取本题refusal增量，即使发布库catch Exception回退也不能消失；不得给该题继续无标记complete。更新由真实边界编译的上限。
- CLI实际走完整有效Phase4锚，缺失/损坏/模型或代码或提示/参数不符零服务/后端拒绝；dry-run仍0后台可用。None/负值/bool/非整数cap及未知服务明确拒绝；不把None当无限quota。合法0额度正常表示禁止发出。
- 所有post采集普通异常都写终态；来源/配置拒绝是运行级，不继续消费其它题配额。保留原错误、后置错误、已完成结果、当下账本，失败无finished_at，CLI非零。
- 保留Candidate实际reached_via、similarity_order、source_type、sorting_sources；缺分数用原选择序口径，不把weight-fallback标为vector-similarity。fixture/真实只读构造预算分类据实际资源，不能靠标签制造隔离证据。

只改新增评测与必要兼容接缝/CLI、自己的tests和工件；不改.env/gold/冻结r1/r2/既有四轮answer/历史，不发实弹或健康探测，不写库/重建。补齐生产连接与上下文的必要正负例，不用整个理想PATH_RUNNER替代被测接缝。所有冻结断言保持；现有false-starvation正例也保持。

更新当前SHA/配置代次说明、必要测试、Ruff/strict/diff/敏感值扫描；不为了通过提高未授权额度或改掉困难题。修复后停6.1检查点，网络预算/关键词变更仍等待用户安排。
