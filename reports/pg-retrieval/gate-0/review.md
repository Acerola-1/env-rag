# Gate 0 review

审查日期：2026-10-05（Asia/Shanghai）。当前结论：**复审通过，可进入 Phase 1 第 2 组。** 首轮不通过的证据与要求保留在下方作为历史记录，当前证据见 re-review-evidence.json。
本结论针对数据合同和报告可复现性，不否定已验证语料，也不表示检索路线需要改变。

## Re-review result

首轮 G0-1／G0-2／G0-3 已补正。主 agent 阅读修复代码并执行 19 项离线 fixture 测试、两次真实只读审计、报告身份与来源指纹核验；Ruff、格式、OpenSpec 严格校验及 diff 检查通过。

本次另修复实际入口的剩余边界：

- 只读事务改为 REPEATABLE READ；本地产物在采集前后核对字节指纹，运行中变化会失败而非发布完整结果。
- 新输出目录可首次生成；完整报告以保留历史的独立代次生成，再原子切换 symlink。原目录的一次性转换失败会恢复整个旧目录，不逐文件混写。
- 失败报告保存在独立 failures 目录，不再被 finally 删除；异常包含脱敏阶段和诊断路径。
- 目标校验同时检查可读 blocks 产物与 chunks，空目标集合或缺产物不计入有效样本；每个目标附本轮来源 snapshot_id。

实际运行：

- 首次新目录审计 run_id：865a626eb7ce4365。
- 当前 phase-0 发布 run_id：3b7f17b1e30140a7。
- 两次 composite 指纹相同：95f7791fd84171ab727870fc5810d79b4327b0c4fa547d432951e0499a3808f8，含内容、分块、引用、产物字节及参数。
- manifest 的审计源码摘要与当前文件一致。
- 221 份文档／5709 chunks／58 failed 状态保持不变，env_rag 尚未创建。
- 五类正例各 7 道，共 35 道，10 个反例，0 unresolved；真实目标 ID 与 inventory 一致，产物及 chunks 可读，gold 均未审核。

Gate 0 只确认后续实现的输入合同，未证明中文召回率、正文／表格自动枚举正确率、模型调用或 LightRAG 查询兼容。
保留全部排除项和 10 份部分引用、14 个空 sidecar；273-chunk block 是“引用跨度”而非范围内容全部覆盖的证明。
跨存储现场命名仍属有标注的历史观察，运行时语义链路留给 Phase 3。gold 审核留给 tasks 4.5。

下一位执行 agent 先完成 2.1–2.6，交付自有目录、只读原文适配器与结构映射验证。不要直接启动全文索引或融合；交接见 handoff-phase-1.md。

## Historical first review

## Independent evidence

主 agent 阅读审计代码和交付物，并在 READ ONLY REPEATABLE READ 事务中独立核验 PG。原始结果见 independent-verification.json，可复跑入口为 verify_gate0.py，执行方式：

    .venv/bin/python reports/pg-retrieval/gate-0/verify_gate0.py /private/tmp/gate0-recheck.json

该核验只读 PG 和已有本地产物；离线导入 LightRAG 读取源码，没有实例化存储或调用模型。

已确认：

- default 下 doc_full=221、chunks=5709；processed=221、failed=58，当前无 env_rag schema。
- 58 条 failed 错误指向的原始文档均存在且 processed。这不证明每个被拒文件的原 PDF 字节相同。
- 221 份产物的文件名 ID、规范化 merged text 的 content_hash、merged text 的 document_hash 全部复算匹配。
- doc_full.content 带 {{LRdoc}} 前缀，221/221 去除此标记后与本地 merged blocks 文本相同。这是存储格式差异，不是内容损坏；Phase 1 比较原文要明确转换。
- 引用覆盖 211 全引用／10 部分引用／1 无 chunks；这只证明 block ID 引用覆盖，不证明 block 全部文字覆盖。
- GB 8978 表 1 两片在同一 chunk，分别包含 4 和 9 个数据项目。
- 已安装包具有 aquery_data，docstring 声明 chunk_id；PG 首次 ClientManager.get_client 调用 check_tables。运行时检索兼容尚未验证。
- Ruff、格式及 OpenSpec 严格校验通过；它们不替代事实验收。

## Blocking findings

### G0-1: 输入 fingerprint 不覆盖内容与分块

