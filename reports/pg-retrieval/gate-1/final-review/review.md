# Gate 1 最终验收（2026-10-05）

结论：通过 Gate 1，tasks 3.1–3.6 完成，准许进入第4组 Phase 2。此结论限于固定真实范围的三类枚举与异常合同；中文关键词候选、融合及正式质量对照尚未验收。

## 验收依据

本轮独立读取当前源库、原始 blocks/tables 与 v4 目录，并运行正式 CLI。没有以提交报告或测试退出码代替真实行为核验。第三轮的9项独立反例全部通过，主 agent 本轮再增加2项反例；完整测试101项通过，Ruff检查/格式、OpenSpec严格校验、diff检查通过。

| 真实核验 | 结果和证据 |
|---|---|
| GB8978 表1 | complete；13项、两物理片；13/13引用在原始grid上独立回读，cells完全相等；无表2项目混入 |
| GB8978 表2 | ambiguous；缺base caption依据，不强行声称完整 |
| GB18466 第3章 | 正式CLI返回3.1–3.4；4/4引用与原始单元坐标对应，3.3/3.4无负坐标 |
| GB18466 4.1 | 指定4.1.1–4.1.5时只有五条；完整请求含4.1.6，六条齐全 |
| GB3095 第4章 | 正式CLI返回4.1、4.2，排除第5章 |
| 文件枚举 | 年报5/5、水资源公报5/5、GB3095版本2/2；小页容量强制跨页，集合无重复或遗漏 |
| 缺失条款9.9.9 | CLI退出0但coverage=partial，显式记录缺失；原文读完不等于答案已完成 |
| WHO requires_span | 真实大block未能定位目标跨度时返回partial/unresolved_span；未升级complete |
| 真实模型抽取 | 用户明确授权的一次正式CLI调用；deepseek-v4.1-flash，模型耗时2792ms；3.2明示场所8/8，8条引用按原始block跨度逐字回读相等 |

真实重跑和完整参数见`replay.json`、`cli-0.json`至`cli-2.json`。原始表行与正文独立回读记录分别在`replay.json.live.row_citation_reread`及`prose_reread`。模型请求、原始响应、耗时在`model-live.json`，独立回读与调用后源核验见`model-verification.json`。

## 本轮发现及主 agent 补正

在真实PG与正式CLI处理函数中注入固定HTTP响应（没有实际模型调用），可复现：模型引句“污水”在三个单元出现，绑定阶段已判locator_ambiguous，后续verify_citations却将其重新标为True，最终false complete。该反例保存在`replay-before-fix.json`。已修复为保留明确失败及定位歧义/缺失状态；相同入口重跑现为partial，见`model-ambiguous.json`。

同时收紧项目支持核验：命名项须完整出现于引句；较长text主张必须在输入原文逐字存在，且引句属于该主张。新增“门诊、停车场”配“门诊、病房”以及数值999配0.01反例。概念部分重合不能使增添项目或改写数值获得verified。非逐字概述暂作未核验处理。这是保守抽取合同，不是通用语义蕴含判断。

枚举CLI的PG连接增加会话级default_transaction_read_only=on。上述补正仅影响读取/抽取/核验，不改变目录派生配方，未重建v4。11项独立验收测试在`tests/test_gate1_acceptance.py`；未删除、skip或降低此前9项断言。

缺首片allow_partial的剩余物理片引用、模型后/表格完成前source guard、token覆盖全部输出字段、pending extraction空结果、裁切偏移等已由独立入口级反例验证。本轮模拟HTTP用于异常路径；一次真实HTTP调用仅用于8项场所正例，两类证据分别标明。

## 来源与只读边界

开始、正常重跑结束、授权模型调用后均为current；active run=`c15c741742394320`，catalog snapshot=`4919b3938ad93747`，recipe=`phase-1-v4-single-active-snapshot-prune`。源指纹始终为`95f7791fd84171ab727870fc5810d79b4327b0c4fa547d432951e0499a3808f8`。

public八表调用后计数与冻结值逐一一致：doc_full=221、doc_chunks=5709、doc_status=279、llm_cache=16514、entity_chunks=65527、full_entities=221、full_relations=221、relation_chunks=119575。计数核验辅以原文/chunks/status/解析产物字节/分块参数的完整源指纹，未仅靠count判定内容未变。模型走独立HTTP抽取，不读取LightRAG答案缓存。

env_rag目录仍为documents=221、source_units=12269、unit_chunk_links=16783、scopes=1970、scope_units=14557。验收没有DDL/DML、teardown/migrate/build、PDF解析、embedding或融合调用。

## 已知边界及后续

- complete限定于已确认目标范围和明确库内谓词；“等”仍开放，仅接受定义明确点名的8个场所。不会据此声称所有医疗场所已穷尽。
- 表2歧义、不可定位requires_span、预算不足、来源变化或引用歧义保留异常/部分状态；不把这类题混入完整正例。
- 本轮逐项审核的是以上固定Gate1集合，不把Phase0的35道题整体改为reviewed。正式gold仍需Phase2 task4.5审核冻结。
- 101项测试与当前真实小样本证明本阶段合同闭环，不能推导全库所有表格/正文泛化准确率或PG全文召回率。

下一执行agent按`openspec/changes/add-pg-scoped-retrieval/handoff-phase-2.md`执行4.1–4.5，停在Gate2；4.6留主agent。前3轮未通过报告及提交副本作为历史保留；当前Gate1结论以本文件为准。
