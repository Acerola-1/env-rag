# Phase 1 第 3 组枚举报告（tasks 3.1–3.5）


> 主agent最终验收（2026-10-05）：Gate1通过，tasks3.1–3.6完成。101项测试通过；真实表格13/13、正文定义4/4引用回读一致；授权真实模型一次抽取8/8场所引用逐字相等。源库计数/完整指纹与v4目录前后不变。
> 本轮补齐歧义引用状态保留和逐字项目支持核验，详见[最终验收](../gate-1/final-review/review.md)。下一阶段为Phase2中文关键词候选与gold审核，正式召回质量尚未验证。
> 下文为执行agent各轮提交及历史说明，不替代最新验收结论；最终验收前提交副本保存在../gate-1/final-review/submitted-report.md。

---

## 执行 agent 补正轮（2026-10-05，Gate 1 E1–E7）

### 0. PG 服务恢复

复审时 5432 无监听的原因：Apple `container` 运行时 apiserver 未运行（宿主机重启后未自启），
`lightrag-postgres` 容器 stopped。本轮 `container system start` + `container start
lightrag-postgres` 恢复**原有**容器（非重建），核验 doc_full=221、public 八表计数与 Gate 0
冻结值一致——数据完好，无写入。开始与结束时 check_stale 均 current、源指纹==冻结值。

### 0.1 E1–E7 修复对照（全部经正式入口回归验证）

| 发现 | 修复 | 入口级回归 |
|---|---|---|
| E1 正文边界/跨度/预算 | 新编排入口 `read_prose_scope`：unit 文本从原始 parsed block（locator.blockid）读取、有边界；chunk 仅作归属证据（校验 full_doc_id）；requires_span 必须定位子条款跨度，定位不到 → partial+unresolved_span 且不计入 processed；无可读文本同样不计入；预算约束成员数+装配字符数，装配时生效 | fixture：requires_span 未定位 → partial/unresolved_span、processed=0（原反例 requires_span_not_enforced 消除）；无 chunk 文本 → partial/missing_fragment、processed=0（原 no_chunk_text_processed_complete 消除） |
| E2 跨章节同号 | 归组绑定 (文档, 快照, 章节 scope, 表号)；续片本章无 base → 保持 ambiguous 不挂前章；`enumerate_table` 同号多组要求 chapter_scope 消歧，否则 ambiguous 列候选 | fixture：ch4 base + ch7 (完) 不合并（原 cross_chapter_continuation 消除）；两组同号 → ambiguous 列候选 |
| E3 无序号/空 HTML | 表头/数据行按内容形态识别（数字首列或名称+数值对）；无数据行片段不计已读；无可读数据行 → ambiguous；空 HTML=unreadable | fixture+入口：pH/总汞无序号表 → 2 行数据；空 HTML → ambiguous（原 unnumbered_table_empty_complete 消除） |
| E4 可回读引用 | 表格行 citation 绑定 (fragment_index=物理片, row_in_fragment, table_id, blockid, chunk_ids, doc/snapshot/workspace)；正文 citation 绑定 workspace/doc_id/snapshot/unit_id/locator/unit 相对跨度/chunk_ids；verified 由来源回读核验 | fixture：行坐标唯一有序且 < 片数（原 fragment_index 0–12 消除）；正文 span 转 unit 相对坐标 |
| E5 身份/版本窗口 | 三入口统一：读取前后 check_stale + 请求 snapshot 必须是 active；doc 绑定 doc_id；旧快照/空 scope → stale/ambiguous（绝不 0/0 complete）；文件枚举 source_snapshot_id=真实源指纹（与 catalog snapshot 分开）；token 覆盖全匹配集（50k 行预算），最终页后再次核验 | fixture：旧快照 → stale（原 old_snapshot_empty_complete 消除）；最后一页后替换 active → stale（原 final_page_snapshot_replaced 消除） |
| E6 合同/模型核验 | complete 要求 citation_verified 明确 True（缺字段/None 拒绝）、citation 含 workspace/doc_id/snapshot；prose/table 空 items 的 complete 需显式 verified-empty 标记；模型 invalid JSON/非 list/缺 quote/空 quote/编造引句/非 list shape → model_failure:* 降级 | fixture：missing_verified_flag_accepted、model_missing_quote_accepted 均被拒绝 |
| E7 入口/段内抽取 | CLI 新增 enum-table／enum-prose／enum-docs（只读连接、不打印凭据）；GB18466 3.2 场所段内枚举执行：deterministic 8 场所 + **一次真实 LLM 调用**（deepseek-v4.1-flash，2.2s，8 项全部 verified、与 deterministic 一致），complete 限定"该定义明确点名的场所"，"等"开放 | enumeration-runs.jsonl 的 in_definition_place_extraction 记录请求配置/响应/耗时 |

