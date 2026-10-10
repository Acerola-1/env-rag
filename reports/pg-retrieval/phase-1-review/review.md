# Phase 1 structure checkpoint review

审查日期：2026-10-05（Asia/Shanghai）。**v4 复审通过，第 2 组通过结构检查点，可以执行第 3 组。** 首轮未通过的具体证据在下方保留为历史记录。
Gate 0 结论不变。现有结构目录作为已交付构建保留，当前 active 标签不代表已通过结构完整性验收。
本轮主 agent 只读现有数据库、执行离线反例、写入审查文档；没有迁移、构建、回退或删除任何数据库对象。

## V4 re-review result

主 agent 复核 S1–S7 的补正实现、执行实际只读查询和连续分页；复审过程中另外修正两处读取／发布边界。最终证据见 re-review-evidence.json 和 v4-live-verification.json，原提交报告保留为 v4-submitted-*。

- 通过的 active run：c15c741742394320；recipe：phase-1-v4-single-active-snapshot-prune；snapshot：4919b3938ad93747。
- 独立查询：221 documents、12269 units、16783 links、1970 scopes、14557 scope_units；各表当前一个目录快照。
- scopes 状态：219 ambiguous、1747 confirmed、4 requires_span。原提交 manifest 的双倍分布、旧 run ID 和 scope 总数混用已按现场结果更新。
- GB 3095 第4章包含引言、4.1、4.2，排除第5章；GB18466 4.1 的单 block 跨 chunks 保持有效。
- GB18466 标题为医疗机构水污染物排放标准，编号 GB18466/2005；字段带原文位置与置信状态。未知字段与部分引用保留。
- table 链接必须来自真实完整 id 属性，普通提及与前缀相似 ID 不产生内联依据。全部链接仍为 partial，不能以 ID 命中证明全文覆盖。
- catalog-stale 为 current，源指纹与 Gate 0 一致，八张 public 表计数保持不变。

本轮直接补正：

1. 分页原先使用 pg_current_xact_id，未改源数据也会因新事务 ID 报 stale。现改为文档内容、分块、顺序和引用的 SHA-256。实际 GB8978 两页 token 相同且续页成功；内容／顺序／引用／正文变化的反例改变 token。
2. 旧快照目录修剪原先在发布事务之外，失败可能删掉旧 active 的目录。现将 active 切换和修剪放在同一锁定事务，整个构建（包括 staging 写入）持有 workspace 会话锁，避免一个构建清理另一个进行中的目录。

63 项测试通过（16 项审计、47 项 Phase1）；Ruff、格式、OpenSpec 和 diff 校验通过。新增发布失败／并发构建测试为隔离状态模型，不能当作生产故障注入或性能测试。真实迁移／重建来自执行 agent 的记录，本轮主 agent 没有重复执行数据库写入。
本轮更改只影响分页和构建生命周期，没有修改 v4 的目录派生算法或重新构建目录；报告保存当前代码摘要，区分审查版本与构建运行证据。

### Accepted boundary for group 3

本通过只确认结构目录可以作为第3组输入，不表示枚举结果完整或正确。confirmed 仅表示结构范围，requires_span／partial／ambiguous 必须由第3组读取层处理或明确拒绝，不可直接映射为答案 complete。
新生成的 logical_table 或跨度定位如果改动派生配方，需要按新 recipe 建目录；raw source 冻结指纹保持不变，不能以旧 source→skip 路径冒充实现生效。
当前发布策略修剪旧目录行、保留 retired 账本；不能直接切换已删除旧目录。回退通过重建目标配方或关闭新路径，仍不承诺历史原文。
下一位 agent 执行 handoff-phase-1-enumeration.md 的 3.1–3.5；3.6 Gate1 留给主 agent 审查。

## Historical first review

## Confirmed evidence

- 独立 READ ONLY REPEATABLE READ 查询确认一个 active run e7723bb5096b4449，两个 failed run。
- 当前目录 221 documents、12269 source_units、16783 links、1817 scopes、10108 scope_units 与报告相同。
- public 的八张表计数与 Gate 0 报告一致，见 live-verification.json。计数相同不能单独证明历史无写入；代码公开表操作均为 SELECT，本轮查询全程只读。
- 全量现有测试实际为 35 项，通过；Ruff、格式、OpenSpec 严格校验、diff 检查通过。报告中的 33 是旧统计，需更新。
- 所有 links 的 coverage_status 为 partial；这点是合理的保守语义，不应该为通过验收改为 full。
- GB 18466 的 scope 4.1 对应一个原始 block，但该 block 含 4.1.1–4.1.6，且跨 chunks，因此成员只有一个不是漏项。本审查纠正中途基于报告“后续 block”描述的初步判断。

