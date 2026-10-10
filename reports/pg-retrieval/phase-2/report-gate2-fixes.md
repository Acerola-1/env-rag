# Phase 2 Gate 2 补正报告（G2-1–G2-8）

> 主agent补正复审（2026-10-06）：仍未通过Gate2。原13反例修复已确认；141既有测试通过，新11项生产入口反例失败，详见[复审](../gate-2/re-review/review.md)。
> 正式CLI两版本/含修改单文件集合为空，原标准章节混入其他来源/标题项目；gold三处typed目标误指目录。0.966机制自检不批准为质量指标，gold仍未冻结。
> 以下执行agent原提交保留历史；原件在../gate-2/re-review/submitted-fixes-report.md。下一轮按handoff-phase-2-fixes-r2.md补正。

执行日期：2026-10-05。范围：按 `handoff-phase-2-fixes.md` 修复 G2-1–G2-8，消除主 agent 的 13 项独立反例。**停在 Gate 2 复审，4.1–4.5 未勾选，4.6 留主 agent。** gold 仍为 unreviewed（材料已按逐题意见修正），指标未填。

## 独立反例

`uv run pytest tests/test_gate2_acceptance.py`（13 项，未改动、未 skip）→ **13 passed**；另新增 `tests/test_search_guards.py`（5 项构建生命周期、隔离 fixture）→ 全过。完整测试 **141 passed**（原 123 + Gate2 13 + 新增守卫 5）。

## 各项修复

### G2-1 精确条件（反例 1/2/3 通过）

- 路由前先 `tk.normalize_text` 统一全角/破折号（`query._split_codes`），全角编号进入编号路由而非关键词放宽。
- 请求编号去重后逐个路由；**任一编号/版本缺失 → 整体 `missing`**，已解析目标的部分证据保留在候选与 note 中，缺词不再触发 fallback、也不被关键词候选替代。
- 无年份裸编号（`GB50014`）与带年份同等约束：`self_code` 无命中即 missing。
- 真实 CLI 复验：`GB3095-2012 与 GB3095-1996` → missing（2012 候选保留 + 明示缺 1996）；`GB50014 环境空气` → missing 0 候选；全角 `ＧＢ３０９５－１９９６` → missing 且 `parsed_codes` 正确。

### G2-2 完整文件谓词（反例 5/6 通过）

- `expand._doc_predicate`：编号（含可接受的 2 位年份变体，逐个占位符）、名称短语（`_name_phrase` 屏蔽停用/框架词后取最长中文串）、workspace 全部贯穿 `enumerate_documents` 分页。
- 无法导出可核验谓词 → `ambiguous`，**不再用 `TRUE` 枚举全库**。
- 真实 CLI：`GB3095-2012 --expand-docs` → 仅 2012 版（`self_code=GB3095 AND self_code_version IN (12,2012)`）；年报 → 仅 5 份。

### G2-3 构建/读取身份（反例 4/10/11 通过）

- 构建：来源指纹在快照前、派生后**两次**核验；发布事务内再核验 catalog 未替换；失败绝不改动旧 active（`prior=active` 时只记 note）。
- `search_builds` 主键冲突修复：同身份 force/失败重试改为冲突安全（active 行保持 active，成功后发布、失败回滚原状态），隔离测试覆盖重试/force/派生失败/来源变化四种分支。
- 查询：`finish()` 在所有返回路径（含无命中/早退）复验 search_id + catalog + active 代次，变化即 stale。
- `check_search_stale` 将 CLEAN_VERSION 纳入身份（`expected_search_id` 与 active 不一致即 stale）；真实复验：recipe/清洗变化后 stale 并要求重建。

### G2-4 caption 局部化（真实重建 e3cb2a39）

- 索引改为按 `unit_chunk_links` 把表 caption 赋给**实际链接的 chunk**；文档级 caption 信号只进文档行（A 权重），不再复制到全文档。
- 真实重建 `search_id=e3cb2a39dee53d9d`（221/5709）；GB8978 caption chunks 24→**12**，`表6` 命中 20→**4**（仅真正含表6的物理片 chunk-015/016/017/018）。
- recipe 升为 `phase-2-v2-local-caption-identity-guard`，旧索引原子替换并修剪。