### 0.2 本轮实测（恢复后的真实库）

- T1 GB8978 表1：complete，13 项，序号 1–13，行引用绑定物理片 0 + 行内坐标。
- T2 GB8978 表2：ambiguous（无 base caption 证据）。
- P1 GB18466 第3章：complete，3.1–3.4 齐全、全部 verified、正文单元文本来自 parsed block（source=parsed_block）。
- D1 年报：complete，5/5，source_snapshot_id=真实源指纹 ≠ catalog snapshot。
- 全程 public 八表计数不变；开始/结束 check_stale 均 current。

### 0.3 第一轮补正遗留问题（第二轮复审 R1–R7 已修复）

第二轮复审（gate-1/re-review/review.md）发现 4 个入口级反例，全部修复并经正式入口回归：

| 复审发现 | 修复 | 入口级回归（真实 CLI / 隔离正式入口） |
|---|---|---|
| R1 正文 CLI 3.1–3.4 退出1；9.9.9 空清单 complete | CLI enum-prose 分支调用 bind_citations；requested_clauses 传入 reader；缺失条款 → partial + "requested clauses missing" 警告；读取层 zero-item 标记不再被答案层误用 | **真实 CLI**：3.1–3.4 exit 0、complete、4 项全部绑定正确 unit；9.9.9 exit 0 但 coverage=partial + 缺失集合记录 |
| R2 表格行引用指错原始行 | row_in_fragment 改为**原始 grid 行号**（表头/脚注剔除不重编号）；独立回读核验 | **真实 CLI**：表1 13/13 条 citation 重读 raw grid 与 items cells 相等 |
| R3 requires_span 自动取首条 | requested_clauses 传入 reader，按请求条款定位；无请求条款的全 scope requires_span 读取仅在 block 含可定位子条款结构时成立，否则 unresolved；span 裁切偏移记录于 UnitText.span_offset_in_unit；重复条款更新 start+end 保持 text 一致 | fixture：7.1/7.5/7.6 单元请求 7.5 → 定位 7.5（不含 7.1/7.6）；无子句结构 → unresolved；重复条款 span 与 text 一致 |
| R4 窗口/workspace | doc_enum 增加 live source 指纹前后核验（builder._live_source_fingerprint）；workspace 贯穿全部 count/page 查询（不支持值明确拒绝）；token 覆盖全部输出字段；表格入口读取后二次守卫（通过 fixture guard_calls 观察） | fixture：final_page_snapshot_replaced → stale（保留）；live source 变化 → stale |
| R5 项目支持关系 | _quote_supports：引句逐字存在之外，claim 的实质 token（2+ 字滑窗）必须出现在引句中；"停车场"配"门诊、病房"引句 → unsupported_or_fabricated_citation | fixture：停车场反例被拒；"列出门诊"配同引句通过 |
| R6 身份/来源字段 | complete 的 citation 必须 snapshot_id/doc_id/workspace **非空**；结果级 catalog_snapshot_id/workspace 必须非空；prose 读取层 source_snapshot_id 取构建记录的真实源指纹（不再空串） | fixture：空 identity 被拒 |
| R7 证据一致性 | Ruff format 修复（cli.py/prose_enum.py）；enumeration-runs.jsonl 改为**逐行 JSONL**（8 行：meta+6 CLI 运行+1 段内场所抽取），每行含 cli_command 完整参数；模型 run 保留 request_messages/raw_response；报告分区标注历史与本轮 | 本文件本轮小节 + JSONL 每行独立可解析 |

