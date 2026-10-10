# 5.2 当前仅补 V1：有效向量覆盖，不是返回point数量

当前5.2仍未通过；见phase-3-local-review-r4/review.md。N1异步/N2/N3已修；原252项与前3轮24项独立用例全过。新增3种向量覆盖用例2失败/1通过（全套253 passed/2 failed）。**只修这一处，不重做其它修复，不进入5.3–5.6/Gate3。**

正式fetch仍以原生retrieve的items数量判断vectors_returned。实际发布get_vectors_by_ids会丢弃无vector的point，并按原始chunk身份返回映射；VECTOR helper只能使用请求chunk对应的向量。测试已复现：point.vector=None，或point有向量但payload原始ID不是请求chunk，两者返回条目数量都完整，却实际WEIGHT回退且适配器误标vector-similarity。

修复要求：在读取/选择边界观察发布存储交给选取器的有效向量映射，逐阶段对照请求chunk身份和可用向量；缺失/不匹配不计入有效覆盖。记录requested、有效returned、missing/mismatched摘要和阶段/集合，原始point数量另列。覆盖不完整必须weight-fallback+degraded，不能用PG verified抵消；正常有效向量正例保持。别只重命名items为vectors，也别修改发布包或重建数据。

先跑tests/test_local_adapter_review_r4.py三个场景，再修正式入口；原r1/r2/r3断言与文件保持，无删除/xfail/弱化。修复后完整测试、Ruff/OpenSpec strict/diff/凭据扫描通过。只需一题必要真实运行（优先fact-002，实体+关系选取），保存按实际映射的向量覆盖证据、PG逐候选回读及source/catalog/search/gold/env前后守卫，0答案LLM、hashing_kv=None。其它既有样本无相关改动可沿用本轮证据，不要求四题重复整轮；不升级依赖，不改gold/原库或重建。

交付新代码/SHA、该题最小请求/响应摘要、真实服务计数/覆盖/只读守卫与回收证据，再停5.2复审。此前handoff冻结身份及PG default↔vector '_'↔graph base映射不变。
