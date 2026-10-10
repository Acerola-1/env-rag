# 5.2 第三轮补正：原 M1–M3 的五个具体反例

5.2仍未通过，见phase-3-local-review-r3/review.md。原246项和前两轮18项独立用例继续通过；本轮6项5失败/1通过（全套247 passed/5 failed）。**仅补N1–N3，不进入5.3–5.6/Gate3，不升级、不重建、不改gold或原库。** 5.1/Gate2保持。

1. **N1（M2，两项）**：Neo4j包装必须await真实session.run完成后再记success/耗时，async异常记failure再抛；当前记录的只是协程创建成功。chunk选取的vector支持只看该阶段/该chunks集合的实际向量覆盖，entities query_points非空不能掩盖空/不足chunk vectors；按阶段记录选择原因、集合/请求身份、预期与实际向量覆盖。保留正确WEIGHT/truncation/empty/error降级，不用PG verified抵消。
2. **N2（M1，一项）**：正式run_frozen的失败终态要序列化失败adapter的真实records和group_records，并绑定失败query_id；当前只有错误字符串、已完成results和post，没有失败的llm/failure凭证。保持统一writer、原错误、post/cleanup状态、无finished_at。无服务调用的前置拒绝明确零调用，不伪造日志。
3. **N3（M3，两项）**：Neo4j storage构造失败时可避免先获取driver；一旦已获取，回收必须被await纳入所有权边界，不能create_task后直接raise。生产原生client/driver.close失败绝不触发会flush的storage.finalize；分支判定应是拥有原生handle，而非close成功与否。错误继续可见且不跳过其它清理/post/终态。

先跑 `tests/test_local_adapter_review_r3.py` 复现五个失败，修正式代码；原r1/r2文件及断言保持，无删除/xfail/弱化。失败测试使用实际发布读取方法与假原生传输，别只把同步fixture改成“成功”。建议一次自查：异步成功/失败；实体命中+空或不足chunk向量；首请求失败+第二请求成功的独立账本；失败LLM凭证持久化；close失败不finalize；部分driver获取回收或构造前不获取。

先完成上述安全/失败用例，再做同一冻结小样本必要真实验证（原默认四题即可，不调用答案模型、hashing_kv=None）。root本轮没有重复真实embedding/LLM。保存实际服务凭证、阶段排序来源、逐候选PG回读、资源回收和source/catalog/search/gold/env前后核对。Ruff/OpenSpec strict/diff/凭据扫描后提交5.2复审；保留历史交付，不为刷新报告重复多轮模型请求。

冻结身份及映射沿用r2交接：source95f7791f…；catalog c15c741742394320/4919b3938ad93747；search872d689343a9cbb6；gold1bf130077c21583a89c5ca14695694d9552c558a7d8dc5d45ff0d9f72cfd7a5e；PG default↔vector '_'↔graph base。
