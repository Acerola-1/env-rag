# 改进组3 r1 补正：最终发布窗口内容守卫（F1）

交接：`handoff-phase-4-improvement-3-fixes-r1.md`。仅 F1，已通过部分（3 份并集、引用快照、搜索层解耦、并集统计）未返工。全程 0 真实网络/DB/模型/embedding/rerank/写库/探测；第二轮暂停；gold/.env/真实锚/全部旧冻结/历史交付逐字节保护（一处例外如实披露，见"事件披露"）。

## 一句话结论

**发布窗口现在与"当下目录"核对**：base+related 合并之后、发布之前，守卫经既有只读分页通道把 base 匹配窗与 related 归属匹配集**重新读一遍**，逐字段（身份/版本/title/逐分支归属判据）与读取基准的分支 token 比较——标准在同快照下改登版本、无关行变成匹配修改单（行数不变）、匹配行反向消失，全部落入非 complete 并记录原因；复读无法完成时同样显式非 complete。reviewer 冻结矩阵从 2 失败/1 正例到 **3/3**；自有矩阵 18→21（新增窗口三例）；全工程 **526**；改进组1/2 冻结 **18**、评分冻结 **35**、评分自测 6+10+12/13（同一细类标签观察，非阻断）；六腿存储输入回放仍 **3/3/3/2/5/5**、complete、search 层读取 **0**，且 related 腿每次多出 **1 次**无谓词全扫描=守卫复读真实在场的计量证据。

## 改动（允许面内三处）

| 文件 | before→after（本轮编辑前实测） | 内容 |
|---|---|---|
| `enumerate_/doc_enum.py` | e553d052→495efb96 | 新 `verify_publication_content`：先复用 `verify_publication_snapshot`（身份链保持，且 reviewer 的注入点在其内生效），再做两次有界重读——`_match_page` 全窗 vs `enum.read_token`（行身份字段全参与），`_meta_page` 全窗经 `_attribution_rows` 重算 vs `related.read_token`（匹配集含逐分支判据——新携带/不再携带/判据变化在总行数不变时仍被捕获）。任何不匹配或重读异常返回明确 reason：调用方发布 stale/非 complete，reason 入 trace。重读走**现有只读分页通道与同一预算公式**，无新旁路。 |
| `search/expand.py` | b004c9fa→7ce0a67c | 发布守卫调用替换为 `verify_publication_content(conn, workspace, enum, related, args, codes, page_size)`；guard reason 继续进 trace `publication_guard` 并驱动 combined=stale。已读行**保留发布为诊断**（不按新行悄悄覆盖旧行——守卫只否决 complete，不改写 items）。 |
| `answer.py` | 65eefd79→98328f7f | 文件条目独立复读从"仅 doc_name"扩到 `self_code`/`self_code_version` 身份字段：同快照下版本改登时条目降级 `citation_verified=False`+flag——文件复读与全匹配集合守卫**职责分列、分别留证**。 |
| `tests/test_phase4_improvement3_union_enumeration.py` | 8c294b78→7857e791 | +3 窗口用例（自有 fake，非改注入点）：匹配行反向消失→非 complete+旧行保留诊断；版本改登→非 complete 且旧字段不再 verified；复读传输失败→"could not be completed" reason、非 complete。UnionConn 加无谓词全扫描计数 knob（构造失败时序，fake 目录、真实守卫）。 |

未动 `query.py`（行内归属原语与路由语义原样：25bed96d 不变）、`evaluation.py`（a42d5c68 不变）、LocalCandidateAdapter/fusion/rerank/正文引用/模型策略；旧冻结文件零改动。

## 验收（交接 §验收与停止点逐项）

- **先红**：reviewer 冻结矩阵改动前实测 **2 失败/1 正例**（`pytest-review-r1.txt` 复现记录，注入发生在真实最终守卫执行前、snapshot/行数/公开来源身份不变、正式 answer 入口+实际守卫+文件复读全部执行）。**修后 3/3 绿**（`pytest-reviewer-frozen.txt`），稳定正例仍完整 2 份（`members_total==processed==2`）。
- **本组原 18 项 + 改进组1/2 冻结 18 项保持**（`pytest-matrix-r2.txt` 21、`pytest-frozen-improvements.txt`）：零相关证据非 complete、合法重叠新增 0 仍 complete、版本/自身编号/年报分页/搜索解耦均原样通过。
- **六腿原存储输入 owning 离线回放**（`union-reconcile.json`+`replays/`6 份）：3/3/3/2/5/5、全 complete、missing/extra 0、search 层读取 0；对账差异相对上一代仅为**新增守卫证据与读取计量**（related 腿无谓词全扫描 5→6；trace 增 `publication_guard` 复读语义不变为 stable）；不回填发现召回、不冒充现场运行（全部 存量产物读取/构造/离线owning回放 标注）。
- 一次全工程 526 + 评分 35 + 自测；Ruff 工作面/strict/diff/敏感扫描/历史清单复算见本目录工件。旧 r3 12/13 细类标签观察非阻断、旧目录未动。

## 事件披露（不作掩盖、不回写、不豁免）

本轮复跑上一代回放脚本时**误将输出写回原代目录**：`phase-4-improvement-3/replays/` 6 份终态报告漂移（运行时间戳+复读计量字段），在 `protected-recheck.json` 的 drift 列表如实保留（1180 条复算、6 条漂移、其余 1174 零漂移）。**发布结果逐腿未变**：原代 `union-reconcile.json`（不含时间戳的逐字段对账文件）重跑后**字节不变**、其 SHA 仍在原代清单中零漂移——即 items/coverage/统计/gold 对账与已验收记录完全相同（3/3/3/2/5/5）。旧 manifest 不回写；r2 代回放独立写入本目录（`replay_union_r2_offline.py`，OUT 固化指向 r2）。教训入记忆：任何代次复跑必须先改 OUT。

## 停止点

提交后停主 agent 复审；不自行放行改进组3，不勾 6.2/6.3/Gate4，不启动第二轮；正式评测 PG 预算重标定留待后续有界真实检查。
