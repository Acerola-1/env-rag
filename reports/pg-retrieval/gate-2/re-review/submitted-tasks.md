# Tasks

当前状态（2026-10-05）：Gate0、v4结构检查点、Gate1通过，1.1–3.6完成。Phase2实现已提交但Gate2主agent验收未通过：既有123项测试通过，新增13项独立反例失败。4.1–4.5恢复未勾选，4.6保持未完成；按handoff-phase-2-fixes.md补正，不进入Phase3。最新结论见reports/pg-retrieval/gate-2/review.md。
初步事实在 design.md 中，不等于第 0 阶段完成。
执行顺序：第 1 组（Phase 0）→ Gate 0 → 第 2–3 组（Phase 1）→ Gate 1 → 第 4 组（Phase 2）→ Gate 2 → 第 5 组（Phase 3）→ Gate 3 → 第 6 组（Phase 4）→ Gate 4。
每个勾选项在对应阶段报告中附命令、产物或测试证据。不能只凭脚本退出码或当前会话描述勾选。

## 1. Phase 0：只读审计与数据合同

- [x] 1.1 编写可复跑只读审计入口，连接使用只读事务与超时且隐藏凭据；验证读查询可运行、没有初始化存储／DDL／DML，并交付 run-manifest.json 和操作说明。
  证据：`uv run env-rag-final audit`（`src/env_rag_final/audit/`，单 READ ONLY 事务＋statement_timeout=30s；staging 目录采集、全部成功后原子提交，失败记录失败阶段）；`reports/pg-retrieval/phase-0/run-manifest.json`（run_id、全部 8 个交付步骤、审计代码逐文件 SHA-256）。
- [x] 1.2 导出相关 PG 表字段、索引、扩展、文本搜索配置、依赖版本及脱敏 workspace 配置；以 schema.json 核实实际 schema，不只检查 SELECT 1。
  证据：`reports/pg-retrieval/phase-0/schema.json`（三表字段/索引、扩展=plpgsql、default_text_search_config=english、ts_debug 实测、row_counts）。
- [x] 1.3 将全部 `.parsed` 元信息与 doc_full、doc_status、chunks 对应，统计孤儿、重复、缺失、失败和引用；交付 inventory.jsonl，报告 222／221 差异和 58 failed 的实际身份，不自动处置。
  证据：`reports/pg-retrieval/phase-0/inventory.jsonl`（279 行三类身份）；222/221 差异=water-58（water-58 与 water-44 的规范化合并正文 MD5 相等，raw merged text 与 PDF 字节未比较/不等，本轮 `_duplicate_pair_evidence` 复算）；58 failed 逐行身份＋指向的原始 doc 全部 processed（本次核验）。
- [x] 1.4 核实 MinerU document_hash、PG content_hash、doc_id、sidecar_location 和分块参数的语义；交付来源指纹合同，明确哪些可比较、哪些不能作同一哈希。
  证据：inventory.jsonl 每行 hash_verification（221/221 复算一致）＋audit.md §1.2 哈希合同（doc_id=md5(doc_name)；content_hash=md5(norm(merged blocks))；document_hash=sha256(merged)；source_content_hash=sha256(PDF 字节)，三者不可互认）；另实测 doc_full.content 去除 {{LRdoc}} 前缀后与本地合并正文 221/221 逐字符相等。
- [x] 1.5 审计 block／table 到 chunk 引用覆盖并保存代表性多对多映射；mapping-samples.jsonl 包含 GB 8978 的两片表 1、GB 18466 的正文定义、一个跨 chunk 范围及缺失／歧义样本，未找到的案例标明缺口。
  补正证据：`reports/pg-retrieval/phase-0/mapping-samples.jsonl` 全部结论由本次运行采集产生——GB8978 表 1 两片（caption/dimension 本次从 tables.json 读取）、GB18466 定义 3.1–3.4＋4.1 跨 chunk（子串核验分支输出）、block 跨多 chunk 最大值本次聚合实测 **273**（water-145，与主 agent 独立核验一致，不再写死 14）、空 sidecar chunk 计数由查询产生、全库覆盖 211 全/10 部分/1 无 chunk 并注明"ID 引用覆盖≠全部文字覆盖"。
