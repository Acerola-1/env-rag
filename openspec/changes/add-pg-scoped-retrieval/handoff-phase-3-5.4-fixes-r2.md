# 仅5.4剩余C1–C3，完成后停检查点

前轮14项已通过，R3/原始响应保存及独立排序复验确认。现原309项通过、新6项失败；报告phase-3-rerank-review-r2/review.md。5.3及之前结论保持，不进入5.5/5.6，不重跑真实精排/检索。

## C1 规范来源身份与正确请求

- 正文与当前PG匹配后，也须复算/核验内容SHA与长度，doc归属必须非空且正确。错误SHA/空doc_id可以明确拒绝，或由当前真实行规范化并保存原值与修复依据；不可把旧错误元数据原样标verified发布。
- 核验选定回放entry的query_id/workspace/query与冻结题目合同，并保留请求编号/版本来源约束。不允许不同问题候选以相同字典id/库指纹进入本题评分。字段缺失时拒绝/显式兼容来源证明，不能默认当作相等。
- 旧测试_usable仍用sha-{order}，按首轮交接允许改成真实正文SHA和规范回放question/workspace；断言按该真实fixture SHA比较，顺序/两版本/来源/降级语义保持，不删弱化。fake当前PG行必须明确存在。

## C2 按实际单元类型补关联

- 关联unit_chunk_links与source_units，以workspace/snapshot/doc/unit组合键取真实unit_kind；只有table才能创建table_unit/table_id。block链接如需保留，使用block/source_unit关联语义。
- snapshot以已验证的active目录身份为准，缺少/不符时拒绝；移除snapshot缺失时扫描所有代次的分支。
- 原PG发现路径保留；新来源结构关联标明是关联补全，不假装新的PG检索命中或请求范围确认。不要靠tb前缀猜类型/locator。
- 主agent已经只读确认实际41条新增关联中29 block/12 table；不能继续宣称41条都是表片。修复输出需可独立按类型核对。

## C3 净化覆盖所有写盘路径

- 对HTTP错误正文、非JSON、异常消息等完整证据先净化，再限制长度；secret跨边界时不能留下前缀。
- 终态writer及其他JSONL/报告出口统一净化已配置key/password/token与敏感字段。前置/身份错误detail也不能绕过；保留真实错误类型/状态和非敏感原因，不暴露headers。
- fixture凭据用长度足够且不与正常chunk ID/正文冲突的合成值，保持source正文/hash核验语义，不靠一字符占位key碰撞让来源字段被改写。

## 有界验证与交付

先复现冻结test_rerank_review_r2.py六项，一次补三组；原309项与r1独立14项保持。生产补关联分支要通过owning入口的fake PG运行，而不是transport分支跳过后声称已测。

**0新模型/embedding/reranker调用，不必新精排运行。** 补正后可对已验收997ms原始响应做新派生metadata映射并独立重排，明确输入正文SHA不变与派生来源；旧runtime保持原状，不把派生数据冒充新HTTP响应。实际类型核验仅必要只读目录查询即可。

Ruff/format/OpenSpec strict/diff/凭据扫描、最终manifest与新失败/正例证据齐全；报告区分历史41误标与修复后类型数量，停5.4主agent复审，不进入展开/生成/Gate3。
