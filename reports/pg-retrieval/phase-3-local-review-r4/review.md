# 5.2 第四轮独立验收：当前仅剩 V1 向量覆盖判定

日期：2026-10-07。**5.2仍未通过，仅修下述一处；5.1/Gate2保持，5.3–5.6/Gate3不进入。**

提交五项SHA匹配，前3轮24项独立验收文件SHA未变且全部通过，原252项完整通过。N1异步图查询、实体命中与chunks集合隔离；N2失败服务凭证落盘；N3构造前不获取driver、原生close失败不回退finalize，均已确认修复。本轮新增3个向量覆盖用例：2失败/1通过；全套253 passed/2 failed。没有修改应用实现、旧断言或冻结金标。

## V1：返回 point 数不等于请求 chunk 的有效向量覆盖

位置：`src/env_rag_final/local_adapter.py:538–542`（原生retrieve摘要）与954–967（覆盖判定）。当前vectors_returned实际是原生retrieve返回的条目数。真实发布包get_vectors_by_ids则先检查point.vector，并解析/映射原始chunk身份，才能把数据交给选取器；VECTOR helper还按请求chunk身份使用映射。

通过正式fetch、实际发布Qdrant读取/选取函数、假原生传输复现两种情况：

| 返回值 | 发布包实际选择 | 当前适配器 | 验收 |
| --- | --- | --- | --- |
| 请求ID全部返回，但point.vector=None | 无有效向量，WEIGHT | vector_backed=True、vector-similarity | 失败 |
| 请求ID全部返回且有向量，但payload原始chunk ID为unrelated-chunk | 请求chunk无可用向量，WEIGHT | vector_backed=True、vector-similarity | 失败 |
| 请求ID及原始chunk身份正确、有效2560d向量 | VECTOR | vector_backed=True、vector-similarity | 通过 |

三种情况PG候选均可回读verified，因此PG正确不能替向量排序背书。异常两例没有服务超时/认证错误，只是实际选取器不能使用收到的数据，必须weight-fallback并degraded。详见tests/test_local_adapter_review_r4.py、acceptance-tests.txt；日志记录了实际发布函数的WEIGHT回退。此问题是原N1“完整有效向量覆盖”的最后缺口，不是新增质量门槛。

修复应观察发布存储get_vectors_by_ids交给选取器的**有效向量映射**，逐阶段与请求chunk身份匹配，而非原生point条数。返回point数可保留为传输统计，不能命名为vectors_returned或据此标vector_backed。至少保证无向量、原始身份不匹配均不算覆盖；正确向量正例保持。无需改算法、重新embedding或重建索引。

## 本轮核验边界

root现场只读核对八表221/5709/279/16514/65527/221/221/119575、内容source/catalog/search/gold/env前后无漂移，冻结匹配；Qdrant/Neo4j元数据符合既有记录，见live-inventory.json。0实际模型请求、0生产初始化/写库、0重建。提交40/40候选与220/220等数字仍为执行agent观测；其中覆盖数字当前代表point数量，本轮未批准为有效向量完整性的独立证明。

Ruff/format、OpenSpec strict、diff与凭据扫描通过；OCR仅本地范围/规则解析，coverage.json列明逐文件跳过理由。没有重新验收已通过阶段。

下一步仅按handoff-phase-3-5.2-fixes-r4.md修这一处。先过三种入口用例与旧测试，再做一题必要真实验证即可（建议fact-002，覆盖实体与关系选取）；没有相关改动的其它版本/反例沿用当前证据，不要求重复四题整轮调用。完成后停5.2复审。
