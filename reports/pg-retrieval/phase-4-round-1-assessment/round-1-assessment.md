# 6.2 第一轮离线评分与口径核验（assessment，2026-10-08）

范围与守卫：仅用 round-1 既有工件（809 项 manifest 复算全匹配）、固定 gold（SHA `1bf13007…` 匹配）与本地解析产物；**0 模型/embedding/rerank/PG/Qdrant/Neo4j 请求、0 写库**；未改生产实现/提示/.env/锚/gold/冻结；未重跑任何线上查询；复跑 `assess_round1.py` 零网络、产出可复算。评分工具自带离线测试 6 项（`test_assessment_round1.py`，全离线通过）：真实行通过、复制后篡改（错值/错文档/挪动 grid 行号）全部拒收、掩码判 pending、混入 extra 检出——证明评分器**既非全拒也非全过**。

## 1. 评分规则（schema 摘要）

引用核验复用**已验收 answer 合同函数**（同一实现）：table 行按原始 grid 行坐标重读（非去表头重编号）、prose 按 raw unit-relative 完整跨度重读、catalog 行按真实字段来源判定——不查前缀、不以"词出现在全文"充当支持。逐类投影：file=doc_id 集合全等；prose=目标文档内 gold 声明投影（编号+名称/完整条款），越界项记 extra；table=按 gold 四种投影形态（row_cells/seq_cells/seq_name/name）逐格比对，非 complete 展开不计整题 exact；fact=gold 原行逐格相等且主体/平均时间/数值/单位同格绑定；synthesis=claims 绑定核验+gold 括注条件 token 核对后**逐题人工判定**。反例按**实际行为**独立判，expected 仅事后对照。`pass_mechanical` 含义=机械投影+引用全核验+覆盖 complete，**不豁免人工终审**；一切 pending/待审行保留在分母。

## 2. 正例 93 行判定（分母全保留）

| 类别 | pg | local | fusion |
|---|---|---|---|
| fact (7) | PASS 1 · FAIL 1 · 待审 5 | FAIL 1 · 待审 6 | PASS 1 · FAIL 1 · 待审 5 |
| file_enum (6) | PASS 5 · 待审 1 | **PASS 5 · FAIL 1（file-enum-005 漏 2 份）** | PASS 5 · 待审 1 |
| prose_enum (6) | PASS 5 · FAIL 1 | **PASS 1 · FAIL 5** | PASS 5 · FAIL 1 |
| table_enum (6) | PASS 5 · 待审 1 | **PASS 1 · FAIL 5** | PASS 5 · 待审 1 |
| synthesis (6) | 全 6 待人工（实交付判 FAIL 见 §4） | 同左 | 同左 |

要点（均为工件证据直接可判，未发布任何百分比汇总）：
- **file-enum-005 local**：gold 3 份仅交付 1 份，**漏 2 判错**（pg/fusion 交付 3 份投影全等，其中 2 份 citation 缺 doc_name 字段→pending 元数据缺口，非判分依据）。
- **prose local FAIL×5**：prose-enum-001 local 混入他文档 13 项、prose-enum-006 local 混入 12 项、prose-enum-002 local 越界 1 项（均 complete/交付却投影不符）；prose-enum-004 local 漏项；prose-enum-005 三路漏"一级/二级/三级"适用区内容。pg/fusion 五题投影全等通过。
- **table local FAIL×5 / pg·fusion 各 1 待审**：local 混入他文档行（002:+7、003:+5、005:+32、006:+100 行 foreign/extra）；table-enum-003 pg/fusion 因两行单元格被 sanitizer 数值碰撞掩码（`6000`→`<redacted>`），离线**无法证实也无法证伪**→`pending_artifact_masking`（该两行运行期复核曾为真，本轮不据掩码给分也不判错——工件缺口如实上报）。
- **fact 待审 10 行**：pg/fusion 以 prose 条款为载体（如 fact-001 交付 4.2 句+内嵌表格 HTML），gold 谓词为 table_row；claim 句子本身未显式绑定数值/单位——按"数字碰巧出现≠事实被支持"不判 pass，**也不武断判错**，整体入待审。fact-002 三路保持缺单位/未交付的既有失败形态（partial_fragment_correct×2 + 无交付）。

## 3. 反例 30 行（实际行为）

| 反例 | pg | local | fusion | 行为判定 |
|---|---|---|---|---|
| neg-003 | complete 1 份 | 同 | 同 | **ok**：仅自身编号集合，无引用文档混入（机械核验） |
| neg-004 | 13 项 ok | **44 项=set_violation（13 目标+31 他文档混入，判错，不以"都真/≥13"过关）** | 13 项 ok | 合并合同仅 pg/fusion 满足 |
| neg-005 | **complete+跨两文档 38 行=违反冻结 ambiguous，判当前行为失败**（不宣称底层表身份已串并） | ambiguous 77 行：状态合规、内容待审 | 同 pg | |
| neg-008 | ×3 budget_failure@PG 守卫 | | | 成员/字符展开路径**未获生产验证**（覆盖空白如实） |
| neg-001/006 | missing×2 + local partial(0 交付) | | | 拒绝形态记录；无 false complete |
| neg-002 | partial×3（0 交付） | | | 仅"本腿未见外来 workspace"观测，不升格 same-id 对抗 |
| neg-007/009 | partial(0 交付)/coverage 记录 | | | 保守拒绝与错误交付分列：均 0 交付，无 over-claim |
| neg-010 | pg model_failure 0 交付；fusion **交付 4 条**（引用真实但未答所问→over-answer 疑点，入人工待审）；local 未发出 | | | |

