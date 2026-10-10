# Phase 3 / 5.5 执行提交：精排后完整范围展开与按题型回答（2026-10-08）

## 0. rev-4 补正（answer-review r4：D1–D2，2026-10-07）

r4 复审：原 377 项与三轮冻结矩阵保持，C1 连续逐字声明与 A3 失败出口结论确认；新矩阵 4 项中 2 正例通过、2 反例失败，两处剩余边界按 `handoff-phase-3-5.5-fixes-r4.md` 仅修 D1/D2，不返工已通过部分。

- **D1 已读范围 ≠ 已回答范围**（`source_kind` + `_bound_fills_slot` 分源类型）：表格行是**原子断言单元**（绑定行结构填槽，语义不变）；正文/context_only 的引用范围可以大于断言范围——主体/平均时间只按**声明自身**（已经 C1 证明为来源连续逐字片段）核对，段落里"读了但没回答"的另一主体、另一平均时间不再填槽。两版本只答总汞：总汞 claim 保留为已核实证据，两版本总镉槽显式缺失 → `incomplete_answer_coverage` + partial。不新增 LLM、不自动补模型未输出的项目、不以全拒绝正文达标；both-subjects 正例、多项联合、多版本/多平均时间正例原样保持。
- **D2 同一括号内是多个局部单位断言**（`_unit_note_segments`）：保留括号边界，括号内部继续按标点分割句段——`（总汞单位为mg/L；pH为无量纲）` 与两个括号 `（总汞单位为mg/L）（pH为无量纲）` 归属完全一致：总汞从其明确 mg/L 说明得 `source_context`（complete），pH 的无量纲**不跨对象传播**；无主体的整表句段（"（均为无量纲）"、"（均为无量纲，单位略）"）经内部分割后仍整表生效。行单位列优先、单对象括号、标题隔离与缺单位正负例全部保持。
- 验证：冻结 `tests/test_answer_review_r4.py` **4/4**（missing-cadmium/combined-bracket 反例 + both-subjects/separate-brackets 正例）、r3 **6/6**、r2 **7/7**、r1 **9/9** 未改动；自有矩阵 +2（仅答总镉的镜像负例、参数化"括号内含标点仍整表"正例）共 38 项；全套 **383 passed** = 377 + r4 4 + 新增 2。Ruff check/format（src+tests，78 文件）、OpenSpec strict、`git diff --check`、凭据扫描（0 敏感值命中）净；manifest 重算 **25/25 SHA**（r4 冻结入册；answer.py/test_answer.py/report/manifest 之外全部字节一致，历史运行代次未动）。
- 真实调用边界：本轮 **0 新真实模型/embedding/rerank/DB 请求**，不重跑检索/真实合成；fixture 成功与真实端到端合成（两个历史 503）继续分列——真实合成仍未成功验证。5.6/Gate3/Phase4 不进入。停 5.5 检查点待复审。

<details><summary>rev-3 补正（answer-review r3）</summary>

## 0a. rev-3 补正（answer-review r3：C1–C3，2026-10-07）

r3 复审：原 366 项与两轮冻结反例保持、A3 失败出口保持；5 项新反例集中于**词集不构成关系证明**、**问题与回答缺少逐要素合同**、**标题主体给括号断言背书**。本轮按 `handoff-phase-3-5.5-fixes-r3.md` 统一修 C1–C3，不新增第二次 LLM 调用。

