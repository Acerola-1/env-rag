# Phase 3 阶段总结（任务 5.6 材料，2026-10-07）

**状态**：5.1–5.5 工程检查点均通过主 agent 独立验收；本文件为证据整合与复跑说明，供主 agent 裁决 Gate 3。**5.6 与 Gate 3 已通过主agent最终裁决（§12）**；Phase4已交接，真实评测未执行。**本轮（5.6）0 真实模型/embedding/rerank/数据库请求、0 数据写入；主agent另作一次最小系统提示一致性调整（无服务调用）；材料审查后按主agent安排执行了唯一一次有界 syn-004 真实验证（§8，结果仍为服务侧 http_503）**；真实端到端合成成功**仍未验证**（三次真实必要请求均为失败回执，历史 503 原样保留）。

## 1. 冻结身份合同（全部阶段共用）

- 来源指纹 `95f7791fd84171ab727870fc5810d79b4327b0c4fa547d432951e0499a3808f8`；目录 run/snapshot `c15c741742394320`/`4919b3938ad93747`；search active `872d689343a9cbb6`；gold SHA `1bf130077c21583a89c5ca14695694d9552c558a7d8dc5d45ff0d9f72cfd7a5e`（`gate-2/review-r5/gold-approved.json`，31 正例 fact 7/file 6/prose 6/table 6/synthesis 6 + 10 反例）。
- 八表计数 221/5709/279/16514/65527/221/221/119575；workspace 映射唯一已核实 **PG `default` ↔ vector `_` ↔ graph `base`**，不泛化、拒绝 env 覆盖。
- `lightrag_llm_cache` 16514 行前后一致**只作漂移检查**；零答案缓存读写的证明是直接 HTTP 代码路径（无 hashing_kv/openai_complete_if_cache/LightRAG 实例化）。
- 每次正式运行由入口计算并记录输入摘要与前后身份；与已验收摘要的比对是 reviewer 侧动作，两种表述在本报告中保持分列。输入摘要记录本身不拒绝文件篡改；首次PG读取用于前置身份采集。

## 2. 各阶段最终验收事实（历史退回仅作历史，当前结论唯一）

### 5.1 发布包兼容与只读接入策略（compat_runtime.py rev 5）

- 最终代次 `phase-3-r5/`（run `compat-f17917f2f455`，scratch `lightrag_probe_0033d69b98`，cleanup dropped=true/ownership_verified=true，required_probe_contract.problems=[]）；reviewer 独立正式 CLI 复跑 run `compat-1d137f8354a2`。代码 SHA `5fa566b2…`。
- 验收 `phase-3-review-r5/review.md`（2026-10-06）：**5.1 通过**，全套 220 passed；r1–r4 历轮退回（D1–D4、E1–E3、F1–F2）为历史。冻结 `tests/test_phase3_compat_review_r3/r4/r5.py`（r5 四项断言未改）。
- 真实服务：0 LLM/embedding；真实仅自有 scratch 库 CREATE/DROP 与首次 OID 故障注入回收（F1/F2 部分实弹，终态保留库名/oid_known=false）。
- 边界保持：查询运行用 naive 模式与本地 fixture；真实 local 语义、原 Qdrant/Neo4j 运行兼容性由 5.2 另行证据；不得让初始化路径触及正式库。

### 5.2 LightRAG local 候选适配器（local_adapter.py rev 5）

- 最终代次 `phase-3-local-r5/`（提交）+ `phase-3-local-review-r5/formal-cli/`（reviewer 独立复跑），均仅 fact-002：LLM 1（keyword）、embedding 3、Qdrant 3、Neo4j session.run 5、PG 只读 3，全部 success；10/10 候选按 (workspace, chunk_id) 回读 verified；向量覆盖 entities 29/29、relations 3/3。代码 SHA `0bbad976…`（5.3/5.4/5.5 全程保持未变）。
- 验收 r5（2026-10-07）通过，全套 255 passed；r1–r4 退回历史。冻结 `tests/test_local_adapter_review.py`（10）、`_r2`（8）、`_r3`（6）、`_r4`（3）。
- 边界保持：raw `points_returned_raw` 仅传输统计；缺向量 → weight-fallback+degraded，PG verified 不抵消；**目标文档命中 9/10 与来源 verified 10/10 是两项不同观测**；keyword 抽取非确定性（r5 与 r4 词集不同，计数不可比）已记录。

