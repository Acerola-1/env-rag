# Gate 1 审查：未通过（2026-10-05）
> 第二轮复审索引（2026-10-05）：PG已可连接，计数/源指纹核验一致；3.1补正通过，3.2–3.5仍退回。最新结论见 [re-review/review.md](re-review/review.md)。以下保留首轮审查。

审查范围：tasks 3.1–3.5 的枚举实现、实际导出结果和调用路径。Gate 0 与 v4 结构检查点的既有通过结论保留；本轮不进入 Phase 2。3.1–3.5 恢复未勾选，3.6 保持未完成。

## 已执行与证据边界

- 当前 90 项既有测试全过；Ruff 检查/格式、OpenSpec strict、diff check 通过。新建只读审查脚本直接调用产品函数，复现 9 个反例，见 counterexamples-offline.json。这些反例是隔离依赖下的调用路径验证，不声称在真实库中制造了变更。
- 已提交 7 次枚举记录保留，见 submitted-enumeration-runs.jsonl；原报告保留为 submitted-report.md。表 1 的 13 项及正文 9 个目标编号确实在记录中存在。当前本地 GB18466 原始 blocks 复核支持 3.1–3.4 和 4.1.1–4.1.5 的条款集合；4.1.2 的拼接文本仅多一个换行，不作为漏项证据。
- PG 实际复跑失败：配置指向的本地 5432 无监听，连接被拒绝；进程查询未见 PostgreSQL，Apple container 服务未运行。未启动服务、未执行数据库写入，也未调用 LLM。因此本轮不能确认 active build、public 八表计数或源组合指纹仍与历史记录一致。连接失败不是本轮拒绝的唯一依据，下列调用路径反例足以推翻“异常无 false complete”。
- 本轮独立核对本地 blocks/tables 字节指纹，结果见 review-manifest.json。它只能确认本地解析产物；不能替代 PG 指纹。

## E1 高：正文读成员计数不等于读完目标原文，跨度保护未接入

位置：prose_enum.py:108–149、193–224。

入口读出 locator、requires_span 后没有使用，直接把每个关联 chunk 全文拼接；单元到 chunk 的关系只证明引用，不能把 chunk 全文当成该单元的边界。多个成员共享 chunk 会重复加入全文。预算只计单元，一个大单元可以展开数百 chunk。随后按条款号保留首次出现，第一次被 chunk 截断而后片含剩余条件时会丢弃尾部。

调用路径反例：requires_span=true 的单元读入 Annex 4 和 Annex 5，未定位任何范围仍返回 complete；无 chunk 文本的单元警告后仍 processed=1/1、complete；首次重复条款截断时第二次的“后续重要条件”消失。见 requires_span_not_enforced、no_chunk_text_processed_complete、first_duplicate_discards_tail。

必须从原始 unit/locator 读取完整且有边界的原文，或证明 chunk 到 unit 的字符映射；局部请求定位不到跨度须 partial/ambiguous。缺文本不得算成功处理。预算同时约束实际字符/上下文和成员；抽取层核实目标项目集合和剩余范围，不能直接沿用读取层的 complete。

## E2 高：跨章节同号续表仍会错误合并，同号请求会任取第一组

位置：tables.py:141–150；table_enum.py:67–68。

编号续片只按表号向前查找，没有章节边界条件。反例“第 4 章表 1 base + 第 7 章表 1(完)”被合成 confirmed。现有跨章节测试只覆盖两个 base，遗漏续片跨章节。即使生成两个同号组，enumerate_table 也用 next 任取第一组，接口没有章节消歧。

补正必须按文档、快照、章节/原文范围、表号共同归组；章节归属不明应保留歧义。同号多组要求明确 scope 或 ambiguous，不能任取。三段归组各阶段都要遵守边界。

## E3 高：无序号表格全部被当表头，空结果仍 complete

位置：tables.py:405–416；table_enum.py:97、126–174。

第一片仅以“遇到数字首列”结束表头。包含 pH、总汞的无序号表格全被放进 header，输出 items=[]、members=1/1、complete。真实标准有无序号/名称首列的表格，数字序号不能作数据行存在的前提。空 HTML 也会被计成已读片。

补正需依据 HTML 和真实表结构识别表头/数据行；无法识别时明确 ambiguous。空/无效片、歧义列不能 complete。结果还必须保留表头、单位、注释，不能只在内部解析后丢弃。

