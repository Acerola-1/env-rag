# 改进组1 增量补正 r2 — 执行报告

交接：`handoff-phase-4-improvement-1-fixes-r1.md`（F1–F4）。全程 0 网络 / 0 模型 / 0 数据库 / 0 写库 / 0 探测；不启第二轮、不切默认路径、不改提示/gold/旧锚/评分 r1-r3/历史运行/冻结。评分 r3 通过结论保持不变。

## 一句话结论

新增冻结验收 9 项从 7 失败/2 正例 → **9/9 通过**；首轮真正修好的正文短范围、正常跨段、quote-only 接口全部保留（自有 14 项语义不变全绿，另加 3 项归属用例）；全工程 477 通过；回放改为无金标输入并新增 6 项 `run_answer` owning 入口离线回放，原始请求 trace + 原始 sidecars 端到端 pass-through 发布 complete、4.3.4 = 53 字、零模型调用。

## 验收数字

| 检查面 | 结果 |
|---|---|
| 复现基线（补正前） | 7 fail / 2 pass（与交接一致） |
| `phase-4-improvement-1-review/test_improvement1_review_r1.py` | **9/9**（零删改/xfail/弱化） |
| 自有 `tests/test_phase4_improvement1_prose_integrity.py` | 17/17（14 项原语义 + 3 项 F3 归属新增） |
| 新增自有 `tests/test_phase4_improvement1r2_owning_replay.py` | 6/6（1 原始产物 pass-through + 5 构造/篡改经 owning） |
| 全工程 `pytest tests` | **477 passed**（基线 468 + 本组新增 9；含 gate2 r8 冻结回归） |
| 评分冻结矩阵（r1 17 + r2 18，ENV→已验收 r3 评分器） | **35/35** 对新代码 |
| 评分自测 r1 / r2 | 6/6 / 10/10 |
| 评分自测 r3 | **12/13**：`test_appended_fabricated_wording_breaks_declared_span_support` 第二断言的细分类标签 `unsupported_declarations` 不再触达（新严格回读更早拒绝，**整题 FAIL 判定不变**）——与首轮相同、交接明示非阻断，未改旧评分目录 |
| Ruff | `ruff check` 全绿；本组 5 文件 `ruff format` 后全库 src+tests **86 文件 formatter-clean** |
| OpenSpec strict / `git diff --check` | `Change 'add-pg-scoped-retrieval' is valid` / 干净（最终复跑确认） |

## 源码改动（SHA 前后见 `sha-after-r2.json`）

| 文件 | r2 基线 | 修复后 | 内容 |
|---|---|---|---|
| `enumerate_/prose_enum.py` | 28e2b73a… | 3d922e20… | `ASSEMBLY_SEPARATOR` 协议常量（装配/间隙记账/两侧重装配单点同源）；分隔符"声明仅核验、协议才重建"；数值跨度=键存在即声明、畸形拒绝不降级；`structural_boundaries` 归属三分（attributed 保留 / ambiguous 记 note 交调用方降 partial / independent 干净切）；段形状非 list/dict 安全拒绝不逃出链路 |
| `search/expand.py` | 15422a8d… | d328e76b… | `_expand_prose` 改用 `structural_boundaries`；交付项或兜底体被 ambiguous 位实际裁剪 → complete 降 partial + `warnings`/`boundary_ambiguities` 随结果发布；join 走协议常量 |
| `answer.py` | 0cd30bc3… | fef50024… | `_reverify_prose_items` 对称执行协议重装配/声明键存在性/各坐标协议校验；problem 文本区分"伪 separator 非协议""畸形坐标拒降级"；Gate-2 r8 quote==跨度老形状保留 |

首轮的四项正修复（短范围、装配顺序、跨段间隙、全文回读）未回退。

## 证据分列（标签如实）

- **原始产物读取 + 离线answer入口回放**：`owning-replay/stored-trace-prose-enum-003-real-sidecars/`（已存 5.3/5.4 重放报告、已存身份注入、原始 sidecars；发布态 complete/4 项/53 字/0 模型/前后置身份一致）；`replay-evidence-r2.json`（五题函数级，输入=问题解析并与 trace 记录输入对照）。
- **构造读取注入**：跨段合法、attributed 表、ambiguous 表三组 + 自有 3 项边界用例。
- **构造篡改注入**：伪 separator、char_start=null（真实 expand 之后注入条目，expand/验证一律真跑；owning 发布 partial + 拒收原因 + 不静默丢项）。
- **构造测试**：函数级矩阵反例全套。
- 无任何"真实数据库重跑/冷生成"宣称；本轮 0 条腿评测。

## 交付物（`phase-4-improvement-1-r2/`）

`baseline-shas-r2.json`（改前冻结，含 r1 代次基线引用）｜`sha-after-r2.json`（前后差异+新文件）｜`diagnosis-r2.md`（根因/输入输出/正反例/无金标路由证明/owning 终态）｜`report-r2.md`｜`replay-evidence-r2.json`｜`generate_replay_evidence_r2.py`｜`owning-replay/`（6 份发布态 `answer-runtime-latest.json` + `owning-replay-evidence.json`）｜`generate_owning_evidence.py`｜`improvement-1-r2-manifest.json`。首轮 `phase-4-improvement-1/` 报告与 manifest 原样保留为第一轮提交，未被覆盖。

## 诚实记录

1. 旧评分 `main()` 因已验收代码 SHA 漂移而拒绝新 answer.py 属**正确跨代保护**：未给旧锚加豁免、未回写旧配置锚、未覆盖历史裁决（33/45/15 与 9/14/7 基线不动）；新回放各自记录本轮代码身份与规则，不发布"两轮增益"或新真实质量汇总。
2. 复核中曾清理 `reports/pg-retrieval/**/__pycache__`，其中评分 r1 清单**记录了**两个 .pyc 条目；重编译同名 .pyc 后逐条 SHA 与清单复算一致——全库所有 manifest（含 round-1 809 项、r1 9、r2 4、r3 4、improvement-1 6、主 agent review 12 等）**零漂移**，gold SHA = `1bf130077c21583a…` 匹配冻结，`phase-4/phase-4-config-anchor.json` 未动，`.env` 未读取。
3. prose-002 的 round-1 trace 记录输入 `["4.1.1"]` 与问题文本（同时点名 4.1.1/4.1.2）不一致：属历史请求解析观察项，不在本组改动面，仅如实记录。
4. neg-010 勘误维持首轮交付方式（只在新台账，历史评分原因字段未改写）。

## 边界与停止点

未改 6.2/6.3/Gate4 状态；未切默认融合；未更新目录/索引配方；未做存储 initialize；未动提示/模型配置/单位版本/声明支持政策；完整引用要求未降低。本组不跑 123/246 腿、不真实生成。提交后停主 agent 复审；后续改进组或有界真实验收另行安排。