- [x] 1.6 离线核对 LightRAG 发布包公开证据接口、实际 ID 字段、workspace 命名与存储初始化副作用；交付 compatibility.md，区分已确认接口与未验证运行兼容性，禁止实例化存储连接现有库。
  补正证据：`reports/pg-retrieval/phase-0/compatibility.md` 为真 Markdown，每次运行实际执行探针（接口存在性/签名、aquery_data docstring chunk 字段、ClientManager.get_client 源码扫描确认 initdb+check_tables、workspace 发布包常量）并附原始探针记录 §3；三库 workspace 现场取值标注为首轮（2026-10-04）历史观察、本轮未重新连接；运行时验证划归 tasks 5.1。
- [x] 1.7 保存默认中文全文检索词项探针和应用分词候选方案；search-probes.json 展示整句词项失配、编号规范化与标题／正文例，不将未跑的方案标为成功。
  证据：`reports/pg-retrieval/phase-0/search-probes.json`（probe_1 已执行：整句 lexeme 失配；probe_2 已执行：5/5 编号规范化；probe_3 naive 基线；probe_4 明确 pending，jieba 未安装、pass=null）。
- [x] 1.8 提出真实文档白名单、五类问题各至少 6 道的候选和至少 8 个反例；交付 sample-set.json，记录依据和 gold 审核状态，无材料支撑的题列缺口而非编造答案。
  补正证据：`reports/pg-retrieval/phase-0/sample-set.json`（5 类×7 题、10 反例）全部 target_docs 为真实 workspace／doc_id／完整 doc_name（集合题附匹配谓词＋当前全部候选 ID，无省略号占位）；白名单校验升级为 parsed 产物存在且 chunks 可读，不满足的题移入 displaced_unresolved_targets 并使 meets_minimum=false（fixture 验证）；当前 35 题全通过、0 displaced；gold 全部 unreviewed。
- [x] 1.9 汇总 audit.md，列已观察事实、推断、未验证项、下一步和构建 schema 占用检查；复跑审计统计一致或解释来源变化，报告不含凭据。
  补正证据：`reports/pg-retrieval/phase-0/audit.md` 全部数字由本次运行记录生成（计数、273 跨度、consistency_checks 实测分支、规范化重复定因、LRdoc 存储格式说明）；来源快照指纹两次复跑一致（composite 95f7791fd84171ab…，组件=PG 原文/chunks/doc_status/产物字节/分块参数），灵敏度由 tests/test_audit_fixtures.py 14 项离线 fixture 验证；首轮报告保留于 phase-0-first-run-historical/，差异见 changelog-vs-first-run.md；`env_rag` schema 未占用且当前用户可 CREATE（schema.json app_schema_plan）；凭据扫描 0 命中。
  首轮审查：名称 fingerprint 不能证明内容或分块未变化——已按 handoff-phase-0-fixes.md 补正，1.10 复审定论。
- [x] 1.10 完成 Gate 0 技术审查并记录 review.md：主 agent 确认身份合同、白名单、排除项和兼容性风险，记录实际准许进入的工作组；不通过时修报告，不改现有语料。
  复审（2026-10-05）：reports/pg-retrieval/gate-0/review.md；主 agent 补齐稳定快照、缺产物校验、完整代次发布与失败证据保留，19 项 fixture 通过；两次只读实际审计 run 865a626eb7ce4365／3b7f17b1e30140a7 来源指纹一致，35 道正例身份核验通过。仅通过信息合同，不代表检索或 gold 审核完成。

## 2. Phase 1：自有目录与稳定来源读取

