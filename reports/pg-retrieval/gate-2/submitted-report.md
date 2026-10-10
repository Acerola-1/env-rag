# Phase 2：中文关键词检索（tasks 4.1–4.5）

执行日期：2026-10-05。范围：应用侧受控分词、env_rag 派生搜索索引、编号/版本限定查询路由、候选到完整范围的展开、gold 待审材料与评测入口。**停在 Gate 2，4.6 留主 agent。** gold 尚未逐题审核，任何指标不得视为 Gate 2 通过。

固定输入（执行前后均核验）：workspace=default；source fingerprint=`95f7791fd84171ab727870fc5810d79b4327b0c4fa547d432951e0499a3808f8`；active run=`c15c741742394320`；catalog snapshot=`4919b3938ad93747`；recipe=`phase-1-v4-single-active-snapshot-prune`。public.lightrag_* 与 MinerU 产物只读；本轮写入仅限 env_rag 中本应用对象（迁移 0008/0009、搜索索引行、search_builds 账本）。

## 4.1 分词层与探针

实现 `src/env_rag_final/search/tokenizer.py`，版本 `phase-2-v3-jieba-0.42.1-cfs-index`：

- jieba 0.42.1 由 uv 锁定（`pyproject.toml`/`uv.lock`），HMM 关闭（纯词典、确定性）；受控词表 `vocab/base.txt`（环保术语 93 词）、`vocab/stopwords.txt`（提问/框架词）、`vocab/synonyms.txt`（查询侧放宽）。
- **索引/查询两侧为同一模块的不同模式**：索引侧 `cut_for_search`（最大词＋子词超集），查询侧 `lcut`（最大词）。已用测试 `test_index_mode_is_a_superset_of_query_mode` 与真实探针证明查询词必在索引词流中——这不是"两边各做一次分词"，而是同一词典的定向扩展。
- 编号不参与分词：`GB 3095—2012`/`ＧＢ３０９５－２０１２`/`gb3095/2012` 全部规范化为 `gb3095` + `-2012` 相邻词项，查询侧以短语 `<->` 要求同序相邻；无年份编号（`GB 3095`、`GB/T 18883`）为单词项。条款号 `4.2.1`、表号 `表 1`/`续表 2`、`PM2.5` 同样受保护。
- 词表更新方式：改 `vocab/*.txt` 即改变 `vocab_sha()`；`vocab_sha` 参与 `index_identity`（catalog+source+tokenizer 版本+词表 SHA+清洗版本+配方），`check_search_stale` 检测到不一致返回 stale/reasons，要求重建——变更不会静默沿用旧索引。

证据：`tokenizer-probes.json`（22 真实文本用例：真实 heading/caption/chunk 正文/英文；11 编号规范化用例；20 条索引↔查询一致性用例，0 失败；naive 基线对照）。索引↔查询一致性用例在同一 `to_tsvector('simple', tokens_text)` 上回验每个查询词项，`pass=true` 仅当全部命中。

真实缺陷与修复：v1 曾出现索引 `污水排放` 与查询 `医疗机构污水` 不对称（AND 0 命中）；改为索引模式 `cut_for_search` 后消除。`gb3095/2012` 斜杠形式曾漏规范化；修复 `_CODE_BASE_YEAR` 分隔符后 bump 版本 v3。两次搜索构建的身份随版本变化并原子替换（旧索引在同事务修剪）。

## 4.2 派生检索索引

- 迁移 `0008_search_builds`（构建账本，含 tokenizer_version/vocab_sha/index_recipe，部分唯一索引保证单 active）与 `0009_search_objects`（`search_documents`、`search_chunks`，含 `search_text` 与 `tsv`，GIN + identity B-tree）。
- 权重：A=文档名/标题/自身编号；B=heading+caption；C=chunk 正文。HTML 清洗（`clean.py`）按真实形态处理：`<table>`/`<td>` 去标签保留文本、`<sup>/<sub>` 保留内文（`mg/m3`）、`<drawing>` 保留 caption 丢弃图片路径、`<equation>` 与行内 `$…$` 置空、markdown 标题记号去除保留文字。
- 构建守卫：先 `check_stale` 确认目录 current；一次只读 REPEATABLE READ 读 public 源；构建前 `_live_source_fingerprint` 对照；目录文档数≠源文档数则拒绝；写入后计数核对（221/5709）；`pg_advisory_xact_lock` 串行发布；失败写 `status=failed` 且不动旧 active。
- 真实构建：`uv run env-rag-final search-build` → `search_id=b1cd771ee0e2b55f`，docs=221、chunks=5709，elapsed≈26s。manifest 见 `index-manifest.json`（6 次构建历史、row_counts、indexdef、代码 SHA）。
- **EXPLAIN 与计时**（`explain-evidence.json`，`EXPLAIN (ANALYZE, BUFFERS)` 实测）：三类查询均走 `Bitmap Index Scan on idx_schunk_gin`，执行 1.2–4.5 ms（`医疗机构 & 水污染物` 58 行过滤、`环境空气 & 浓度限值` 55 行、`gb3095 <-> -2012` 12 行）。数据量小仍明确使用 GIN，非 seq-scan 侥幸。

