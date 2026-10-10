# Phase4 改进组1诊断：正文范围、跨单元顺序与完整引用（2026-10-08）

证据类型标注：**[原始历史]** round-1 已验收工件离线读取；**[原始产物离线读取]** 原 `__parsed__` blocks/tables（Gate-0 指纹 fccb2748… 已在评分代次对账）；**[构造测试]** 内存/临时 fixture；**[离线正式入口回放]** 经 `search.expand._expand_prose` + `answer._reverify_prose_items` 真实函数调用、fake 只读连接提供目录行，零网络/零数据库/零模型。

## 1. 原失败的真实调用路径（[原始历史]）

`answer.run_answer → expand_candidates → _expand_prose → read_prose_scope → "\n\n".join(u.text) → extract_clauses_regex → bind_citations → verify_citations → answer 侧 _reverify_prose_items → coverage 决定`。四处缺陷沿此路径叠加：

1. **条款边界（根因）**：`extract_clauses_regex` 把每条正文的 end 定为“下一个编号条款头，否则 len(text)”。prose-enum-003/pg scope `…:scope:4.3`（GB8978-1996，doc-b45c5102）6 个成员块中首块 a00e1705（2957 字）结构为：`## 4.3 其他规定\n4.3.1…\n4.3.2…\n4.3.3…\n4.3.4 对于排放含有放射性物质的污水，…GB 8703—88《辐射防护规定》。\n<table id="tb-b45c…-0001"…`——**4.3.4 真句在块内偏移 136..190，190 处行首即表1 的 `<table` 起点**（tables.json 表条目 tb-…-0001 的 blockid 正是 a00e1705）；其后 5 个成员（71860670/7861e856/8447a0b0/4353d898/f275d616）全是该节后续表分页块（首行为 `## GB 8978—1996`/`## 表 5 部分行业最高允许排水量`/`## 表5(续)`、内含 `<table tb-0004…0011`）。4.3.4 作为节内末条款，正文一路吞到裁剪后装配文本 EOF：**交付 20,636 字（归一 20,631），其中仅前 54 字属于条款本体，其余为表1至表5(续) 的 HTML**。同路径同样形态还有 prose-enum-002 的 4.1.2（4,008 字含表2尾）与 prose-enum-006 的 4.2 无子条款正文（2,273 字含表尾）——非孤例，故修复必须一般化（未硬编码题号/doc_id/长度）。
2. **跨单元 segments 声明顺序错误**：`bind_citations` 用 `sorted(touches, key=lambda x: x[2])`——x[2] 是**每单元各自从 0 起**的 rel_start。真实 4.3.4 的 6 段声明顺序变成 [7186…,7861…,4353…,f275…,8447…,a00e(136)]，装配序（a00e→7186→7861→8447→4353→f275）被打乱；构造复现：第一单元非零起点+第二单元零起点的合法续文，旧代码输出 [u2,u1] 反序（[构造测试]）。
3. **装配分隔符未表达**：`read_prose_scope` 的装配按 `char_start` 记账 +2 间隙，`_expand_prose` 用 `"\n\n".join(...)` 拼接；回读侧（生成 verify 与 answer `_reverify_prose_items`）用**裸拼接** `"".join(parts)`。真实算术：6 段裸拼接 20,626 字，交付 20,636 = 20,626 + 5×"\n\n"；归一后 20,631 = 20,626 + 5 个折叠空格——长度差即间隙字符本身，旧代码从不映射它。
4. **完整声明未被回读**：生成侧 `verify_citations` 与答案侧 `_reverify_prose_items` 都只验证 **≤120 字 quote** 在跨度内。4.3.4 的 quote（“4.3.4 对于排放…规定。”）真实且位于 a00e 跨度内，于是 20,636 字含表尾的整段交付照样 `citation_reverified=True`、coverage=complete——短引句为无来源尾文背书。

## 2. 修复合同落实（全部一般化，无题号/文档/长度硬编码）