### 5.3 候选融合（fusion.py rev 4）

- 最终验收 rev4/r4（2026-10-07）：全套 279 passed；F1/F2/F3(-a/-b)/F4 全 resolved。代码 SHA `be1cd4c5…`。冻结 `tests/test_fusion.py`（11）+`_review_r1`（8）/`_r2`（2）/`_r3`（3）。
- 真实证据代次：rev1 `phase-3-fusion/`（fact-002/syn-001/neg-001 两路合并；LLM 2、embedding 5、Qdrant 5、Neo4j 10；neg-001 local 跳过、0 调用）+ reviewer 19/19 全文独立回读；F1/F2 修复证据 `phase-3-fusion-r2/`（PG-only fact-002）与 `phase-3-fusion-r2-f1/`（PG-only neg-010，6 usable/0 拒绝）+ reviewer formal-cli；r3/r4 轮 0 实弹复用上述。
- 语义保持：usable 上限 40/查询（超出 partial）；两路分数**并存不求和**；同内容不同版本不合并；缺目标版本记 missing、邻居不替代；`--pg-only` 输入显式空集不回补。

### 5.4 联合精排（rerank.py rev 4）

- 最终验收 r4（2026-10-07）：全套 319 passed；R1–R4/C1–C3/D1–D2 全 resolved。代码 SHA `e2a8e089…`。冻结 `tests/test_rerank.py`（18）+`_review_r1`（14）/`_r2`（6）/`_r3`（2）。
- 真实精排账本（fact-002，10 合并输入、16441 字符）：首次 **404**（133ms，URL 重复拼接，degraded 无伪分数，保留历史）→ **200/863ms** 成功 → 最终已验收证据 **200/997ms**（`phase-3-rerank-r2/rerank-runtime-latest.json`，sha `4ad5a56f…`）；服务 SiliconFlow 风格 `/v1/rerank`，模型 `Qwen/Qwen3-Reranker-4B`（key 永不落盘）。r3/r4 轮 0 新调用；10个ordered候选的附加路径映射（12 table + 29 block 类型证据）标注非实弹。
- 语义保持：候选按响应 index 映射回身份（同正文两版本不并）；回放身份不符与声明快照冲突在**服务前**拒绝；>40 输入显式拒绝；认证缺失不发 "Bearer None"；401/超时/非2xx/异常分数 → degraded 保原序；`enrichment_basis` 记录为关联补全非检索命中；**修正历史：首轮"41 条表片"实为 12 table + 29 block**。

### 5.5 完整范围展开与按题型回答（answer.py rev 4，工程检查点通过）

- 最终验收 `phase-3-answer-review-r5/review.md`（2026-10-07）：383 passed / 回答专属 64；C1–C3/D1–D2/A1–A3 四轮冻结（r1 9/r2 7/r3 6/r4 4）未改。代码 SHA `29e0aa29b2b49be4…`（rev-4；`phase-3-answer/answer-manifest.json` 25/25 SHA 全核验；`7f7b43b5…` 为其 rev-3 前代）。
- 编排合同：回放已验收 5.3/5.4 代次（输入文件SHA由入口记录、代次identity由守卫绑定；前置身份采集后、范围读取与模型请求前拒绝不符代次）；范围由 targets_resolved/typed 定义、精排顺序**仅优先级**、成员**永不被 top-k 截断**（解析目标缺席候选集补注册；噪声文档展开记录但不降级所选范围）；全部引用独立回读（表行 raw grid、正文 raw unit-relative 跨度）；fact/file/prose/table 确定性渲染 0 答案模型；synthesis 需显式 `--allow-model`，预算每运行 1 次，refuse-not-truncate。
- 声明证明合同：数值=完整带符号 token；单位后缀与行单位候选集等值绑定；平均时间逐字绑行；级别列数值核对；正文 claim 仅接受**来源连续逐字片段**（应用侧只可附加版本年份前缀与结尾标点）——词集/数字集合不再是放行证明；表格行按绑定行结构、正文按声明自身断言范围填**版本×主体×量/平均时间×等级**槽（已读≠已答）。无法证明的改写明确 model_failure/partial，不承诺开放语义推理，不新增第二次 LLM。
- 失败出口（A3）：连接取得与后置守卫在统一 try/finally 边界；失败仍写终态报告并抛出（CLI 非零）；原错误与后置错误并存，results 仅诊断。
- 真实代次（本轮均不重复执行）：Run A `phase-3-answer/`（fact-002 初判，历史）→ `phase-3-answer-r2/`（当前：单位缺失 partial）；Run B `phase-3-answer-fusion/`+`phase-3-answer-enums/`（table/prose 13/13、4/4 complete）；Run C `phase-3-answer-syn-check/`（syn-001 条件不可完整定位，含正式 `search-query --expand` 控制对照，公开 incomplete、0 调用）；Run D `phase-3-answer-syn4-check/`（syn-004 两范围 5+3 项、8/8 回读 problems[]、0 调用）+ `phase-3-answer-syn/`、`phase-3-answer-syn2/`（唯一必要请求两次 **http_503**，各 64ms，`http://127.0.0.1:8787/v1/chat/completions`，无凭据回执；/models 401 仅证端口应答，上游根因未独立确认）。