- **C1 明确放行的声明证明**（`_prose_claim_problems` 重写，`_extract_terms` 移除）：正文类来源的 claim 只接受**来源连续逐字声明**——应用侧允许附加的装饰仅为版本年份前缀（"2012版…"）与结尾标点，核心句必须是绑定条目原文的连续子串，否则一律 `model_failure`（partial）、不补问。内容词/数字的集合匹配不再是放行证明：总汞 0.1 与总镉 0.05 数值互换、或从句重排（每个词和数字都存在于原文）均被拒。r2 的逐字正文正例与"停车场"编造反例原样通过；r3 正确正文正例（complete）与互换反例（model_failure）经 owning 入口通过。
- **C2 逐槽集合合同**（`_question_slot_terms`/`_slot_subject_hit`/`_bound_fills_slot` 取代 B2 交集接地）：必要槽 = **版本 × 主体/指标 × 量/平均时间 × 等级**，全部由问题文本导出——分母不再因"已读行恰好没有该词"而缩水（头部等级词"二级"保持为必要槽，答对的一级行只是离题证据）；主体身份按**整词精确**而非子串：PM1 槽不能被 PM10 行填（ASCII/数字两侧必须非词字符边界；CJK 主体按包含；"PM2.5（细颗粒物）"类单元格可填）；**多回答项允许共同填槽**，多指标比较不再要求单条 claim 同时携带全部指标；缺槽 → `incomplete_answer_coverage` + partial，`missing_answer_editions` 按槽（label/主体/平均时间/等级）列举。展示字段 `question_elements`（主体+平均时间）与 r2 冻结断言取值一致，新增 `question_levels`。
- **C3 单位断言的局部作用范围**（`_unit_note_segments` + `_note_applies_to_row` 重写）："无量纲"归属只读其**所在局部句**（括号组独立成段，段外按标点分割）——`表 1 总汞及pH限值（pH为无量纲）` 中标题并列提及总汞不给括号断言背书，无单位的总汞行落 `unverified_absent` → partial；未提名主体的"无量纲"句段（"表 8 无量纲控制指标"、"（均为无量纲）"）仍为整表声明。行单位列最优先、pH 行归属自身、既有缺单位正负例全部保持。
- 验证：冻结 r3 **6/6**、r2 **7/7**、r1 **9/9** 未改动通过；自有矩阵新增 5 项（C1 带版本前缀逐字正例、C1 从句重排拒绝、C2 四槽联合完成正例、C2 缺平均时间负例、C3 括号整表声明正例）后共 36 项；全套 **377 passed** = 366 + r3 6 + 新增 5。Ruff check/format（src+tests，同 reviewer 口径）、OpenSpec strict、`git diff --check`、新工件凭据扫描（0 实际值泄漏）净；manifest 重算 24 SHA，r1/r2/r3 三轮冻结、rerank/fusion/local_adapter/cli 与历史运行代次全部原样。
- 真实调用边界：本轮 **0 新真实模型/embedding/rerank/DB 请求**、不重跑检索/真实合成；fixture 合成成功与真实端到端合成（两个历史 503）继续分列——真实端到端合成仍未成功验证。5.6/Gate3/Phase4 不进入。停 5.5 检查点待复审。

</details>

<details><summary>rev-2 补正（answer-review r2）</summary>

## 0b. rev-2 补正（answer-review r2：B1–B3，2026-10-08）

r1 复审：A3 失败出口通过并保持；A1/A2 点名反例通过，但 6 项新反例证明关系核验仍是部分文字匹配。本轮按 `handoff-phase-3-5.5-fixes-r2.md` 建立**完整事实字段绑定**，不逐例追加正则，不再调用 LLM 做二次验证。

- **B1 完整测量关系**（`_claim_relation_problems`/`_prose_claim_problems`）：
  - 值 token **带符号且完整**：`-35` 与 `35` 不同、`+35` 为显式正号同源值、`3` 永不被 `35` 子串放行、PM2.5 内嵌数字按词形排除；“24小时平均”整体按量词剥离，其数字不得冒充值（`_AVG_RE` 含数字前缀，先剥离再取值）。
  - **单位必须绑定**：数值后的任何单位串（不限 lexicon）与绑定行的单位候选集做归一等值核对——`g/m³` 对源 `μg/m³` 是百万倍量纲错误，直接 `model_failure`；无法证明等值换算即保守拒绝，等值正例（含空格分隔 `35 μg/m³`、`+35`）经 owning 入口验证通过。
  - **平均时间/量核对**：claim 断言的小时/日/年平均必须逐字出现在绑定行（源“年平均”配“小时平均”拒绝）；级别列规则保留。
  - **正文声明不再免检**：prose 路径“无数字”≠支持——除引句逐字外，claim 的内容词必须逐词出现在绑定条目原文（应用侧保守词集，不做开放语义）；“停车场允许无条件排放污水”+ 真实引句 → model_failure；同 fixture 的逐字正文正例保持 complete。
