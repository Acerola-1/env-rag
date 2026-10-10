# 改进组2：local 答案范围混入 — 离线诊断

范围：仅诊断、不改生产代码。样本限定为已审 `phase-4-round-1-assessment-r3/adjudication.json` 指向的三条 local 失败腿 + 一条正确对照。全部结论均以**原始工件 + owning 入口（run_answer）离线复现**支撑；gold 只在事后核对；0 网络/模型/DB/写库/探测。复现入口：`replay_local_scope_offline.py`（发布态终报在 `replays/<qid>/answer-runtime-latest.json`，对账在 `local-scope-reconcile.json`）。

## 1. 一句话根因

local 腿没有任何代码/版本目标解析：评测层把**本地发现的全部候选文档逐个晋升为 `typed_targets`（target_type=doc, discovery="local"）**，而 5.5 答案入口的作用域规则把 typed_targets 直接当作"5.3 已确认目标"全量展开——每个被选文档都按原问题的章/表号读出完整答案并合并发布；引用逐条真实、coverage 机制正常，于是范围混入仍报 complete。正确对照 table-enum-001/local 并非有防护，而是其 10 条候选恰好全部落在目标文档上——同一机制的运气分支。

## 2. 逐阶段来源表（四样本实测，值取自本轮发布态与已存工件）

| 阶段 | prose-enum-001/local | prose-enum-006/local | neg-004/local | table-enum-001/local（对照） |
|---|---|---|---|---|
| 原问题意图 | GB **18466-2005** 的 3 章术语 | GB **3095-2012** 的 4.2 节 | GB **8978-1996** 表1 | GB **8978-1996** 表1 逐行 |
| local 候选（fused usable） | 10 条，跨 **3** 文档（68a0×6、9bb1×3、b45c×1） | 10 条，跨 **4** 文档 | 10 条，跨 **2** 文档（b45c×7、68a0×3） | 10 条，全在 **1** 文档（b45c×10） |
| 转换后 fused-replay | `targets_requested=null`、`targets_resolved=[]`、typed=3 个 doc(discovery=local) | 同左，typed=4 | 同左，typed=2 | 同左，typed=1 |
| answer scope_selection | selected=**3 文档**（全部 typed） | selected=**4 文档** | selected=**2 文档** | selected=1 文档 |
| 展开 | 每文档各自解析 "3 章"→prose 4+8+5 | 每文档 "4.2 节"→1+1+4+7 | 每文档 "表1"→13+31 | 13 行 |
| 发布 items | **17**（goal 4＋foreign 13） | **13**（1＋12） | **44**（13＋31） | **13**（13＋0） |
| coverage | complete（0 问题） | complete | complete | complete |
| 与第一轮已审事实 | 17/超13 ✅ 一致 | 13/超12 ✅ 一致 | 44=13+31 set_violation ✅ 一致 | 13 集合正确 ✅ 保持 |

本轮当前代码（含改进组1）离线复现四腿的文档集、条目数、coverage 与旧运行**完全一致**——混入不来自改进组1的正文/表格边界，属独立的 local 范围层缺陷。离线观察标注：不改旧评分、不发布真实增益。

## 3. 真实调用路径与决定性分支（带位置）

1. `src/env_rag_final/evaluation.py:860 _local_path` → 真实 LocalCandidateAdapter 取得候选（**无代码解析**；候选 paths[].discovery ∈ entity/lexical/vector，`file_path` 携带文档身份但从未被用于约束）→ `evaluation.py:931` 调 `_synthesized_fused_result(q, usable, "local")`。
2. `evaluation.py:950-981 _synthesized_fused_result` ——**决定性分支 1**：`targets_resolved: []`（L966），`typed_targets` = usable 中出现过的每个 doc_id 逐个 `target_type="doc", discovery="local"`（L967-973）。发现即目标。
3. `answer.py:1928-1996`（run_answer preflight）读已存 fused/rerank 文件回放 → `answer.py:1438-1446 _answer_one` ——**决定性分支 2**：`resolved` 汇总 targets_resolved（空）+ **所有 typed_targets 的 doc_id**；`answer.py:1451 if resolved: selected_docs = resolved`。basis 文本宣称 "typed targets (5.3)"，但入口不验证 typed_targets 的来源/出处（5.3 真实解析 vs local 合成晋升同样被信任）。
4. **未触发的假说排除**：`answer.py:1474-1479` 的"无 resolved 目标 → 回落到全部 replayed candidate_docs"兼容分支在四腿均未走到（typed 恒非空）。交接给的这条线索经复现证明**不是**本批样本的决定路径。
5. `expand.py:_requested_targets` 从问题解析出章/表号 → 对**每个 selected doc** `expand.py:854 _resolve_clause_target` 在各自目录中解析同号 scope（每部标准都有自己的"3 章"/"表1"）→ `_expand_prose`/`_expand_table` 全文展开。他文档展开本身逐条引用真实、回读通过（改进组1 语义正常）——这正是"引用真实 ≠ 目标归属正确"。
6. `answer.py:1546+` coverage 只由各 expansion 状态汇成——**没有答案-目标一致性门**，全 complete → 整题 complete。
7. 对照组：`inputs/pg/<同题>-fusion.json` 有 `targets_requested=[{code,version}]` + `targets_resolved`（代码+版本→唯一 doc），pg/fusion 腿 selected_docs 恒为单目标文档；`evaluation.py:1045+` fusion 腿走真实 `_run_fusion`，同样有解析。差异定位：**混入是 local 腿缺目标解析（输入约束）+ 答案层不核对 typed 出处（范围确认缺失）的合取**，不是展开/验证/coverage 组件缺陷。

