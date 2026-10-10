# 改进组1 增量补正 r2：F1–F4 根因与修复

复现基线：新增验收 9 项中 7 失败 / 2 正例通过（`reports/pg-retrieval/phase-4-improvement-1-review/test_improvement1_review_r1.py`）。全部修复仅动本组允许的三个源文件与本组自有测试；旧工件、冻结矩阵、gold、配置锚、评分 r1/r2/r3 字节不变（见 `report-r2.md` 的清单复算）。

## F1 — 装配协议不受引用自报约束

**根因**。首轮把分隔符作为"声明"同时当成"重建规则"：生成侧 `verify_citations` 与独立侧 `answer._reverify_prose_items` 都用 `sep = cit.get("assembly_separator") or "\n\n"` 再 `sep.join(pieces)`。于是矩阵反例——

```
u1 = "前言\n4.1.1 " + "合法正文。"*40, u2 = "合法续文。"
citation.assembly_separator = "停车场允许无条件排放污水。"
item.text = fake_separator.join(真实片段)     # quote 保持不变
```

按被污染的 separator 重建后 recon 恰好等于 text，全文回读"包含"全文 → 两侧都判通过。quote 完全正确也救不回来，因为它验证的正是伪造出来的装配规则。第二个反例 `separator = 7`（int）直接 `'int' object has no attribute 'join'` AttributeError 逃出链路。

**修复**。引入唯一协议常量 `ASSEMBLY_SEPARATOR = "\n\n"`（`prose_enum` 顶部）：

- `read_prose_scope` 的单位间隙记账（`assembled_len += len(text) + len(ASSEMBLY_SEPARATOR)`）与 `_expand_prose` 的装配 join 都改用该常量——装配来源与验证规则同源单点；
- 两侧验证**只用协议常量重装配**；citation 的 `assembly_separator` 键只做**存在时核验**：非字符串或 != 协议 → 直接判 unverified/partial（不抛异常）。类型、允许值、实际装配来源三点全部锁定。

**保留面**（正例证明）：真实两个换行间隙、词边界（全文回读用 collapse 而非删空所有空白——"in coming"≠"incoming"）、`requires_span` 非零 offset、正常跨段续文：冻结矩阵 2 项正例 + 自有跨段用例 + owning 合法跨段用例全部 complete。

## F2 — 数值跨度声明不可被类型损坏绕过

**根因**。首轮判定"是否数值跨度条目"用的是**值的类型**（`type(char_start) is int and type(char_end) is int`）。矩阵三例把声明字段改坏（`null_start`：None；`string_start`："0"；`missing_end`：删掉 char_end），条件变 False → 条目**静默降级为 quote-only**——`text` 尾部追加的"停车场允许无条件排放污水。"24 字伪造句不再被全文回读检验，quote 完整正确照样两侧通过。

**修复**。声明判定改为**键存在性**：`declares = "char_start" in cit or "char_end" in cit`。

- 键在（任一侧）即数值跨度条目；此时必须两侧键都在且都是真 int（`type(...) is int`，排除 bool/str/None/float/缺侧），否则**专属拒绝**：生成侧 `supported=False`，独立侧 problem `"... declares a numeric span with malformed coordinates ... refusing instead of downgrading to the quote-only path"`。绝不回落 quote-only；
- char_start/char_end（装配坐标）与 unit_rel_start/unit_rel_end、segments rel_start/rel_end（raw 单位坐标）各按自己的协议校验（bool 拒绝、越界拒绝、lo==hi 拒绝），两侧一致执行；
- **真正未声明数值跨度**（两个键都不存在）= 模型 quote-only 路径，保持既有语义：不新增全局数字坐标要求，不放宽 C1 逐字声明合同；
- 声明跨度但**完全不交付 text 键**的 Gate-2 r8 历史形状保留通过（quote==整个跨度逐字）；text 键存在但损坏（非 str/空）→ 拒绝。

证明：矩阵 null/string/missing 三例双侧拒绝（`test_malformed_declared_numeric_span_cannot_downgrade_to_quote_only`）；真 quote-only 正例保留（`test_genuine_quote_only_model_path_remains_supported`）；全套含 gate2 r8 回归通过。

## F3 — 结构边界需要归属依据

**根因**。首轮把所有行首 `<table`、纯表/图题注、表标题、附录头、table-kind 单位起点一律当硬边界。矩阵构造"本条限值如下，表内规定属于本条：→ 内嵌表 → 本条补充要求 → 4.2 下一条"因此被切在表前：4.1 交付只剩冒号前一句，表内值与"每日监测一次"丢失，而 coverage 仍判 complete——截掉要求还不吭声。

**修复**（`structural_boundaries(units, text) -> (cuts, notes)`，无题号/doc_id/固定长度硬编码）。对每个候选标记，看它**前面最近一条非空行**：

| 前导行形态 | 判定 | 行为 |
|---|---|---|
| 以"：/:“结尾 **且** 提及 表/图 对象 | attributed | 不是边界：条款体穿过表格与后续正文，直到下一条款头 |
| 以"：/:“结尾但**无**对象指认 | ambiguous | 切（安全默认）+ 记 ambiguity note；被交付项在该位裁剪时 `_expand_prose` 把 complete 降为 partial，note 随 warnings/boundary_ambiguities 发布 |
| 句子符号结尾/页眉/无内容 | independent | 干净硬边界（原首轮行为） |

真实数据实证（离线读取原始 sidecars 佐证）：