### 0.4 第二轮补正后的实测（真实库、正式 CLI）

| 运行 | coverage | 关键断言 |
|---|---|---|
| prose-ch3（3.1–3.4） | complete | 4 项、全部 verified、引用绑定正确 unit（385d9e8e/ad9d292d/90d4b1c5） |
| prose-41-full（4.1.1–4.1.6） | complete | 6 条含 4.1.6 |
| prose-999（9.9.9） | **partial** | 0 项 + "requested clauses missing: ['9.9.9']"（原反例消除） |
| table-1 | complete | 13 项；13/13 条引用重读 raw grid 与 cells 相等；header/units/footnotes 随结果交付 |
| table-2 | ambiguous | 无 base caption 证据 |
| docs-nianbao | complete | 5/5 跨页、token 覆盖全字段 |
| in_definition_place_extraction | 8 项全 verified | 与 deterministic 一致；"等"开放边界保留 |

### 0.6 第三轮补正（G1–G4，独立验收测试收口）

第三轮复审把残留问题固化为 tests/test_gate1_acceptance.py 的 9 项独立验收测试（初始 9/9 失败）。
本轮的修复目标是让这 9 项在**正式入口/引用路径**上通过，未删除/skip/降低任何断言。

| 组 | 修复 | 验收证据 |
|---|---|---|
| G1 原文引用 | `bind_citations` 重写——数值跨度裁到 owner 边界并按 overlap 归属、unit 相对坐标加 `span_offset_in_unit`（裁切单元回读到原父块）、跨单元主张保留 `unit_segments` 逐段来源；模型引句路径先定位 quote 得到精确 unit 内坐标，多单元歧义 → `locator_ambiguous`（不核验），找不到 → `locator_missing` | 3.3/3.4 的 -1 起点修复：raw[unit_rel_start:unit_rel_end] 4/4、41 全条款 6/6、场所 8/8 均可回读；裁切 7.5 的引用落在原父块 7.5 范围 |
| G2 完成前检查 | 表格入口在构造结果前再次 check_stale；正文 CLI 在模型/抽取完成后再次检查 source+active（变化 → stale，不保留 complete）；文档 token 覆盖全部返回字段（doc_type/title_confidence/unknown_fields 等） | fixture：表格第二次守卫 stale → coverage=stale；正文 CLI 模型后 stale → stale；token 三字段变更即变 |
| G3 缺片元数据 | 表格片元数据改为按**稳定物理片身份**（table_id）键控，缺片不再压缩索引；`allow_partial` 读取第二片时仍返回正确的 table_id/原始行坐标 | fixture：缺第一片 → partial/missing_fragment、items[0] 指向第二片 table_id=b、cells 正确 |
| G4 严格答案合同 | 读取层与答案层分离：reader 只给 `read_status`（不再预填答案 complete，warning 字符串不再能许可空 complete）；零项+非空成员 → complete 永远拒绝；模型成功响应经 CLI 不再 TypeError（模型分支不再复用抽取器返回值形状）；明确名词的场所主张必须**完整名称**出现在引句中（"门诊停车场"配"门诊、病房" → unsupported） | fixture：pending warning + 空 items → validate 拒绝；"门诊停车场"反例被拒；模型成功响应进入 CLI 正常产出 |

