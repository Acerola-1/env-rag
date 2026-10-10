# Gate 2 主 agent 验收（2026-10-05）

结论：**未通过**。保留Gate0、v4结构检查点及Gate1通过结论；4.1–4.5恢复未勾选，4.6保持未完成。已实现且真实运行的分词/GIN/编号正例作为进展保留，不能据此进入Phase3。

## 已确认的进展

提交的123项测试本轮复跑通过，Ruff/OpenSpec严格校验/diff检查通过。jieba0.42.1确实锁定；当前search_id=b1cd771ee0e2b55f，索引221文档/5709chunks。独立EXPLAIN复跑了真实tsquery，已有GIN查询可用。GB8978表1手动指定table_number、top-k=1展开仍返回两片13项，Phase1枚举合同继续有效。

主agent新增`tests/test_gate2_acceptance.py`的13项独立反例：**13失败**，加上既有测试为123通过/13失败。详见`test-results.txt`。未删除或修改原123项测试，也未替执行agent改检索实现。审核使用[open-code-review-delegate](/Users/acerola/.agents/skills/open-code-review-delegate/SKILL.md)的文件/规则选择流程，由主agent完成代码和行为审查；本文件只覆盖Phase2新路径，覆盖明细另存review-coverage.json。

## 阻断项

| 编号 | 发现与复现 | 要求 |
|---|---|---|
| G2-1 强编号/版本条件 | 真实`GB3095-2012 与 GB3095-1996`返回ok，只有2012，1996仅note；`GB50014 环境空气`返回ok及25个其他候选；全角`ＧＢ３０９５－１９９６ 二级标准年均限值`不进编号路由，放宽后ok及20个候选。`query.py:149`重置missing、无年份编号未命中直接fall back、正则前未规范化 | 任一显式目标缺失必须missing/incomplete，已找到方可作为明确部分结果；缺失裸编号不能替代；全角等变体先统一规范化再路由 |
| G2-2 文件展开改变谓词 | 真实`GB3095-2012 --expand-docs`返回2012+2026且complete；年报查询展开成全库221文档且complete。`expand.py:99–112`只取第一个编号、丢版本；无编号用TRUE，且不向enumerator传workspace | 把完整强限制/名称/类型/全部编号谓词贯穿分页，无法确认谓词则ambiguous；不能用全库结果顶替匹配集。workspace不可丢 |
| G2-3 构建/读取变化窗口 | `_build_locked`只在derive前核验一次live fingerprint，派生后/发布前没有复核；独立测试在tokenize中使来源变化仍发布。`run_query`也只检查开始，完成前source/active替换检测不到；CLEAN_VERSION变更后check_search_stale仍current | 源行快照与完整指纹一致，产物/目录/算法/词表守卫包围整个派生和发布窗口；读取结束核验source/catalog/search代次，变化返回stale；清洗版本参与stale判断 |
| G2-4 caption被复制到所有chunks | `index.py:185–187,233`按doc_id汇总所有表caption并加到每个chunk。真实GB8978的24个chunk全含表6 caption，原文只有chunk015明确提及“表6”，搜索表6却给20个chunk。不能把仅含注入caption的chunk标为该表真实证据 | 通过已审核unit_chunk_links把caption赋给实际片段相关chunks；需要文档级caption信号时独立记录，不能伪造成chunk定位。索引改变升版并重建，仅写env_rag |
| G2-5 范围确认与枚举尚未闭环 | 真实`GB18466 第3章 --expand`仅给not_expanded（要求调用方预先给scope_id）；手动scope3只读unit数，read_status=complete、coverage=ambiguous，无抽取项目/引用。展开异常/partial没有统一传到顶层状态。search-bench不调用展开 | 从候选结合请求确认章节/表/条款范围，无法确认明确ambiguous；接已通过的枚举抽取/引用路径，返回全部items与统一状态。文件结果和发现候选分别保留；不得靠人工预知gold范围证明检索到范围 |
| G2-6 同义词路径不正确 | `污水=废水\|水污染`被组装为`'废水' <-> '水污染'`的相邻短语，不是候选同义词选择；词全OOV时早退，缺词先被删除，可能永远到不了其同义词。独立路径反例失败 | 每个概念原词/受控同义词形成可记录的OR组，概念组之间AND；不能先删掉概念再称同义词召回。保留强限制与每级实际执行日志 |
| G2-7 分词探针没有测试索引模式 | `probe._consistency`调用`tokens_text(text)`默认query，再与同一query词项回验，20/20并不证明cut_for_search实际索引模式。独立注入“不一致index、正确query”的探针仍pass | 使用实际mode=index及实际query词流经PG回验；增加编号/中文/英文/真实正文/相邻位置的探针。保证仅针对实际探针条件，不宣称任意不同上下文必然词项一致 |
| G2-8 评测合同与gold未冻结 | eval把任何非unreviewed（含rejected）计入指标；hits在全部候选计算却展示截断后的top-k，目标排第2而k=1仍recall1；目前只有doc召回，编号目录行就能加分，尚无目标证据召回、集合/引用/反例指标。gold多处错误及缺口见逐题审核 | 明确审核状态白名单、每题有效gold、冻结版本/来源；定义排序/候选预算和目标证据组、先截断再计分。文件doc召回可保留独立诊断，但不能替代目标chunk/unit/scope召回。执行三类集合/引用对照及至少8反例 |

