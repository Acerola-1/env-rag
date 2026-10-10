# Phase 4 评测实现与运行计划（6.1–6.3 离线准备，2026-10-07）

**第一轮最新裁决（2026-10-08，以此为准）**：123腿执行交付通过，但出现反例错误complete/正例漏项，质量未过。暂不启动第二轮；先按handoff-phase-4-offline-assessment-round-1.md对现有工件做0网络/模型/数据库的独立评分与时延口径核验。固定提示/模型/源码/gold不变，PG1024护栏保留；6.2/6.3/Gate4仍未完成，默认路径不变。下文旧检查点保留历史。

**pilot-r2最新裁决（2026-10-08，以此为准）**：PG标定与九腿工程执行通过，但syn-004实际交付0、local术语题多13项，质量失败计入基线。暂不改提示/合同/模型，PG累计信封保持1024；第一轮41题×3路123腿交接与预算已准备，用户下发后执行并停复审，不自动第二轮。分母正例93/反例30分列，答案模型≤21，keyword≤82，PG总cap125952；见handoff-phase-4-6.2-round-1.md。6.2仍未完成，不宣称质量通过或融合增益。下文旧检查点保留历史。

**最新检查点（2026-10-08）**：pilot-r1的9腿全部在PG累计信封24处停止，已到达的local服务成功、保护有效，但精排/答案尚未验证。此24额度由主agent设低，下一步按handoff-phase-4-6.2-pilot-r2.md进行0模型PG-only标定（3腿，PG1024/腿），达门槛后同范围9腿一次复跑（仅提高PG，其它付费服务cap不变）。现行代码每腿一个累计信封，“two envelopes”历史文案仅属保守编译口径，不意味着发现/答案各获一次额度。6.2仍未完成，不扩为246腿。下文首次试跑前状态保留历史。

**当前状态（2026-10-08）**：6.1已验收通过（454项，四版冻结与自有矩阵71项）；用户明确确认DeepSeek恢复可用并允许恢复原模型。答案/关键词均为deepseek-v4.1-flash，新配置锚代次phase4-deepseek-restored-pilot-r1已通过零后端校验；源码/来源/gold/提示不变。按 `handoff-phase-4-6.2-pilot.md` 直接执行单轮3题×3路9腿，keyword≤6、answer≤3、rerank≤3、embedding≤24批；执行后停主agent复审，不自动扩批。6.2完整两轮评测未完成。**下文2026-10-07初稿及“DeepSeek额度阻塞/HY3/待授权”表述均为历史，以本状态和当前交接为准。**

**主agent审查状态（2026-10-07）**：允许6.1先做离线实现；下文初稿的三路径与预算表尚不能作为网络许可，必须按 `openspec/changes/add-pg-scoped-retrieval/handoff-phase-4-6.1.md` 统一可比答案/反例矩阵/调用前硬预算。原186仅正例，默认全41题为246；原≤14答案预算不覆盖三路同合同生成。关键词配置未更换。

按 `handoff-phase-4.md`：本文件只给**评测实现/运行计划、逐路径输入合同与调用上限**，不发起任何真实请求；实施与有网络评测需主 agent 另行授权。配置锚见 `phase-4-config-anchor.json`（冻结身份、模型配置、预算、可用性状态）。

## 1. 评测入口实现计划（对应 6.1，为新增代码，不改已验收组件）

- 新增 `src/env_rag_final/evaluation.py` + CLI 命令 `eval-run`（argparse 追加，现有 17 命令不动）：
  - 输入：`--round N`、`--paths local,pg,fusion`、`--query-ids`（默认冻结 31 正例 + 10 反例全量，不删题不缩分母）、`--report-dir reports/pg-retrieval/phase-4/round-N/<path>/`。
  - 行为：逐题逐路径调用**现有已验收入口**（`lightrag-local` 合同 / `search-query`+expand / `fuse-candidates`→`rerank-candidates`→`answer` 回放**本轮评测自己产出的**融合与精排代次——绝不回放 Gate3 旧代次冒充冷生成）。
  - 每题每路径落盘：实际候选（含分数与来源路径）、精排 ordered 与 degraded 记录、展开 coverage 与 items_count、每次生成的完整 context/messages、生成结果与 coverage、分阶段耗时与端到端耗时、逐请求服务调用账本（复用各入口既有 receipts）。
  - 冷生成证明：answer 层本为纯 HTTP 代码路径（无 LightRAG/ClientManager/hashing_kv 实例化）——零答案缓存读写由代码路径本身证明；评测入口不读取任何旧 runtime 的答案字段作为输入；`lightrag_llm_cache` 行数前后一致仅作漂移检查。
- 测试：新增 fixture 矩阵（假传输/隔离来源，沿 answer 测试基建），覆盖三路径编排、缓存禁用断言、分母保全（失败题保留）、反例期望行为匹配；冻结文件不动。

