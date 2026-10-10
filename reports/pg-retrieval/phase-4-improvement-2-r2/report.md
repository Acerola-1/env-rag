# 改进组2 r2 补正：归属证据双向闭合 + 无编号范围确认

交接：`handoff-phase-4-improvement-2-fixes-r1.md`。全程 0 真实网络/模型/数据库/写库/探测；第二轮保持暂停；canonical 编号门、评测停止晋升、空发现处理与改进组1 未返工；诊断目录、实施代次、round-1、评分 r1-r3、旧冻结/gold/.env/锚逐字节保留。

## 一句话结论

**A/B 两组接缝闭合**：归属放宽只认 5.3 真实发布形状（typed doc_attribution + allowed_set_basis 交叉印证 + catalog_row 引用绑定本请求 workspace/active snapshot/doc_id，且目录行经 owning 守卫连接复核存在与名称），候选自报标签一律无效；已确认归属目标没有 usable chunk 也照常注册并完整读取；无编号问题的范围依据同样必须可验证——本地自报的 typed/targets_resolved 一律只是发现（显式 ambiguous、零展开），可信上游 code_exact 解析则保留但每个文档仍过当前目录身份门。冻结新矩阵 **6/6**（先复现 5 失败/1 正例）、自有 26、全工程 **505**、改进组1 冻结 **12**、评分冻结 **35**、评分自测 6+10+12/13（r3 同一细类标签观察，非阻断）全绿；**四条已修腿发布 items 与已验收代次逐条完全相同**（4/1/13/13、外来 0、complete、零模型）。

## 改动范围

| 文件 | before→after | 内容 |
|---|---|---|
| `src/env_rag_final/answer.py` | 62e8f996→14c9673b | 见下 A/B |
| `src/env_rag_final/evaluation.py` | a42d5c68→a42d5c68（未动） | 本轮零改动 |
| `tests/test_phase4_improvement2_target_confirmation.py` | 自有模块 | 正例升级为真实结构化上游 fixture；新增双向闭合/绑定缺陷/无 chunk 完整读/无编号成对等 8 项；原 18 项断言零删减零弱化（明细见 sha-after/自有清单） |

### A 归属证据双向闭合

1. **新 `_attribution_evidence_map`**：仅从 fused 回放自身收集发布证据——typed `target_type=doc & discovery=doc_attribution & citation_verified is True` + **非空字符串** membership_basis（布尔拒绝）+ citation `kind=catalog_row` 且 workspace/active snapshot/doc_id 三者与本请求一致 + `allowed_set_basis.verified_attributions` 同 doc 同 basis 交叉印证（typed 无 basis 背书、basis 无 typed，均拒——闭合是双向的）。候选路径上的自报 `discovery=doc_attribution`/任意 `membership_basis` 字符串完全不进证据集。字段形状与存量 `inputs/pg/neg-010-fusion.json` 逐字段同构（该文件 verbatim 含 9bb1/b423 两份真实归属证据）。
2. **目录复核经 owning 连接**：unknown self_code 文档仍必须命中 `_DOC_META_SQL`（同 workspace+active snapshot），证据 doc_name 与目录行名称冲突即拒；确认后入 allowed 并记录完整依据文本。
3. **无 chunk 完整读取**：已确认归属目标不在候选中时走既有 `target_resolved_replay` 注册→正式 expand 完整读取（`_synth_leg`/冻结矩阵均经 `run_answer` 验证最终 items，不是 helper 断言）。
4. 请求谓词不变：`_attribution_requested` 为假（自身编号/普通请求）时证据整体不启用——同一份结构化证据，正负两腿只差问题措辞。

### B 无编号时确认范围依据

1. **拆掉 `elif resolved:` 捷径**：resolved 列表混有 typed 发现、纯 local 合成可自报 targets_resolved——非空不再等于确认。
2. `path_provenance.discovery_only=True` 或 `targets_confirmed=False` 的回放**不能自证**目标：其 typed/targets_resolved 字段按发现处理——显式 ambiguous、`selected_docs=[]`、items 零展开；原发现条目与拒绝理由留在 `target_confirmation.discovery_proposals_kept_for_audit/refusal_basis` 供审（本路未确认≠全库缺失文案保持）。
3. **可信上游**（无上述发现标记，或 5.3 真实缺省形状）的 `targets_resolved` 若携带真实 code_exact 解析形状（code+version+docs），其 code/version 成为请求分支——但只是提案：每个文档仍逐一经当前目录 canonical 身份门，噪声外来文档照样 rejected；`branch_source` 入审计。
4. file_enum 分页/年报/上游已验证 missing/stale 不回退（存量对照与 `test_pg_upstream_missing_status_preserved` 保持）；不从 gold/其它路径回填发现与目标。

## 先红后绿

改动前复现：`pytest-red-reproduction-before-fix.txt`（5 失败/1 正例，与主 agent review 目录 `pytest-review-r1.txt` 判定一致，逐字转录、时间先于本次编辑）。改动后：冻结矩阵 6 全过（`pytest-frozen-matrix-r2.txt`）。

## 证据（`attribution-and-scope-trace.json`、`four-leg-preservation.json`、`replays/` 4 份终态）

- 归属轨迹四步完整落盘：①上游发布证据（typed+basis+targets_resolved，_M 无任何 usable chunk）→②owning 守卫连接的 documents 行复读（workspace/snapshot/doc_id 逐条）→③确认结果（allowed/依据文本/rejected/unresolved/branch_source）→④最终 items 的 doc/clause/verified/reverified + 完整读取注册 flag + 模型 0。
- 伪标记安全拒绝：候选自报 `doc_attribution`+basis 字符串、无上游发布证据 → allowed 仅合法标准、该文档 unresolved 并记录"仅认上游发布且经允许集交叉印证"的理由。
- 可信/不可信无编号成对：同一份问题、同一份 code_exact 解析形状——fusion 形状确认并完成（外来 rejected 可审），discovery_only 自报形状 ambiguous 零展开（提案保留审计）。
- 四条已修腿：items JSON 规范化后与已验收代次 `phase-4-improvement-2/replays/` **完全相等**，coverage/model_calls/foreign 逐项核对；证据标签均为 存量产物读取/构造/离线owning入口回放，无现场数据库重跑或冷生成冒充。

## 保持与不回退

工程 497→505（+8 自有，0 删改）；改进组1 冻结 9+3、评分冻结 35、诊断/实施代次、round-1、gate-0/1/2 与全部历史 reports 清单 1093 条复算 **drift 0**；gold SHA `1bf13007…` 匹配；.env 未读；敏感扫描两轮模式+逐条定性（配置键名/f-string/公开 doc_id/gold SHA，真实凭证 0）。r3 自测 12/13 为同一 `unsupported_declarations` 细类标签观察（整题 FAIL 判定不变），未更新旧锚、未加豁免。

Ruff 口径（如实记录）：**本组工作面** `src/ tests/ reports/pg-retrieval/phase-4-improvement-2-r2/`（89 文件）`ruff check` 与 `ruff format --check` 全 clean。全仓扫描另有 16 处 lint 违规与 6 个未格式化文件，全部位于**历史冻结产物**（phase-3-review、phase-3-answer-review、phase-4-improvement-1-r2 两脚本、assessment-r2/r3 脚本）——它们的 SHA 已入各代历史清单，逐字节保护优先，不做触碰（重扫零漂移复算已证其未动）。openspec strict valid；`git diff --check` 干净。

## 停止点

按交接交付后停主 agent 复审。第二轮保持暂停；6.2/6.3/Gate4 未勾选；默认融合未切换；file-005 漏项、合成声明政策、单位等挂账未触碰。