- GB8978 `a00e…` 4.3.4 句后同一 block 内即表：前导行 "…还须符合 GB 8703—88《辐射防护规定》。**…**（句子结尾、无表指认）→ clean cut → 4.3.4 保持 53 字真句，表尾仍被排除 ✅；切点后残留仅 28 字页眉 "GB 8978—1996\n\n\nGB 8978—1996"，非句子 → 不触发 ambiguous；
- GB18466 TABLE@175/@1956 前导行是页眉 "GB 18466 — 2005" → clean cut，4.1.1/4.1.2 真句保持 ✅；
- GB3095 4.2 前导行 "…一、二类环境空气功能区质量要求见表 1和表 2。**…** —— 提及表但**以句号结尾**：这正是必须"冒号+指认"双条件的原因；若只按"提到表"豁免，48 字真句会被整张表吞回 ✅ 保持 clean cut；
- 物理 table-kind 单元起点同样受归属规则约束：attributed 孪生例中条款穿过表单元延续到下一编号条款（自有用例 `test_table_kind_unit_with_attributed_intro_is_kept_not_cut`）；页眉前导时仍照旧切。

**不是全保表尾，也不是全拒表格**：内嵌证据（`<sub>` 等句中 HTML、句子中段"执行表1的规定"）保留；无指认的宣告式冒号 → 显式 partial + 记录，绝不静默 complete。

表枚举通路不消费本边界（`_expand_table` 独立路径），自有用例证明表格全部合法行仍保留。

## F4 — 回放无金标输入 + owning 入口

**根因 A（输入泄漏）**。首轮 `_replay` 把 `gold.expected_items` 解析成 `["4.3.1","4.3.2","4.3.3","4.3.4"]` 当 `requested_clauses` **输入**传给 `_expand_prose`——原问题只请求 4.3 节。金标清单进入了输入路由。核验用 `len>=3` 与"任意命中"，掩盖漏项/多项。

**修复 A**。`_request_from_question(question, scope_number)`：剥 GB 号后解析原文数字，仅把**比 scope 更深**的编号作为输入（显式条目请求），否则 None（章节/节请求 → 子项由源结构发现）。与已存 round-1 trace 记录的输入对照（`replay-evidence-r2.json`）：

| qid | 问题解析输入 | 已存 trace 记录 | 一致 |
|---|---|---|---|
| prose-enum-003 | None | None | ✅ |
| prose-enum-001 | None | None | ✅ |
| prose-enum-002 | ["4.1.1","4.1.2"] | ["4.1.1"] | 问题文本明确点名两条；round-1 记录只存一条——trace 自身的输入解析漏记观察项（不属本组组件，未动路由件，如实记录） |
| prose-enum-004 | None | None | ✅ |
| prose-enum-006 | None | None | ✅ |

gold 仅事后：`_set_match` 按 **编号+全文+来源** 一对一配对（来源=workspace/doc_id/单元集内/citation_verified/citation_reverified 全真），列 missing/extra；五题均 `missing=[]、extra=[]`、0 回读问题、complete。prose-004 OCR 罗马标签保留源样（`require_clause=False` 的说明写在 helper 内，仍全文+来源一对一）。

**修复 B（owning 入口）**。新增 `tests/test_phase4_improvement1r2_owning_replay.py`（6 项，全部经 `answer.run_answer`）：

1. **原始产物 pass-through**：prose-enum-003 用**已存 5.3/5.4 重放报告原文件**（`phase-4-round-1/inputs/pg/prose-enum-003-{fusion,rerank}.json`）+ **已存身份材料**（其 `identity_before` 注入 `_capture_identity`，前后置一致、零漂移）+ 原始 sidecars（真实 `PARSED_ROOT`）+ fake 只读连接（scope 成员/单元行来自已存 trace 记录）。发布态：complete、恰好 4 条、4.3.4 交付 **53 字**、无 `<table`/表尾、模型调用 0。
2. **合法跨段**：构造两 block（真实 "\n\n" 间隙）读取注入 → complete；发布态 citation 携带 assembled-order segments + 协议 separator；独立回读 0 问题。
3/4. **篡改条目**（伪 separator 重拼 / char_start=null，quote 不变）：在**真实 expand 完成之后**注入到条目（expand 先被真实调用——不是 mock 恒真；expand/验证函数一律真跑），owning 独立回读拒绝：partial、专属 problem 文本、`citation_reverified=False` 随发布项保留（不静默丢项伪装干净）。
5/6. **结构案例经 owning**：attributed 内嵌表 → complete 且 总汞/0.05/每日监测一次 全部在发布文本；bare 冒号 → partial 且 `boundary_ambiguities`+警告随发布。

边界：真 `asyncpg.connect`、`httpx.AsyncClient.post` 均装"必须不发生"炸弹；fake 连接记录全部 SQL 且用例断言只读。发布态终报落盘 `owning-replay/*/answer-runtime-latest.json`（6 份）+ `owning-replay-evidence.json`；复算脚本 `generate_owning_evidence.py` / `generate_replay_evidence_r2.py`（离线，重跑再生）。

## 泛化性说明

规则全部按结构形态（冒号/对象指认/键存在性/协议常量）定义，无题号、doc_id、字符长度硬编码；真实数据四文件（GB8978/GB18466/GB3095/GB3838）与矩阵构造同向；篡改/伪造的正反例对称覆盖。prose-002 的 trace 记录输入少一条属历史请求解析观察，不在本组改动面。