- **B2 问题要素覆盖**（`_question_element_terms`）：必要集合 = 版本 × **问题∩已读行的接地要素**（如 pm2.5×年平均；词形来自 tokenizer∩行内容，不硬编码 id/年份/污染物名）。两版本各答 PM10（真实合法行/引句/单位全对）不再 complete：合法但不相关的行保留为诊断证据，缺失要素记 `incomplete_answer_coverage` + partial；`test_requested_pollutant_cannot_be_replaced_by_other_verified_rows` 通过。
- **B3 单位优先级与作用范围**（`_fact_unit_evidence`/`_row_unit_cell`/`_note_applies_to_row`）：行自身单位列**最优先**（总汞 mg/L 不受“（pH为无量纲）”表注影响）；无量纲声明必须**绑定适用对象**——仅当表注不提名其他主体（整表注）或本行主体被表注提名（pH 行）才生效，绝不整表传播；单位列→适用表注→表头/caption 词库的次序保持，无法裁决即 `unverified_absent`→partial。配套正例：同表内 pH 行 dimensionless、另一行按自身单位 complete。
- 大小写归一集中在关系层（`_norm_ci`：元素接地、主体、表注归属、选择评分），**原始回读逐字节判等不动**。
- 全部验证为 fixture/只读路径：0 新真实模型/embedding/rerank/DB 请求；fixture 合成成功与真实端到端合成（两个历史 503）继续分列，不冒充。

冻结 `tests/test_answer_review_r2.py` 未改动且 **7/7**；r1 冻结 9/9、原 357 项全保持；自有矩阵 +2 必要正例后 **366 passed**（=357+7+2）。Ruff/format（src+tests 同 reviewer 口径）、OpenSpec strict、diff、manifest 重算、rev2 全代次凭据扫描 0 泄漏；历史运行代次全部原样保留，仅代码/测试/报告/manifest 更新。A3 与 5.1–5.4/Gate2 结论不动。

</details>

<details><summary>rev-1 补正（answer-review r1）</summary>

## 0c. rev-1 补正（answer-review r1：A1–A3，2026-10-08）

主 agent 验收：原 343 项独立复跑保持、18/18 引用回读与范围展开证据保留，9 项 owning 反例失败，集中 A1–A3；本轮按 `handoff-phase-3-5.5-fixes.md` 仅补三组，0 新真实模型/embedding/rerank 请求，两个历史 503 不冒充成功调用。