当前状态（2026-10-05）：v4经主agent复审通过结构检查点。当前active run c15c741742394320、snapshot 4919b3938ad93747；原提交与首轮退回记录保留，当前证据见phase-1-review/re-review-evidence.json。第3组已通过最终Gate1验收。此前退回记录保留为历史。

- [x] 2.1 实现显式辅助schema迁移、所有权与回退保护；验证不支持的名称在SQL前拒绝、外来对象阻止回退、迁移重跑安全；schema.py、S1行为测试及执行agent真实迁移记录见结构报告。
- [x] 2.2 实现组合身份和稳定快照读取；总数count(*)、序号缺口检查、内容/分块/引用SHA-256 token；未变化GB8978实际两页续读成功，变化反例stale，同ID多workspace测试通过，证据见v4-live-verification.json。
- [x] 2.3 元数据保留原文位置、引句和置信度；GB18466标题正确，引用-only不赋自身编号、封面日期与未知字段反例通过；真实样本及报告见structure-report.md。
- [x] 2.4 多对多映射依据来自实际sidecar和完整table元素id，纯文本/相似id不误连；12269 units、16783 links，全部partial保持保守，证据见manifest和行为测试。
- [x] 2.5 层级范围聚合后代、持久化requires_span；1970 scopes/14557 members，第4章含4.1/4.2排除第5章，GB18466单block跨chunk保持有效；requires_span 4个。局部抽取安全由第3组执行，结构状态不等于答案complete。
- [x] 2.6 源指纹守卫包围派生，source+recipe绑定身份；workspace锁覆盖整个构建，active切换与旧目录修剪同一事务；新增失败回滚与并发staging串行化反例通过，来源current、active唯一。旧目录已修剪时回退需重建配方；不承诺历史原文。真实查询、63项测试和代码摘要见phase-1-review/re-review-evidence.json。

## 3. Phase 1：三类枚举闭环与 Gate 1

最终结论见reports/pg-retrieval/gate-1/final-review/review.md。此前9项独立验收及本轮新增2项反例全部通过，完整测试101项通过。表1引用13/13、正文定义引用4/4、真实模型明示场所8/8独立回读一致；PG/source/active前后实测不变。以下各项保留的第三轮及早期退回描述均为历史，以最终验收为准。

- [x] 3.1 实现逻辑表及续表关联；GB 8978 表 1 两片顺序正确，同 chunk 不漏片；反例验证不同章节同表号不合并，无法确认的关联保留歧义。
  主agent第二轮：跨章节同号续片的归组条件已补正；真实表1两片顺序/归属正确、表2保留歧义，3.1保留勾选。表格行坐标与答案完整性另由3.2验收。
  第二轮提交证据（以下不替代上述主agent验收结论）：补正（E2/E7）：归组全程绑定 (文档, 快照, 章节 scope, 表号)；编号续片本章无 base 保持 ambiguous 不挂前章；正式入口 `enumerate_table` 始终提供 HTML 表头签名与 table_seq 排序，同号多组要求 chapter_scope 消歧（否则 ambiguous 列候选，不再 next 任取）。入口级回归：ch4 base + ch7 (完) fixture 不合并（复现原反例后消除）；实测（恢复后的真实库）GB8978 表1=confirmed 两片同 chunk 都保留、表2=partial、跨章节同号两组 → ambiguous。
