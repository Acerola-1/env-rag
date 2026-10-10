# Gate 1 第二轮复审：仍未通过（2026-10-05）

> 第三轮索引：最新验收见 [../review-3/review.md](../review-3/review.md)。表1行坐标和正文CLI正例已修好，另9项独立验收仍失败。以下保留第二轮结论。

结论：保留 Gate 0、v4 结构检查点及本轮已验证的 3.1 续表归组补正。3.2–3.5 仍需补正，恢复未勾选；3.6 不勾选，不进入 Phase 2。

## 本轮确认的事实

- 已连接原有 PG。container ls 显示 lightrag-postgres 为 running；主 agent 未启动、重建或更改任何服务。主复跑脚本所有 PG 连接强制 default_transaction_read_only=on；CLI 子进程按当前实现执行 SELECT 路径。本轮没有数据库写入，没有真实模型调用。
- public 八表前后计数均与冻结值相同：doc_full=221、doc_chunks=5709、doc_status=279、llm_cache=16514、entity_chunks=65527、full_entities=221、full_relations=221、relation_chunks=119575。开始/结束源指纹均为 95f7791fd84171ab727870fc5810d79b4327b0c4fa547d432951e0499a3808f8；active run=c15c741742394320，catalog snapshot=4919b3938ad93747，recipe=v4。
- 正式表格 API 返回表1 complete/13项/2片，表2 ambiguous。文件 API 用缩小页容量返回年报5/5、水资源公报5/5、GB3095版本2/2；无重复。正文原始 block 路径可读出3.1–3.4，主 agent 手动调用 bind_citations 后可以验证合同；这不等于正文 CLI 完成。
- 一个真实 WHO Annex 3 requires_span 范围未找到数字子条款，返回 partial/unresolved_span/processed=0，行为保守。不能由此认定所有可定位大 block 都正确处理请求。
- 提交的段内场所8项与本地GB18466 3.2逐字原文相符，保持“等”的开放边界合理。本轮没有复打模型请求；现有文件仅保存型号/耗时/成功标记和加工后的items，缺少实际messages和原始响应，尚不能独立复核所称真实模型调用的完整输入输出。
- 87 项测试通过，Ruff check通过，OpenSpec strict与diff check通过；Ruff format --check 当前失败（cli.py、prose_enum.py 两文件）。测试仍缺下列正式入口/精确回读反例。

所有真实输出和计数见 replay-live.json；新增隔离调用路径反例见 replay-offline.json。两类证据分开保存。

## R1 高：正文正式 CLI 正例失败，缺失条款却 false complete

CLI 请求 GB18466 第3章并指定3.1–3.4，实际退出1：complete citation must bind snapshot_id for independent re-read。cli.py的抽取分支没有调用 bind_citations，模型分支也同样没有绑定。

同一入口指定不存在的9.9.9，实际退出0，items=[]、complete、source_snapshot_id=""，warnings="items pending extraction (reading layer complete)"。contract.py 允许 warning 只要包含 extraction/items 就绕过空结果检查，读取层标签进入答案层后未移除，缺失请求项目也未核验。

必须让正式编排入口绑定并独立核验项目来源，再决定答案 coverage；明确请求的条款缺失须 partial/ambiguous并记录缺失集合。读取阶段可独立有read_status，但不能预填答案complete。禁止用自由文本warning充当“已验证空集合”许可。

## R2 高：13条表格行引用全部指错原始行

真实表1确实输出13项，两片归属也正确。但 row_in_fragment 在删去表头后从0重新枚举；实现定义的是片内展开grid行号，实际回读 raw grid 时每项都偏到上一行。第一项“总汞”指向表头，13/13条引用与输出cells不相等，仍全部 citation_verified=True。见 row_citation_reread。

解析时保留原始grid坐标，不因删表头/脚注而重新编号。合并单元格如使用展开grid须明确坐标合同；核验器按citation重新读片并比对cells/支持范围，不能只断言坐标小于片数。还有缺片allow_partial路径压缩frag_meta索引而解析使用原target.fragments，存在索引错位风险；覆盖“缺第一片、读第二片”的入口反例。header、units、footnotes目前仍未出现在最终结果，须交付。

## R3 高：requires_span自动选首条，局部请求未传到读取层

