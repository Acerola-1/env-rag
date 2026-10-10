# Phase 1 enumeration handoff

## Scope and inputs

第2组结构检查点已通过。只执行 tasks 3.1–3.5，交付后停在 Gate1，3.6 由主 agent 审查。先阅读 design、specs、tasks 和 phase-1-review/review.md 的 V4 re-review result。

- 工作区 /Users/acerola/Dev/Python/RAG/env-rag-final，PG workspace=default。
- 当前 active run c15c741742394320，recipe phase-1-v4-single-active-snapshot-prune，catalog snapshot 4919b3938ad93747。
- raw source 指纹 95f7791fd84171ab727870fc5810d79b4327b0c4fa547d432951e0499a3808f8；221 份文档、5709 chunks。
- 1970 scopes、4 requires_span；全部 16783 links 的覆盖状态为 partial。这些都是输入状态，不能直接当作答案完整性。
- 真实题目候选在 phase-0/sample-set.json，gold 全部未审核。不要用待审核答案计算正式质量指标。

## Work sequence

### 3.1 Logical tables

在同一文档、章节／附录、来源快照内，根据表号、caption 的续／完、顺序、表头和行序关联物理表片段。疑似关系保持 partial／ambiguous，不强合并同文不同章节的表1。
GB8978 表1的两片同在一个 chunk，必须保留两个 table units；去重 chunk 不能丢片段。
只操作本应用辅助对象。如果给构建增加 logical_table 或局部跨度派生结果，升级 recipe 并重建新目录，记录 run／snapshot；原文源指纹须保持冻结值。

### 3.2 Table enumeration

使用已有 tables.json／HTML，处理 rowspan／colspan、重复表头、标题单位、脚注和数学表示。输出每行项目、值、单位或请求列，引用原始 table ID／locator／chunk。
读取全部逻辑表片段和行，序号连续只是辅助校验，不能单独证明不缺片。表格上下文与其所属限制条件必须一起保留，禁止混入别的表。
验收样本 GB8978 表1：原始13项完整且无表2项目；缺片、列歧义、不同章节同表号返回明确状态。

### 3.3 Prose enumeration

先确定请求的真实条款／章节或局部跨度，再完整有序取证，按范围分批抽取 items＋来源引句。可复用现有模型做小范围正文抽取，记录实际配置、请求、输入证据、输出、耗时及失败，不调用模型重新猜文件清单或表格行。
每项引句必须可回读且支持对应主张；去重保留原始证据。模型失败、无效 JSON、虚构引句和预算不足不能输出 complete。
requires_span 或大 block 的小条款请求必须有可验证字符跨度／单元 locator，找不到则 partial／ambiguous，不把273个chunk当作一个子条款。
真实案例：
- GB18466 第3章定义：列出3.1–3.4各术语；另用“医疗机构污水定义包含哪些场所”验证段内枚举。
- GB18466 请求4.1.1–4.1.5：边界排除4.1.6；若请求完整4.1，则包含原文4.1.6。同一 block 跨 chunks 不代表只有第一个chunk。
- GB3095 第4章：读取4.1和4.2，排除第5章。

### 3.4 Document enumeration

基于明确库内匹配条件，对当前活动目录完整分页，不取 top-k 充当全部文件。同一次读取绑定 active snapshot，期间目录更新或源变化不得混版本；复用修正后的内容 token，不能使用事务ID作为版本。
验证 GB3095 已入库版本、移动源年报或水资源公报的确定文件集合；缩小页容量至实际跨至少两页，结果无重复、无漏项。
输出匹配谓词、知识库快照、总量、已读量、未知元数据排除项；只声称读完匹配结果，不声称全部现行法律／所有语义相关文档已找齐。

### 3.5 Output contract

统一保存 query_id、workspace、source/catalog snapshot、scope IDs、完整成员与处理量、items及可验证引用、coverage_status、warnings和失败阶段。
结构 confirmed、关联 partial、答案 complete 是不同语义。答案 complete 必须有目标范围、全部处理量与项目核验依据。stale、预算耗尽、缺续表、未定位跨度、歧义列和模型失败都要显式处理。
读取前及完成前检测相关来源和active目录一致性；任何未验证的来源变化不能发布完整答案。

## Deliverables and verification

- 枚举实现、可复跑 CLI、必要的辅助对象迁移／构建更新、使用说明。
- reports/pg-retrieval/phase-1/report.md、enumeration-runs.jsonl、三类真实输出和范围／引用／项目核验记录。题目、输入快照和模型配置明确。
- 新增有意义的行为测试：缺片、跨章节同表号、合并单元格、长正文分批、requires_span、伪造引句、预算耗尽、跨页token、目录更新及stale。
- 固定真实例题的期望集合从原文人工核验，标明谁审核和依据。可提出局部 gold 供主 agent 复核，不批量标记整个35题benchmark为reviewed。
- 不新增中文分词器或全文索引，不运行 reranker／LightRAG融合，不重新解析PDF、向量化或修failed。已有 public.lightrag_* 和 MinerU 产物保持只读。
- Ruff、受影响测试、OpenSpec严格校验、diff检查通过。只勾选有证据的3.1–3.5，3.6保持未完成。

## Copyable prompt

请在 /Users/acerola/Dev/Python/RAG/env-rag-final 按 OpenSpec add-pg-scoped-retrieval 执行 tasks 3.1–3.5。先阅读 handoff-phase-1-enumeration.md 和结构复审结论，实现逻辑续表、HTML行列枚举、完整正文／局部跨度抽取、文件清单完整分页及统一引用与覆盖状态。只操作应用辅助对象，原文库和MinerU产物保持只读。复用现有模型仅做小范围正文抽取，保存实际请求和证据；不做全文检索或融合。真实验证GB8978表1、GB18466正文和GB3095文件/章节清单，覆盖缺片、预算、requires_span和stale反例。交付可复跑报告与输出，停在Gate1，3.6留给主agent审查。
