# 第一轮离线评分补正 A1–A6（主 agent，2026-10-08）

直接执行本交接，不需要再申请授权。**仅离线补正，不启动第二轮。** 0 网络/模型/embedding/rerank/PG/Qdrant/Neo4j 请求、0 写库、0 健康探测；不改 src、已验收 tests、gold、.env、配置锚、历史运行/报告/manifest。Gate 3 和6.1保持通过，6.2/6.3/Gate4保持未勾选。

## 工作代次与验收接口

保留原 `phase-4-round-1-assessment/` 目录（含六项测试）原样，输出到 **`reports/pg-retrieval/phase-4-round-1-assessment-r2/`**。评分器可以复制修正；保持 `score_row`、`verify_citations`、`answer_items`、`doc_registry`、`pre_expansion_docs`、`main` 的现有接口供冻结矩阵使用。

主 agent 新冻结矩阵在 `reports/pg-retrieval/phase-4-round-1-assessment-review/test_assessment_review_r1.py`（17项，当前12失败/5正例通过），不可删改/xfail/弱化。用环境变量指定新评分脚本运行：

```bash
ENV_RAG_ASSESSMENT_SCRIPT="$PWD/reports/pg-retrieval/phase-4-round-1-assessment-r2/assess_round1.py" \
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -q \
  reports/pg-retrieval/phase-4-round-1-assessment-review/test_assessment_review_r1.py
```

先复现，再完整修同一类判定原则；不要只针对题号、数字或这17项样本打补丁。只新增必要正负例，不重跑全套工程验收。原六项测试中“掩码就让整题 pending”的断言属于本次被纠正的评分政策：原文件保留作历史，新代次应同时断言引用细项 pending 与非complete整题 FAIL，不能以旧错误政策强迫放行。

## A1 集合与声明投影

- prose 要匹配编号+被问内容+文档/版本/范围；同一句正确原文配伪造条款号必须失败。连续引句真实不自动支持修改后的交付声明。
- `seq_name` 应从实际交付形成投影并列未命中项，不能只收 gold 命中的子集导致 extras 消失。name-only 的合法同名子行消费按既有合同保留；不得把所有多行都拒绝。
- 保持 table-enum-001、prose-enum-002 等真实正确交付通过，并保留已确认 local 混入/漏项失败。

## A2 fact 关系与来源资格

- 所有载体（表格/正文/模型声明）的 PASS 都必须具有独立来源核验、正确身份、完整被问关系、完整答案覆盖；不得存在正文特例绕过 citation verdict。
- 禁止以固定数组索引和字符串集合猜级别/单位。用冻结 gold 的被问断言与真实表头/行结构/正文关系核对；无法离线证明的载体保留人工待审，不能假机械通过。
- fact-005 的二级新扩改20、现有30，不能由一级10+现有30凑词满足；引用根本不成立时不得 PASS。fact-002 缺单位保持 partial 和正确片段，不从 gold 或常识补单位。

## A3 来源身份与元数据

- 对 table/prose/catalog 共同核对 workspace、doc、snapshot 与本腿受冻结守卫保护的身份；内容回读存在性只是其中一项。反例行为评分也不能绕过共同来源资格。
- catalog 引用以独立已有、SHA守卫的原始/映射证据核对真实名字、标题、编号版本和归属依据；“doc_id自洽+任意非空name”不是真证据。
- file-enum-005 的两个合法归属文档允许缺 self_code 与 citation 的冗余 doc_name；可借已冻结、独立输入中的真字段定位核验。若证据确实不足就注明 pending，既不强制凭空加字段，也不拿同一答案为自己背书。

## A4 先守卫、后评分

- 验证原运行manifest、gold、锚/配置、pre/post实际身份一致性以及所复用代码/解析证据身份，成功后才允许逐行评分/汇总。
- 任一不符非零退出，落独立净化的输入拒绝诊断；不得产出/覆盖可信 adjudication。原始普通异常保留。不需要任何线上核验。
- 正常输入通过必要正例；错误 gold SHA 必须在第一次 score_row 之前被拒，冻结测试使用进程内常量和临时输出不会改 gold。

## A5 发现召回口径

- 阅读 `fusion._normalize_pg` 与已保存运行形状：typed_targets 是从 PG 的真实 discovery_candidates 分离出来；文件/范围的 typed discovery 必须保留，不能只看 chunk candidates。
- file-enum-005/pg 全部三个 typed 文档是真发现（discovery_total=3，captured=True，chunks=0），`pre_expansion_docs` 必须识别三份；禁止依赖 gold 答案来修这个值。
- 保留类型、workspace、来源阶段。没有保存全局排序就不可拼typed/chunk再假称统一recall@20；明确分列可证的排名口径与typed发现覆盖，缺顺序的指标 pending。不得用 resolved目标、展开、精排或答案回填。
- 显式零发现始终零；映射不足的 typed 证据召回保持 pending。重新生成逐题缺口与汇总，撤下旧0.959/0.952/0.991作为可比较发现召回的结论，只有口径审查通过后才发布新数字。

## A6 最终裁决与报告一致

- canonical rows 统一增加 `final_status`（PASS/FAIL/PENDING）和决定性理由；机械投影、引用证据缺口、coverage、人工语义判定分列。共同原则：已经有决定性整题失败，就不能因为另一个细项 unknown 把整题改为待审。
- table-enum-003 的掩码引用细项仍 pending，但 ambiguous 的整题 exact 是 FAIL。
- 18条正例合成已审整题失败逐条写 `manual_review`（理由+实际交付/来源定位，不仅布尔），`final_status=FAIL`；别继续以“待人工”计38待审。93正例和30反例分母全部保留，汇总从canonical rows生成。未能证明的其他载体如实pending，不强迫填出通过数。
- 反例expected仍仅事后评分，不路由；neg-003/004正确行为保留，neg-005不符冻结合同保留且不宣称底层身份串并。
- 修正正例 synthesis HTTP 为9，全轮11中的另外2为neg-010；第一轮拒绝为3，非旧试点15。保留正确的10个answer预留/实发差额修正与时延不确定说明。

## 交付停止点

新脚本、必要测试、可零网络复算的adjudication、人工判定及证据、更新报告、稳定文件SHA manifest（不把__pycache__当交付）、敏感扫描。注明原始机械表被新代次替代，原目录不改。复算原809项与原评分9项清单仍匹配，生产/冻结/gold/锚字节未变。

修完17项冻结矩阵与必要正例后一次提交，停止主 agent 复审；不自行扩批、修生产代码、换提示/模型或勾6.2/6.3/Gate4。