## Findings and acceptance

### S1 [P1]: 迁移和回退没有真正限定应用所有权（2.1）

位置：catalog/schema.py:170–226。
teardown 接受任意 schema_name 并直接插入 SQL。假连接调用 teardown(schema_name="public") 捕获到 DROP SCHEMA IF EXISTS public CASCADE；没有实际执行。
_assert_owned 只检查有限字符串，允许 DROP TABLE IF EXISTS public.owned_elsewhere 及 ALTER TABLE other.foreign_table。迁移的 --schema 参数只替换部分 DDL，初始化和迁移账本仍写 env_rag；并非声明的完整隔离 schema 支持。

修正：只允许经过标记与验证的应用 schema；拒绝 public／系统 schema、任意标识符与注入。schema 参数必须全路径一致，否则删除该未支持接口并明确拒绝。迁移与回退验证所有权，不自动接管同名未知 schema。
验收：假连接证明拒绝路径在任何 SQL 执行前失败；在隔离的应用测试 schema 验证迁移／重跑／回退，不访问现有 public 对象，账本与所有 DDL 同属于所选 schema。

### S2 [P1]: 父范围被子标题截断；大 block guard 未持久化约束（2.5）

位置：catalog/scopes.py:59–77、big_block_guard；builder._derive。
每遇编号标题就 flush 旧范围。真实 GB 3095-2012 第 4 章只包含引导 block，4.1、4.2 的 blocks 被分到独立范围；第 4 章仍为 confirmed。父章节读取会遗漏子章节。离线和真实产物反例见 offline-counterexamples.json。
big_block_guard 只返回 warnings，_derive 不修改 scopes，不保存该要求。真实 373295 字符／273 chunks 的 WHO block 所属范围仍为 confirmed 且 note=NULL。文档所谓“强制 span 提取”没有可执行机制。

修正：建立层级范围，父范围包含按源顺序排列的所有目标子范围成员，或明确支持层级展开并定义查询合同；保留叶范围局部边界。对未定位的内嵌条款持久化 partial／ambiguous 或 requires_span 等约束，读取必须处理或拒绝，不能凭 warning 宣称 complete。
验收：GB 3095 第 4 章同时覆盖 4.1／4.2，排除第 5 章；同 block 多条款有可验证的局部跨度／待定位状态；273-chunk 大 block 内的小条款不能直接当作整个 block 完整回答。不要错误修坏 GB 18466 的单 block 跨 chunk 情况。

### S3 [P1]: 元数据包含已确认的错误标题和自身编号误判（2.3）

位置：catalog/metadata.py:62–108。
当前库 GB 18466 标题为“部分代替 GB 8978—1996”，不是“医疗机构水污染物排放标准”。算法把第一条非排除文字当标题，未识别部分代替行。
离线正文“本文件／依据 GB 3838-2002 执行”被赋 self_code=GB3838，引用随后从 referenced_codes 排除，违反自身／引用编号合同。
head 用 join(body.split("\n", 60))，最后一个元素包含剩余全文，不是只取封面60行；日期全文首次匹配也可能命中别的文件日期。字段 provenance 主要为描述，没有原文位置、引句与可核查置信度；stats_period 未列未知值。

修正：自身编号只取可靠自身声明或封面独立编号行，引用、替代、依据行不赋自身。标题从已确认业务标题提取，识别“部分代替”、公告／前言和页眉；不能确认则 unknown。限制候选区域，字段附位置、原文引句和置信状态；日期冲突显式标未知／待核验。
验收：真实 GB 18466 标题正确；引用-only、封面替代、正文引用日期和同号不同年反例通过；unknown 字段列举准确。

### S4 [P1]: 构建的产物守卫没有覆盖实际派生窗口（2.6）

