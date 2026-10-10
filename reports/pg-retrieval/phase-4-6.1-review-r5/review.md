# Phase 4 / 6.1 rev-4 复审（2026-10-08）

**6.1通过并勾选；Gate3保持，6.2与网络评测未启动。** 本轮仅审S1/S2补正，其余通过结论沿用。未修改任何提交源码。

## 验证与裁决

四版冻结r1/r2/r3/r4为20/12/7/4，自有28，合计71项通过；全套454项通过（12.15s）。没有新增反例或重复已通过模块的功能审查。

- S1通过：当前题已执行HTTP才计issued；外题在途凭证不计入；无当前题可靠回执为unknown，命名的请求前守卫拒绝为before-http-zero。异常分支通过按腿annotations交给owning入口，finally将三态写入失败腿与终态，原错误保持。已执行失败计1、明确请求前拒绝计0与unknown三态的正负例通过；返回/抛错不双计。
- S2通过：锚温度声明与现行answer.py实际payload字面量比较，声明1/实际0在任何后端接触前拒绝，0的完整正例通过。严格必填结构、keyword解析/fallback、代码/提示/其它参数比较保持。

Ruff check/format、OpenSpec strict、diff通过。r1–r4冻结、17份Phase3冻结、27份历史运行/控制工件与gold未变；answer/expand已批准兼容缝未变，CLI及rerank/fusion/local/compat未变。.env与HY3成功代次字节身份一致，敏感值扫描0命中。

## 显式建立新代码锚

6.1批准后，原 `phase-4-config-anchor.json` 按字节归档为 `phase-4-config-anchor-gate3.json`，保留其SHA与旧answer SHA。当前锚新代次为 `phase4-6.1-approved-r4`，仅更新已批准兼容缝的answer代码锚，并登记evaluation/CLI/expand的复现SHA。附加复现SHA是reviewer台账，不冒充运行时自动强制校验。

来源身份、模型配置、参数预算与旧锚逐字段完全相同；未现场重冻数据库或回写漂移。新锚调用零后端验证器通过；新锚建立后r3/r4共11项锚/凭证测试再次通过。旧真实Phase3运行与manifest保持原样。

## 下一步授权范围

关键词仍为DeepSeek，用户报告额度耗尽，未做健康探测、未静默改模型。网络预算与关键词模型更换均未授权。

已准备单轮3题×3路径的9腿试跑提案（fact-002/prose-enum-001/syn-004），只经dry-run生成矩阵与上限：backend_fetches=0。初次dry-run题号prose-001不存在，被入口在后端接触前拒绝，日志保留；正式提案使用冻结题号prose-enum-001。这是离线准备，不是6.2实测或质量结论。

试跑提案上限为keyword6、embedding24批、Qdrant48、Neo4j60、计量PG432、rerank3、answer3；这些是工程预算闸门计数，不是账单价格或未计量传输的总量承诺。PG建连/关闭/事务控制/run级身份读取的已声明排除口径保持。两轮全41题三路评测的246腿尚未授权。

本轮0真实模型/embedding/rerank/DB请求、0写库；仅本地测试/文档/锚/工件写入。6.1通过证明评测工具满足工程合同，不宣称HY3质量、稳定性或融合增益已验证。

下一步交接：[handoff-phase-4-6.2-pilot.md](/Users/acerola/Dev/Python/RAG/env-rag-final/openspec/changes/add-pg-scoped-retrieval/handoff-phase-4-6.2-pilot.md)。用户授权模型处置与试跑预算前不得执行真实命令。
