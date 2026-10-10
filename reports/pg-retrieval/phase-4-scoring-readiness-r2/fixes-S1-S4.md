# S1–S4 补正对照（phase-4-scoring-readiness-r2）

输入为上一代只读基线；生产源码/gold/.env/真实锚/历史/35 冻结未动；本组 0 网络/DB/模型请求。
独立评审 17 项先复现红相（15 失败/2 正例），修复后 `ENV_RAG_SCORING_READINESS_SCRIPT`
指向本副本 **17/17**；矩阵字节未改、无删断言/xfail。

## S1 完整新代输入合同（红→绿：清单/身份/绑定 6 项）

- 消费登记器：terminal、每题 answer/fusion/local 输入与发现回执等**实际读取**的每个文件都
  登记并必须绑定在运行清单且 SHA 相等——仅遍历清单条目不够；缺失即净化拒绝、无裁决。
- 身份字段：pre/post 逐字段核 source/catalog run+snapshot/search/gold/**env_sha/counts**；
  counts 比批准锚 `eight_table_counts`；env 至少前后相等，且锚含 env 锚时必须一致；
  结构必填、matches_frozen 自报 true 不替代实值；无旧代字段豁免。
- 分母：terminal 必须覆盖固定 gold 的 31×3+10×3 **唯一键**，题号/路径/category/is_counter
  逐个匹配；重复键/缺键即拒（"只计 93+30"不再可行）。
- 谱系：`code_anchors` 六键（含 synthesis_system_prompt_sha256）与 `evaluation_code_anchors`
  必需键先查结构完整再逐项比磁盘 SHA；删键=拒绝，不能"省略比较"；批准锚在校验中绝不
  由当前代码回写。
- 题绑：消费的 answer/fusion/local 工件的 `query_id`/`workspace` 与该 key 绑定核对，
  拿别题首条 results 当当前答案被直接拒绝（真实 owning 目录形状兼容）。
- 兼容模式：以上仅在生成模式生效，旧代输入口径原样。

## S2 人工只能解决语义缺口（红→绿：PASS 滥用/错轮 3 项）

- 硬失败归纳**先于人工层**：budget/runtime 失败、coverage≠complete、0 交付
  （"raw 对而应用未交付"）、missing/extra/foreign 集合违规、非纯掩码的引用失败
  ——合成题即使 judgement 固定 pending 也过不了这些字段；partial 的真实片段保留为
  诊断，PASS 不升级整题；引用伪造同样硬 FAIL（`manual_pass_refused` 公开冲突）。
- 记录同一绑定入口：schema/键合法/重复冲突/类型/审查者/理由/已核项校验；
  **错轮提交直接拒绝+诊断**（不再静默"不匹配"——上一代自有断言按交接明示允许且已
  强化为拒绝）；缺记录=PENDING；未知 judgement 不允许任意 PASS；合成 PASS 须具名
  整题语义审查项。PASS 只解除记录明确审核的缺口；正文/附录分列、gold 不改。
- 成对证明不全拒：完整覆盖+独立引用通过的合成行，具名语义记录可 PASS
  （`test_complete_synthesis_recorded_semantic_pass_applies`）。

## S3 typed 证据召回按组合身份（红→绿：doc≠unit 3 项）

- 保持发现段原始身份（workspace,doc_id,chunk_id + typed 目标），不再先降成 doc 列表。
- 映射按完整 **(workspace, doc_id, snapshot, unit_id)** 组合索引；同 unit_id 跨文档
  不覆盖、不互计；unit 命中=发现的 chunk 真在该 unit 的 chunk_ids 内，或 typed 目标
  自带该 unit（/scope 经映射成员关系）身份；纯 typed-doc 只算文档发现。
- 期望单位集合固定自 gold target_evidence；未映射单位留在分母：存在未解析→发布指标
  **null(pending)**，已知 covered/missed 分列展示但绝不缩分母给满分；
  零发现保持 0；枚举/精排/展开不反灌；跨 workspace/snapshot 条目加载即拒、空表拒绝。
- 映射采集仍只设计未执行；行数来源=已存活跃 build-manifest（unit_chunk_links=16783、
  source_units=12269、scope_units=14557、scopes=1970）；`requires_span` 字段位置按
  phase-1 源定义核对后才写；完整采集时同一只读快照、排序组合键、完整性/终态与内容
  清单守卫留作正式提案条款。本组 fixture 只证明接口。

## S4 唯一拒绝出口覆盖全部消费（红→绿：诊断缺失 3 项）

- 记录/映射装载、输入核验、answer/fusion 解析、记录绑定、评分、recall、账本与结果
  构造全部纳入生成模式**同一 owning 失败边界**；`InputIntegrityError` 自身也先落
  净化诊断再非零抛出（旧代码 except 专门放行不写诊断的路径已闭合）。
- 裁决文件仅全程成功时**原子发布**（写 partial→rename）；输出位已存在直接拒绝，
  不覆盖任何既有裁决/诊断；同目录多轮诊断使用不重名序号，绝不盖别题历史诊断。
- 兼容模式边界保持原状（冻结矩阵依赖其行为）。

## 验收命令与结果（原始输出在同目录）

| 套件 | 结果 |
|---|---|
| 独立评审 17 项（ENV→r2） | **17 passed**（`pytest-reviewer17-r2.txt`） |
| 自有矩阵 21 项（19 强化+2 新增） | **21 passed**（`pytest-own-matrix-r2.txt`） |
| 35 项历史冻结（字节未动，ENV→r2 兼容） | **35 passed**（`pytest-frozen35-compat-r2.txt`） |
| r3 自测（备案细标签） | 12/13，判罚不变（`pytest-r3-selftest-compat-r2.txt`） |
| strict / diff / ruff check+format | 全 0（`quality-commands.txt`） |

来源分类：全部为合成 fixture + 已存真实工件副本；新实际请求 0、写库 0。
本组不建正式锚、不问额度、不跑 123/246 腿、不改默认融合；6.2–6.5/Gate4 未勾。