位置：catalog/builder.py:102–120、_derive、发布段。
两次 artifact hash 都在 _derive 之前，实际读取 blocks/tables 时已不受守卫覆盖。离线假连接在 _derive 中改变产物版本，build_catalog 仍返回 published=True；见 builder-change-counterexample.json。
_verify 只查 link/scope 到 unit 的关系，不验证 link.chunk_id 的 workspace／doc／存在性或构建范围覆盖。

修正：把前后检查包围实际派生读取；发布前确认所消费的源版本与声明一致，失配拒绝激活。来源解析目录要与被 fingerprint 的路径一致，不能忽略 parsed_root。验证 chunk 引用归属和已知范围缺口；缺来源不能默默跳过后当成功全量目录。
验收：派生期间改 blocks/table 的 fixture 和 source 版本变化反例使 build 失败、旧 active 不变；孤儿 chunk 或错误 doc/workspace 链接阻止发布。现有原库保持只读。

### S5 [P1]: 构建身份与发布并发不受合同约束（2.6）

位置：builder.py:122–139、INSERT 的 ON CONFLICT DO NOTHING、发布事务；schema.corpus_runs。
snapshot_id 只来自源指纹，幂等跳过只比较源指纹；修正 scopes／metadata 算法后仍跳过当前坏目录，修改目录版本也不参与判断。corpus_runs 不保存 snapshot_id，读者没有明确的 active run→目录版本关系。
没有每 workspace 的发布锁或 active 唯一约束。一个现场 active 只能证明当前状态，不能证明两个并行 publish 不会同时 active；失败后残留同 snapshot 记录配合 ON CONFLICT DO NOTHING 可能复用旧派生结果。

修正：构建身份绑定源 snapshot＋目录配方／版本／配置，保留明确 run→snapshot 关系。修复算法必须产生新 build，旧版本不可被幂等复用。建立发布串行化和数据库约束，明确失败记录的重试与清理，不静默复用旧行。
验收：相同源／相同配方幂等，配方更新真正重建；中途失败后重试输出完整新版本；隔离数据库并发构建最终恰好一个 active，失败不会使旧 active 丢失。不得将“常量长度64”测试充当 stale 行为验证。

### S6 [P1]: 适配器身份查找和分页未保证 workspace／快照一致（2.2）

位置：catalog/source.py:61–100、doc_chunk_total、read_chunks_ordered、get_chunk。
doc_exists 先按 id 单独 fetchrow，不筛选请求 workspace；同 doc_id 在多个 workspace 时任取一行，会错误拒绝有效记录。get_chunk 的 owner_workspace 也来自未限定的另一张表，未使用 chunk 自身 workspace。
存在性、序号校验、总数、当前页各开独立连接／事务，分页无冻结 snapshot／cursor。读取过程中插入、重分块或替换可能造成分页缺项／混版本且不报告 stale。

修正：所有身份按实际组合键查询，只在目标组合不存在后做跨 workspace 区分；读取会话或版本绑定使统计、校验和页面来自一致快照，续页改变来源必须 stale。验证序号缺口，不只 NULL／负数／重复。实际原文变化时不可沿用旧 catalog locator。
验收：两个 workspace 同 ID 时各自正确，错误 workspace 和缺失仍区分；分页中源变化返回 stale／拒绝；在独立测试 schema 或假连接中检验，禁止为反例改 public 原文。

### S7 [P2]: 表格 ID 子串不等于内联 table 元素证据（2.4）

位置：catalog/units.py:127–130。
if tid in content 会把正文仅提及 table ID 的 chunk 标为 inline_table_id。离线无 HTML table 的反例仍产生该依据，见 table-link-counterexample.json。

修正：解析或严格匹配实际 table 元素的完整 id 属性，处理拆分／畸形片段时明确 partial 或 unresolved；不要将普通引用／更长 ID 的前缀当表片段。未知 sidecar ref 要记录缺口，不静默丢弃后声称已核验。
验收：普通文字 table ID、前缀相似 ID 不生成 inline_table_id；真实单／双引号属性正确关联；多片段同 chunk 与空 sidecar 仍保守保存。

## Required next step

任务 2.1–2.6 保留交付证据但重新标为待验收；第 3 组与 Gate 1 不动。
先执行 handoff-phase-1-fixes.md，再以新目录配方构建和重新生成报告。不要因为源指纹不变复用旧 active 的错误 scopes／标题。
当前计数和原始样本必须保留，不重新解析或向量化，不修改 public 语料。测试优先行为反例与真实范围证据，删除恒真断言。
