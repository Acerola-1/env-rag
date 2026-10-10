# Phase 2 Gate 2 补正交接

Gate2未通过，4.1–4.5重新未勾选，4.6留主agent。先阅读reports/pg-retrieval/gate-2/review.md、gold-review.json、gold-source-proof.json和tests/test_gate2_acceptance.py。当前123既有测试通过，但13项新增独立反例失败；不可删/skip/降低断言来达标。

## 修复顺序

1. **G2-1 精确条件**：先统一全角/空格/破折号/斜杠编号规范化，再检测全部编号。任一编号/版本不存在整体missing/incomplete并明确缺失目标；已有部分证据独立保留，关键词不得替换缺失目标。无年份缺失编号同样强约束。
2. **G2-2 完整文件谓词**：版本、全部编号、名称/类型、workspace贯穿enumerate_documents。年报只五份、GB3095-2012只2012；明确无法把自然语言转成可核验谓词时ambiguous，不用TRUE。相关修改单以明确归属字段/证据匹配，不能伪造self_code。
3. **G2-3 构建/读取身份**：完整source fingerprint包围源快照/派生/发布；目录快照、词表、分词/清洗/配方同时稳定。发布与活动目录切换协调，不给旧目录发布新索引；失败回滚不改变旧active，账本同身份失败重试/force安全，测试隔离执行。查询包括无命中早退等路径完成前复验来源与search/catalog活动身份；CLEAN_VERSION变化会stale。
4. **G2-4 局部索引**：caption按真实unit_chunk_links赋给相关chunks；文档级caption可单独参与文档发现，不能复制到所有chunk再标为局部证据。落实文档/标题A、局部heading/captionB、正文C的定义。改变索引派生后升版并显式重建env_rag搜索索引，保存新身份/前后指纹。
5. **G2-5 范围闭环**：把请求的编号/版本/表号/章节/条款与候选绑定，确认真实scope后使用已有完整枚举入口，输出items及可回读引用；读完成与抽取完成区分。无法确认保持ambiguous，异常/预算/变化统一体现。保留发现候选，不让枚举替换候选来计算recall；人工指定scope路径作为诊断，不作为自动定位成功。
6. **G2-6/7 同义词与探针**：同义词是同概念OR选择、概念间AND；保留原词，未命中词的受控同义词需实际尝试，不能先删掉概念。分词一致性探针使用真正mode=index与query模式分别经PG回验，包括编号短语位置及真实中英文正文。每级写实际执行的查询和限制，不能只填日志。
7. **G2-8 Gold/评测**：按主agent逐题意见修正并补齐31题（至少五类各6），显式保留题干/答案修改记录及困难题；表格按列头/原始行，正文按逐项原文跨度，文件按明确匹配集合。提供结构化workspace/doc/unit/chunk/scope目标证据及可接受替代组、完整集合和条件，保留OCR异常，不编造原PDF纠正。反例问题/期望一致，至少8项真实执行或隔离正式入口回归，不用“Phase1测试存在”代替本轮证据。

## 评测口径与审核停点

只有显式reviewed/approved且完整、当前来源一致的gold可进入指标；rejected/pending/缺字段不计。主agent本轮gold-review.json是审查参考，不是已冻结benchmark；修订材料交主agent确认后冻结版本。修复时可独立推进代码、原文补证、评测入口和反例，不得预先填通过值。

明确candidate top-k是一个排序后预算；目录直达、文档级信号、chunk发现分开保留；先取实际前k再计hits。文档命中诊断与Gate2目标证据recall分别报告，不让code_exact目录行替代答案证据。冻结证据单位/替代组/分母，保存每题实际词项/约束/放宽/候选/定位/展开/输出/引用与失败，不复用旧答案或LightRAG答案缓存。

Gate2门槛不变：已审核PG证据recall@20≥0.90、明确编号/版本正例100%、三类enum各≥5/6集合完全正确、引用错误0、反例无false complete。不得用rank/文档recall掩盖答案unit未被发现、展开没抽取或缺片。

## 交付与边界

仅写本应用env_rag辅助对象；public与解析原产物只读，不修failed、不重新解析、不embedding、不运行Phase3。现输入目录v4保持，通过构建守卫生成新搜索索引；若目录派生改动再显式升recipe并解释，避免无必要目录重建。

保存提交原件和本轮补正报告、探针、索引manifest、可复跑正式CLI JSONL、全部反例、raw gold证据和审核状态。构建/来源变化及force重试放隔离库或fixture，不在原库制造变动。运行全部受影响测试、Ruff、OpenSpec严格校验、diff；只按新证据勾4.1–4.5，4.6未勾，停Gate2。

可转交：请在env-rag-final按handoff-phase-2-fixes.md补正Gate2的G2-1–G2-8，逐一消除13项独立验收反例，并修正真实版本/文件集合/局部caption/范围展开和证据评测口径。复用主agent gold-review.json补原文材料，gold未经审核不计算通过指标。保留原文库、MinerU只读，只重建自有搜索索引，交付后停Gate2。