关键样例核验结论与主 agent 已确认三项一致：local 反例混入 31 项、neg-005 两路不符冻结合同、file-enum-005 local 漏 2 份；真实正例同时通过（neg-003、neg-004 pg/fusion 等），拒收非全局性。

## 4. 合成人工审查记录（18 正例 + neg-010，逐题）

- **syn-001 ×3**：三路均 `incomplete_conditions`（HTTP 未发出，0 交付）→ **整题失败（未回答）**。
- **syn-002**：pg 交付 4 条全绑定引用（4.1 执行表1/消毒排放/禁排区/脱氯 0.5 mg/L，均为真实来源语句）但**缺 6.1 取样监测与表2/预处理标准侧**→整题失败，4 条记"正确片段"；fusion HTTP 9 claims 全拒 0 交付→失败；local 未发出→失败。
- **syn-003**：fusion 交付 5 条绑定真实（4.1/4.2 标准级别选择条款）——**与 gold 要求的 6.1 采样位置（车间排放口/单位排放口）不对题**：quote 真≠答案被支持→整题失败；pg HTTP raw 0 合格 claims；local 未发出。
- **syn-004**：pg/fusion 各 HTTP 200（raw 10/8 条）全数合同拒收、0 交付→整题失败（pilot 结论在生产批次复现：媒体映射实质对不为失败补分）；local 未发出。
- **syn-005**：pg 2 条、local 7→18 问题全拒、fusion raw 0 合格——三路 0 交付→失败。
- **syn-006**：三路 `incomplete_conditions`（过渡期/批准日期条件装配未成立）→失败。
- **neg-010**：见 §3 表（fusion 交付 4 条待人工 over-answer 判）。

**合成 18 正例行：0 行整题通过；11 行发生真实 HTTP（全 200），仅 2 行留有绑定正确的部分片段。** 质量失败按主 agent 裁决计入基线。

## 5. 发现召回口径（pre-expansion only）

仅用展开前 discovery（fusion runtime `candidates` 首 20 / local usable 即 adapter 发现 / pg search 候选），枚举正确性、精排与展开**不回填**：doc 级 recall@20 均值 pg 0.959(n=31)、local 0.952、fusion 0.991；逐题缺口：file-enum-004 local=0、file-enum-005 pg=0、syn-004 local=0.5（明细在 `adjudication.json.recall`）。**typed 证据召回=pending**：chunk→unit 映射属 catalog 侧、离线工件不足，按交接保留 unknown，不杜撰。

## 6. 账本与时延口径修正（对前报告的离线修订，原文不改）

1. **reserved≠issued 的合法差额 = 10 条腿**：全部为 `answer_llm 预留1/实发0`（syn-001×3、syn-002 local、syn-003 local、syn-004 local、syn-006×3、neg-010 local——条件不足在 HTTP 前 skip）。round-1 报告"除 neg-008 外 120 腿逐服务 issued==reserved"**系误写**（该检查当时只算了 PG）；其余服务逐腿相等。15 条拒绝全部 `issued=0` 且此前已发生的调用未被回改。
2. **fusion 腿 `discovery_ms` 含精排（inclusive）**：`discovery_exclusive≈discovery_ms−rerank_ms` 仅作近似并列呈现（表在 `ledger_and_timing.timings`）；`answer_ms` 内含范围展开/生成/复核，独立阶段计时 **unavailable**；模型 `call.latency` 仅为 HTTP 时间。
3. **墙钟口径**：前报告"约 44 分钟"为**作者报告**（后台任务起止时刻差），工件不可自证；工件 mtime 跨度 977.1s，逐腿记录和 744.775s，两者差额**不做归因解释**；串行、无跨题缓存。
4. 服务失败/合同拒绝/条件不足/业务错误四类分列：本轮 HTTP 层 0 失败（答案 11/11、精排 38/38、keyword 79/79、embedding 201/201、Qdrant 201/201、Neo4j 395/395 全部送达）；"差距 100% 来自输出格式"的说法收窄为**已观察证据内**：11 行 HTTP 成功后 9 行 claims 全拒、2 行部分保留，9 行未发出属装配条件不足。

## 7 缺口与待审清单（保留分母，不发布假精确汇总）

- 掩码碰撞 2 行（table-enum-003 pg/fusion）；catalog citation 缺 doc_name 2 行（file-enum-005 pg/fusion）；fact prose 载体 10 行；neg-010/fusion over-answer 疑点；18+3 合成行中已交付片段的语义终判；39+5 机械 PASS 的人工终审抽验。合计 54 行 pending/待审 + 全部机械 pass 仍需主 agent 抽查。
- sanitizer 数值碰撞（`6000` 与配置值同串）为工件侧真实缺口：建议（仅建议，不改）后续为证据掩码加上下文约束或白名单数值域。
- 本轮**未发布**精确率/召回率百分比汇总、未勾 6.2/6.3/Gate4、未启动第二轮、未改默认路径。

工件：`assess_round1.py`（可复跑）、`test_assessment_round1.py`、`adjudication.json`（123 行逐腿判定+recall+账本修正）、`pilot-manifest.json`（本目录 SHA）、round-1 原工件未动。
