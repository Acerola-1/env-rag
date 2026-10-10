# 6.2 第一轮离线评分 r2（补正 A1–A6，2026-10-08）

代次与守卫：本目录 `phase-4-round-1-assessment-r2/` 替代上一版机械判定；原 `phase-4-round-1-assessment/`（含六项测试与 9 项清单）原样保留作历史，其掩码即整题 pending 的政策属本次被纠正项。仅离线：0 模型/embedding/rerank/PG/Qdrant/Neo4j 请求、0 写库、0 健康探测；未改生产代码/提示/.env/锚/gold/历史工件；round-1 原 809 项 manifest、原评分目录 9 项清单、gold SHA 全部复算一致；主 agent 冻结验收矩阵 17/17 通过（先精确复现 12 失败/5 正例），r2 自带必要正负例测试 10/10；`assess_round1.py` 零网络复跑字节一致（adjudication SHA `c97b6742d3dff0e4…`）。

## 1. 判定原则修正（A1–A6 → 实现落点）

- **A1 集合与声明投影**：prose 匹配同时绑定**条款编号+被问内容+目标文档范围**（正确原文配伪造编号不再通过）；`seq_name` 投影改由**实际交付行**形成——匹配不上任何 (序号,名称) 对的行计入 `extra_rows` 并逐项列出，源行真实不再让多项消失；name-only 合法同名子行消费保留。
- **A2 fact 关系与来源资格**：删除固定数组索引+字符串集合的 token 猜测。机械 PASS 只允许"gold 原行逐格精确交付+引用独立核验+覆盖 complete"；正文载体一律不机械过，入人工待审并记录引用状态。fact-004 pg/fusion 旧 `pass_mechanical` 即此类假通过，现转 pending；fact-002 三路正确片段与 partial 形态保留（整题未答=FAIL+片段记录）。
- **A3 来源身份与元数据**：table/prose/catalog 统一核对 **workspace+目录快照+文档存在性**（值来自配置锚冻结守卫，非自报）；内容重读存在性只是其中一项。catalog 引用不得自洽即真：名称/编号版本须与 SHA 守卫的独立运行输入（inputs usable→文件名）核对，伪造名拒收；citation 缺冗余 doc_name 的两份合法归属文档经独立输入定位后通过（file-enum-005 pg/fusion 由旧 pending 转 PASS）。完全无独立证据的归属文档（file-enum-004 三路各 1）如实 pending，不空过也不误判错。反例行为评分同样过来源资格（neg-003 真实通过保留、foreign workspace 拒收）。
- **A4 先守卫后评分**：`main()` 先验 manifest(809)/gold SHA/锚与 pre·post 实际身份/所复用代码 SHA（answer.py、fusion.py 对锚）/解析证据可得性，任一不符写净化后的 `input-rejection.json`、非零抛出，不产出 adjudication；正常输入零网络通过。
- **A5 发现召回口径**：按已验收 `fusion._normalize_pg` 的保存形状分列 **chunk 候选（有序，记 @20）与 typed 目标（doc/scope/table_unit 发现，无排序声明记覆盖）**，不拼接冒充统一 recall@20；显式 0 发现保持 0，`usable/targets_resolved/枚举答案/精排/展开`一律不回填。**旧 pg 0.959 / local 0.952 / fusion 0.991 撤下**（旧读数漏掉 typed discovery）：file-enum-005/pg 实际 `typed_n=3、chunks=0`——三份目标文件是**真实 PG 发现**，不能描述为"PG 漏文件、fusion 补到"，pg/local/fusion 该题发现覆盖均为 1.0。typed 证据（unit/chunk 级）召回仍 pending；本轮不发布新汇总均值，留待口径审查。
- **A6 最终裁决分层**：每行统一 `final_status PASS/FAIL/PENDING + final_basis + final_reason`；决定性整题失败（投影/集合/合同/覆盖/人工）优先于细项 unknown——table-enum-003 pg/fusion 掩码两格仍记 pending 细节，但 coverage≠complete 整题判 FAIL；18 条正例合成逐行写入 `manual_review`（理由+实际交付/HTTP/工件定位，非布尔），汇总全部由 canonical rows 生成。

## 2. 正例 93 行最终裁决（分母全保留）

| 类别 | pg | local | fusion |
|---|---|---|---|
| fact (7) | FAIL 1 · 待审 6 | **FAIL 7**（0 交付×6 + 片段×1） | FAIL 1 · 待审 6 |
| file_enum (6) | PASS 5 · 待审 1 | PASS 4 · **FAIL 1（file-enum-005 漏 2）** · 待审 1 | PASS 5 · 待审 1 |
| prose_enum (6) | PASS 5 · **FAIL 1** | **PASS 1 · FAIL 5** | PASS 5 · **FAIL 1** |
| table_enum (6) | PASS 5 · **FAIL 1（003 ambiguous 整题）** | **PASS 1 · FAIL 5** | PASS 5 · **FAIL 1（同左）** |
| synthesis (6) | **FAIL 6（人工判定，见 §4）** | FAIL 6 | FAIL 6 |
| 合计 | **PASS 36 · FAIL 42 · PENDING 15** | | |

与旧版机械表的差异均为上述原则的直接结果：+file-enum-005 pg/fusion（独立输入定位）、−fact-004 pg/fusion（假 token 通过撤销转待审）、−file-enum-004×3（归属文档无独立证据转待审）、table-enum-003 pg/fusion 待审转整题 FAIL（掩码细节仍记录）、18 合成待审转 FAIL（人工判定落行）。主 agent 确认保留的项全部维持：file-enum-005 local 漏 2、local 混入/漏项各 FAIL、fact-002 片段。