**本轮真实复跑（正式 CLI，全部 exit 0）**：prose-ch3（3.1–3.4 complete，4/4 引用回读）、
prose-41-1-5 / prose-41-full（4.1.1–4.1.6，6/6 回读）、prose-999（partial，缺失集合）、
table-1（complete，13/13 行引用回读）、table-2（ambiguous）、年报/公报/GB3095 分页（5/5、5/5、2/2）。
requires_span：WHO 大块请求 7.5 → partial/unresolved_span（processed=0）；GB3095 第 4 章
含 4.1/4.2、排除第 5 章。3.2 场所抽取经 --with-model 实跑一次：8 项全 verified、与
deterministic 一致、引用 8/8 可回读、请求前后 state=current/current，request_messages/raw_response
完整保留于 enumeration-runs.jsonl（无密钥）。

**测试**：tests/test_gate1_acceptance.py 9/9；全套 99 项通过；Ruff check/format、OpenSpec
strict、diff check 通过。

### 0.5 仍未验证/边界（第二轮后）

- 模型路径真实失败重试未演练（本轮无失败请求可复现）；失败语义由 fixture 固定。
- requires_span 真实 WHO 大 block 的局部请求语义由隔离入口 fixture 覆盖（真实 Annex 数据
  无可定位子条款 → partial/unresolved_span 已在首轮实测确认）。
- 35 题 benchmark gold 审核状态不变；3.2 局部场所题的依据与开放边界已记录。
- 模型 messages/raw response 已随 run 记录（无密钥）；主 agent 复核时可直接读取。

---

生成时间：2026-10-05（第二轮枚举）。输入：active run `c15c741742394320`，目录 snapshot `4919b3938ad93747`，
源指纹 `95f7791fd84171ab…`（冻结值一致）。本报告覆盖 3.1–3.5；3.6 Gate 1 由主 agent 审查，保持未勾选。
全部请求记录在 [enumeration-runs.jsonl](enumeration-runs.jsonl)（7 次枚举 + 运行元数据）。

## 1. 逻辑续表关联（task 3.1）

实现在 `src/env_rag_final/enumerate_/tables.py::link_logical_tables`，对活动目录快照内同一文档的
table units 做三段式归组：

1. **按 caption 分型**：`表 N <标题>` → base；`(完)/(续)/续表 N` → continuation（带或无编号）；
   其他括注行（如 GB8978 "(1997年12月31日之前建设的单位)"）与空 caption 单独处理。
2. **deferred 解析**：无编号括注行的归属方向由证据决定——优先表头签名匹配
   （`<table>` 首行归一化序列，如 GB8978 表2-base 与 `表 2(完)` 的
   `序号/污染物/适用范围/一级标准/二级标准/三级标准` 完全一致，而与 表1 的
   `序号/污染物/最高允许排放浓度` 不同），次选按 (unit_order, table_seq) 最近邻。
   无 HTML 证据时保守归 ambiguous，不猜测。
3. **跨章节同表号不合并**（fixture 验证）；同 chunk 内两片都保留为独立 unit。

GB 8978-1996 实测归组：表1=confirmed（0001+0002，两片同 chunk 且都保留）、
表2=partial（0003+0004，表头签名匹配、缺自身 base caption）、表3/表4=confirmed、
表6=partial（0003 无关项 D1.4.1 已不再混入；0016 仍需 span 定位）、5 个空 caption 片段=ambiguous。

## 2. 表格枚举（task 3.2）

`table_enum.py::enumerate_table` + `read_html_table`（lxml 网格展开，rowspan/colspan 填充）。
重复表头在续片中识别并丢弃；"注："脚注行分离；单位行进入 `units`；首列序号连续性仅作辅助校验，
不单独证明不缺片。

**验收样本 GB 8978-1996 表 1（本次实测）**：coverage=complete，13 项
（总汞…总β放射性，序号 1–13 连续），0 条表 2 项目混入（无"悬浮物/氨氮"），
引用含 table_id/blockid/locator/chunk_ids（chunk-001）。contract 校验通过（complete 需全部成员
已处理且每项带 verified citation）。

**反例**：请求表 2 → ambiguous（base caption 缺失，无法证明归组）；序号断档 fixture →
coverage 降为 partial 并输出"缺片或解析缺行"警告；跨章节同表号 fixture → 两个独立逻辑表。

## 3. 正文枚举（task 3.3）

