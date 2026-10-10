# R1–R4 衔接补正对照（phase-4-scoring-readiness-r3）

输入=上一代只读基线；生产/gold/.env/真实锚/所有旧目录/17 与 35 冻结字节不动。
0 网络/DB/模型/探测。红相先复现：`phase-4-scoring-readiness-review-r2/test_scoring_review_r2.py`
对 r2 副本 **8 失败/2 正例**；修复后同一 ENV 指向本副本 **10/10**（矩阵未改、无删断言/xfail）。

## R1 硬失败先于"任何"人工状态
生成模式下 synthesis 行在**所有 manual 分支与无记录分支之前**归纳已证实硬失败
（partial 覆盖、伪/未验引用、0 交付、集合违规）：无记录或记录 PENDING 也 FAIL，
`final_basis=mechanical_hard_failure`，真实片段与已交记录保留在行上，不以未审身份软化。
真正 complete+独立引用成立而语义未审的合成仍 PENDING（新增自有正例 + reviewer 正例）；
完整具名语义记录仍可 PASS；反例继续行为合同；Round-1 兼容历史不变。
自有 `test_new_output_unaudited_semantic_rows_stay_pending` 按交接明示**强化**为 partial→FAIL。

## R2 typed 身份保留到评分入口
`_fusion_segments` 改为**原样保留上游发布的 typed 目标 dict**（unit_id/table_id/scope_id/
citation 依据/status 不再被复制丢弃）。命中判定全程组合归属：chunk 命中=发现 chunk 的
(workspace,doc,chunk_id) 真在映射 unit 的 chunk_ids 内；unit/table 命中=目标自带该 unit_id
**且其 workspace/doc 与期望单位一致**；scope 命中=目标 scope_id ∈ 映射 scopes 且所属
doc/workspace 一致——同名 scope、另一 workspace、另一文档均不命中；不从名称猜 ID、
doc 目标不升格 unit。真实 main 两类正例（table_unit/scope）读入且命中
（reviewer 两项 + 本目录 `test_typed_target_identity*` 经 a.main 路径）；外 workspace 负例=0。
零发现保持 0、未映射留分母→发布 null、枚举/精排/展开不反灌——全部保持。

## R3 每次失败独立诊断
owning catch 改用**本次调用局部标志** `diag_written`：verify 失败写第一份并置位、
catch 仅在未写时为同一异常补写，**不再以"目录里已有 input-rejection*"为由跳过**。
第二次失败得到第二份含自身原因的新诊断（`input-rejection-1.json`），第一份字节不变
（reviewer `test_each_refusal_gets_new_diagnostic`）；输出父目录按输出合同显式 mkdir；
成功仍原子发布、已存在输出拒绝、历史文件不动。

## R4 真工件/批准锚先验必填再比值
生成模式 main 评分期间 `_STRICT_BIND`：成功 answer/fusion/local 结果行**必须**携带合法
`query_id`（等于本题）与 `workspace`（等于锚工作区）——缺字段即拒绝（"字段不存在就不
比较"不再豁免成功腿）；明确 failure/无 results/absent 腿按既有语义先行返回。裸接口
typed 探针（非 main 消费者，如 reviewer 17 项 fixture）保持宽松"有则比对"，两类数据
按 owning 合同区分，未改任何冻结输入。批准锚 `frozen_identity.eight_table_counts`
必须是**完整八项合法非负整数**：缺失/畸形=输入拒绝，再比 pre/post 真实计数
（reviewer `test_required_frozen_counts_cannot_be_omitted`）。

## 结果
| 套件 | 结果 |
|---|---|
| 新衔接 10 项（ENV→本副本） | **10 passed**（pytest-reviewer10-r3.txt） |
| 旧评审 17 项 | **17 passed**（pytest-reviewer17-r3.txt） |
| 历史 35 冻结（兼容） | **35 passed**（pytest-frozen35-compat-r3.txt） |
| 自有矩阵（21→22，含授权强化+complete 正例） | **22 passed**（pytest-own-matrix-r3.txt） |
| r3 自测 | 12/13 备案细标签同判 |
| strict / diff / ruff check+format | 全净（quality-commands.txt） |

证据全部为合成 fixture/既存工件副本；0 新请求、0 写库、0 生产改动。不建正式锚、
不问额度、不跑 123/246、默认融合与 6.2–6.5/Gate4 不动。停主 agent 复审。
