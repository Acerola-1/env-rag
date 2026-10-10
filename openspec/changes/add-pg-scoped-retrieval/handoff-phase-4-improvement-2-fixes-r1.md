# 改进组2增量补正：归属证据与无编号范围证据

四条原混入（17→4、13→1、44→13、对照13）已修复并独立复验，497工程、30提交/改进组1冻结、35评分冻结均通过。**仅补下面A/B两组，不返工canonical编号门、评测停止晋升、空发现和改进组1。** 可直接实施，0真实网络/数据库/模型/embedding/rerank请求、0写库/探测；不跑第二轮。

新增冻结矩阵`reports/pg-retrieval/phase-4-improvement-2-review/test_improvement2_review_r1.py`当前5失败/1正例，先复现，不可删改/xfail/弱化。实施默认仍仅answer.py/evaluation.py及必要自有测试，其他组件、提示、gold/.env/锚/旧冻结/诊断/历史代次保持。

## A 归属证据双向闭合

1. 拒绝裸路径discovery=doc_attribution、任意membership_basis字符串/布尔。问题有“含修改单”不是外来文件的归属证明，名称相似也不是上游验证。不能凭candidate自己的标签将unknown self_code文件加入allowed。
2. 读取并贯通真实5.3发布形状的typed doc_attribution及allowed_set_basis.verified_attributions、原membership_basis与catalog_row引用。核对同请求、workspace、active snapshot、doc_id和当前目录存在/身份，复用已验收的归属请求与来源验证语义；不能只看citation_verified=True或把字符串改成长字典就放行。元数据核对走owning受预算连接，不按candidate文件名猜canonical。
3. 上游已确认归属目标即使没有usable chunk，仍进入完整scope注册/读取；不能只从candidates_by_doc找证据。原5.3已验收的修改单/整合版正例保持，自身编号请求不放宽。
4. 新矩阵合法typed-only正例用5.3真实字段形状构造，包含有效身份引用和允许集依据，要求目标与合法修改单都交付；两个伪标记反例要求只交付合法标准。
5. 可为本组自有`test_attribution_evidence_honored_for_related_request`正例补上真实结构化上游fixture，维持其保留合法相关文档的断言；仅一条“recorded by 5.3”字符串不是正例证据。原18项其他断言不删弱化，新6项冻结及旧冻结不动。

## B 无编号时也必须确认范围依据

1. 无编号分支不能因为resolved列表非空就认定确认完成：该列表混有typed发现，纯local输入也能自报targets_resolved。
2. 对旧typed discovery=local、path_provenance.discovery_only=True/targets_confirmed=False，以及没有真实逻辑范围/元数据确认证据的发现集合，明确partial/ambiguous、selected_docs与答案items为空；审计保留原发现和拒绝理由。
3. 有真正已确认元数据/逻辑scope的无编号请求保留。确认依据需要可验证的workspace/snapshot/doc/scope或集合谓词与当前目录一致，不把target_type字段名或一个confirmed布尔当证明。新增一项合法无编号scope/元数据owning正例，与伪晋升成对，不能全拒无编号达标。
4. file_enum分页、年报/公报、上游已验证missing/stale保持；本路零发现不伪报全库缺失。不得从gold/PG其他运行/历史答案注入目标，不回填发现与召回。

## 验证与交付

先新6项+原18自有/改进组1相关检查和上述合法无编号正例，再相关范围/归属/版本/文件/预算/终态冻结。相关通过后一次全工程与35评分冻结，Ruff/strict/diff/敏感扫描及保护清单。不要反复全套或新发服务请求。

新证据写`reports/pg-retrieval/phase-4-improvement-2-r2/`，原实施目录保留。附归属证据从typed/允许集到目录核对再到最终items的轨迹、无chunk完整读取、伪标记安全拒绝、可信/不可信无编号范围成对、四条已修复输入的结果保持、SHA前后。证据标构造/存量读取/离线owning回放，不冒充现场数据库。

旧评分r3 12/13细类标签继续非阻断，不更新旧锚或加SHA豁免；当前保护清单通过结论保持。提交后停主agent复审，第二轮/6.2/6.3/Gate4保持暂停，不切默认路径，不扩到其他漏项/合成/单位问题。