## E4 高：项目引用不是可独立回读的原文定位

位置：table_enum.py:157–172；prose_enum.py:217–235。

表 1 只有两片，提交的 13 个项目 fragment_index 却为 0–12；代码把行枚举索引当片索引，每项又挂全部片段引用。项目 13 的片索引 12 不存在。正文引用只有临时拼接串 char_start/end 和前 120 字，无 doc_id、unit_id、chunk_id 或原文 locator；也没有保存对应拼接串。引用不能在结果独立回读时确认其出处，quote 在拼接文本中出现不证明整项主张有依据。

每项需绑定实际 doc/workspace/snapshot、物理片或原文 block、行/字符位置、chunk links、支持项目的完整引句。表格行的来源必须在解析时保留；正文偏移应属于可回读的原始单元，而非临时重复拼接串。核验必须读取绑定来源，不能无条件设 True。

## E5 高：身份、活动版本及返回前检查不闭合

位置：prose_enum.py:69–95、108–128；doc_enum.py:44–64、111–192；table_enum.py:29–40。

正文只检查当前目录总体 current，没有比对传入 catalog_snapshot_id；不存在/退役快照查不到成员就 0/0 complete，已用调用路径复现。scope/unit/link 查询都不含 doc_id，传入的文档身份实际上未参与绑定。三类入口未统一在返回前检查相关来源与 active；文件单页路径只检查一次 active，最后一页获取后替换活动版本仍 complete（调用路径反例）。文件枚举还把 catalog snapshot 写进 source_snapshot_id，提交三个文件输出均有此错误，active 查询不限定 workspace，数据查询硬编码 default。

按组合身份绑定读取并核验 scope/unit 所属文档、活动快照；源指纹与目录快照分别赋值。相关来源/活动目录要包围整个读取与抽取窗口，单页、最后一页、零匹配也不能漏完成前检查。分页 token 覆盖完整匹配集合及输出字段，不能固定截至 10,000；提前空页须 partial/stale，返回前 validate 并检查实读总量。

## E6 高：统一合同及模型引用验证放过未核验结果

位置：contract.py:67–71；prose_enum.py:300–309。

validate 仅拒绝 citation_verified is False，缺字段、None、其他值均可通过。反例缺 verified 字段仍 complete。模型校验把缺失/空引句判为 verified=True，无 error；直接复现“unsupported claim + 空 citation”被接受。JSON 合法不表示 shape 合法，也不表示项目受到引句支持。

complete 必须要求明确布尔 True 及各类引用必要身份/locator，计数应有合理边界和目标处理依据；空匹配的文件清单可合法 complete，但不能把缺片/抽取失败的空表格、空正文当成空集合成功。模型路径要求 shape、非空逐字引句、项目与引句对应，任一缺失或失败降级。引用含真实句子但项目主张不受该句支持的反例也应覆盖。

## E7 中：可复跑入口和正文抽取闭环未交付，报告超出调用证据

位置：cli.py:87–93；table_enum.py:58–86；phase-1/report.md。

CLI 没有三类枚举命令，原 7 次生成脚本也未交付。正文只有分离的 reader/regex/model helpers，没有负责跨度、分批、失败状态、引用、complete 和模型日志的正式编排入口。locate_span 无产品调用方，所谓定位失败进入 unresolved_span 尚未实现。表格入口不传 html_provider、不查询 table_seq，忽略 parsed_root 来加载 HTML，故报告中的表头签名归组不能代表实际入口执行该路径。

GB18466 的 3.2 定义全文包含场所不等于已完成“分别列出场所”问题。交付范围内已要求这类段内枚举及小范围真实模型抽取，不能整体延期到 Phase 2 gold。先针对该局部题从原文审核 gold，再按既有配置实际调用并存请求/响应/失败；固定格式可用确定性抽取，但必须交付段内 items 闭环与证据。模型运行或 PG 不可用时如实保留 pending，不能补勾任务。

## 接下来

执行 handoff-phase-1-enumeration-fixes.md 中 E1–E7，只修第 3 组。每个问题通过正式入口的行为测试及真实原文/目录验证，不只测试 helper 或单独 EnumResult。保留所有历史证据，新输出独立记录来源、配方、题目、运行方式及人工审核依据。停止在 Gate 1，3.6 留给主 agent。
