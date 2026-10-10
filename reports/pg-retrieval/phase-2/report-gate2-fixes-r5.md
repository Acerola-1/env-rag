> 主 agent 第六轮复审：当前31题指标、类别/anchor真实引用、D2已确认；Gate 2仍有普通正文空行偏移与声明位置验证残留。170既有通过、新1失败。以gate-2/review-r6/review.md及handoff-phase-2-fixes-r6.md为最新状态，以下执行汇报原文保留。

# Phase 2 Gate 2 第五轮补正报告（D1–D2）

执行日期：2026-10-06。范围：按 `handoff-phase-2-fixes-r5.md` 修复两个阻断。**停 Gate 2 复审；4.5 已由主 agent 冻结（gold-approved.json），4.4/4.6 未完成。**

## 独立反例

- 原 40 项断言：**保持通过**。
- 第五轮 2 项（`tests/test_gate2_review_r5.py`）：**2/2 通过**。
- 完整测试 **170 passed**。

## D1 类别坐标映射回 assembled_text

`_split_category_sentences` 现在先定位 body 在 assembled_text 中的**真实起点**（`assembled_text.find(body)`，涵盖标题与空白差异），把 body 内的 marker/sentence 偏移统一映射回 assembled 坐标后再产出 citation（`char_start/char_end` 均为 assembled 坐标），quote 直接取自 assembled span。随后照常走 `bind_citations`/`verify_citations`。隔离反例（三类别普通原文，不依赖 GB3838 ID 或 OCR 值）通过：每条 `source[unit_rel_start:unit_rel_end].strip().startswith(quote)`。

**真实位置级回读**（按声明坐标切 raw unit 文本与 quote 前缀比对，非全文子串）：31 题 bench 全部 char_span 引用 **60/60 通过**（修复前 56/60）。修复过程中发现并修复第二个真实缺陷：`bind_citations` 的最大重叠归属会把"最后一个条款的尾部泄漏到后续 unit"的跨度（`extract_clauses_regex` 的末条款延伸到 end-of-text）错误归属给后一个 unit（fact-006/007、prose-003、syn-004 共 4 条）——归属排序改为 **anchor 优先**（包含跨度起点的 unit 是主 owner，再按重叠长度）。D1 的类别引用因此天然落在正确 unit。

## D2 空 discovery 快照权威化

- `discovery_candidates` 语义改为 **None（尚未捕获）vs []（明确的零发现）**：`finish()` 在每个返回路径补齐快照（早期退出捕获当时候选，展开路径捕获展开前列表并置 captured 标志）；eval 侧**显式 [] 一律为 0，绝不回填**，仅 None/缺字段（旧 fixture）回落到旧 candidates 过滤。
- 真实发现阶段的 doc_attribution 候选仍合法参与 recall（快照在展开前取得，构造上不可能含枚举后条目）。
- 反例通过：discovery=[]、枚举归属答对 → exact=true、discovery_candidates_total=0、evidence_recall=0、list_doc_recall=0。

## 审核副本 benchmark（gold-approved.json，`bench-r5.json`）

| 指标 | 值 |
|---|---|
| file_list doc recall@20（reviewed） | **1.0** |
| answer-evidence recall@20（reviewed，typed gold） | **0.949**（56/59；syn-001 0.67、syn-002 0 保留真实排序失败） |
| file_enum 集合 | **6/6** EXACT |
| prose_enum 集合 | **5/6** EXACT（005 ambiguous 公开失败） |
| table_enum 集合 | **5/6** EXACT（003 结构歧义保留） |
| 引用错误 | **0**（60/60 位置级回读 + 167 表行独立回读由主 agent 前轮核验口径一致） |

三类各 ≥5/6、整体 recall@20 ≥ 0.90、强编号/版本定位反例 8/8（neg-001/003/006/006b/010/011/012/013 真实入口重跑）、公开失败题保留未删。

## 边界

- 指标基于主 agent 冻结的审核副本（`--gold` 指定），实现未改 gold；syn-001/002 排序遗漏与 prose005/table003 歧义为公开失败，分母保留。
- 仅改查询/引用实现（query.py 快照、expand.py 坐标映射、prose_enum.py 归属排序、eval.py 快照语义），未重建索引；public/MinerU 只读，未调用模型。
