# 6.1 rev-1 复审（2026-10-08）

**6.1仍未通过；Gate3保持，6.2与网络评测不启动。** Reviewer真实模型/embedding/rerank/DB请求0、写库0。未改提交实现、.env、gold、原冻结或历史；新增冻结tests/test_evaluation_review_r2.py。

原提交 **420项独立通过（10.91s）**，r1冻结20项字节未变且全过。原评测与冻结合并37项通过；现有自有矩阵实际采集17项，报告按实际计数。新增r2矩阵 **12项：9失败/3正例通过**。真实类/实际上下文/自有连接形式配假I/O，所有反例离线。

## 保持通过

真实Candidate对象及全文SourceAdapter读取、融合调用新精排报告、题型兼容缝与真实neg-004的13项、反例微预算透传到实际reader、每题唯一发现工件、先净化后截断、r1 env/catalog/gold漂移与OSError终态、选择集合编译均保持已通过结论。新增category_overrides/expand_budgets/prose_budget为明确默认兼容接缝，原全套与四轮answer冻结通过。现有阶段源码锚的answer/CLI字节变化归为这些授权接缝；旧历史、gold、.env保持。

## 仅修四组剩余边界

**R1：真实上下文/自建连接预算。** Neo4j生产async-with返回另一session，外层.run补丁未覆盖进入后的对象；上限1仍做2次请求。CLI不传conn，answer会自己建连接，pg=0仍执行SQL。把生产形式及所有自建读取接缝纳入真正请求前预算，保持readonly/timeout/close所有权；不是只给测试传wrapped conn。SourceAdapter全文回读、fusion/rerank的source/guard读取也要明列控制边界，工件中的次数不能冒充已覆盖全PG。合法配额与原包装记录不能被破坏。

**R2：预留、实际发出与库内吞掉拒绝。** reserve把预留直接写issued；没有发HTTP的incomplete_conditions也被计1。以真实调用凭证记issued，已发生失败不得改成0；预留可保守占用额度，但不能充当账单计数。发布VECTOR会吞预算异常；当前账本拒绝被忽略且answer仍complete。每阶段对本题新增拒绝事件作显式partial/预算失败，不依赖异常传播。不追加LLM。真实模型调用计1正例保持。

**R3：CLI完整配置与所有失败终态。** 缺锚仍接触entry，CLI只带来源四字段；还须冻结已批准模型/端点类别/维度/提示/代码/参数预算与env，不能现场覆盖expected。JSON cap=null或负值需零接触前拒绝，类型/服务名单也须校验。post采集AdapterError不写终态，OSError已通过但不能代表所有正常异常；统一落盘结果/实际预算/原错/后错再非零抛出。dry-run无锚仍必须零接触可用。6.1最终批准后建立明确的新Phase4代码锚代次，兼容接缝导致旧answer SHA变化不应偷偷改旧Phase3台账来消除差异。

**R4：local原始出处保真。** 正文和验证状态已正确；Candidate.reached_via/selection order/source type和实际weight-fallback目前全丢失并强标local_vector。保留原候选的全部实际来源和选择口径/顺序，不猜浮点分数，不从摘要伪造证据。完整正文/跨workspace拒绝已通过，不重写这些算法。

另有证据限定：neg-008构造的是微预算；正式来源访问仍是生产只读入口，不能因问题带构造就当已隔离的fixture。正式运行应标“真实只读+构造预算”，pytest假来源才标fixture。neg-002输出workspaces观察须如实呈现，不能将没有观测到外来workspace宣称为独立同ID跨workspace对抗验证；可引用既有隔离测试并明确其来源。此为工件分类要求，不要求新的实弹调用。

结果见independent-tests.txt、submitted-suite.txt；逐行见comments.json。只按handoff-phase-4-6.1-fixes-r2.md闭合R1–R4，不重复修已通过部分，不运行真实服务；提交后停6.1复审。

格式检查发现test_search_phase2.py获准新增的fake参数签名未换行，主agent直接做纯格式化；无断言或逻辑变化，不另立返工项。420项为格式化前同语义提交的独立结果，未重复全套。限定范围Ruff/format、OpenSpec strict、diff、敏感值扫描均通过。