- **A1（引用真实≠声明被支持）**：`_verify_model_items` 改为结构化关系核对——声明必须通过①数值按**独立完整 token**（嵌入字母数字串的 PM2.5 数字不计，"3" 永不被 "35" 子串放行）匹配 quote/绑定行单元格/应用版本标签的**年份**（仅 \d{4}，且 19|20 开头；版本身份不为无关数值背书）；②主体 = 绑定行「污染物/项目/指标/名称/要素/术语」列单元格须现于声明（停车场类错配拒绝）；③级别列：claim 含一级/二级…时，其数值必须等于该表头列的单元格值（一级 15 冒充二级拒绝）；④单位 lexicon：claim 单位词必须现于该行单位上下文（单位列/表头/caption/units/footnotes），"吨"对 μg/m³ 拒绝；"无量纲"仅当来源显式声明。关系问题 → `model_failure`，全拒绝同时正例保持。
- **A1-5（确定性 fact 单位）**：`_fact_unit_evidence` 依序取 行单位单元格→表头/caption/units 文本 lexicon→显式「无量纲」；均无 → `unverified_absent`：数字作为已验证证据保留，coverage 显式 **partial**，绝不从 gold/常识补 mg/L。**真实重放**：只读重跑 fact-002（`phase-3-answer-r2/`）：实际网格 3 列（序号|污染物|最高允许排放浓度）无单位列、caption 无单位 → `unit_status=unverified_absent` → coverage partial（原 phase-3-answer/ 的 complete 结论作废保留为历史，本片范围与 13/13 回读不变）；矩阵同形状三列反例 + 4 列单位正例 + 无量纲正例 + caption 单位正例全绿。
- **A2（读两版本≠答两版本）**：绑定成功后按**解析目标推导的必要版本集**（expected，非 query_id/年份硬编码；无版本锚的多文档比较则所有已确认 section 为必要要素）核对已回答集；缺项保留已核实 claim、`incomplete_answer_coverage` + partial，summary 不算回答项。
- **A3（失败出口闭合）**：`asyncpg.connect` 取得移入统一 try/finally 边界——连接失败仍执行后置身份采集（或记录采集错误）、写失败终态与显式零答案服务账本、仅关闭真正取得且自有的连接、抛出使 CLI 非零；后置漂移/采集失败/冻结不符改为「写报告后**抛出**」，原 run 错误与后置错误并存（报告含 `failure`+`identity_drift`/`identity_after_error`+`results` 供诊断，但不再作为可信 complete 正常返回）。CLI 级补正/负例（成功才 `Answer OK`；抛错必 SystemExit 且无 OK 字样）。
- 证据表述更正：`lightrag_llm_cache` 前后 16514 不变只是**漂移检查**，零缓存读写的证明是「直接 HTTP、无 hashing_kv/LightRAG 代码路径」本身；运行代次文件 SHA 由入口计算并记录，与「已验收摘要比对成立」是 reviewer 侧的核对事实，二者不再混同；syn-004 的 503 更具体上游根因**未独立确认**（/models 探针仅证明端口有服务应答）。
- 本轮全套 **357 passed** = 原 343 + 冻结验收 `tests/test_answer_review_r1.py` 9/9 + 自有矩阵新增 5 项正负例；原 24 项矩阵语义保持。

</details>

范围：仅 5.5。5.6 Gate 3 总结与 Phase 4 两轮对照**不进入**；不跑 31 题质量指标，不宣称 Gate 3 通过。原 319 项测试与全部历轮冻结断言保持未动（本轮全库 **343 passed** = 319 + 新增 `tests/test_answer.py` 24 项矩阵）；`rerank.py`（e2a8e089…）、`fusion.py`（be1cd4c5…）、`local_adapter.py`（0bbad976…）与历轮冻结 SHA 全部未变；gold 与 `.env` 未改。

## 1. 集中入口

