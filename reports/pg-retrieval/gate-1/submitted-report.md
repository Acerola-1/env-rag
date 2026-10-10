# Phase 1 第 3 组枚举报告（tasks 3.1–3.5）

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