## 4. 根因 / 非根因

**根因（按决定顺序）**
- RC1 输入缺约束·local 路径独有：`_local_path` 合成 replay 时不做代码/版本解析（也不查目录 self_code），`_synthesized_fused_result` 把发现集合晋升为 typed_targets。
- RC2 范围确认缺失·答案层共享：`_answer_one` 对 typed_targets 一律视为已确认目标，不核对问题代码身份（数据可得：candidates 携带 file_path；目录 documents 行含 self_code/self_code_version；`result.parsed_codes` 已在 `_build_replay_result` 解析好却未在此处使用）。
- RC3 展开选择放大：`if resolved: selected_docs = resolved` + 每文档同号 scope 可解析 → 他文档合法结构被完整读出。
- RC4 最终过滤缺失：答案 items 无文档归属门；引用真实性验证不承担目标归属。

**非根因（复现排除）**：answer 无目标回退分支（未触发）；budget 截断（kept 10/40 未触发）；rerank 缺席 flag（仅记录，不影响归属）；改进组1 正文/表格边界（四腿新旧发布态逐项一致）；引用/回读验证（全部真实通过——问题不在"假引用"而在"真引用不属于题目"）；5.5 多文档全量展开原则本身（对真实解析出的多目标/对比题是正确设计，缺陷在把未解析的发现当目标）。

**挂账（不入本组）**：file-enum-005/local 缺两份（发现层覆盖问题，另一类）；其余缺范围/歧义/单位/合成失败按主 agent 安排后续处理。

## 5. 可接受 vs 不可接受行为

- 允许：local 发现包含噪声/他文档，且作为可审证据保留（expansions/audit 字段）；多文档**合法比较**（问题显式点名 ≥2 代码版本）全部展开回答。
- 不允许：问题点名单一代码版本时，他文档 items 进入答案集合或参与 complete；把"发现即目标"当作 5.3 解析结果消费；用引用真实为归属正确背书；无可确认目标时静默全候选展开（现有 fallback 分支同样应在实现代次里受同一门约束）。

## 6. 最小修复方案（下一步实现代次建议，未动任何源码）

**改动文件最小集**：`src/env_rag_final/answer.py`（一处汇总门）＋可选 `src/env_rag_final/evaluation.py`（停止晋升，第二道）。

1. 第一道（答案层，决定性的）：`_answer_one` scope 汇总处，当 `result.parsed_codes` 点名了具体代码（含版本）时，`selected_docs` 只保留目录身份匹配的代码文档（documents 表 self_code/self_code_version 只读元数据核对——**是目录元数据确认，不新增 PG 关键词检索，不得计入检索增益**）；不匹配的 selected 展开降级为 recorded-only（保留进 `expansions` 审计、不入答案 items、不参与 coverage）。问题点名 ≥2 代码（对比/合成题）→ 全部匹配文档照常回答；问题无代码 → 保持现兼容回退并**显式 partial/ambiguous**（回退分支同受此语义）。
2. 第二道（合成层，卫生性）：`_synthesized_fused_result` 对 local 不再产 typed doc targets（或标记 `provenance="discovery"`），targets_resolved 保持空 → 让第一道/保守回退接管；不改 LocalCandidateAdapter 与任何检索。
3. 兼容风险：synthesis/对比题依赖多 typed targets——由问题代码集合门控自然满足；file_enum 不读 scope，无影响；counter 路由（category_overrides）同规则；已验收 pg/fusion 腿 targets_resolved 本就匹配，输出不变；改进组1 边界/验证语义零接触。

**必要正负例（实现代次验收，owning 入口）**：正例①单代码单版本题+多文档候选 → 答案仅目标文档、他文档在 audit、整题 complete；正例②双版本对比题 → 两版全答；反例③候选只含他文档且问题含代码 → 无可确认目标 → partial/ambiguous 显式（绝不"全候选展开后 complete"）；反例④问题点名 1996 而候选含同码旧版 → 旧版不入答案；审计例⑤foreign 展开完整保留且可审（引用真实，但不进 items/coverage）；回归⑥改进组1 全部冻结/自有/owning 用例与新边界零交互。

## 7. 离线方法与边界声明

四腿均经 `run_answer` owning 入口：已存 `inputs/local/<qid>-*` 重放文件原样引用（SHA 不变记录于对账）、身份材料取自各 fused 文件自身 `identity_before`、原始 parsed sidecars 只读；prose 目录行来自该 local 腿**自己的** runtime expansions 记录（scope_id+unit_ids），表单元行由原始 tables.json 推导构造并以"与已存运行逐文档条目数一致"作为重建一致性校验（四腿 match=True；不足则报缺，未伪造目录/版本/scope）。fake 连接仅应答 SELECT 形态且写语句/未知 SQL 即抛；`asyncpg.connect`、`httpx.post` 装弹；allow_model=False、transport=None；本轮零网络/DB/模型/写库/探测。gold 仅事后（goal 归属由"问题代码×候选 file_path"推出，未用 expected_items/目标集注入）。第二轮保持暂停；未跑 479 全套（本组不改生产代码），未动旧锚/旧评分/历史工件。

## 8. 交付物

`replay_local_scope_offline.py`（复跑入口，离线）；`local-scope-reconcile.json`（四腿逐阶段+对账+一致性标志）；`replays/<qid>/answer-runtime-latest.json`（4 份发布态终报）；`sha-anchors.json`（当前代码 SHA 锚，仅记录）；`protected-recheck.json`（历史清单/gold 复算）；本文件。