## 2. 逐路径输入合同

- **local**：`lightrag-local` 合同逐题执行——KEYWORD_LLM 抽取 → embedding（≤3 批/题，2560d）→ Qdrant/Neo4j 只读检索 → PG 按 (workspace, chunk_id) 只读回读正文。候选=发布包实际返回，不注入、不裁剪。
- **PG**：`search-query --top-k 20` + 按题型 expand/enum；**0 模型 0 embedding**；候选与覆盖即最终产物。
- **fusion**：`fuse-candidates`（PG 发现 + local 证据，usable ≤40/查询，分数并存不求和）→ `rerank-candidates`（≤40 输入，degraded 如实标注）→ `answer`（逐题型：fact/file/prose/table 确定性 0 答案模型；synthesis 需 `--allow-model`，≤1 次/题）。rerank 顺序仅优先级，展开不被 top-k 截断。
- **反例 10 题**：期望 missing/partial 者不触发 local（0 调用，沿用 neg-001 实测语义）；期望 ok 者（neg-010）按所属题型走全合同。
- 引用标注：正文来源与**资料性附录 A** 分列（Gate 3 裁决要求；附录 A 参考浓度不得宣称为第 7 章强制要求）。

## 3. 初稿调用估算（审查未通过，不构成硬上限或授权）（两轮 × 31 正例 = 62 题轮；186 = 62×3 题路径执行）

| 服务 | 上限推导 | 上限 |
| --- | --- | --- |
| keyword LLM（KEYWORD_LLM_MODEL） | local 62 + fusion 的 local 腿 62，各 1 次 | **≤ 124** |
| embedding（Qwen3-Embedding-4B，2560d） | 每次本地腿 ≤3 批（fact-002 实测口径），文本 ≤32/题 | **≤ 372 批 / ≤ ~4 000 文本**（逐请求实测记录） |
| Qdrant 查询 | 同 embedding 腿数 | ≤ 372 |
| Neo4j session.run 组 | ≤5 组/本地腿 | ≤ 620 |
| 联合精排（Qwen3-Reranker-4B） | fusion 62 题轮 × 1 次（≤40 输入/次） | **≤ 62** |
| 答案模型（hy3） | synthesis 6 题 × 2 轮 = 12；反例中期望 ok 者（neg-010）按题型另计 ≤2 | **≤ 14** |
| PG 只读查询 | 每题路径数条（逐请求记录），只读不设硬上限 | — |

费用＝次数 × 服务方单价；单价以服务方账单为准，本计划不填写未经测量的价格。以上为**上限**：反例期望 missing/stale 者大量为 0 调用，实际逐请求账本随运行落盘。**当前阻塞**：keyword LLM 通道（deepseek-v4.1-flash @ 127.0.0.1:8787）已实测 503 且用户告知额度耗尽——local 与 fusion 的真实运行在其恢复或用户明确授权换模型前**不可执行**（禁止静默换模型）；PG 路径与（配置在位的）embedding/rerank 不受此阻塞。

## 4. 指标与报告（对应 6.2/6.3，沿用 design §7 门槛）

- 分母保全：31 正例 + 10 反例全部计入；失败/拒答/partial/degraded/服务失败如实记录，不删题。
- 指标：文档/编号/版本定位 100%；范围覆盖 100%（反例无 false complete）；PG recall@20 ≥ 0.90（漏召回逐条列出）；三类 enum 集合完全正确率各 ≥5/6；引用错误与跨 workspace/版本混入 = 0；融合增益（两轮 enum 完全正确率 ≥ local、至少一类可复现修复案例、fact/synthesis 不下降）；引用来源分列正文/附录 A；complete 不等于语义正确，最终语义由主agent抽查核对。
- 延迟：检索/精排/展开/生成分阶段与端到端 p50/p95、样本量、缓存条件；不填未经测量的收益。
- Gate 4（6.4）：两轮对照后由主agent按上表验收；未达标保留基线与失败报告，不启用未达标默认融合。

## 5. 停止条件与待授权清单

- 停止/降级：预算耗尽、来源/身份漂移、服务异常按合同停止或显式降级，不循环重试凑成功；syn-001 条件短缺、fact-002 缺单位、prose/table 公开歧义原样保留并计入分母。
- 实施前需主agent授权：①6.1 评测入口代码实现（新增代码走测试与审查）；②按 §3 上限授权有网络评测的调用额度与轮次安排；③keyword 模型处置——恢复 deepseek 额度，或明确授权把 KEYWORD_LLM_MODEL 换为可用模型（如 hy3；换模型即配置变更，照旧逐字记录）。三项齐备后才进入真实评测；本文件不构成调用许可。

## 6. eval-run 运行说明与代码代次（rev-2，2026-10-08，全部离线）