- `src/env_rag_final/answer.py`：`run_answer(report_dir, query_ids, *, rerank_report_path, fused_report_path, transport, conn, values, allow_model)`；CLI `uv run env-rag-final answer --query-id … [--fused-report … --rerank-report …] [--allow-model]`。
- 输入合同：消费已验收 5.3/5.4 运行时报告（query/workspace、pg.catalog_snapshot_id、typed_targets、每项 chunk/doc/SHA/全部 paths、原始精排分数与 degraded 逐字段透传）；回放来源与代次显式记录（文件 SHA + started/finished + 代次 identity 绑定），回放代次的 source/catalog/search/gold/八表计数与本轮活体冻结采集不一致时在**任何读取之前**拒绝（`replay-generation` 终态，`_bind_replay_generation`）。
- 守卫顺序沿用历轮合同：config guard → gold SHA → 回放文件解析（全部零接触）→ `_capture_identity` 前置 → 回放代次绑定 → 逐题展开/回答 → 后置采集 + drift + 统一失败终态（`live["partial"]` 在任何 await 前注册；原错误与后置错误并存；每题服务凭证在交换完成即发布）。全部证据经 `_sanitize_evidence`（整份报告在唯一落盘点净化）后截断。
- 展开全部走**正式入口**：`search.expand.expand_candidates` →（`enumerate_table` / `read_prose_scope`+`extract_clauses_regex`+`bind/verify_citations` / `enumerate_documents` 全量分页）；未重写引用/coverage 规则。回放重建忠实保留真实 `run_query` 的 code_exact **文档级候选**（5.3 将其存于 typed_targets；缺失会静默禁用 C5 标题确认路径——已按原形状重建，正式 `search-query --expand` 控制对照证明重建后与正式入口逐字段一致）。
- 范围选择语义：5.3 的 `targets_resolved`+typed targets 定义答案范围（解析目标不在回放候选集时**补注册**后完整读取——发现 top-k 从不定义成员集）；精排顺序只给优先级；非目标候选文档照常展开并落盘（`selected:false`），但不能降级所选范围；`ambiguous/partial` 语义（原表2歧义、prose 标题无法确认、requires_span 未定位）原样保留，生成成功不升级 complete。
- 独立回读：表行按绑定片 raw grid 行坐标重读（`tables.json`），正文条目按 raw 单元块文本的 unit-relative 跨度重读（含跨 unit segments 与 requires_span 偏移）；答案层的 `citation_reverified` 与读层的 `citation_verified` 分列。
- 按题型：fact/file/prose/table 全部确定性渲染（0 答案 LLM）；synthesis 需显式 `allow_model` 授权，预算=每运行 1 次（超出 `model_budget_refused`，上下文超 40k `model_budget_exhausted`，二者均 refuse-not-truncate、报 partial）；claim 校验=版本标签由应用绑定（大小写不敏感、标签冲突在调用前拒绝）、quote 逐字在该版本本轮读取上下文、数值/日期按**完整带符号 token** 核对且版本年份只证身份；`openai_complete_if_cache`/LightRAG 实例化完全不使用，纯 HTTP `/chat/completions`——零答案缓存读写的证明是该代码路径本身；`lightrag_llm_cache` 行数（16514）前后一致只是**漂移检查**，不单独充当零读写证明（rev-1 更正，见 §0）。claim 校验并通过完整测量关系核对：带符号完整值 token、主体、平均时间/量、级别列、单位后缀等值绑定与正文逐词支持（answer-review r2 B1/B2）。

## 2. 验收矩阵（`tests/test_answer.py`，24 项，全部经 owning 入口 `run_answer`）

类1 完整成员：精排把续片 chunk 置最低分（0.02）仍两片 13 项、行引用独立回读 13/13；解析目标不在候选集时补注册后全读；噪声文档歧义记录不能降级所选范围（13 项 complete + `selected:false`）。
类2 条款边界：3 章整读 3.1–3.4 complete；请求 3.1 至 3.5 缺 3.5 → partial 且 4 条已读条目保留；requires_span 偏移由正式读层合同承接（跨度不合法=unresolved 不升级）。
类3 文件集合：GB8978 全谓词分页 2/2、同编号不同版本按 doc_id 独立、不合并、零项枚举不 complete。
类4 保守语义：fused stale/missing 直接返回（0 展开读）；rerank degraded 回放 → 明确 degraded 回答允许（源完整时 complete + "never a claimed rerank success"）；fusion 预算截断 → 永不 complete；rerank absent → 优先级回落 fusion 顺序、0 伪造分数。
类5 模型路径：单次调用+应用绑定 edition/快照+上下文 SHA+净化 messages/raw 回执；缺版本 → `incomplete_conditions` 0 调用；正确引句配 44μg/m³（数值不在引句）→ `model_failure`；401/非法 JSON → 失败回执保留、不伪造；fixture key 写入响应 → 终态 `<redacted>` 且 claim 同时因数值不支持被拒；`allow_model=False` → `model_not_authorized` 但两 section 上下文仍完整核实（先核实后调用）。
类6 入口与守卫：未知题号在身份采集前拒绝（identity 调用 0、conn 查询 0、零调用账本落盘）；回放代次 source_fingerprint 不同 → 绑定拒绝且 0 目录读；workspace 覆盖 env → 身份采集前拒绝；回放题目不符 → 绑定拒绝且终态含凭证；表2歧义保留 ambiguous。

## 3. 有界真实验证（各阶段回放/真实分列）

