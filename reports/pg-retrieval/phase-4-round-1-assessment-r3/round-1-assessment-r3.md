# 6.2 第一轮离线评分 r3（增量补正 R1–R3，2026-10-08）

代次与守卫：本目录 `phase-4-round-1-assessment-r3/` 为最终裁决代次；`phase-4-round-1-assessment/`（r1）与 `phase-4-round-1-assessment-r2/`（r2）经复算逐字节保留（4 项与 9 项原清单全匹配），原运行 809 项清单全匹配。仅离线：0 网络/模型/DB 写/健康探测；未改生产代码、tests 冻结、gold、.env、锚、两轮冻结矩阵与历史工件。验收：两轮冻结矩阵 **35/35**（本轮先在新代次上精确复现 14 失败/4 正例，再修）+ r3 自有必要测试 13/13 + 历史 r2 10 项与 r1 6 项在各自原工件上回归通过；adjudication 重跑字节一致（SHA `9e2ec407e24b03cd…`）。r2 的 36/42/15 与 20/3/7 作为未通过工具的暂存结果撤下，不再引用。

## 1. R1 完整声明支持与身份（先于评分的可审计规则）

规则（无 LLM、逐条可复算）：金标两种形状的编号均绑定 `item.clause`（字符串金标取前导编号；无编号名称投影**不硬造编号**）；`item.doc_id` 与 `citation.doc_id` 同时存在必须一致，prose 范围判定由 OR 改为 AND（矛盾归属直接不可入范围并记身份失败）；所交付全文须能由**声明的原始 unit 跨度/按声明顺序的跨 unit segments** 拼接后经空白归一完整回读——不要求 text==quote（合法 quote 截 120 字，声明跨度可支持全文），不以 gold 子串或词集放行附加声明。

真实行变更（本轮唯一正例变化，逐行分列）：**prose-enum-003 三路 PASS→FAIL**。pg/local/fusion 的 4.3.4 交付同一 20,636 字符原文（归一 20,631），而 citation 的 6 段声明顺序拼接为 20,626——全文不在声明顺序跨度内，`unsupported_declarations` 记录 idx/clause/doc_id/段数/长度与问题串，**旧 citation 顺序原样保留、未重排**。prose-enum-001/002/004/006 与全部 table/file 真实交付在新规则下复验仍逐条被声明跨度支持，保持通过；篡改面（错编号 9.9.9、真实引句尾部追加伪造声明、声明文档与引用文档矛盾）全部拒收且经真实行证明非全拒。

## 2. R2 反例：整题行为合同与安全观测分字段

按主 agent 2026-10-08 裁决表逐题落实到 canonical rows（`final_basis=frozen_behaviour_contract` 等），`local_safety_observations` 单独成字段，宽泛的"missing/partial/ambiguous/isolation 同类即 PASS"取消：

| 反例 | r3 整题 | 局部观测（分列） |
|---|---|---|
| neg-001/006 pg·fusion | **PASS**（显式 missing 答复，0 交付） | 未用版本替代 |
| neg-001/006 local | **FAIL**（partial/条件不足≠明确 missing 答复） | 未乱答、无 false complete |
| neg-002 ×3 | **PENDING**（隔离合同需对抗证据） | 本腿未见外 workspace——观测级，不升格 |
| neg-003 ×3、neg-004 pg·fusion | **PASS**（结构证据：集合/覆盖/引用身份） | |
| neg-004 local、neg-005 pg·fusion | **FAIL**（保持已确认） | neg-005 仅判当前行为，不宣称底层表身份串并 |
| neg-007 ×3 | **FAIL**（partial≠冻结 ambiguous） | 保守拒绝、未编造表号 |
| neg-008 ×3 | **PENDING**（成员/字符展开预算反例未实测） | PG 请求前额度闸门拒绝正常——控制项独立记录（不折整题 PASS；亦非 6.1 工程验收回退） |
| neg-009 ×3 | **FAIL**（expected 应答而 0 交付=整题未回答） | 不构成内容丢失/版本乱答证据 |
| neg-010 pg·local | **FAIL**（同上） | model_failure/条件不足保留 |
| neg-010 fusion | **FAIL**（主 agent 语义裁决：4.1 四条排放/消毒/禁排/脱氯真实但未答替代关系） | manual_review 含四条 `delivered_item_citations` 实际工件位置 |

