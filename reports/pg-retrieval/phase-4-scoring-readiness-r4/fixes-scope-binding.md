# 生成模式严格绑定作用域衔接（评分准备 r4）

按 `handoff-phase-4-scoring-readiness-fixes-r3.md` 只补一处作用域衔接。0 网络/DB/模型/健康探测、0 写库；生产源码/gold/.env/真实锚/所有旧目录/全部冻结矩阵逐字节未动。全部证据为合成 fixture 或既存工件副本；`PYTHONDONTWRITEBYTECODE=1` 全程；输出只落本新目录。

## 唯一衔接（before/after）

**before（r3 副本）**：生成模式 main 只在 `_score_legs` 期间设 `_STRICT_BIND=True`，finally 立刻关回；随后 `recall_report`/`typed_evidence_recall` 经 `_fusion_segments`/`pre_expansion_docs`/`local_discovery_identities` 再读正式 fusion/local 工件时已是宽松裸探针状态——成功结果行缺 `query_id` 或 `workspace` 仍照常出分。复现红相与主 agent 一致：`test_scoring_review_r3.py` 对 r3 副本 **2 失败 / 1 正例**（fusion 缺 qid、local 缺 workspace 仍发布 123 行裁决）。

**after（r4 副本）**：严格绑定作用域包围**整个正式生成消费过程**——`_score_legs`、S1 消费覆盖检查、`recall_report`、`typed_evidence_recall` 全在同一 owning try 内；finally 恢复**进入前保存的值**（成功与任何异常都恢复），入口外直连的裸接口 fixture 保持宽松语义。被点名的读取函数本身不加特殊判定，仍只经 `_bind_leg_identity` 的既有规则（缺字段仅在 strict 内拒绝；显式 failure/no-results/absent 先行返回不套）。正式成功 fusion/local 行缺 qid/workspace ⇒ 本次净化拒绝诊断、非零、无裁决；完整字段的真实零发现仍是合法正例（0 召回不反灌）。

## 明确不动

硬失败归纳（R1）、typed 身份保留与组合归属（R2）、诊断唯一性（R3）、answer 必填与锚八表结构（R4 原有部分）、分母/投影、兼容模式、任何生产代码、review-r1 17 项 / review-r2 10 项 / review-r3 3 项 / 历史 35 项冻结矩阵字节。

## 自有矩阵变化（handoff 明示允许，只强化不弱化）

1. `test_typed_recall_zero_discovery_no_backfill_and_pending_missing` 的主入口 fusion fixture 行**只补合法身份 metadata**（`query_id=prose-enum-003`、`workspace=default`，与其题/锚工作区一致）并沿用原 `rewrite_manifest` 刷新；零发现/引用/分母/输出断言一字未改。
2. 新增一项生命周期正例 `test_recall_rejection_restores_scope_and_next_legal_run_publishes`：recall 路径拒绝后 `_STRICT_BIND` 恢复 False、无裁决、诊断落盘；同入口随后补合法身份的新一轮正常发布 123 行。自有矩阵 22→**23**。

## 结果（最终字节复跑，原始输出在本目录）

| 检查 | 结果 | 文件 |
|---|---|---|
| review-r3 新冻结（完整 owning 入口） | **3/3** | pytest-reviewer3-r4.txt |
| review-r2 冻结 | **10/10** | pytest-reviewer10-r4.txt |
| review-r1 冻结 | **17/17** | pytest-reviewer17-r4.txt |
| 历史评分冻结兼容（ENV_RAG_ASSESSMENT_SCRIPT） | **35/35** | pytest-frozen35-compat-r4.txt |
| 自有矩阵（22 原语义 + 1 生命周期正例） | **23/23** | pytest-own-matrix-r4.txt |
| 前代自测 compat（备案细标签） | **12/13 同判**（唯一失败仍 `test_appended_fabricated_wording_breaks_declared_span_support`，与前代一致、非阻塞） | pytest-r3-selftest-compat-r4.txt |
| ruff check / ruff format --check / openspec --strict / git diff --check | 全净（0） | quality-commands.txt |

## 身份谱系

评分副本 SHA256 见 sha-list.json；before-after 见 sha-before-after.json（r3 代次、评审矩阵、生产 answer、gold、.env、真实锚全部保持）。本副本继承 r3 的全部已验收修正，仅上述作用域一处不同。