- [x] 3.2 实现已有 HTML 的行列视图与表格枚举；真实表 1 输出 13 项及原始引用，测试处理 rowspan／colspan、重复表头、单位、注释和缺片，缺片不得返回 complete。
  最终验收：表1两片13项、raw grid引用13/13相等；缺首片partial仍引用正确剩余物理片；表头/单位/脚注交付。证据见final-review/replay.json及11项独立验收测试。
  第三轮主agent：13/13原始grid行引用已验收通过；G3缺首片allow_partial仍IndexError，保留正例修复但3.2未完成。
  本轮退回R2：真实表1的13项cells正确，但13/13 raw行坐标不匹配；缺首片allow_partial会IndexError，单位/表头/注释未交付。
  第二轮提交证据（以下不替代上述主agent验收结论）：补正（E3/E4）：表头/数据行按内容形态识别（数字首列或名称+数值对），无数据行片段不计已读，无可读数据行 → ambiguous；行引用绑定 (物理片 fragment_index, 片内行号 row_in_fragment, table_id, blockid, chunk_ids, doc/snapshot/workspace)，坐标唯一有序且 < 片数。入口级回归：无序号 pH/总汞表 → 2 行数据（原反例消除）；空 HTML → ambiguous（原反例消除）；实测（真实库）GB8978 表1 complete、13 项、序号 1–13、0 表2 混入。
- [x] 3.3 实现正文完整范围读取和分批 items＋引句抽取；GB 18466 定义及跨 chunk 样本无漏项／多项，检查每项引用与原文一致，预算不足返回 partial 与剩余范围。
  最终验收：正式CLI定义3.1–3.4、4.1五条/六条边界、GB3095第4章正确；缺失9.9.9及WHO未定位跨度为partial。原始单元偏移与模型quote坐标回读一致，模型场所8/8；证据见final-review/replay.json、cli-*.json、model-verification.json。
  第三轮主agent：正常3.1–3.4 CLI成功、9.9.9 partial已验收；G1正文3.3/3.4原文坐标为-1、裁切偏移未用、模型成功CLI绑定报错，3.3未完成。
  本轮退回R1/R3：正文CLI正例退出1，缺失9.9.9空complete；requires_span自动取首条，来源指纹空、原始跨度偏移未闭合。
  第二轮提交证据（以下不替代上述主agent验收结论）：补正（E1/E4/E5/E7）：新编排入口 `read_prose_scope`——unit 文本从原始 parsed block（locator.blockid）读取、有边界，chunk 仅作归属证据（校验 full_doc_id）；requires_span 必须定位子条款跨度，定位不到 → partial+unresolved_span 且不计入 processed；无可读文本不计 processed；预算同时约束成员数与装配字符数（装配时生效）；chunk 截断重复条款保留最长体（尾部不丢）；正文引用绑定 workspace/doc_id/snapshot/unit_id/locator/unit 相对跨度/chunk_ids，verified 由来源回读核验。入口级回归：requires_span 未定位 → partial/unresolved_span processed=0、无文本 → partial/missing_fragment（原反例均消除）。段内抽取实测：GB18466 3.2 场所枚举——deterministic 8 场所（门诊/病房/手术室/各类检验室/病理解剖室/放射室/洗衣房/太平间）+ 一次真实 LLM 调用（deepseek-v4.1-flash，2.2s，8 项全部 verified 且与 deterministic 一致，"等"保持开放边界，complete 限定为"该定义明确点名的场所"），请求/响应/耗时记录于 enumeration-runs.jsonl 的 in_definition_place_extraction。真实复跑：3.1–3.4 与 4.1.1–4.1.5 在恢复后的真实库全部 complete 且与 submitted-prose-vs-original 的编号集合一致。
- [x] 3.4 实现文档目录的精确条件查询与完整分页；固定库内文件集合结果一致，使用缩小页面容量跨至少两页验证无重复无遗漏，并报告未知元数据边界。
  最终验收：真实年报5/5、水资源公报5/5、GB3095版本2/2跨页；workspace/源变化守卫及所有输出字段token反例通过。证据见final-review/replay.json与tests/test_gate1_acceptance.py。
  第三轮主agent：workspace与live source守卫已修复；G2 token仍漏doc_type/title_confidence/unknown_fields，3.4未完成。
  本轮退回R4：仍无live source守卫，workspace请求与page/count查询不一致，token未覆盖全部输出字段。
  第二轮提交证据（以下不替代上述主agent验收结论）：补正（E5）：active 快照每页+返回前核验（最后一页后替换 → stale，fixture 复现原反例 final_page_snapshot_replaced）；token 覆盖全匹配集（50k 行预算，超限降 partial，去掉 10k 固定截断）；source_snapshot_id=构建记录的真实源指纹、catalog_snapshot_id=目录快照（分开）；active 与数据查询同 workspace。实测（真实库）：年报 5/5、水资源公报 5/5、GB3095 2/2 跨页无重复无漏项；开始/结束 check_stale 均 current。