## 3. 证据类型标注（回放 / 真实读取 / fixture / 真实成功 / 真实失败）

| 项 | 类型 | 出处 |
| --- | --- | --- |
| 5.2/5.3/5.4 服务成功、5.5 确定性读取 | 真实只读读取；仅对应5.2/5.3/5.4代次包含真实服务成功，5.5枚举读取不含答案模型成功 | phase-3-local-r5、phase-3-fusion-r2(-f1)、phase-3-rerank-r2、phase-3-answer(-enums/-syn-check/-syn4-check) |
| 精排 404 与三个答案 503 | 真实服务**失败**回执 | phase-3-rerank/rerank-runtime-20261007T085918.json、phase-3-answer-syn/syn2、phase-3-answer-syn3 |
| 5.5 回放链路 | 已验收代次的 REPLAY（输入 SHA+identity 绑定），非新检索轮 | 各 answer-runtime `replay_sources` |
| 全部验收矩阵/反例 | fixture（假传输、隔离来源），不代表真实网络响应 | tests/test_answer*.py 等 |
| 真实端到端合成成功 | **未验证**——fixture 通过不冒充 | 本节即声明 |

## 4. Gate 3 条件核对（详见 `gate3-checklist.json`，逐条含证据）

1. 身份/版本一致 — **passed**（§1 合同 + 每代次前后采集与回放绑定；19/19 全文独立回读）。
2. 联合精排真实发生 — **passed**（fact-002 一次已验收真实 200/997ms 合并集合精排 + 404/863ms 历史；其它题显式 absent，不伪造）。
3. 确认范围完整、不被 top-k 截断 — **passed**（真实13/13两物理片与3.1–3.4读取、独立回读；低排名续片0.02是fixture反例（真实两片共享chunk-001，实际精排第1位0.999273）；合成上下文8项离线位置复核）。
4. 降级与失败可见 — **passed**（stale/missing/degraded/ambiguous/partial/model_failure 全部显式落盘；A3 失败终态非零退出被冻结断言覆盖）。
5. 正式链路可复跑 — **passed（文档级）**：README《Phase 3 运行说明》命令经 parser 核对；本组未发起新真实执行。
6. 真实端到端合成成功 — **unverified**（三次真实必要请求均 503，见 §8；准备材料见 `syn-prep-syn004.json`；服务不可用不循环重试）。

## 5. 保留的能力边界（不得写成已具备）

- fact-002 当前答案 partial（原始网格无单位列、caption 无单位声明；数字为已验证证据，不从 gold/常识补单位；旧 complete 结论作废仅作历史）。
- syn-001 的 2012 条件范围未完整定位，公开 incomplete（正式控制对照同判）。
- prose/table 既有公开歧义（原表2双逻辑表 ambiguous）与 requires_span 未定位语义保持，成功生成不升级 complete。
- 两次历史 503 与 5.6 验证轮的第三次 503 都是失败记录，不是成功合成；**真实成功合成未验证**。
- 正文声明采用保守合同（连续逐字/有限装饰），无法证明的改写明确拒绝；这不承诺开放自然语言语义推理。
- 精排只给优先级；融合质量与 31 题指标不在本阶段宣称；Phase 4 冷生成对照未开始。
- 5.6 初始文档与命令核对为**离线**完成；随后仅执行 §8 的一次有界答案请求，未重新运行完整检索与精排链路。

## 6. 交付物索引