真实反例及输入参数在`replay.json.runs`。该脚本直接调用生产run_query，通过强制只读PG连接；未模拟数据库、未调用模型。来源/算法变化与同义词/评测/探针反例则使用隔离fixture执行生产入口，证据类型分别标明。

构建生命周期还有明确需补的分支：search_builds以search_id为主键，force/失败后同身份重试仍走无冲突处理的INSERT，必然发生主键冲突；同身份已有行的ON CONFLICT DO NOTHING也不能完成强制重算。这一项为代码/DDL审查事实，本轮未在真实库force或制造失败；在隔离测试修复并证明失败不影响旧active，不能为了验收在原库制造异常。

## Gold逐题审核

已阅读全部31正例/10反例，逐题意见见`gold-review.json`，原始block全文与展开后的HTML原始行在`raw-gold-materials.json`，活动目录身份与39条参考unit的chunk关联核对见`gold-source-proof.json`。没有把提交候选整体标reviewed，也没有计算Gate2指标。

具体错误包括：

- fact-004：GB3838表1列头为I/II/III/IV/V，对应COD15/15/**20**/30/40。提交的III类15错误，gold.py使用row[3]实际读II类。
- fact-005：GB14554表1二级臭气浓度“新扩改建20／现有30”；问题未限定条件而gold只给20。
- table-enum-004：GB3838表1的25网格行含1表头，序号1–24，实际24项目；题干25项必须显式修订并留历史。
- file-enum-005：“含修改单”只列原标准，漏了2026修改单及含修改单整合文档的相关身份。两者self_code未知不能擅自升级编号，但封面可证明归属；完整集合按明确归属依据形成。
- prose-enum-002/syn-005省略4.1.2县级/20床适用条件；prose-enum-001的quote只到3.2，不能支持3.3/3.4。不能以简述或截断引句证明完整清单。
- syn-001必须保留2026过渡期至2030年末（PM2.5年均15/30）与2031起（10/25）的条件，再与2012的15/35比较。
- neg-003问题“涉及”与期望“仅自身编号”不一致；neg-009文件身份没有导入不代表内容不可检索，该内容已通过重复原件入库。需修正问题/期望一致性。

原提交11题明确有gap，这个保守标记是正确的；但gap题没有冻结完整预期，4.5“冻结已审核gold”不能勾完成。“全部由脚本重推导、任何缺依据退出”也与gold.py中的硬编码expected、描述性quote及无quote题不一致。已提供可补齐的原始材料，保留问题ID与修改记录，不悄悄换容易题。

独立映射诊断另显示：提交table-enum-001候选有正确文档，却没有两片对应chunk001；syn-002命中正确文档，却未命中4.1对应001/002或6.1对应003。这些是基于真实链接和候选的单题检查，**不是冻结后的整体recall指标**，但足以说明31/31文档命中不等于目标证据召回。

## 数据与验收边界

独立SELECT-only复跑前后public八表计数一致，且源完整指纹、active目录、search索引均current未变：doc_full221/chunks5709/status279/llm_cache16514/entity_chunks65527/full_entities221/full_relations221/relation_chunks119575。catalog active=c15c741742394320、snapshot=4919b3938ad93747、source=95f7791fd84171ab727870fc5810d79b4327b0c4fa547d432951e0499a3808f8，search active=b1cd771ee0e2b55f。后续gold源核对仍同一current目录。

本轮未执行迁移/构建/重建，未调用模型/embedding/reranker/融合；原PG与MinerU产物未被修改。当前搜索索引的发布事实保留，不代表其caption/guard合同已通过。

下一位agent按`handoff-phase-2-fixes.md`补正。优先修G2-1/2/3，再修定位/展开/评测；保留当前反例测试和原始报告，停在Gate2复审，不能进入Phase3。