### G2-5 范围闭环（真实 CLI）

- 从请求解析目标范围（`第N章`／`N.N`／`表N`），解析到唯一 catalog scope 才自动展开；解析不到或同号多个 → `ambiguous`，不猜。
- 展开调用 Phase 1 枚举入口并返回**实际 items 与可回读引用**（`_expand_prose` 现做 clause 抽取+引用绑定+核验），读完成（read_status）与抽取完成（coverage）分开，异常/预算经 `fail_stage` 统一体现。
- 真实 CLI：`GB18466-2005 第3章` → 自动解析 scope:3，complete、5 items（3.1–3.4）；人工 scope 路径保留为诊断（trace 记录 `resolution` 与 auto_target）。

### G2-6/7 同义词与探针（反例 7/12 通过）

- 同义词改为**每概念 OR 组、概念间 AND**：`'原词' | '同义词'` 组合进 AND；OOV 词不再先删（保留原词组），日志记录每组的原词、同义词与是否在库（`present`）。
- 探针改用真实 `mode="index"` 与 `mode="query"` 分别经 PG 回验；新增编号短语相邻用例（`gb3095 <-> -2012`）与真实中英正文；注入不一致 index 流的反例被检出（test 12 通过）。

### G2-8 Gold/评测（反例 8/9/13 通过）

- gold v2（`phase-2-gold-candidates-v2-gate2-corrected`）：31 正例全部附 typed `target_evidence`（workspace/doc/unit/chunk/scope），并按逐题意见修正：
  - fact-004 III 类 COD **20**（按 I–V 列头索引；15 为 I/II 类）；
  - fact-005 二级臭气浓度保留新扩改建20／现有30；fact-007 表4/表2 分别引用；
  - table-enum-004 题干更正为 **24 项**（25 网格行含表头），保留原题历史；
  - file-enum-005 纳入修改单与含修改单整合版（封面/标题归属，不冒认 self_code）；
  - prose-enum-001 四术语各附原始块；prose-enum-002/syn-005 保留 4.1.2 县级/20床条件与排放去向；prose-enum-004 III 类含越冬场/洄游通道/水产养殖、OCR 类号保留原号；
  - syn-001 保留 2026 过渡期（至2030末）与 2031 起两阶段；
  - prose-enum-003 从真实块读取（容忍 `##` 标题）；table-enum-003/006 按名称去重；syn-003 完整块引句。
  - neg-003 问题/期望一致化；neg-009 期望更正（去重≠内容不可检索）。
- 评测合同（`eval.py`）：eligible 白名单（reviewed/approved）；候选**先截断到 top-k 再计 hits**；evidence recall 按 gold typed 证据组（支持可接受替代）经 `unit_chunk_links` 解析到物理 chunk/unit 后与截断候选集比对；文件 doc 召回**仅 file_enum**且单列为诊断（`list_doc_recall_at_k_reviewed`），不替代证据召回；展开读取只作诊断输出，**不替换候选计分**。
- 反例走正式入口真实执行（`counterexamples.jsonl`）：neg-001/006/006b missing、neg-003 仅 self_code=GB3838 命中。

## 机制自检（非 Gate 2 指标）

将 31 题在内存中临时标 approved 跑正式 `search-bench`（不落盘、不写入 gold）验证评测机制可算：file doc recall **1.0**、evidence recall **0.966**（仅 syn-002 未满：题面无编号/表号，多范围合成依赖展开诊断；作为已知门槛项交审核）。该数字**不是** Gate 2 结论，gold 未审核。

## 未完成 / 边界

- gold 仍全部 unreviewed；主 agent 审核并冻结前不计入任何指标，report 未填通过值。
- syn-002 类型（题面无显式范围号的跨范围合成）的自动候选发现仍不足；其范围证据需经 `--expand` 诊断路径查看，是否要求自动发现由审核定义。
- 表2 缺 base caption、requires_span 未定位等 Phase 1 保守行为保持不变。
- 未运行融合、未重解析、未 embedding；public 与 MinerU 只读。