## 3. 反例 30 行（实际行为；expected 仅事后对照）

| 反例 | 最终 | 依据 |
|---|---|---|
| neg-003 ×3 | **PASS** | 自身编号集合+覆盖+引用身份全通过（来源资格加入后真实行为不变） |
| neg-004 pg/fusion **PASS**；local **FAIL** | 13 项合同满足；local 44=13+31 混入判错，不以"≥13/都真"过关 |
| neg-005 pg/fusion **FAIL**；local PENDING | 两路 complete+跨文档 overclaim，不符冻结 ambiguous；**仅判当前行为，不宣称底层表身份串并**；local ambiguous 77 行内容待审 |
| neg-008 ×3 | **PASS+覆盖空白注明** | PG 构造守卫按预期拒绝；成员/字符展开路径**未获生产验证** |
| neg-001/002/006/007 ×3 | PASS（事后对照） | 0 交付、无 false complete，与期望（missing/isolation/ambiguous）同属保守拒绝侧；neg-002 仅观测级隔离，不升格 same-id 对抗实弹 |
| neg-009 ×3 · neg-010 pg/local | **PENDING 上报** | 期望为应答（ok）而 0 交付——"应答未答"质量缺口如实记录，不填 PASS 也不武断 FAIL |
| neg-010 fusion | PENDING | 交付 4 条真实引用但未答修改单范围之问，over-answer 疑点入待审 |
| 合计 | PASS 20 · FAIL 3 · PENDING 7 | |

## 4. 合成人工判定（已逐行写入 canonical rows，18 FAIL）

- **syn-001 ×3**：三路 `incomplete_conditions`（版本对未全解析）→ HTTP 未发出、0 交付 → 整题失败。
- **syn-002**：pg HTTP 交付 4 条绑定真实来源（4.1 执行表1/消毒/禁排/脱氯 0.5 mg/L）但缺 6.1 取样监测与表2/预处理侧 → FAIL，4 条记正确片段；fusion HTTP raw 9 claims 全拒 0 交付 → FAIL；local 未发出 → FAIL。
- **syn-003**：pg HTTP raw 0 合格 → FAIL；local 未发出 → FAIL；fusion 交付 5 条绑定真实（4.1/4.2 级别选择条款）**不对题**（gold 问 6.1 采样位置）→ quote 真≠答案被支持 → FAIL。
- **syn-004**：pg/fusion 各 HTTP 200（raw 10/8）合同全拒 0 交付（raw summary 媒体映射不为失败补分）→ FAIL；local 未发出 → FAIL。
- **syn-005**：三路均 HTTP 发出、合同拒收后 0 交付 → FAIL。
- **syn-006**：三路 `incomplete_conditions`（过渡期/批准日期条件）→ 未发出 → FAIL。

计数订正（对旧版 §4/§6）：**正例合成实发 HTTP = 9 腿**（账本凭证：syn-002/003/004 的 pg+fusion、syn-005 三路），另 2 腿为 neg-010，全轮 answer HTTP 合计 11；旧表述"18 行中 11 行发生 HTTP"有误。第一轮预算拒绝 = **3 条**（neg-008 三路，issued=0），旧"15 条拒绝"为试点代次数字。

## 5. 发现召回（分段口径；不发布均值）

逐题×路径的 `chunk_recall_at_20 / typed_coverage / union_coverage` 与 `explicit_zero` 全部在 `adjudication.json.recall`。要点：file-enum-005 pg=typed 3/3（chunks 0）——路径对照结论按此修正；typed 证据召回=pending（chunk→unit 离线映射不足）；无保存全局发现顺序，不合并统一 @20。旧均值 0.959/0.952/0.991 自本报告撤下。

## 6. 账本与时延（保留的修正）

1. answer_llm **10 条腿预留 1/实发 0**（syn-001×3、syn-002/003/004 local、syn-006×3、neg-010 local）——"除 neg-008 外 120 腿逐服务相等"误写维持更正；其余服务逐腿相等。
2. fusion `discovery_ms` 含精排（inclusive）；exclusive≈discovery−rerank 仅近似；answer_ms 复合不可拆、独立阶段计时 unavailable。
3. "约 44 分钟"仍为**作者报告**非工件自证（记录总和 744.775s、工件 mtime 跨度 977.1s，差额不归因）；串行、无跨题缓存。
4. HTTP 层本轮 0 服务失败（11/11 送达均 200）；差距归因维持"已观察证据内"表述。

## 7 待审清单与缺口（分母全保留，不发布假精确汇总）

正例 PENDING 15 = fact 正文载体 12（含 fact-004 转回）+ file-enum-004 归属文档缺独立证据 3；反例 PENDING 7（neg-005 local 内容、neg-009×3 与 neg-010 pg/local 应答未答、neg-010 fusion over-answer）。另：table-enum-003 两格掩码细节 unknown（整题已 FAIL 不软化）、typed 证据召回 pending、机械 PASS 36 行仍受主 agent 抽审、neg-008 成员/字符展开覆盖空白、sanitizer 数值碰撞（`6000`）仍为工件侧真实缺口（仅建议，不改生产）。

工件：`assess_round1.py`（零网络可复算）、`test_assessment_round1_r2.py`、`adjudication.json`（123 canonical rows+分段召回+账本）、`assessment-manifest.json`（本目录 4 文件 SHA）；凭据模式扫描 0 命中（宽松词表命中的 29 处均为 `condition_tokens` 字段名与方法学注释文字，非机密）。原目录与原运行工件未动。