- **边界**：`prose_enum.structural_cut_positions(units, text)` 汇总三类独立结构起点——目录 `unit_kind='table'` 的单元起点、行首 `<table` 对象、纯“表/图 N（续）”题行与 `# 表N/附录X` 标题行；`extract_clauses_regex(..., hard_ends)` 将每条正文终点改为 min(下一条款头, 其后第一个结构起点, EOF)。句中“执行表1的规定”、行内 `<sub>` 等内嵌证据不受影响（[构造测试] 断言保留）。`_expand_prose` 的无子条款 fallback 正文同样在第一个结构起点截断。
- **装配序与间隙**：`bind_citations` 多段声明改按 `u.char_start` 排序，并显式记录 `assembly_separator="\n\n"`；两侧回读（`verify_citations` 与 `_reverify_prose_items`）按声明序、用声明的分隔符重建原文比对。声明顺序≠装配序、重复段、漏段一律拒绝；文本比对用**空白折叠**（保留词/表格边界，非全删空白，非 gold 子串、非词集、无第二 LLM）。
- **全文背书**：数字跨度条目（有 int char_start/char_end）必须满足 `collapse(text) ⊆ collapse(重建跨度)`；quote-only 模型路径维持原语义（无数字跨度即跳过全文检查），C1 逐字合同不变。失败即 `citation_verified/citation_reverified=False` → 既有 coverage 决定将 partial/失败如实呈现（`problems` → partial；`citation_reverified False` → partial），修复后不再出现“表尾错误却 complete”。
- `read_prose_scope` 将目录 `unit_kind` 随 `UnitText` 带出（默认 "block"，兼容既有构造方）。

## 3. 修复前后对照（[离线正式入口回放]，明细 `replay-evidence.json`）

| 题 | 原交付 | 回放新交付 | 独立回读 |
|---|---|---|---|
| prose-enum-003 4.3.4 | 20,636 字含表1–表5(续) HTML；6 段声明乱序 | 53 字纯条款句，无表尾 | 4 条全 verified，problems=0，coverage complete |
| prose-enum-001 3.1–3.4 | 4 条 68/127/46/40 字（本无表尾） | 同集合，逐条 gold 覆盖 | verified，problems=0 |
| prose-enum-002 4.1.1/4.1.2 | 4.1.2 4,008 字含表2尾 | 31/128 字，gold 覆盖 | verified，problems=0 |
| prose-enum-004 五类别 | I类/Ⅰ类/Ⅰ类/N类/V类（16/50/50/26/149） | 类别投影保留，同名标签 gold 文本任一行覆盖即可 | verified，problems=0 |
| prose-enum-006 4.2 正文 | 2,273 字含表尾 | 48 字 | verified，problems=0 |

反例面（[构造测试]，tests/test_phase4_improvement1_prose_integrity.py）：错序/重复/漏段/坐标错位/真实 quote+尾部伪造句 → 生成 verify 与独立 `_reverify_prose_items` 双双拒收、quote 不变救不回；requires_span 非零 offset 合法正例、缺条款/空范围/预算 partial 语义保持不变。

## 4. 跨代耦合记录（不返工、不豁免）

- 已验收评分 r3 的 `main()` 按 A4 合同对 live 代码 SHA 校验：本轮 answer.py `c017606c→0cd30bc3`、fusion.py 不变、expand/prose_enum 不在其 code_anchors 集合——**旧评分 main 对新实现非零拒绝属正确跨代保护**；未给旧锚加豁免、未回写任何历史裁决或 adjudication（809/9/4/4 四张清单复算全匹配）。
- 两轮冻结矩阵 17+18=35 项以 `ENV_RAG_ASSESSMENT_SCRIPT` 指向已验收 r3 评分器、对**新生产代码**全过（矩阵断言的是评分判定语义，不依赖旧 answer.py）；r2/r1 评分器自测 10+6 全过；**r3 自测 13 项中 12 过**——唯一红项 `test_appended_fabricated_wording_breaks_declared_span_support` 的第二行断言（细类标签 `unsupported_declarations`）：新 `_reverify_prose_items` 在全文回读阶段就拒收该条目，评分器的“跨度不支持”细分类分支因此不再触达；**整题 final FAIL 判定保留**（该测试第一行断言通过）。此为已验收评分代次与改进后代次的预期语义耦合，r3 目录按边界条款保持字节冻结，不做修改或弱化，留主 agent 复核裁决。
- `pytest tests` 全套 468 项（454 基线 + 本组 14）一次通过；裸 `pytest` 会收集 reports/ 历史矩阵且缺 env 指向而读旧 adjudication——属跨代读态，不是实现回归，正式验收命令均带 `ENV_RAG_ASSESSMENT_SCRIPT`。

## 5. 未扩权声明

未运行 123/246 腿评测、无真实生成、无新配置代次、未勾 6.2/6.3/Gate4、未切默认路径、未改 gold/提示/模型/锚/历史工件；如后续需要 schema 重建或路由类改动，本组仅保留诊断未实施。