- 本报告；`gate3-checklist.json`（结构化清单）；`syn-prep-syn004.json`（一次必要真实合成请求的无凭据审查材料，**本组不执行**）；`phase-3-manifest.json`（证据 SHA 台账）。
- README.md 新增《Phase 3 运行说明（5.6 交付）》：各命令真实调用属性、回退与失败语义。
- 各阶段原始证据（只读引用，未改动）：`phase-3-r5/`、`phase-3-local-r5/`、`phase-3-fusion*/`、`phase-3-rerank*/`、`phase-3-answer*/` 及四轮 answer 冻结、历轮 review/manifest。

## 7. 主agent离线补正与裁决（2026-10-07）

材料审查时真实请求尚未执行；随后的一次有界执行及本次裁决见 §8、§9。

- 0.02低排名续片是fixture；真实GB8978表1两片共享chunk-001，已验收精排该chunk第1位0.999273。真实13/13证明完整物理片读取，不能据此声称真实跨chunk低排名续片已经实测。
- answer运行级连接/身份守卫/未捕获异常写终态后抛出，CLI非零；已记录的model_failure/partial/ambiguous作为业务结果正常返回、CLI可为0。模型HTTP失败不能用shell退出码判断成功，必须看coverage/model.status/call.status。前一份交接措辞在此更正。
- 采用原建议的一句系统提示，要求正文claim连续逐字、表格按行列归属；算法/引用/集合验证未变。原实现验收383项保留；提示调整后重新跑回答专属64项（fixture，非真实模型服从性证明）。当前answer.py SHA=2a53f2d7b959b34434a0a78d4345c205693b01b56378e94f70c62608d6bea8e6。旧answer-manifest与历史runtime原样保留，当前阶段台账记录新提示版本。
- syn004完整拟送messages及上下文已落盘；8条定位由原始blocks离线重建、逐段raw坐标复核，上下文SHA及1934字user-content与历史503逐字一致。没有重新采集生产身份或查询per-unit chunk映射，真实执行仍必须走正式guard。
- 已有GB3095 7.3上下文含附录A材料，按原始块保留，并在引用明细标注。成员读全不等于范围已经纯净；不得把附录语句归成第7章要求。不得手工删改上下文制造成功。
- 该定性题的应用槽仅检查两版本，成功后还须人工核对每条声明确实回答环境要素并有原文支持；HTTP200或coverage complete本身不代表问题语义正确。

## 8. 有界真实验证执行（2026-10-07，主agent安排的唯一一次）

按 `syn-prep-syn004.json` 的入口合同执行一次正式 `answer --query-id syn-004 --fused-report reports/pg-retrieval/phase-3-answer-fusion-syn/fusion-runtime-latest.json --allow-model`，新代次 `phase-3-answer-syn3/`。结果：**第三次 http_503**（73ms，同端点，无凭据回执）；失败回执如实保留、不重试、不删历史 503。

- 前置全部通过：身份前后冻结（指纹 `95f7791f…`、run/snapshot `c15c7417…/4919b393…`，无 drift、无运行级 failure）；回放输入 SHA 与准备材料一致（fusion `824c7085…`、rerank `4ad5a56f…`，syn-004 rerank-absent 显式记录）；8/8 独立回读 problems[]。
- 实际请求与准备材料逐字一致：user content 1934 字符、context SHA `b0487919fa1d1def…` 与两次历史 503 相同；system prompt SHA `626fda41…` 即主agent对齐后的提示。`model_calls_used=1`，`model.status=model_failure`，coverage=partial（业务结果，CLI 退出 0——符合 §7 退出码语义）。
- 真实端到端合成**仍未验证**：三次真实必要请求均收到配置模型端点的 HTTP 503。前置守卫、范围与引用回读及失败处理已核验；具体代理或上游根因未独立确认，真实输出与成功后的验证路径尚未实测。本次额度已用，不自动重试或健康探测。

## 9. 主 agent 真实验证裁决（2026-10-07）

本次有界执行与失败回执验收通过；5.1–5.5工程结论保持。真实合成成功及人工回答核对仍缺失，5.6/Gate3不勾选，Phase4不进入。本次一次请求额度已用，不自动第四次重试；当前无新增应用代码返工项。

