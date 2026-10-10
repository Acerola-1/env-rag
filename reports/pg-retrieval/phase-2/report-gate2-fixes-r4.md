# Phase 2 Gate 2 第四轮补正报告（C1–C5）

主agent第五轮复审（2026-10-06）：168既有测试/原40反例通过，新增2反例失败，Gate2仍未通过。4.5金标已审核冻结到独立副本，4.4/4.6仍未完成；类别坐标5条不合格，来源合格正文仅4/6，空discovery回填仍存在。完整结论见../gate-2/review-r5/review.md。以下执行agent提交及未审核状态保留历史，不替代主agent结论。

执行日期：2026-10-06。范围：按 `handoff-phase-2-fixes-r4.md` 修复第四轮 7 项生产入口反例。**停 Gate 2 复审；4.4–4.5 未勾选，4.6 留主 agent；gold 仍全部 unreviewed，指标未填。**

## 独立反例

- 原 33 项断言（13+11+9）：**保持通过**。
- 第四轮 7 项（`tests/test_gate2_review_r4.py`）：**7/7 通过**。
- 完整测试 **168 passed**。

## 各项修复

### C1 兜底答案走完整引用管线

无子条款 scope 的兜底答案（如 GB3095 4.2）不再手造 `citation_verified=True`：full body（**取消 400 字静默截断**）→ 记录去标题后的真实偏移 → `bind_citations` 绑定 workspace/doc_id/snapshot_id/unit_id/locator/unit 相对跨度/chunk_ids → `verify_citations` 独立按逐字子串重判 → 重算 unverified/coverage。真实 prose-006 引用现在可独立回读（workspace/doc/snapshot/unit 齐全、unit_rel 跨度命中原文）；超预算场景不再伪装 complete（隔离反例通过）。

### C2 投影评分收紧

- **同名子行消费仅限显式 name 投影**：full-cells / {seq,name} 投影下，同名不同值的额外行（总汞 999）→ extra，exact=False（反例通过）。
- **文件枚举完成状态进入质量判定**：`document_enumeration` 的 coverage/fail_stage/members 状态传入 `_evaluate_enum_set`；partial/budget_exhausted 的分页读取即使候选恰好等于 gold 也判 not exact（反例通过）。

### C3 discovery 与枚举答案分离

`SearchResult` 新增 `discovery_candidates`：展开前快照预算内排名候选（并排除 document_enumeration 标记），`to_dict` 单独输出。recall（doc 与 evidence 两口径）只从 discovery 列表计算；枚举答案只进集合检查。反例：发现 0 候选 + 枚举答对 → `evidence_recall=0`、`list_doc_recall=0`、`exact_match=True`——两者互不倒灌。B3 文件题进枚举的行为保留。

### C4 表格 gold 验证逐 cell

反向子串放行（`head in row or row in head`）废除。表格 quote 按单元格等值核对：quote 拆分为 cell 序列，必须是某真实网格行的**逐 cell 连续投影**（允许 colspan 展开的重复单元格投影）；真实行+编造尾值（`0.05 | 原文不存在的999`）被拒（反例通过）。31 题 gold 重建后全部通过该严格验证。

### C5 范围发现与答案投影闭环

- **prose-004（GB3838 §3 水域功能分类）端到端打通**：标题确认（scope title vs 请求内容词，可审计记录 matched_terms/relaxed 标志；`见表N` 的表引用 scope 排除出 prose 确认）→ 正文按类别句切分（`_split_category_sentences`，≥3 个 N类/级 标记才触发）→ 每类一条 item、保留源 OCR 罗马数字原样（I/Ⅰ/Ⅰ/N/V）、逐条 bind+verify → **EXACT**。
- **prose-003 gold 完整四条要求**（附录A混合污水/附录B负荷/附录C年总量/GB8703放射性），关键词前缀反例被拒（exact=False）。
- prose-005（GB14554 哪几级）保持 **ambiguous 公开失败**：标题「4.1 标准分级」不含请求核心词（厂界标准值在正文中），body 证据评分下 4.1 与兄弟 4.2 打平（GB14554 第4章正文多处提及厂界标准值），ancestor-tiebreak 条件不满足——不再用不可审计的手段强行消除歧义。table-003 的 Phase 1 结构 ambiguous 同样保留。

## 真实复跑（31 题 bench，`bench-r4.json`）

| 类别 | 集合检查 |
|---|---|
| file_enum | 6/6 EXACT |
| prose_enum | 5/6 EXACT（005 ambiguous 公开失败） |
| table_enum | 5/6 EXACT（003 结构歧义保留） |

机制自检（非指标）：evidence recall 0.949 / file doc recall 1.0；syn-001（0.67，前言条件块未进 top-20）与 syn-002（0）保留为真实排序失败，不改 gold。全套 168 测试、Ruff check/format、OpenSpec strict、diff 通过；public 八表冻结计数不变，索引按新词表重建 `872d689343a9cbb6`（词表新增 标准分级/分级/级别/分类，触发身份变化按合同重建），源指纹/catalog 未变；未调用模型。

## 边界

- prose-005 与 table-003 为公开失败行；其确认/结构歧义需要更细的正文语义信号或主 agent 对 Phase 1 结构状态的进一步裁决，本轮未强行通过。
- gold 仍全部 unreviewed；所有 EXACT 数字为行为证据，Gate 2 指标待主 agent 审核冻结后计算。
