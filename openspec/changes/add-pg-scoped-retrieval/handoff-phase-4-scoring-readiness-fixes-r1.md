# 评分准备 S1–S4 有界补正

## 范围与开始方式

本组仍为零网络/DB/模型请求，不需新额度。已验收兼容与新旧人工结论分离保持；不改生产源码/gold/.env/真实锚/历史目录/35冻结。新副本和报告放在 **phase-4-scoring-readiness-r2/**，输入为上一组只读基线。before SHA先捕获；脚本输出只能写新空位；PYTHONDONTWRITEBYTECODE=1防历史pyc变化。

先用独立矩阵确认红相：
`reports/pg-retrieval/phase-4-scoring-readiness-review/test_scoring_review_r1.py`（17项，当前15失败/2正例）。
补后设置 `ENV_RAG_SCORING_READINESS_SCRIPT` 指向新副本复跑；矩阵字节不改，不删除断言/xfail。测试辅助构造来自只读上一代test_scoring_readiness.py，不包含真实服务。

## S1 一个完整的新代输入合同

在生成模式执行统一结构/身份验证，不放宽兼容模式已验规则：

- 固定gold正例31/反例10×pg/local/fusion的每轮123个**唯一**键，题号/路径/category/is_counter逐个匹配；不能只计93+30。
- source/catalog run+snapshot/search/gold/counts/env的pre/post逐字段核对，结构必填；counts比批准锚冻结计数，env至少pre/post相等，并与批准运行代次的env锚（有则必须校验）一致。matches_frozen自报true不代替值。不能为旧代生成模式缺字段加豁免。
- code_anchors中已验六代码/提示、evaluation_code_anchors中评测及改进调用链的必需键先检查结构完整再比SHA。删键不能“省略比较”；旧兼容模式保持原输入口径。
- 评分每个**实际读取**的terminal、answer、fusion/local inputs及发现回执等必须出现在所绑定运行manifest并通过SHA；仅遍历manifest既有条目不够。跨目录来源必须是显式绑定附件，不能隐式从别代补齐。合法失败腿没产answer可如实判FAIL/待审，但存在未登记的文件不得悄悄消费。
- answer/fusion回放的qid/workspace、题面等与该key/冻结问题绑定核对，不能只相信文件路径。根目录/轮目录形状兼容真实owning工件，禁止拿别题首条results作当前答案。

实现可集中在输入校验/读取注册器；不另写检索或改既有投影规则。批准锚不能在校验中由当前代码回写。临时fixture锚完整正例保留。

## S2 人工只能解决语义缺口

在人工层之前归纳不可覆盖的硬失败：budget/runtime/coverage不complete、独立来源/引用失败、明确数值不支持、漏项等。尤其synthesis不能因为j固定pending便避过这些字段。partial真实片段要保留诊断，但PASS记录不把整题升级；引用伪造同样硬FAIL。无需第二次LLM，不改gold语义或从raw自动补答案。

人工记录用同一绑定校验入口，明确缺记录=PENDING、提交错轮/错key/错runtime/错响应=拒绝且诊断。核对schema、键合法/重复冲突、类型与审查者/理由/已核项；PASS只解除其明确审核的缺口，未知judgement不允许任意PASS。正文/附录来源仍分列，raw答对但应用不交付仍不算完成。

上一组自有`test_wrong_round_record_does_not_apply`用静默忽略作成功，这是与交接不符的**非冻结**断言：允许强化成拒绝+诊断。其它已通过断言不得弱化；旧35项冻结不动。新未审合成可PENDING，完整且独立引用通过的合成经具名语义记录可PASS，成对证明不全拒。

## S3 不再把文档覆盖称为typed证据召回

保持发现段原始身份而非先降成doc列表。以完整(workspace,doc_id,snapshot,unit_id)索引映射；发现chunk必须真在目标unit.chunk_ids中才支持unit发现，typed unit/table目标按自身身份核对，scope按真实成员关系，纯typed-doc仅算文档发现，不自动命中其所有unit。

固定gold target_evidence的期望单位集合，未映射单位仍在期望分母中。已知命中/未命中/未知分列；有未知则整题typed指标pending/null，可列有明确标签的已知部分但不发布缩水分母满分。同unit_id跨文档不覆盖、不互相计分；零发现保持0，枚举/精排/展开不反灌。可暂缓typed完整实现，但必须给pending/null与原因、保留接口正负例；不得仅改字段名把doc率填回typed。

映射采集仍仅设计、不得执行。设计行数/字段从已存活跃manifest核实，scope的requires_span实际schema字段位置需对照源定义，不把猜测写成已验证。完整映射采集时需要同一只读快照、排序组合键、完整性/终态与内容清单守卫；本组fixture只证明接口。

## S4 唯一拒绝出口覆盖全部消费

把记录/映射装载、输入核验、实际answer/fusion解析、记录绑定、评分/recall/账本与结果构造纳入同一owning失败边界。InputIntegrityError也要诊断，不能专门except后直接raise漏写。任何普通异常保留真实类型/净化原因、先写新输出位置input-rejection，再非零抛出，裁决文件只能最后成功时原子发布。目标父目录处理要明确，不覆盖别题/历史诊断；不吞错误后继续产部分可信裁决。

给出少量必要正例：完整新代可评分、正确正文PASS、正确chunk→unit命中；错误SHA/坏JSON必须诊断存在。两轮错误记录不借其它轮。输出已存在拒绝不得覆盖。

## 交付与停止点

新评分副本/专项原始结果、四组修复对照、准确输入合同、manifest最后写、工作面ruff/strict/diff/敏感扫描、源码与历史SHA复核。复跑独立17项+原35冻结+自有矩阵；来源未改不重复526。r3备案12/13细标签保持观察、不改旧目录。

明确注明“zero新请求、fixture/已存工件副本”；本组不建真实正式锚、不问额度、不跑123/246腿、不改变默认融合。停主agent复审；6.2–6.5/Gate4不勾。通过之后才进入正式评测交接。