**Run A — fact-002（回放：已验收 phase-3-fusion latest + phase-3-rerank-r2 精排代次，SHA/identity 双绑定；本轮真实：身份守卫读取 + env_rag 只读展开/回读 + sidecar 只读，0 答案模型）**
表1 `members 2/2`（两片都读，含最低分续片）、13 行原始坐标、独立回读 13/13 problems[]；答案行=总汞 0.05，绑定 caption「表 1 第一类污染物最高允许排放浓度」；`model_calls_used 0`；前后身份 frozen。
初版（`phase-3-answer/`，历史保留）判 complete；A1-5 补正后只读重跑（`phase-3-answer-r2/`，rev-1）：实际网格 3 列表头无单位列、caption 无单位声明 → `unit_status=unverified_absent` → **partial**（数字证据保留，不从 gold/常识补单位）。初版 complete 结论作废，r2 为当前结论。

**Run B — table-enum-001 + prose-enum-001（回放输入：本轮新建 PG-only 融合 phase-3-answer-fusion，只读 PG、0 模型/embedding/精排，5.3 的显式 PG-only 语义；本轮真实：展开读取与回读）**
13/13 行（两片 4+9，序号 1–13 完整、续片在内）complete；GB18466 3 章 3.1–3.4 complete、4/4 引用独立回读；rerank 缺回放=显式 absent 标记；`model_calls_used 0`。→ `phase-3-answer-enums/`

**Run C — syn-001（建议题）条件核实失败 → 公开 incomplete，0 调用**
正式控制 `search-query --expand`（`phase-3-answer-syn-check/formal-expand-control.json`）：C5 仅确认 2026 版 scope:4.2 一个范围，2012 版无可确认范围——**与 5.5 回放路径逐字段一致**（同 doc/scope/items/coverage），证明不是回放缺料而是条件无法完整定位。答案层按合同保持 `incomplete_conditions`（缺版本上下文）、0 模型调用、gold 不动。→ `phase-3-answer-syn-check/`

**Run D — syn-004 定位成功 + 唯一必要请求遭服务端 503 → 公开失败保留**
PG-only 融合（`phase-3-answer-fusion-syn`，0 模型）→ 两版本/两要素范围均确认：GB3838-2002 scope:3（5 项）+ GB3095-2012 scope:7（3 项），8/8 独立回读 problems[]，只读核实运行（`--allow-model` 关）0 调用；随后授权唯一必要请求：`http://127.0.0.1:8787/v1/chat/completions` 返回 **http_503**（64ms，失败回执落盘，无伪造合成）；补跑一次同请求仍 503（两次回执分列 `phase-3-answer-syn/` 与 `phase-3-answer-syn2/`）。只读健康探测（`/models`，不带密钥、非模型请求）得到 401——仅证明该端口有服务在应答，**503 的更具体上游根因未独立确认**，两次失败均原样公开。按合同保留 `model_failure` partial、不再消耗请求；条件核实（范围+引用）全部真实通过，失败仅在服务侧。

## 4. 检查与边界

全套 343 passed；冻结断言未删未弱化；Ruff check/format 净；`openspec validate --strict` valid；`git diff --check` 净；新代次工件凭据扫描 0 实际泄漏（配置密钥值逐一比对）。rev-1 补正同上 §0。生产 PG/public 八表/MinerU/目录/索引全程只读，未实例化 LightRAG/ClientManager，未迁移/重解析/embedding；本轮未重复 keyword/embedding/local/rerank 整轮。不宣称检索质量提升、不宣称 Gate 3；5.6/Phase 4 未进入。停 5.5 检查点待主 agent 复审。

## 5. 交付物

- `reports/pg-retrieval/phase-3-answer/answer-report.md`、`answer-manifest.json`（本文件）
- 运行代次：`phase-3-answer/`、`phase-3-answer-enums/`、`phase-3-answer-syn-check/`（含正式控制）、`phase-3-answer-fusion/`、`phase-3-answer-fusion-syn/`、`phase-3-answer-syn/`、`phase-3-answer-syn2/`（均 `*-runtime-latest.json`）
- 代码：`src/env_rag_final/answer.py`、`src/env_rag_final/cli.py`（`answer` 命令、`--rerank-report`、`--allow-model`）
- 测试：`tests/test_answer.py`（24）