独立离线核对提交台账54/54、两份终态同字节、实际messages与准备材料逐字一致、1934字user-content、context/system SHA、前后身份一致且冻结匹配、8/8回读无问题、显式rerank-absent、一条503/73ms且无生成项目。CLI退出0属于已记录的业务失败，不代表合成成功。此次reviewer未调用数据库或模型，未重复已通过的代码测试。详见 `../phase-3-real-validation-review/review.md`。

## 10. 换模型验证（2026-10-07，主agent指示）

503 根因指向原上游模型通道：主agent将 `.env` 的 `QUERY_LLM_MODEL` 由 `deepseek-v4.1-flash` 改为 **`hy3`**（仅此一行；`LLM_MODEL`/`KEYWORD_LLM_MODEL` 未动；回放 env_sha 差异按合同记录为 warning、不作拒绝）。同命令重跑一次，新代次 `phase-3-answer-syn4-hy3/`：

- **首次真实 HTTP 200**（22.1s，`model_calls_used=1`，回执与 raw_response 已落盘）：模型按提示输出合法 JSON——summary 加 2 条 items，edition 标签合法、quote 逐字（GB3838-2002 引五类水域功能句；GB3095-2012 引「以下为环境空气中部分污染物参考浓度限值。」）。
- 两条 claim 均为对原文的**改写**（如「对地表水规定质量标准」非原文连续片段），按已验收 C1 合同被拒绝 → `model.status=model_failure`、coverage=partial、`answer_items=0`。拒绝是合同的正确行为，不伪造通过；HTTP200 不等于成功合成（§7 语义）。
- 前置不变：身份冻结无 drift、8/8 回读 problems[]、syn-004 rerank-absent 显式、user content 1934 字符。本轮未重试、未再调用。
- 状态：真实模型交换已实测成功；**真实"通过全部验证的合成"仍未验证**——下一步（接受该拒绝为结果，或由主agent另行安排提示/模型调整后再验证）由主agent裁决。

## 11. 多样本诊断（2026-10-07，主agent指示：排除偶然）

同一输入（同回放、同提示、temperature=0）用 hy3 连续 3 次有界验证，各 1 次请求、回执全留：`phase-3-answer-syn5/`、`-syn6/`、`-syn7/`。

| 运行 | 结果 | 模型行为 |
| --- | --- | --- |
| syn5（41.4s） | partial / model_failure | 结论句为转述（"对地表水（水域）规定质量标准"），按 C1 拒绝 |
| **syn6（45.2s）** | **complete / ok** | **结论句=原文逐字句**（GB3838 五类水域功能句；GB3095 附录A引言句），0 验证问题、2 条引用核实、coverage=complete |
| syn7（28.9s） | partial / model_failure | 结论句为转述（"对地表水环境要素规定质量标准"），按 C1 拒绝 |

结论：hy3 的转述行为**非偶然也非必然**（3 次中 1 次按合同要求逐字作答）——temperature=0 下上游仍有非确定性。**syn6 是首个真实成功端到端合成代次**：真实 HTTP 200、应用侧全部合同（范围/引用/逐字声明/槽覆盖/预算）真实通过、coverage=complete、身份冻结无 drift。剩余未决：按既有裁决，主agent须人工核对回答是否真正回答"分别对哪些环境要素规定质量标准"的问题语义——特别注意 GB3095 的支撑句来自**附录A（资料性附录）引言**，此前已标注"附录语句不得归为第7章要求"；回答的字面（"对环境空气规定质量标准"）与附录A引言的支撑关系是否可接受由主agent裁决。4 次 hy3 运行共 4 次真实请求，无重试、无挑选，全部回执公开。

## 12. 主agent最终裁决（2026-10-07，取代§9的等待状态）

5.6完成，Gate3放行。5.1–5.5工程结论保持；syn6真实成功与环境要素识别语义通过。Phase4交接就绪，本轮未执行Phase4或新请求。

syn6两条claim对本题的环境要素识别通过：GB3838为地表水，GB3095为环境空气。GB3095引句来自附录A资料性引言，只接受其介质识别，不能据此断言第7章要求或强制限值。独立回读两条claim的原始声明跨度及冻结gold适用范围，未改历史运行或金标。四次HY3为1 complete/3 partial，三次诊断为1/3；拒绝正确但质量/稳定性未证明，留Phase4固定样本。62/62提交台账匹配，reviewer新增DB/模型请求0，既有代码测试结论沿用。详见 `../phase-3-gate3-review/review.md` 及 Phase4交接。§8–§11保留当时执行与等待状态。
