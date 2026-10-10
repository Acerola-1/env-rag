# 改进组2：目标身份确认与发现隔离 — 实施报告

交接：`handoff-phase-4-improvement-2-scope-implementation.md`。全程 0 真实网络/模型/数据库/写库/探测；第二轮保持暂停；诊断目录、round-1、评分 r1-r3、改进组1 与全部旧冻结/gold/.env/锚逐字节保留。

## 一句话结论

**发现不再当目标**：评测合成层不再把 local 候选晋升 typed 目标；答案层对每个候选/上游目标统一经"已守卫的 workspace+catalog snapshot 目录行"做 canonical self_code/version 确认——四条旧混入腿的原输入回放后外来 items 全部为 0、目标逐项完整且 complete、对照腿发布不变；18 项新验收矩阵、497 全工程、47 冻结（35 评分+9+3 改进组1）、16 评分自测全绿；旧 r3 自测 12/13 仍为同一细类标签断言（整题判定不变，非阻断）。

## 改动（仅允许的两文件）

| 文件 | before→after | 内容 |
|---|---|---|
| `evaluation.py` | 5a41ee1b→**见 sha-after** | `_synthesized_fused_result` 停止晋升：`typed_targets=[]`、`targets_resolved=[]`，新增 `discovery_docs`/`targets_confirmed:false`/`path_provenance.discovery_only`；usable、paths、凭证、预算原样保留；空发现=missing+discovery_only（本路零发现标记），不再可被读成全库缺失 |
| `answer.py` | fef50024→**见 sha-after** | ①`_confirm_scope_identities`：对 universe（上游 resolved+typed+候选）逐文档 `_DOC_META_SQL` 读 canonical 身份——代码匹配且（未给版本→多版本合同全保；给版本→`_version_matches` 严格匹配）入 allowed；不匹配 rejected（附 canonical 码）；缺行/self_code 未知 unresolved（绝不按名称猜）；唯一放宽=既有归属路由：**仅当问题确为 含修改单/相关文件/整合版 且候选带 5.3 记录的 doc_attribution/membership_basis 证据**——单纯布尔 verified 标记或名称相似不放行，伪造 typed code_exact 同样被拒。②file_enum 显式跳过门（枚举文档即答案，分页/多版本/年报合同不回退）。③无代码分支且无上游 resolved：显式 ambiguous、零展开（"discovery alone 不是范围依据"），**不再**落入旧"全部候选"兼容回退。④上游 missing/stale（非 discovery_only）保持原状态；本地零发现 missing → ambiguous + 专属文案（"not a verified absence"）。⑤部分确认：unconfirmed_branches → 强制不 complete（items 保留）。⑥`scope_selection.target_confirmation` 全审计：request_branches/identity_source/allowed+basis/rejected/unresolved/unconfirmed/rule。全部读走 ctx 连接（无新连接、无绕过计量）；守卫前后、终态、净化、账本未动。 |

复用已验收件：`_split_codes/_dedupe_codes`（问题编号解析）、`normalize_code`、`_version_matches`（含 2/4 位年号互认）、`_attribution_requested`、`_DOC_META_SQL`；未新写"GB 数字"简单正则，未动 LocalCandidateAdapter/fusion/rerank/search.expand/正文表格验证器/目录 schema/提示词。

## 验收矩阵（`tests/test_phase4_improvement2_target_confirmation.py` 18 项，全经 owning 入口；先红后绿）

- 存量四腿原输入回放：prose-001 目标 4 条完整、GB8978 rejected、含修改单整合版 unresolved（外来 0，旧 13→0）；prose-006 4.2 单条、2026/HJ2.2 rejected、EPA unresolved；neg-004 13 行全 verified+reverified、GB18466 31 行不入答案；table-001 对照发布逐项不变。允许集/排除原因均可从"问题分支×目录身份"复算。
- 转换+入口联测：无 typed 也不回落全候选；发现列表/paths 保留；PG 调用零（炸弹）。
- 反例：仅他文档、同码错年份、目录缺行、self_code 未知普通请求、伪造 typed/自报名称——全部不混入、不 complete、无全库 missing 假报。
- 多目标：两代码全确认→complete；缺其一→items 保留但不 complete（未确认分支入 flags）。
- 归属成对：含修改单请求+5.3 证据→保留；自身编号请求→同类文档一律拒；无证据名称相似→拒。
- 无编号无范围依据→ambiguous 零展开；无版本代码→多版本合同保持；file_enum/上游 missing/stale/预算/净化不回退。
- 噪声（不同码文档）被展开记录也只是 unselected：不进答案、不降级已确认目标（complete 保持）。

## 实施后四腿新终态（存量产物读取 + 离线 answer 入口回放；`replays/` 4 份发布态终报 + `post-implementation-reconcile.json`）

| 腿 | items（旧→新） | 外来 | gold 事后缺项 | coverage | 模型 |
|---|---|---|---|---|---|
| prose-001/local | 17 → **4** | 0 | 0 | complete | 0 |
| prose-006/local | 13 → **1** | 0 | 0 | complete | 0 |
| neg-004/local | 44 → **13** | 0 | 0 | complete | 0 |
| table-001/local | 13 → **13** | 0 | 0 | complete | 0 |

相对旧运行的差异仅为**离线观察**（存量输入重放，非新真实评测；未发布任何真实质量指标）。

## 回归与数字

全工程 `pytest tests` **497 passed**（479+18）；评分冻结 r1 17+r2 18=**35/35**（ENV→已验收 r3 评分器）；改进组1 冻结 9+3=**12/12**；改进组1 自有 17+owning 7 全绿；6.1/评测与答案评审套（172 项相关面）全绿；评分自测 r1 6/6、r2 10/10、r3 **12/13**（同一 `unsupported_declarations` 细类标签断言：新代码更早拒收，整题 FAIL 判定不变——继续非阻断、未返工旧评分目录）。Ruff check/format 全库 clean；openspec strict valid；`git diff --check` 干净；敏感扫描 9 文件 0 命中；全库 1059 条清单条目复算**零漂移**（gold/锚/.env/诊断目录/全部历史代次未动；`.env` 未被读取）。

## 诚实记录与边界

- 旧评分 main 因 live 代码 SHA 漂移拒绝新实现属正确跨代保护，未加豁免、未回写旧锚；配置锚待主 agent 组通过后另建。
- 存量四腿测试中 fake 目录身份 = 原始 doc_name+封面行经**目录构建同一已验收提取函数**推导（provenance 记录在测试内）；合成场景的元数据行显式标注构造。未从文件名伪造 canonical 后声称现场目录验证。
- discovery/召回仍只来自原发现（`discovery_docs`/usable 原样），答案确认不回填召回；本组属答案策略层身份约束，非 local 语义检索增益。
- 未改 file-005 漏项、合成声明政策、单位、其它歧义问题；未跑 123/246；未勾 6.2/6.3/Gate4；未切默认融合。

## 交付物（`phase-4-improvement-2/`）

`baseline-shas.json`｜`sha-after.json`｜`post-implementation-reconcile.json`｜`replays/<qid>/answer-runtime-latest.json`×4｜`replay_after_implementation.py`（禁服务复跑入口）｜`protected-recheck.json`｜`report.md`｜`improvement-2-manifest.json`。验收测试在 `tests/test_phase4_improvement2_target_confirmation.py`。

**停止点**：提交后停主 agent 工程复审；第二轮保持暂停；后续（有界真实验收/其它挂账组）由主 agent 另行安排。
