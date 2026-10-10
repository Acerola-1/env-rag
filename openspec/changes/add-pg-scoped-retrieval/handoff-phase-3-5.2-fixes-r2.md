# 5.2 第二轮补正：只修 M1–M3

当前5.2未通过；见phase-3-local-review-r2/review.md。原L1/L2主要问题已修，原238项与首轮十项继续通过；本轮8项7失败/1通过（全套239 passed/7 failed）。**只修原L3/L4/L5剩余合同，不进入5.3–5.6/Gate3。** 5.1/Gate2、原gold及源/目录/索引不变，不升级依赖，不改原库。

1. **M1 统一身份与失败终态**：post不能只调用matches_frozen，必须比较实际before/after，尤其env字节SHA；漂移/采集失败非零。post与资源清理后统一落盘终态再raise，fetch失败的identity_after/identity_after_error、原错误、已完成结果与失败服务记录不能丢。无finished_at，不覆盖原失败。本地未知query_id/gold/config先验证，再做必要只读身份采集。
2. **M2 真实服务证据/正确降级/独立请求**：每次fetch新的账本，复用adapter不混账。在底层Qdrant query_points/retrieve与模型/PG/图读取边界记录实际尝试、成功、失败、耗时、去凭据输入/结果摘要（embedding只需模型/输入或指纹/输出shape与摘要，不必保存巨大向量）。组级helper统计单列，不伪装底层调用；CLI/flat/by_service同源。发布Qdrant与VECTOR helper会吞异常，必须在吞异常前留状态；缺向量/读取超时降级并标WEIGHT/truncation，不标vector-similarity。保留各选择阶段原因，PG verified不能抵消排序/服务失败。移除assembly为来源追踪重复执行的VECTOR选择，来源从真实source_id/src_tgt追踪，生产选择优先release函数；保留最终预算与所有来源。
3. **M3 部分构造回收**：binding内原生client创建即建立资源边界，storage构造、元数据解析、锁绑定任一失败都close；成功才转移fetch所有权。生产清理只close，不调用会flush的原生finalize；非空待写队列也拒绝flush并close，不continue漏连接。单项失败不跳过其它回收/报告。

先用 `tests/test_local_adapter_review_r2.py` 复现七个失败，再修正式入口。原10项文件SHA与断言保持，全部旧断言不删除/不xfail/不弱化；新增必要的M1失败+post错误、M3中途失败测试。测试替身应在原生客户端或服务边界注入，不能绕过本轮要验证的真实分支。

本轮root未重复真实模型请求。补正后先通过安全/失败用例，再用同一冻结小样本最小真实验证（0答案生成、hashing_kv=None、cache不读写）。逐候选PG身份回读，实际服务计数与去凭据结果证据、正确排序来源、资源关闭及前后身份核对都进统一报告；保留原提交作为历史。必要调用一次即可，不做整轮质量评测，不为了修日志重建索引。Ruff/OpenSpec strict/diff/凭据扫描后仅5.2提交复审。

冻结合同沿用此前handoff：source95f7791f…，catalog c15c741742394320/4919b3938ad93747，search872d689343a9cbb6，审核gold SHA1bf130077c21583a89c5ca14695694d9552c558a7d8dc5d45ff0d9f72cfd7a5e；显式映射PG default↔vector '_'↔graph base。