- [x] 3.5 实现统一结果合同（身份、快照、范围、items、引用、coverage、warnings）；真实查询与缺失、歧义、stale 反例输出可区分，记录可复跑 CLI 示例。
  最终验收：待抽取空结果不能complete；部分词重合、额外场所/改数值、歧义定位不能verified；模型后/表格完成前守卫通过。枚举CLI会话强制只读；真实模型一次调用请求/响应完整保留于final-review/model-live.json。
  第三轮主agent：G2抽取后/表格完成前守卫仍缺；G4待抽取空complete/部分词重合验证仍可绕过，模型日志未完整交付；3.5未完成。
  本轮退回R1/R4/R5/R6/R7：warning允许待抽取空complete，项目支持关系/身份定位与版本守卫仍不完整，CLI及运行记录需补正。
  第二轮提交证据（以下不替代上述主agent验收结论）：补正（E4/E6/E7）：complete 要求 citation_verified 明确 True（缺字段/None 拒绝）且 citation 含 workspace/doc_id/snapshot；prose/table 空 items 的 complete 需显式 verified-empty 标记（读取层 complete 加 "items pending extraction" 标记）；模型 invalid JSON/非 list/缺 quote/空 quote/编造引句/shape 非法 → model_failure:* 降级。入口级回归：missing_verified_flag、model_missing_quote 原反例均被拒绝。CLI 新增 `enum-table`／`enum-prose`／`enum-docs`（只读连接、不打印凭据、完整参数）；11 次真实枚举（2 表格+1 正文+1 文件+1 段内场所抽取等）记录于 enumeration-runs.jsonl，含来源核验与实际模型请求。
- [x] 3.6 完成 Gate 1 并交付 phase-1/report.md：正例范围覆盖 100%、引用错误为 0、异常无 false complete，附对应测试与三类真实输出；未通过项保持未勾选。
  主agent最终验收（2026-10-05）：final-review/review.md；101项测试、Ruff、OpenSpec严格校验、diff通过；真实三类枚举与一次授权模型抽取完成，独立原文回读无引用错误。限固定已审核Gate1范围，35题benchmark未整体审核；准许进入Phase2，执行交接见handoff-phase-2.md。

## 4. Phase 2：中文关键词检索与 Gate 2

当前状态（2026-10-05）：Gate2主agent验收未通过（13项独立反例全失败），执行agent已按handoff-phase-2-fixes.md完成G2-1–G2-8补正并复跑：**13/13反例通过、全套146项测试通过**；真实索引按caption局部化重建（active `e3cb2a39dee53d9d`，recipe `phase-2-v2-local-caption-identity-guard`，GB8978表6命中20→4）；gold v2按逐题意见修正（31正例全带typed target_evidence）。4.1–4.5仍**未勾选**（待Gate2复审），4.6未勾。补正证据见`phase-2/report-gate2-fixes.md`、`selfcheck-machinery.json`、`counterexamples.jsonl`；gold仍全部unreviewed，指标未填。下列原提交证据保留为历史，不能替代主agent结论。