`prose_enum.py`：先经 scope_units 读全部成员单元（ordered、budget-aware、复用 SourceAdapter
composite-key 读取），逐 unit 汇编正文并记录 char span；条款抽取默认用确定性
`regex_clause_split`（markdown 标记容忍、重复条款按首次出现去重——chunk 重叠导致 3.1/3.2
重复出现，首次出现及其原文证据保留）；`extract_items_with_model` 已接入现有 OpenAI 兼容
模型配置，transport/invalid JSON/编造引句分别返回 model_failure:*，调用方不得输出 complete。
**本次实测未调用 LLM**（regex 路径覆盖验收样本；模型路径的失败语义由 fixture 验证），
正式模型抽取待 gold 审核后启用。

实测：

- **GB 18466 第 3 章**：members 3/3、complete，定义 3.1–3.4 齐全（修复了 markdown `##` 前缀
  挡住条款识别的问题），全部 citation verified；3.2 文本含"门诊、病房、手术室、各类检验室、
  病理解剖室、放射室、洗衣房、太平间"场所枚举。
- **GB 18466 4.1.1–4.1.5**：complete，五条齐全且各条文本不含 4.1.6（边界正确）；4.1 的单
  block 跨 chunk 布局经 scope 成员顺序完整读取。
- requires_span 语义：`locate_span` 在大 block 内定位字符跨度（fixture 验证）；定位失败返回
  partial/ambiguous + fail_stage=unresolved_span，绝不把 273-chunk 引用跨度当作子条款答案。

## 4. 文件完整分页枚举（task 3.4）

`doc_enum.py::enumerate_documents`：显式谓词 + 完整分页（不取 top-k）；每页重算
matched-set 内容 token（SHA-256 over 全部匹配行——首轮实现用 page token 导致页间必然
stale，已修正），active snapshot 前后一致校验；目录更新 → stale 拒绝混版本。

实测（page_size 缩小至 1–2 强制跨页）：年报 5/5 complete（跨页）、水资源公报 5/5、
GB3095 2/2（air-02 2012 + air-03 2026 两版本各自列出）。输出含匹配谓词、快照、总量、
已读量、unknown 元数据标记；只声称"读完全部匹配结果"。

## 5. 统一结果合同（task 3.5）

`contract.py::EnumResult`：query_id / workspace / catalog+source snapshot / scope_ids /
members_total+processed / items+citation(verified) / coverage_status / warnings / fail_stage /
predicate / read_token / model_calls。`validate()` 强制：complete ⟺ 全部成员已处理 ∧
fail_stage 为空 ∧ 每项 citation verified；stale fail_stage ⟹ coverage=stale。
confirmed（结构）、partial（关联）、complete（答案）三种语义分离，fixture 覆盖。

## 6. 测试与校验

- `uv run pytest tests/`：**90 项**通过（63 项结构 + 27 项枚举行为反例：caption 分型、
  前向/后向归属、跨章节同号、rowspan/colspan、重复表头、序号断档、条款边界 4.1.5/4.1.6、
  编造引句、invalid JSON、complete 语义、doc-set token、分页 epoch、requires_span 定位）。
- Ruff 检查/格式、OpenSpec 严格校验、diff 检查通过；public 原文库与 MinerU 产物全程只读
  （本轮未重建目录、未改 recipe，枚举运行于已通过复审的 v4 目录）。

## 7. 已知边界

- 表 6 的 D1.4.1 片段（附录内表格）与 表 2 的括注 base 仍标 partial——附录归属和跨附录
  关联留给后续 span/locator 精化，不强行 confirmed。
- 模型抽取路径未在真实请求中启用（避免在 gold 未审核时产生"看似已验证"的输出）；
  启用时的配置与失败语义已固定并可复跑。
- 14 个空 sidecar chunk、10 份部分引用、4 个 requires_span 范围继续作为显式边界带入
  Gate 1 之后的任务。

停在 Gate 1 前：3.1–3.5 已交付并附实测证据，3.6 留给主 agent 审查。