- **CLI `eval-run`**：
  - `--dry-run`：零后端接触、**不需要**配置锚；矩阵与上限工件由 owning 入口重生成（246 executions / backend_fetches=0）。
  - 真实模式（网络评测仍未授权）：分发入口前必须先通过 `validate_phase4_anchor`（rev-3）——**完整性 schema 先行**：frozen_identity/model_config（answer·keyword·embedding·rerank 四子节含类型要求）/code_anchors 必填项/frozen_budgets 必填项，**空节或缺节是违规、不是可选跳过**；再**比较全部必填值**（含 gold 内容哈希与路径、端点类别、维度、提示 SHA、代码锚字节、参数常量、env 守卫；rev-4：`answer_temperature` 声明值与 answer.py 生成 payload 的 temperature 字面量**逐值比较**——代码 SHA 固定实际值不能代替"声明=实际"校验，锚声明非 0 即拒），其中**关键词身份按生产实际解析核对**（`KEYWORD_LLM_MODEL` 优先、缺失时 `LLM_MODEL` fallback——local/fusion 抽词模型不同则两轮评测不可比）；锚缺失/损坏或任一不符即**零服务/零后端**非零退出；`expected` 来自锚、不可现场覆盖。
- **预算口径（rev-2）**：预留≠实发。`reserved_total` 为请求前闸门（含保守占用），`issued_total` 只认真实 I/O 凭证——已执行失败的调用不归零、缺条件跳过 HTTP 的模型调用计 0；**answer 阶段同在预算作用域内**，CLI 形态不传 conn 时经 `asyncpg.connect` 缝包装自建连接（answer 自有连接/SourceAdapter 回读/fusion/rerank 守卫 SQL/`local_adapter` 证据 SQL 全部计入；local_adapter 组调用+语句双计数为刻意保守多计，不作废原包装记录）。运行报告含 `budget_coverage_declaration`：哪些缝计量、哪些不计量（建连/关闭、事务控制/SET LOCAL、run 级 identity 采集、未被已验收包装记录的直通方法）、以及"工件中的计数不冒充全 PG 覆盖"。rev-3 追加精排凭证口径：**进入 `run_rerank` 入口不是实发**——reserve 保持请求前闸门，`mark_issued` 仅由本题真实 call 凭证触发；rev-4 收紧：结果项 call 为 dict＝已进入 HTTP（含执行后 401/timeout，计 1）；call=None 计 0；抛错路径只认**本题 qid** 的 runtime 结果项或在途 `failure_service_records`（其 `query_id` 必须是本题——其它题的 call 永不计入本题），仅命名守卫阶段（与 rerank 入口终态逐字一致：pre-flight/pre-flight-parse/pre-flight-read/identity-capture/identity-before/unknown-query-id）的无 call 终态才是明确 HTTP 前拒绝计 0，**存在某个 failure 本身不构成本题零调用证明**；runtime 不可读或非守卫失败=显式 `unknown-no-receipt`（不猜已执行、不伪称确定 0）。三态 `rerank_issuance`（executed/before-http-zero/unknown-no-receipt）**在异常路径也经账本注解发布到 leg 记录与终态**，原始错误原样传播；两路不双计。
- **拒绝不被吞**：discovery 与 answer 两阶段各自核对本题账本拒绝事件增量；release 库捕获预算异常回落（VECTOR→WEIGHT）时该题显式 budget_failure/partial 并停止追加配额。
- **证据分类按实际资源**：正式运行的 neg-008 标 `production_readonly_with_constructed_budget`（构造微预算经 `expand_budgets→prose_budget→read_prose_scope` 到达真实 reader，来源访问仍是生产只读入口）；仅注入假源/假 runner 的 leg 标 `isolated_fixture`（由实际注入判定，不由题目标签制造）。neg-002 隔离输出如实为"本腿观测"，未观测到外来 workspace 不升格为同 ID 跨 workspace 对抗验证（构造性拒绝见 `tests/test_evaluation.py::test_local_rejects_foreign_workspace_and_unverified`，来源为 fixture）。
- **local 出处保真**：候选的 `reached_via`（全部来源路径）、`similarity_order`、`source_type` 与 `sorting_sources`（weight-fallback/truncation-fallback 等实际选择口径）原样落 input 工件与 receipts；score 保持 None，不把 weight-fallback 冒充向量排序、不从摘要伪造证据。
- **代码锚代次说明（R3）**：`phase-4-config-anchor.json` 的 code_anchors 保持 Gate-3 时代字节，本轮**未编辑**。已验收兼容缝造成的 answer.py 字节差异，锚校验时**如实上报为漂移**（旧锚下 CLI 真实模式拒绝执行是安全默认，与网络评测未授权一致）；6.1 获批后由主 agent **显式建立新的 Phase 4 代码锚代次**，不通过修改旧台账偷偷消除差异。本轮自有测试逐项核验：rerank/fusion/local_adapter/compat_runtime 与提示 SHA 与锚一致，仅 answer.py 因授权缝漂移并被报告。
