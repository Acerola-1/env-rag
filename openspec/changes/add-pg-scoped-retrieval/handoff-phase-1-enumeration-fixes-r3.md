# Gate 1 第三轮补正：以独立验收测试收口

先读 reports/pg-retrieval/gate-1/review-3/review.md、replay.json、acceptance-results.txt，以及 tests/test_gate1_acceptance.py。

既有90项测试通过，但主agent新增9项独立验收全部失败。目标是修复正式入口/引用路径，使这9项按当前验收期望通过。测试期望来自已约定的行为与真实反例；不得删除、skip、xfail或降低断言来勾选任务。需要因接口重构调整调用形式时，保留相同的原文回读、精确范围和stale断言，并在报告说明。

3.1保持通过。保留本轮已修好的表1 13/13原始行坐标、正文3.1–3.4 CLI成功、9.9.9 partial、source指纹、workspace、JSONL格式。3.2–3.5仍未完成，3.6由主agent复审。public和MinerU只读，不重建PG/v4目录，不执行Phase2。

## 修复四组残留问题

1. **G1 原文引用**：bind_citations分别处理模型quote与数值坐标。模型无char_start时先定位quote，不做max(None, int)；歧义定位明确降级。数值跨度裁到owner边界，去掉跨单元空白，unit坐标加span_offset_in_unit；跨多单元的主张保留各段来源，不用一个owner截断证据。真实3.3、3.4当前start=-1，必须修成可回读原文范围；裁切7.5的引用应落在原父块7.5，不是引言/7.1。
2. **G2 完成前检查**：表格入口读取后check_stale；正文正式CLI/编排在全部抽取/模型成功处理后再次检查source及active，变化返回stale，不保留complete。失败路径保留实际失败阶段。文档token覆盖所有返回字段，包括doc_type、title_confidence、unknown_fields。三类读取连接强制只读；固定输入下保存真实守卫证据。
3. **G3 缺片元数据**：按稳定物理片身份/原始片号查元数据，保留空/缺片占位或用映射，不能压缩列表后拿原始fi索引。缺第一片、读取第二片allow_partial应返回partial/missing_fragment，保留第二片正确table_id和raw行引用。
4. **G4 严格答案合同**：读取完成状态与答案coverage真正分离，不能用warning字符串许可空complete；明确可验证零匹配文件集可complete，待抽取/缺项目正文与表格不得complete。项目支持关系针对明确点名的名词/场所核验完整名称；“门诊停车场”配“门诊、病房”不能verified。通用claims无法证明支持时保留未核验/partial，不以任意2字重合升级。形状/type/模型失败经正式编排降级。

## 验证与交付

- 先运行独立9项验收，再完整tests。全部通过后复跑真实CLI：GB18466 3.1–3.4、4.1.1–4.1.5及完整4.1、缺失9.9.9、GB3095第4章、GB8978表1/表2、年报/公报/GB3095分页。
- 正文与表格每项按独立原文locator/坐标回读，逐项保存quote/主张支持结果。表格13/13保持；正文4/4、请求局部裁切偏移也须正确。requires_span无法证明范围应partial，不能因父块出现任意数字就把整块当请求范围。
- 修复G1/G2后从实际--with-model入口做一次已授权的小范围3.2明确场所抽取；保存实际request_messages/raw_response、配置名称、耗时、前后source/active及输出引用，无密钥。保持8个明确点名场所、“等”的开放边界，gold不扩展到全部35题。
- 当前JSONL最后一条仍缺messages/raw_response，别复用加工后的旧记录冒充本次真实CLI。交付严格JSONL、运行完整参数、代码SHA、public计数及源指纹前后核验；旧报告留档，当前摘要仅列已验证事实。
- Ruff check/format、OpenSpec strict、diff check。仅勾选全部必要行为与真实证据齐全的3.2–3.5；停Gate1，3.6留主agent。
