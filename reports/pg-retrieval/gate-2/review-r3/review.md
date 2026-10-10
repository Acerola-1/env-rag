# Gate 2 第三轮复审（2026-10-06）

**Gate 2 未通过。4.1–4.3 可按本轮独立证据勾选；4.4–4.6 未完成，不进入 Phase 3。**

原 13 项与第二轮 11 项反例确实修好，两个验收文件 SHA-256 与前轮一致。提交时完整 152 项通过；主 agent 新增 9 项独立反例后，完整结果为 **152 passed / 9 failed**。未修改实现、旧测试、gold 审核标签或数据库；只增加审查证据、验收断言并更新阶段状态。

## 本轮确认有效的修复

- 分词实际 PG 探针 25/25 通过，含此前漏跑的编号相邻/点号编号。每例回验 query_terms 的前 12 组；这是所选样本的词项一致性证据，不是全语料语义召回率。
- 现有索引 `e3cb2a39dee53d9d` 对应 221 文档/5709 chunks；三类实际 EXPLAIN 均用 GIN Bitmap Index Scan，执行时间 1.583/0.932/0.596ms（一次测量）。GB8978 的 12 个含 caption chunk 与真实 unit_chunk_links 的 caption 逐个相等，未复制到全篇。
- missing 版本/裸编号/全角编号保持强限制；两 GB3095 版本、GB18466 含修改单、自身编号分别返回 2/3/1 份；第3章写法输出四术语，不再计章标题。
- 六道文件题**单独使用 expand_docs**全部集合相等：2/5/5/7/3/1 份。三道此前错误 gold 的正文目标已修好（syn002、syn004 两目标）；syn002 排序未中仍作为公开失败保留。
- 六表输出的 167 条物理行引用在独立原始 grid 上逐条相等；正文输出 12 个引句在所声明 raw block span/segments 中回读成立（短 quote 允许是完整跨度的前缀）。这证明这些位置上的引句/行来源存在；不证明答对题面或清单完整。

## 仍然阻断的五组问题

### B1 [P1] 范围短缺被重新升级为 complete

`src/env_rag_final/search/expand.py:604` 只依据 read_status 与“有一些 verified items”判完成，忽略请求条款缺失。

正式 CLI 请求 `GB18466-2005 4.1.1至4.1.7 有哪些要求？ --expand` 返回 status=ok / coverage=complete / 6 项，warnings 同时明确 `requested clauses missing: ['4.1.7']`。这是实库 false complete，不是 fixture 推断。

此外，38 行章规则仍强制“第”前缀；固定 prose-enum-001 的“3章”依旧 ambiguous，和第二轮交接及本轮报告所称支持不符。

验收：`test_missing_requested_clause_is_not_overwritten_by_successful_read`、`test_requested_chapter_without_di_prefix_is_recognized`；正式输出 `cli-missing-clause.json`、`cli-chapter3.json`。

### B2 [P1] 集合全对只比较编号，不比较答案

`search/eval.py:217`、236、254：表格产生集只取 cells[0]，gold 优先取 seq；正文产生集只取 clause，gold 只取第一词。

三个独立反例均错误得到 exact_match=True：

1. 序号 1 的“总汞/0.05”改成“总铅/999”；
2. 同序号的年平均/小时平均两行，丢掉一行；
3. 保留 4.1.2 编号，把必要条件和要求改成完全相反内容。

当前 table001 的 13/13 和 table004 的 24/24 是**序号一致**，不能据此称集合完全正确。citation_verified=True 也不能替代评测时的身份、位置与内容回读。

真实固定题还没有题目投影：table002 应六污染物却交付 14 物理行；table006 应十污染物却交付 14 行；prose006 询问 4.2，却给出 4.3/4.4 并 complete。编号成员齐全与题目答案完整必须分开。

table005 的 32 行 raw-grid 材料现在完整且可用，但 expected_items 混入表头和注释，生产是 30 数据行/24控制项目；双方还分别被评分器变成 dict 字符串和序号，无法比较。保留 raw grid 作证据，另定义按题面投影的 expected answer 与单位/注释上下文。

验收：前三项内容反例，`benchmark.json` 六表/六正文逐题结果。

### B3 [P1] 文件集合未进入 benchmark 的枚举与评分

`search/eval.py:336` 无题型分派，统一 expand=True，从不传 expand_docs；259 行又只支持 expected_items，实际六文件 gold 用 expected_doc_ids；评分数据只从 scope_expansion 读取。

