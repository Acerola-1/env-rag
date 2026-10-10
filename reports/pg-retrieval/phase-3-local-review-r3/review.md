# 5.2 第三轮独立验收：未通过，仅补正 N1–N3

日期：2026-10-07。范围仍是原M1–M3，不推进融合、精排或质量评测。**5.2仍未通过；5.1/Gate2保持通过，5.3–5.6/Gate3未进入。**

## 验证结果与已经修复的部分

- 提交五项SHA匹配；前两轮独立验收文件SHA保持、18项全过，原246项完整通过。新增6项5失败/1通过，全套247 passed/5 failed。见acceptance-tests.txt/all-tests.txt。本轮不改应用实现或旧断言。
- M1的完整env前后漂移拒绝、post结果写入失败终态已修；M2的请求独立账本、Qdrant调用边界、helper分组、删除重复VECTOR选择已修；M3的Qdrant构造失败回收和正常close路径已修。下面只列剩余实际反例。
- 原生客户端只读现场核对八表221/5709/279/16514/65527/221/221/119575、内容source、catalog run/snapshot、search、gold/env前后无漂移，冻结匹配。Qdrant5709/65526/119574点/2560d与Neo4j base66069节点/121819关系符合提交。见live-inventory.json。
- Ruff/format、OpenSpec strict、diff通过。所有新反例均使用假传输、实际发布包读取方法或正式run_frozen/fetch入口；0实际模型请求、0生产初始化/写库、0重建。未重复真实模型子集，提交40候选仍是执行agent观测，root未重新生成。
- OCR只做本地预览/规则解析；coverage.json逐文件标明本轮范围和历史阶段跳过原因。

提交运行的embedding实际为2/3/2/2次（fact-002因关系选取多一次），合计9；报告“每查询2次”需据日志修正。这是统计表述补正，不要求增加模型请求，也不单列验收门槛。

## N1 / P1：M2异步记录与选择阶段的判定仍不正确（2个失败）

位置：`local_adapter.py:219–248`（Neo4j包装）与`927–953`（排序来源）。

**异步图查询**：_wrap_run同步调用session.run取得协程对象，立刻写success与耗时，再把协程交给发布包await。实际网络执行和异常发生在之后，包装层看不到。用真实发布Neo4JStorage.get_nodes_batch与异步假driver复现：await期间TimeoutError，by_service却只有success，没有failure。成功正例仍通过。修复必须await真实session.run完成后再记success，异常在同一边界记failure后重抛；耗时应包含执行等待。

**实体命中掩盖chunk向量缺失**：qdrant_with_data对本次所有Qdrant成功记录做any；entities集合query_points有结果，也被当作chunks向量读取成功。用实际Qdrant读取方法、实体检索非空、chunks retrieve空集合复现：发布包走WEIGHT，PG候选可验证，但输出vector-similarity且没有该缺口的degraded。上一轮空向量测试没有非空实体查询结果，这正是本轮补齐的生产前置条件。

修复按具体选择阶段和集合核验向量支持：entities查询不能替chunks选取背书；只拿到部分引用向量也不能视作完整VECTOR成功。保留阶段/请求身份与预期、实际向量覆盖情况，WEIGHT/truncation/empty/error分别记录，不以任意成功请求或PG verified代替正确排序来源。不要求改算法、评测质量或重建向量。

## N2 / P2：M1失败请求服务凭证仍未进入统一终态（1个失败）

位置：`local_adapter.py:1420–1425`、1453–1456。

run_frozen捕获fetch异常时只保留错误字符串和此前completed results，没有序列化失败adapter的boundary.records/group_records。通过正式入口注入keyword服务TimeoutError，ServiceBoundary已记录llm/failure，最终报告也有identity_after，但整个终态找不到这条失败服务记录。提交报告声称“失败时服务记录保留”不成立。

修复在异常终态保存失败query_id、其实际调用/分组凭证和原始错误，保留已完成results及post/cleanup状态；所有异常仍由统一终态写盘，无finished_at。前置校验失败没有服务账本时应明确零调用，不能伪造。原有post/漂移断言不改。

## N3 / P1：M3部分图绑定未等待回收，close失败又进入flush入口（2个失败）

位置：`local_adapter.py:690–711`与1120–1126。

**部分Neo4j绑定**：driver创建后storage构造失败，异常分支create_task(driver.close())后直接raise；fetch的resources还没有这个driver。正式fetch反例确认：返回失败终态时已获取driver尚未关闭，asyncio.run结束还可能取消未完成任务。可先完成可能失败的storage构造再获取driver，避免无谓获取；已经获取的资源则必须纳入可await的回收边界，不能以fire-and-forget当完成清理。新断言允许构造失败时完全不获取driver。

**close失败的生产finalize回退**：closed_handle只在close成功后置True；原生Qdrant client.close抛错时仍进入resource.finalize。该真实发布finalize包含flush。正式fetch反例用实际发布类+close失败假客户端，将finalize替换为禁止调用探针，观察到两次原生finalize调用。没有实际写生产数据，但生产flush接入仍被重新打开，违反close-only；待写队列的拒绝信息也不能保证该回退不flush。

修复按“是否拥有原生handle”区分生产和非原生资源，而不是按“close是否成功”；任何原生close失败只记录/报告，继续其它回收，绝不回退有flush能力的finalize。未知待写队列继续拒绝flush并close，错误不跳过其它资源/post/终态。

## 下一步

仅按`handoff-phase-3-5.2-fixes-r3.md`一次补齐五个具体反例，保留全部旧断言。修复通过后才做必要的小样本真实运行；没有新修改或失败依据，不扩大测试/重做已验收阶段。neg-001宽泛发现相关版本仍允许，missing答案期望保持，质量结论留Gate3。