- [ ] 4.1 运行应用分词探针，确定分词器／环保词表版本并通过 uv 锁定；验证索引和查询词项一致，编号规范化覆盖空格、破折号、全角字符，记录词表更新方式。
  主agent：G2-7，20/20探针实际用query模式，未验证index模式；独立不一致分词反例仍pass。补正探针及版本核验。
  证据：jieba 0.42.1 uv 锁定；tokenizer `phase-2-v3-jieba-0.42.1-cfs-index`（索引=cut_for_search 超集、查询=lcut，同一词典/同一模块）；编号规范化 11 用例（`ＧＢ３０９５－２０１２`/`gb3095/2012`→`gb3095-2012` 等）；20 条真实文本索引↔查询一致性 0 失败（tokenizer-probes.json）；词表 SHA 参与 index_identity 与 check_search_stale，变更即要求重建（v1→v3 两次真实重建留档）。
  补正(G2-7)：探针实际用mode=index与mode=query分别经PG回验（25用例含编号短语相邻），注入不一致index流的反例被检出；test 12通过。
- [ ] 4.2 在辅助 schema 构建文档和 chunk 搜索视图、带权 tsvector＋GIN 及必要 B-tree；真实样本验证 HTML 清洗、标题／caption／正文可检索，EXPLAIN 和计时记录实际执行情况。
  主agent：G2-3/4，构建derive后无source守卫，清洗升版不stale；caption复制到全doc chunks导致伪局部证据；force/失败重试主键冲突路径需隔离证明。
  证据：迁移 0008/0009；真实构建 search_id=b1cd771ee0e2b55f（docs=221 chunks=5709，构建前来源指纹核验、构建后计数核对、原子发布）；权重 A/B/C；HTML 清洗真实形态（table/sup/drawing caption/equation/行内数学，clean_markup 测试）；EXPLAIN ANALYZE 实测三类查询均 Bitmap Index Scan on idx_schunk_gin，1.2–4.5ms（explain-evidence.json、index-manifest.json）。
  补正(G2-4)：caption改按unit_chunk_links赋给实际链接chunks（文档级信号只进A权重文档行）；真实重建search_id=e3cb2a39dee53d9d，GB8978caption chunks 24→12、表6命中20→4。
- [ ] 4.3 实现精确编号直达、元数据限定、核心词匹配与可记录的受控放宽；测试长自然语言提问、同义表达和多版本样本，放宽不移除强限制。
  主agent：G2-1/6，部分目标缺失仍ok、缺失裸编号回退他文档、全角编号未进强路由；同义词多候选误构造成相邻短语。
  证据：实现编号→元数据限定（restricted_to_code_docs）→核心词 AND→记录阶梯放宽（OOV 剔除/同义词代入/OR 兜底，逐级 tsquery+命中数入 trace）；真实反例：GB3095-1996 missing 不替代（列 2012/2026）、同一编号全版本分别保留不任取首项、多方编号对比各自保留、GB50014 不在库 missing；22 项 Phase 2 行为测试含放宽仅空结果触发、编号缺失早期返回。
  补正(G2-1)：全角规范化先于编号检测；全编号路由，任一缺失即missing（部分证据保留、关键词不替代）；裸编号同等约束；test 1/2/3及真实CLI通过。
- [ ] 4.4 从候选定位到范围并完整展开；测试候选 top-k 小于范围成员数、超长范围、文件多页，验证展开不随排名截断且预算耗尽有明确状态。
  主agent：G2-2/5，2012文件展开混入2026、年报变成全库221份；workspace及谓词未贯穿，自动scope确认/正文items未闭环。
  证据：--top-k 1 展开 GB8978 表1 仍 2 物理片 13 项 13/13 引用；GB18466 scope:3 3/3；739 成员 → partial/budget_exhausted 且告警含剩余起点；--expand-docs GB3095 全量分页 2/2；未知 scope ambiguous（测试）。
  补正(G2-5)：请求→范围解析（第N章/N.N/表N）自动确认scope并返回items+引用；解析不到保持ambiguous；真实CLI第3章5 items complete。