位置：src/env_rag_final/audit/collect.py:634-639。
当前摘要只包含两份分别排序的 ID、文件名清单。主 agent 修改内存中的 content_hash 和 chunks_in_db 后，摘要仍是 83ab60eff7c98450，见 fingerprint-check.json。因此两次相同摘要不能证明语料或分块未变，也不符合 manifest 声明的变化检测。

补正：保存每文档／每产物来源指纹，包括实际 PG 内容或摘要、chunk ID／顺序／内容／heading／sidecar、解析 blocks／tables 的字节摘要及分块参数；对有关联的 canonical 记录生成完整 SHA-256。使用稳定只读数据库快照，检测本地产物读取前后变化。记录实际审计代码摘要，不能只用初始化提交号＋dirty=true标识未提交代码。

验收：相同输入重跑一致；独立改变原文、chunk 内容／顺序／引用、tables 产物时指纹均变化。在 fixture 中验证，禁止为测试改现有库。报告明确支持哪些来源与变化。

### G0-2: 报告写死结论，与采集结果矛盾

位置：collect.py:493、_audit_md、_inventory 的 gap explanation，以及 compat.py:79。

- mapping-samples 的结构字段实际为 WHO/UNICEF 文档中一个 block 跨 273 个 chunks，observed 却写 14；audit.md 又写 water-126 Attachment D。独立查询确认最大样本是 273，说明必须由实际结果产生。
- 连续序号、状态数量一致、meta 全 NULL 等描述在模板中写死，原入口未执行对应全部校验。主 agent 独立确认当前值成立，不等于原入口能随变化正确报告。
- water-58 与 water-44 的规范化文本相等、规范化 MD5 相等；原始 merged text 不相等，SHA-256 document_hash 也不同。重复拒绝结论成立，“内容完全相同”必须限定为去掉文件派生标记后的规范化正文，不能混称原文或 PDF 字节相同。
- compatibility.md 为固定文本模板且输出为 JSON 包装，包含没有复跑记录的 inspect／三库命名探针声明。生成器没有执行相应 introspection 或 Qdrant／Neo4j 采集。PG 建池检查风险已由主 agent 独立确认；三库一致性须保留原始观察或标未验证，不能由各库只有一个取值推出同一语料。
- manifest 只列六步，缺 audit.md 和自身生成状态；异常均包装为连接失败，不能定位阶段。失败时可能留下新旧报告混合。

补正：动态结论由采集结果生成，历史／人工观察附时间、依赖源码位置／摘要或原始探针记录；未运行项标未验证。输出真正 Markdown，保存步骤状态和统一 run ID，避免旧成功 manifest 与新失败产物混用。

验收：fixture 改变计数、block 跨度、缺失记录、排序后文字和 JSON 同步变化；异常只输出类型但能定位阶段；无证据的事实不输出“已确认”。

### G0-3: 目标白名单含无法执行的省略身份

位置：samples.py、sample-set.json。
file-enum-002/003/004/005 和 syn-007 的 target_docs 为 air-15…19／待枚举等说明，不是实际文件。35 题数量达标不证明目标资料已经固定。部分 gold_sources 使用省略 ID，不能直接回读。

补正：每题输出实际 workspace／doc_id／完整 doc_name 和来源快照；集合查询另记录明确匹配谓词，并保存当前全部候选身份。缺失 locator 标 pending，不使用伪装实际 ID 的省略号。校验目标同时具有解析产物和可读 chunks，不只检查 doc_full 存在。

验收：所有正例目标可由 inventory 回读，未知／缺失样本单独归类；目标未解析不能标 meets_minimum=true。gold 保持 unreviewed 是正确行为，此次不要求完成正式 gold 审核。

### G0-4: Gate 0 审查项被删除

原 tasks.md 未保留 1.10，“1.10 留给主 agent”的陈述与文件不符。本轮恢复该项，并将 1.5／1.6／1.8／1.9 改回待验收；原交付证据保留。

## Accepted boundaries and next step

- 接受 PG 独立路线和辅助 schema 设计；不启动 Phase 1 迁移／目录实现。
- 保留 1.1／1.2／1.3／1.4／1.7 已执行记录，规范化重复的表述以本审查限定为准。
- 1.5／1.6／1.8／1.9 补正后复审，1.10 未完成。审查记录存在不等于 Gate 0 通过。
- 部分引用、空 sidecar 与未审核 gold 可作为 Phase 1／2 显式输入；不要求 Phase 0 修复语料。
- 下一位 agent 只执行 openspec/changes/add-pg-scoped-retrieval/handoff-phase-0-fixes.md，完成后由主 agent 复审。