read_prose_scope 使用 locate_first_numbered_clause，不接受requested clause/range，也不读取scope的真实边界来选择跨度。含7.1、7.5、7.6的 requires_span 单元，在请求scope为7.5时读的是7.1，却返回processed=1/1、complete（隔离正式reader路径）。CLI的clause_wanted在读取之后才过滤，无法指导大block定位。未定位数字条款的真实Annex样本可保守返回partial，但一旦找到任意数字条款就不安全。

必须传递显式目标子范围，按原文scope/locator核验边界。全scope请求不能拿首条代表全部。跨度裁切后须保存原始unit offset；当前裁切后从0装配，bind_citations的unit相对坐标不包含裁切偏移。最长重复条款更新text/end却不更新start，跨度也与内容不相等，见 duplicate_span_disagrees_with_text。无边界chunk_fallback不得升级为完整unit；parsed_root参数仍被忽略。

CLI的SourceAdapter仍由POSTGRES_*原始环境键构造，连接时不符合asyncpg kwargs；修正正式调用方的host/port/user/password/database映射，测试实际需要fallback的路径。通过原始unit读取的正常例不会暴露此错误。

## R4 高：读取/抽取窗口及workspace守卫未闭合

enumerate_table只调用一次check_stale，完成前没有守卫。隔离正式table入口安排第二次守卫为stale，结果仍complete且guard_calls=1。read_prose_scope有前后守卫，但CLI在reader返回后抽取/调用模型，抽取结束时没有重新检查。

enumerate_documents始终只读已存的active记录及目录token，根本不调用live source check；原文改变但目录尚未重建时仍可complete。其workspace参数用于active和输出，却被_match_page/_match_count的_ws(args)固定为default；隔离入口请求another-workspace，所有数据查询仍default，返回结果却标another-workspace。token也只覆盖五个字段，未覆盖doc_type、unknown_fields、title_confidence等输出字段。

三类入口均在全部读取和抽取完成前检查相关来源/active，守卫须可观察快照外新状态。workspace一致贯穿查询或明确拒绝不支持值；源指纹与目录快照独立且非空。源/目录变化应返回stale，不保留complete。

## R5 高：模型仍以引句存在替代“支持对应项目”

模型缺引句已能拒绝，补正有效。但返回“原文明确列出停车场”，citation.quote="门诊、病房"，在原文“本定义列明门诊、病房。”上仍citation_verified=True且error=None。这不是虚构引句，是不受真实引句支持的虚构项目，前次E6已要求覆盖。

为段内明确名词等抽取任务实施对应项目核验，或输出未核验/degraded而不宣称complete；项目与引句的语义支持关系不能仅用substring检查代替。类型不正确的item字段也应进入model_failure，不得抛出未分类异常。完整模型编排须传播fail_stage、预算、调用日志及最终来源守卫。

## R6 中：合同身份和来源字段仍不足

reader的source_snapshot_id一直是默认空串，提交的正文结果也是空串。合同仅检查citation含snapshot/doc/workspace键，不检查非空值、是否等于结果身份、原始locator/span或计数非负。结合R1/R2，引用字符串和标签不能构成有效核验。

统一source/catalog双版本及组合身份一致性、各类必需locator，complete要求明确的目标范围/处理依据。真正零匹配文件结果可以complete；表格/正文未找到目标或抽取待处理不能通过warning绕过。

## R7 中：报告与可复跑证据仍不一致

enumeration-runs.jsonl实际是单个格式化JSON对象（run_meta、runs、in_definition_place_extraction），不是逐行JSONL；runs只有5条，加1段内记录，不是tasks声称的11次。没有本轮4.1.1–4.1.5输出或水资源公报复跑记录。主agent本轮独立复跑了公报等，但不能替代执行agent所声称的记录。

主agent未调用模型，因此不会否认现有型号/耗时记录；但messages、原始响应未交付，不能写“请求/响应已记录”。报告保留历史需明确标注，当前Ruff格式失败也应如实说明。

补正时由正式入口生成严格JSONL或按实际格式改文件名/读取器，保留旧文件；保存题目、完整参数、输入快照、引用回读、模型messages/raw响应、失败阶段和本轮检查。先验证实际CLI，再写“入口级全部通过”。

## 后续

按 handoff-phase-1-enumeration-fixes-r2.md 只补正R1–R7，保留已通过的结构和3.1。固定已有真实正例/反例，交付对应入口结果，不把本轮问题推迟到Phase2。3.6由主agent复审。