- [ ] 4.5 冻结至少 30 道正例题的 gold 与至少 8 个反例的期望行为；主 agent 审核原文依据，未审核题不进入指标，保存 benchmark 版本和审核记录。
  主agent：G2-8，逐题审核发现III类COD误列15（应20）、条件缺失、24项误为25等；已交31/10审核与原始材料，gold尚未冻结。评测仅doc命中、非审核状态入分及top-k之外命中入分；没有证据召回/三类集合/引用/反例指标。
  证据：gold-candidates.json 版本 phase-2-gold-candidates-v1：31 正例（fact 7/file 6/prose 6/table 6/synthesis 6）全部由 gold.py 从原始产物重推导（表行网格、block 引句、产物清单身份），含 gap 的题保留缺口不编造；反例 10；search-bench 入口逐题保存原始 run（search-runs.jsonl 31 行，与 active search_id 一致）；未审核题 pending_review，recall_at_k_reviewed=null 未计算。**待主 agent 审核后方可计指标。**
  补正(G2-8)：gold v2 31正例全带typed target_evidence并按逐题意见修正（COD 20、24项、file-005含修改单、syn-001过渡期等）；评测先截断再计分、evidence recall经unit_chunk_links解析、file doc recall单列；反例真实执行。机制自检（非指标）evidence_recall 0.966/file doc 1.0。
- [ ] 4.6 完成 Gate 2 并交付 phase-2/report.md：PG recall@20 ≥ 0.90，强编号／版本定位正例 100%，三类 enum 各 ≥ 5/6 集合完全正确，引用错误为 0；失败题和分词／放宽日志全部保留。

## 5. Phase 3：LightRAG 兼容与联合检索

- [ ] 5.1 在隔离临时库／测试 workspace 实测发布包公开接口、来源 ID 及初始化副作用；交付 compatibility-runtime.md，证明正式只读接入策略，兼容失败不得迁移现有库或自动升级依赖。
- [ ] 5.2 实现 LightRAG local 候选适配器；运行实际证据请求，验证模型／embedding 必要调用、workspace 和 ID 对应，不能只凭 import 或旧源码功能认定通过。
- [ ] 5.3 合并两路候选、按身份去重并保留路径；测试重复召回、不同 workspace 相同 ID、同内容不同版本，分数不直接相加且跨版本来源不丢失。
- [ ] 5.4 对合并集合执行联合 rerank，记录真实分数、调用及失败；验证同一测试候选集确实参与合并后精排，认证失败／超时／异常分数返回 degraded。
- [ ] 5.5 实现精排后完整 scope 展开和按题型生成；真实续表低排名样本仍完整保留，跨版本比较分别读取两份范围，缺少一份明确 incomplete。
- [ ] 5.6 完成 Gate 3 并交付 phase-3/report.md：真实链路可复跑，身份／版本一致、无范围截断、降级可见；更新独立／融合 CLI、开关和回退说明。

## 6. Phase 4：无缓存污染的真实对照与交付

- [ ] 6.1 实现固定配置下 local／PG／融合的评测入口；每个请求保存实际候选、精排、范围、上下文、生成与时间，验证答案缓存和旧答案复用均被禁用，重复请求确实冷生成。
- [ ] 6.2 在冻结白名单完成至少两轮对照；报告 fact、三类 enum、synthesis 的分母、recall、范围覆盖、漏／多项、集合完全正确率、引用／版本错误和降级，附原始运行记录。
- [ ] 6.3 报告检索、精排、展开、生成及端到端 p50／p95，说明样本量、并行与缓存条件；结合真实数据提出预算，不填写未经测量的延迟收益。
- [ ] 6.4 完成 Gate 4 审查：两轮 enum 均不低于 local、至少一类有可复现修复案例、fact／synthesis 不下降且满足其余 design 门槛；不通过保留基线和失败报告，不启用未达标默认融合。
- [ ] 6.5 运行受影响测试、uv 锁定环境、Ruff、git diff --check 与 OpenSpec 严格校验；交付最终状态／证据索引，分别列代码实现、真实查询、质量指标和未覆盖边界，不把计划 artifact 完成当功能完成。