18 条正例合成逐行 FAIL 与原始 HTTP 账本保持；分母仍 93+30，全部汇总由新 canonical rows 生成。

## 3. R3 拒绝边界闭合

- **后置身份必验**：`identity_after` 缺失或四字段（source_fingerprint/catalog_active run+snapshot/search_active/gold_sha）不完备→评分前拒绝；字段须与冻结锚及 before 一致，`finished_at`/`matches_frozen` 布尔不可替代（测试用内存副本删除 post 即拒）。
- **解析证据内容绑定**：不再以目录存在为准——复用已验收审计函数 `fingerprint_artifacts` 全量重算 blocks/tables 字节指纹，与 Gate-0 冻结分量 `parsed_blocks_tables_bytes` 对账（本轮 `fccb2748…` **匹配**），不符即拒绝。
- **统一拒绝诊断**：main 的验证/读/解析整段设单一边界，普通异常写净化 `input-rejection.json`（保留真实异常类型/原因，凭据模式剔除）并非零抛出、绝不产出 adjudication（损坏 manifest 用例诊断类型 JSONDecodeError）；SystemExit/KeyboardInterrupt 不吞。正常输入零网络全通过。
- 全程仅用已冻结文件、原始解析产物与本地代码身份，无新增线上核验。

## 4. r3 记分（分母全保留，由 canonical rows 生成）

| 类别 | PASS | FAIL | PENDING |
|---|---:|---:|---:|
| fact (21) | 0 | 9（0 交付×6 + 片段×3） | 12（正文载体待人工） |
| file_enum (18) | 14 | 1（file-005 local 漏 2） | 3（file-004 独立证据缺口） |
| prose_enum (18) | 8（pg 4·fusion 4·local 0） | 10（pg 2·local 6·fusion 2） | 0 |
| table_enum (18) | 11 | 7 | 0 |
| synthesis (18) | 0 | 18（人工判定） | 0 |
| 正例合计 | **33** | **45** | **15** |
| 反例 30 | **9** | **14** | **7** |

FAIL 构成：synthesis 18、projection_mismatch 7、no_delivery_coverage 6、foreign_doc_rows 4、partial_fragment_correct 3、unverified_citation 3（=R1 的 prose-003×3）、coverage_not_complete 3、set_mismatch 1。fact 无机械 PASS 为 A2 收紧后的真实状态（正文载体待人工）；召回口径、账本修订（10 腿预留/实发差、拒绝 3 条、合成 HTTP 9+2=11）与时延说明同 r2 保持原样（见 `adjudication.json.ledger_and_timing`）。

## 5. 遗留待审清单

正例 PENDING 15（fact 载体 12、file-enum-004 3）；反例 PENDING 7（neg-002×3 隔离合同、neg-005 local 内容、neg-008×3 覆盖空白）；table-enum-003 两格掩码细节 unknown（整题 FAIL 不软化）；typed 证据召回 pending；机械 PASS 33 行受主 agent 抽审；neg-008 成员/字符展开生产路径未实测；sanitizer 数值碰撞工件缺口（仅建议）。本轮**不发布**成功率/召回均值等汇总指标；不勾 6.2/6.3/Gate4，第二轮未启动，默认路径未改。

工件：`assess_round1.py`（零网络可复算）、`test_assessment_round1_r3.py`、`adjudication.json`（123 行 canonical + R1 unsupported 记录 + R2 分字段 + 分段召回 + 账本）、`assessment-manifest.json`、`input-rejection-*.json`（正常输入不产生）。
