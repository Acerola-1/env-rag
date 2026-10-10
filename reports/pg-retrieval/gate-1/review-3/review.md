# Gate 1 第三轮复审：仍未通过

日期：2026-10-05。3.1保持通过；3.2–3.5仍未通过最终验收，3.6保持未完成，不进入Phase2。

## 已确认修复

- 主agent真实复跑：表1 complete/13项/2片，**13/13条引用按原始grid坐标回读cells相等**。R2的表头偏移正例已修好。
- 正式正文CLI请求3.1–3.4退出0、complete/4项；请求9.9.9退出0、partial并记录缺失集合。原先的CLI正例报错和该缺失条款false complete均已消除。
- prose的source_snapshot_id已填真实源指纹；重复条款更新start/end有效；CLI中SourceAdapter连接键映射已修正。
- 文件查询workspace已贯穿count/page，live source前后检查已接入；真实年报5/5、公报5/5、GB3095版本2/2跨页均complete。
- 当前8行JSONL均可单独解析，格式交付已修好。表头/单位/脚注目前以table_structure warning随结果交付，不作为本轮退回原因。
- 既有90项测试通过；Ruff check/format、OpenSpec strict、diff check通过。
- 主复跑前后public八表计数与冻结值一致、源指纹均95f7791fd84171ab727870fc5810d79b4327b0c4fa547d432951e0499a3808f8，active为c15c741742394320 / 4919b3938ad93747 / v4。原文库与目录均未写入，未变更服务，未发起真实模型请求。

## 独立验收结果

主agent新增 tests/test_gate1_acceptance.py，**9项独立验收全部失败**。这些测试表达前轮已要求的结果合同、原文坐标和完成前检查，不按当前实现改期望。失败日志见acceptance-results.txt；真实与隔离证据见replay.json。总状态是既有90项通过＋新增9项失败，不能再写“全部测试通过”。

### G1 高：正文引用仍不能完整独立回读，模型成功路径报错（3个失败）

真实GB18466定义3.1、3.2的引用可回读，**3.3、3.4的unit_rel_start为-1，2/4条引用回读不匹配**，但全部verified且complete。bind_citations用最大重叠选择owner，却仍以跨单元空白起点计算相对坐标，未裁到owner的原始边界。

requires_span已经记录span_offset_in_unit，但绑定时没有使用。裁切7.5后引用仍指向原始父块起点，独立回读落在“父块引言/7.1”。存字段不等于坐标换算生效。

模型合法输出通常只有quote而没有char_start。bind_citations直接max(None, owner.char_start)，抛TypeError。主agent走实际CLI入口、真实只读PG、仅在HTTP边界提供合法成功fixture响应，CLI退出1，错误为 int/NoneType不能比较。**不是实际模型服务失败，也不是网络错误**。模型quote需要在绑定的原始单元里定位并保存确切跨度，歧义要明确报告。

对应测试：test_model_quote_without_coordinates_gets_exact_source_span、test_sliced_unit_citation_uses_original_offset、test_separator_whitespace_never_creates_negative_unit_coordinate。

### G2 高：完成前守卫仍缺；文档token仍漏输出字段（3个失败）

enumerate_table仍只有读取前一次check_stale。第二次守卫应返回stale的隔离正式入口，实际只调用一次并complete。CLI enum-prose在reader结束之后才调用模型/抽取，返回前仍没有来源检查。独立测试在合法模型响应后改变源状态，**CLI仍输出complete而非stale**。

doc_enum的_live_source_fingerprint和workspace已接好，但_set_token仍只有doc_id/doc_name/self_code/version/title；改变doc_type、title_confidence、unknown_fields，token不变。报告所说“全部输出字段覆盖”没有对应当前代码。

对应测试：test_table_rechecks_source_before_complete、test_prose_cli_rechecks_source_after_model_extraction、test_document_token_covers_every_returned_metadata_field。

### G3 高：缺首片allow_partial仍崩溃（1个失败）

真实表1的原始行坐标已修复；但是缺首片时frag_meta被压缩、rows.row_origins保留原始片号，meta=frag_meta[fi]仍IndexError。原始坐标修改没有解决元数据错位。

应以稳定物理table_id/原始片号关联元数据；缺首片读到第二片时返回partial/missing_fragment并保存第二片正确引用，不能崩溃。

对应测试：test_missing_first_fragment_returns_partial_with_correct_remaining_source。

### G4 高：complete与项目支持关系仍可被绕过（2个失败）

contract仍允许warning含items/extraction就放过空prose/table complete，读取状态没有真正与答案状态分离。9.9.9这道CLI已能降partial，但底层合同的原反例仍成立。

_quote_supports以“任意两个字重合”当支持关系。“停车场”单独反例现已拒绝，但**“门诊停车场”引用“门诊、病房”仍被verified、error=None**。只能证明部分词出现，不能证明新增的停车场得到原文支持。给不受支持的项目加一个原文词就能通过，不符合明确命名集合的核验要求。

对应测试：test_pending_extraction_warning_cannot_authorize_complete_answer、test_partial_word_overlap_does_not_verify_extra_claim。

## 证据交付仍需补齐

JSONL格式已正确。最后一条场所抽取记录的实际keys仍没有request_messages或raw_response，model_call只含model/latency_ms/ok/error；与本轮报告“模型run保留完整输入输出”不符。本轮未重打真实模型调用，不否认原有调用记录。正式--with-model成功路径还需修G1/G2后实跑，按真实日志保存messages及未经重写的响应，不能仅给helper结果加cli_command。

## 接下来

按handoff-phase-1-enumeration-fixes-r3.md修复以上9项验收测试，再跑完整测试及真实CLI。保留本轮通过的13/13表格坐标、正文正例、缺失条款降级、workspace/source检查和JSONL。无需重建PG/v4目录。3.6由主agent复审。
