# 评分准备复审（2026-10-09）

**本轮未通过；正式付费两轮仍暂停。** 已通过的兼容模式和“新代不继承旧人工结论”保留，只补下面四组接缝。没有生产改进、网络/数据库请求或新模型调用。

## 实际验证

提交矩阵独立复跑19/19；历史冻结矩阵35/35。新增独立 owning-entry 矩阵17项：**15失败、2正例通过**，原始输出见pytest-independent-r1.txt。两正例为稳定来源正文可PASS，以及已映射且真正发现目标chunk的unit可命中。各输入均为临时合成终态+既存工件副本，不冒充未来运行/现场库。

29份选定保护清单1233条SHA、提交before/after登记11项、6个当前来源锚均无漂移。这是reviewer选定范围，不声称重跑提交方全部1369条。生产源未改，不重复526工程全套。OCR只作无LLM文件/规则选择；preview1533条全部登记reviewed/skipped，具体范围见ocr-coverage.json。

## S1：新代输入绑定不完整（阻断）

`verify_inputs` 只校验 manifest 中已列文件，未检查评分实际消费的文件是否都列入。删除terminal或answer文件的manifest条目、保留文件后，仍出裁决；所以“文件在目录内”被误当作“已受清单保护”。

同一入口另有四个正向放行洞：仅post.env_sha漂移或counts变化仍接受；93+30只验数量，重复一个key/漏另一个key仍接受；删掉批准锚的rerank/local/compat及全部evaluation_code_anchors仍接受；answer文件内query_id换成另题仍按目录题号评分。必须统一以**完整批准身份/来源谱系 + 固定gold×路径的唯一矩阵 + 实际消费工件清单 + 题目绑定**为输入合同，而不是继续逐个补布尔。

## S2：人工PASS能救合成硬失败（阻断）

真实已存syn-002/pg有4项逐字来源、coverage=partial。新代给它一个绑定正确的PASS记录，工具发布整题PASS；把其中引用改为伪造quote、coverage声明complete，也能PASS。根因是synthesis分支总返回`synthesis_pending_human_review`，finalizer只检查judgement是否在_POS_FAIL，没有将coverage与独立引用核验的明确失败纳入不可覆盖条件。人为审核语义不能覆盖这两类应用合同失败。

新代记录的错轮也被静默忽略（提交测试正是断言PENDING），与既定“错绑定拒绝”合同不符。修复应共用完整记录验证器：消费的run/round/qid/path/runtime/response绑定与可审核缺口一致；未提交记录才是待审，提交错记录是输入拒绝。保留无记录不继承旧结论、正确fact载体记录可PASS等正例。

## S3：所谓typed证据召回实际是文档命中率（阻断发布指标）

`typed_evidence_recall` 先丢掉发现chunk/unit身份，读取doc列表，再以“目标unit所属文档出现在列表”记unit命中。同文档仅发现c-other、目标unit只链接c-target，也报1.0。`chunk_ids`根本不参与。映射还仅以unit_id为键，另文档同id会覆盖原条目；缺映射unit从分母排掉，一命中+一未映射报1.0。

须用workspace/doc/unit组合键与真实发现chunk→unit链接或有类型目标对应关系，typed-doc命中不为文档全部unit背书。未映射unit保持固定期望分母，整题指标pending/null并列已知部分；不得发布缩水分母的满分。可以只把现有结果更名为doc覆盖并把typed指标留待审，但不能继续称证据级召回。本轮冻结正例保持；全量映射采集仍未授权。

## S4：拒绝出口未包围实际评分读取（阻断）

前置try结束后，answer JSON解析、人工SHA/response绑定、recall读取等才执行。损坏answer JSON或错误记录SHA会抛异常，却没有input-rejection.json。部分load_records/mapping抛InputIntegrityError也被直接raise而无诊断。必须一个owning失败出口包围全部消费/校验/评分/附加读取，任一普通异常先净化诊断再非零，不产裁决；失败前内存计算不算发布。不借他题记录，不修改原输入。

## 裁决与范围

评分器“就绪”的结论撤为待补正；19项与35项通过的事实保持。只在新评分副本代次修S1–S4，详见handoff-phase-4-scoring-readiness-fixes-r1.md；旧代码、工件、gold、真实锚、历史评分、全部冻结字节不动。第二轮与额度问题延后到评分准备真正通过。6.2–6.5、Gate4和默认路径不变。
