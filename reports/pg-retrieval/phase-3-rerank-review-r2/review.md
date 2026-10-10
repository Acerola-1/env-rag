# 5.4 第二轮：三组剩余补正，R3与原始响应核验已通过

2026-10-07。5.4仍保持未勾选；5.1–5.3/Gate2保持通过，5.5/5.6/Gate3不进入。仅复审R1–R4，不做新精排或检索运行。

## 已通过部分

- 原独立14项全过、文件SHA与首轮主agent保存值一致。原矩阵与全套309项通过；本轮新增6项失败，最终为**309 passed / 6 failed**。
- 提交八项SHA匹配。当前原始响应results按(-score,index)独立重排，与10条published ordered的index/score逐项相等；source_verification记录10/10、typed目标3项保留，提交before/after冻结匹配、无drift。997ms/HTTP200为执行agent的新实证，本轮没有新HTTP调用。
- R3完整前置普通异常出口、每题live HTTP账本、超大分数安全拒绝，以及基本完整来源回退已经确认。R1的正文逐字匹配实际PG、workspace/verified拒绝与缺正文整题降级通过。R4原始响应保存与完整key回显净化通过。
- Ruff/format（含CLI）、OpenSpec strict、diff通过。主agent仅修改审查产物、状态和新独立测试，未改实现或旧断言。

## C1 来源元数据与问题绑定仍不完整（R1）

`_verify_candidates_against_source`核对了正文，却继续返回原candidate，未复算/核验content_sha256，doc_id为空时跳过归属比较且不填入PG full_doc_id。于是真实正文可以带错误SHA或空doc_id，以source_verified并status=ok输出。这不是要拒绝可修复的合法正文：可以显式拒绝，或从当前源行生成规范身份并记录修复，不能原样发布错元数据。

两个canonical元数据反例失败。另一个问题绑定反例失败：fused_result.query与gold题目不同，依然使用gold问题给原回放候选评分；run_rerank只以字典key选择题目、检查报告级指纹，没有核验本题query/workspace及对应来源约束。不能让来自其它问题/编号版本条件的候选因当前库冻结而成为本题可信输入。

旧矩阵的_usable仍生成sha-0占位值，因此“fixture均为可复算SHA”的提交陈述对该矩阵尚不成立。补真实fixture SHA与输入元数据，保留所有原顺序、来源和降级断言。

## C2 新增关联把正文block伪装为表格片（R2）

`_enrich_table_paths`读取全部unit_chunk_links，没有查询source_units.unit_kind；每个unit一律写table_id并生成citation.kind=table_unit。**主agent只读查真实source_units：41条新增关联实际29个block路径、12个table路径，29条被错误标为表格。**原始结果及每条kind比对见unit-type-probe.json。先前“41条表片补齐”不可当作表格溯源正确的证据。

生产分支的独立入口反例也失败：explicit fake PG来源存在、block/table各一个，结果将block-original列入table_id。修复要按实际单元类型、workspace/doc/snapshot组合键关联；正文关联可保留为block或source_unit元数据，不能伪造table。只在固定active snapshot关联，禁止snapshot缺失时扫全部代次；新结构关联要与原PG发现路径语义区分，不把所有链接宣称成“已命中/已确认的请求表”。

## C3 净化顺序与终态覆盖仍有缺口（R4）

错误正文先resp.text[:300]再_sanitize_evidence，secret跨截断边界时仅剩前缀，完整key替换不再匹配，前缀原样落盘。新的401截断边界反例失败。异常消息[:200]同样需要先净化后截断。

_write_terminal仍直接json.dumps(report)，前置/身份等失败detail并未经过_sanitize_evidence。前置guard错误消息包含配置key的反例把合成key原样写入报告。应让所有终态/各证据出口都统一净化，不能只处理_call_rerank内HTTP正文。

本轮反例均使用**合成fixture凭据**，没有证明真实key已泄漏；实际配置值扫描0泄漏。问题是净化保证尚未覆盖这两个路径。

## 下一轮范围

只补C1–C3，冻结tests/test_rerank_review_r2.py六场景保持，原309项与独立r1全部保持。类型修复用explicit fake来源和只读目录核验；原始响应/真实10候选正文输入已有证据。**无需新模型/embedding/reranker或检索重跑**，沿用997ms原始响应，补正元数据后指明派生证据，不篡改旧运行。本轮真实后端只做一次READ ONLY单元类型查询，0模型/写入，未重新采集整套冻结身份。交接handoff-phase-3-5.4-fixes-r2.md。