独立重跑完整31题与正式 `search-bench --expand --only file-enum-001` 均证明：**六文件题全部 ambiguous，enum_set_check 全部 null**。即使 standalone 文件入口 6/6 对，Gate 2 评测也未覆盖这个行为。

验收：文件 gold 集合检查、benchmark 文件入口分派两个反例；`cli-file-bench.json`、`files-and-final-source.json`。

### B4 [P1] 固定六题分母被失败状态缩小

`search/eval.py:346`、433、456 将 ambiguous 从 eligible/reviewed 中删掉，三类集合汇总只以剩余可用结果计分。六题中一题成功、五题 ambiguous 的生产评测反例报告 questions=1/exact_match=1。

来源/快照/工作区失效必须拒绝这轮指标；固定正确身份上的普通检索或答案失败则应保留在 **/6** 中计为不正确。不给 ambiguous 候选记作可信证据，与从固定质量分母删题是两件事。不能把“1/6”汇总成“1/1”。本条重申上轮交接“各≥5/6、全部保留分母和失败行”，不允许降低原 stale/跨工作区隔离断言。

验收：`test_fixed_six_question_enum_denominator_keeps_ambiguous_failures`。

### B5 [P1] Gold verifier 没有落实逐字与主张支持

`search/gold.py:1299` 在全句不匹配时只检查前80字符，原文前80字符+编造尾句能通过；1286 行表格只判断 table_id 存在，不核对行/列/值。当前真实正文 quotes 经独立完整子串核对成立，不等于这个验证器能发现下一轮错误。

31题和10反例期望已重新逐项审查，见 gold-review-v3.json；尚未冻结计分 gold。除 canonical 项目合同外，仍需补必要条件证据：syn001 的 2030末/2031起日期条件在 2026 前言 `eebc13e2a0348fa67955192750d4e9e6`（亦见4.4），typed组只有两表；fact007 前后建设时期两表同为pH 6~9，但 typed组仅表4，前轮要求的表2来源仍未附。不能只核对目标存在而让不含必要条件的目标得满分。

至少8项实际反例要附完整结果及行为断言；当前8行只列 status/候选数，neg010 的“不能替代原标准”也不能由混合候选集的 status=ok 证明。保留已有 missing 等有效重跑与隔离反例，补语义断言。

验收：编造尾句反例；31题完整 gold 审核记录和 typed 引句/网格支持检查。

## 固定题真实结果与指标边界

`benchmark.json` 仍使用全部 unreviewed 的提交 gold，正式指标均 null；本轮没有在真实 gold 中写 approved，也没有用自检指标放行。

| 类别 | 当前实际现象 | 对验收的含义 |
|---|---|---|
| file_enum | benchmark 六题均 ambiguous/set_check=null；独立完整分页六题集合正确 | 编排与评分缺口，不能填集合分数 |
| prose_enum | 001/004/005 ambiguous；006给错范围；002/003编号检查为true | 当前答案仍未达到各≥5/6 |
| table_enum | 001/004序号检查为true；002/006项目投影未闭环；003 ambiguous；005 gold/产出合同不一致 | 当前检查不能解释为内容全对率 |

事实/综合题的候选召回应在 discovery 路径计算；无必要时不要对其统一启动 enum scope 展开，否则会把正常候选状态改成 ambiguous。证据召回与答案集合全对分别保留，syn002 的真实召回失败不能删题或改 gold 迎合结果。

## 来源、复跑和检查

- 主 agent 26 次生产检索重跑、31题 benchmark、6次独立完整文件分页、25个实际分词探针，以及3次正式CLI。未调用模型，未重建索引、迁移、写库或处理原始PDF。
- public 八表最终计数 221/5709/279/16514/65527/221/221/119575；来源指纹 `95f7791fd84171ab727870fc5810d79b4327b0c4fa547d432951e0499a3808f8`、catalog `4919b3938ad93747`、search `e3cb2a39dee53d9d` 均保持不变。
- 新反例和全套结果见 `counterexample-tests.txt`、`test-results.txt`。Ruff、OpenSpec strict、diff 检查通过。新增反例失败是保留的验收阻断，不进行 skip/xfail。
- OCR 仅用于文件选择/规则加载；覆盖账本逐项记录 review/skip 与原因，详见 coverage-manifest.json / review-manifest.json。本轮是 Phase2增量验收，旧Gate0/1及历史报告未重新逐文件审查。
- 下一步见 `openspec/changes/add-pg-scoped-retrieval/handoff-phase-2-fixes-r3.md`。先修 B1 和 B2/B3/B4，再按问题投影闭环真实六正文/六表格与完整 gold，不进入 Phase3。