## 4.3 查询路由

顺序（design 决策 4）：**编号定位 → 元数据限定 → 关键词候选**。

- 显式编号直配 `self_code`（自身编号，非引用编号）；请求版本不存在时 `status=missing` 且 note 明确点名存在的其他版本，"另一版本 NOT substituted"；**不任取首项**——同号全版本都作为独立候选返回（`selected_versions` 记录全部）。
- 多方编号（如"GB3095-2012 与 GB3095-2026 对比"）：逐个编号分别定位，各自版本文档都保留；任一编号缺失仍整体报 missing。
- 编号命中后，关键词检索**限定在该编号文档集**（元数据强约束，非排序提示），日志 `restricted_to_code_docs` 记录。
- 核心词 AND（chunk 级＋doc 级）；空结果时按**记录的阶梯**放宽：A 全词 AND → B 剔除语料中不存在的词（逐词命中数、absent_terms 入日志）→ C 受控同义词代入 AND → D 剩余词 OR 兜底。每级保存实际 tsquery、命中数与耗时；放宽不移除编号/版本/workspace 约束。
- 反例实测（真实 CLI）：`GB 3095-1996` → missing（列出 2012/2026，不替代）；`GB 50014-2021` → missing（0 其他版本）；stale 索引 → status=stale、候选为空。

## 4.4 候选到完整范围展开

`expand.py`：发现阶段 top-k 只定位；确认范围后读取**全部有序成员**并调用 Phase 1 已有枚举入口：

- 表格 → `enumerate_table`（逻辑续表重新归组）；正文 → `read_prose_scope`（成员逐条、预算约束、requires_span 规则保留）；文档集合 → `enumerate_documents` 分页（`--expand-docs`，全量自编号集合，绝不用 top-k 冒充清单）。
- 展开按文档去重；未知 scope 保持 ambiguous；每个展开项记录 members_total/processed、coverage_status、fail_stage、chunk_ids。
- 实测：`--top-k 1` 展开 GB8978 表1 → 仍读全 2 物理片、13 项、13/13 原始行引用（含续表）；GB18466 `:scope:3` → 3/3；739 成员的大 scope → partial/budget_exhausted 且告警点名剩余起点（未静默截断）；`--expand-docs` GB3095 → 2/2 两版本完整分页。

## 4.5 Gold 候选与评测入口

- `gold.py` 从**原始产物**重新推导每题（表行→读取 HTML 网格；正文→block 原文引句；文件集→解析产物清单＋身份），任何一项推导失败即退出非零；不做手填。产物 `gold-candidates.json`：
  - 正例 31：fact 7（GB3095 SO2 年均 60/20、GB8978 总汞 0.05、GB3838 COD 15、GB14554 臭气 20、GB3095 发布/实施日期、GB8978 pH 6~9、GB18466 3.2 定义）；file_enum 6；prose_enum 6；table_enum 6；synthesis 6。
  - 反例 10（沿用 Phase 0 反例并按本轮真实验证补充实现依据）。
  - 每题含 target_docs 身份、原文 locator、verbatim 支持引句、evidence_kind、约束与 allowed_status；无法完整列出的题（表2 表1逐项等）保留 `gap`，不编造。
- 评测入口：`search-bench`（只读）跑全部题并逐题保存原始 run 到 `search-runs.jsonl`（31 行，每行含 candidates/trace/耗时/snapshot）；`eval.py` **仅在 gold 审核后**计算 recall 等指标，未审核题列出为 pending_review 且明确标注"任何数字不得视为 Gate 2 结果"。当前 31/31 未审核，故 `recall_at_k_reviewed=None`。
- 待审观察（非结论）：31 题在 top-k=20 的**候选文档召回**全部命中目标文档，但集合完全正确率、引用正确率、反例行为仍需主 agent 逐题审核后按 design 门槛计算。

## 未完成 / 边界

- 4.6 与 Gate 2 由主 agent 执行；gold 全部 unreviewed，metric 未计算、未填通过值。
- 表2 缺 base caption、requires_span 未定位等 Phase 1 保守行为原样保留，未放宽。
- 同义词表为初始草案，仅覆盖少量真实漏召回方向；放宽影响未做全库评估。
- 未实现 LightRAG 联合路径（Phase 3），未做融合对照、未重新解析/embedding/修 failed。
- search-bench 的 recall 只统计**候选文档**层；范围成员覆盖、集合正确率需结合枚举结果评估，属审核后的 Gate 2 工作。
