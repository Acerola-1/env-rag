# 改进组3：file-enum-005/local 修改单漏项离线诊断

交接：`handoff-phase-4-improvement-3-file-enumeration-diagnosis.md`。**本组生产源码一字未改**（当前 answer.py=`14c9673b`、evaluation.py=`a42d5c68`，均为改进组2 r2 已验收态）；0 真实网络/模型/DB/embedding/rerank/写库/探测；第二轮保持暂停。四样本经 `run_answer` owning 入口离线回放（`diagnose_file_enum_offline.py`，服务炸弹；目录行=SHA 受保护的 gate-2 `replay.json` 221 行 document_enumeration 存量集 verbatim；gold 仅事后核验，期望 doc_ids 从未入输入）。

## 一句话结论

**local 腿的"含修改单"增补被一条依赖 PG 搜索索引层的归属路由承担，而 local 合成 fused 的 `pg.search_id` 恒为空串**：归属路由在 `env_rag.search_documents WHERE search_id=''` 上必然零行（实测调用参数证明），`attribution_added=0`；同时 `_expand_documents` 用"基谓词枚举结果"整体替换候选，把 local 路径**自己的发现里已经带着并验证过**的两份修改单文档丢弃；最终覆盖判定只看枚举基集合分页（1/1 complete），增补零结果不参与任何判定也不告警——于是显式"（含修改单）"请求只交付 1/3 仍报 complete。pg 腿同码同表同路由，仅 `search_id` 真实（`872d6893…`）→ emitted 2 → 3 条正确。

## 四样本逐阶段回放（当前源码；`diagnosis-replay.json`）

| 腿 | 谓词（实参） | 归属分支 | added | enum 成员 | 发布 items | coverage | 与第一轮已审存储一致 | gold 事后 missing/extra |
|---|---|---|---|---|---|---|---|---|
| file-enum-005/local | `(self_code=$3 AND self_code_version IN ($4,$5))` = GB18466,{05,2005} | 开 | **0** | 1/1 | 1（68a0） | **complete** | ✔（1 条、complete） | **2**（9bb1、b423）/0 |
| file-enum-005/pg（对照） | 同 | 开 | **2** | 1/1 | 3 | complete | ✔（3 条、complete） | 0/0 |
| file-enum-001/local（同号多版本） | `(self_code=$3)` = GB3095 | 关 | — | 2/2 | 2（2012、2026） | complete | ✔ | 0/0 |
| file-enum-002/local（年报分页） | `(doc_name LIKE '%'‖$3‖'%')` = 中国移动源环境管理年报 | 关 | — | 5/5 | 5 | complete | ✔ | 0/0 |
| 005/local 变体（**构造参数对照**：存储 fused 逐字段复制，仅 `pg.search_id` 置 active 冻结值） | 同 local | 开 | **2** | 1/1 | 3 | complete | —（单变量新腿） | 0/0 |
| 002/local 变体（构造：真实 enumerate 入口强制 `page_size=2`） | 同 | 关 | — | 5/5（跨 3 页） | 5 | complete | — | 0/0 |

归属路由的真实调用参数（全部记录在 `diagnosis-replay.json.attribution_route_calls`）：local `search_id_arg="" → returned_rows=0`；pg/变体 `search_id_arg="872d689343a9cbb6"`；tsquery `'gb18466'`；路由自身的 name/title code_hit 与版本守卫均为**真实实现未 mock**，变体腿 emitted=2 后进入发布集。

## 两份漏项逐份追踪（交接 §2 必答）

| | doc-9bb11e5d…（含2026修改单整合版） | doc-b423a0e3…（修改单2026） |
|---|---|---|
| 发现中是否有？ | **有**——local fused usable 10 条中 9bb1×2、b423×1，`verified=True` 且带 file_path（存量输入逐字段） | 同左（×1） |
| 目录真实依据 | catalog 行 `self_code=None`；title=`GB 18466—2005（含2026年修改单）`（gate-2 存量 gold-source-proof/replay 行 verbatim）；封面行含同号（原始 sidecar） | catalog 行 `self_code=None`；title=`《医疗机构水污染物排放标准》（GB 18466—2005）修改单` |
| 标准号/版本语义 | **related 归属**（name/title 携带所请求码，绝不冒认 self_code——gold match_predicate 原句）；非 canonical self_code 匹配 | 同左 |
| 何时被遗漏 | ①枚举基谓词按 self_code 匹配→天然不含（设计如此，由归属分支负责捞回）；②归属路由读 `search_documents WHERE search_id=''` 零行（**根因**）；③`_expand_documents` 替换 candidates 时连"发现已含"的事实也被抹掉；④coverage 只看 1/1 成员→complete（增补零结果不参与判定） | 同左 |

## 根因（决定性）与单变量证明

1. `evaluation.py:959-963 _synthesized_fused_result`：local 腿合成 fused 的 `pg` 块把 `search_id/catalog_snapshot_id/source_snapshot_id` 硬编码为空串（local 路径没有 PG 搜索运行，这些字段本就无真值可填——这是**事实陈述**不是缺陷指控）。
2. `answer.py:271-273 _build_replay_result`：忠实回填 `result.search_id = pg.get("search_id") or ""`。
3. `search/expand.py:352-441 _expand_documents`（`answer.py` 对 file_enum 以 `expand_docs=True` 调用）：
   - 基集合 = `enumerate_documents` 对 `env_rag.documents`（catalog 层、active snapshot 自取）执行 `_doc_predicate` 强谓词——005 即 1 行，分页/快照/stale 守卫全部正确（001/002/pagesize2 腿证明枚举本体无缺陷）；
   - `result.candidates` 被**整体替换**为枚举行——local 发现里已验证的 9bb1/b423 chunk 候选随之出局；
   - 增补 = `_doc_attribution_route`（`search/query.py:518`）——但它查 **`env_rag.search_documents WHERE workspace=$1 AND search_id=$2`**：搜索索引层，以 search_id 为键。local 腿 `$2=""` → 零行 → `attribution_added=0`（trace 只记录数字）。
4. `answer.py:1963-1974` file_enum coverage：`members_processed==members_total`（1/1）+ items 引用 verified → **complete**。`attribution_branch=true` 而 `attribution_added=0` 不产生任何 partial/ambiguous/flag——"请求显式要修改单、机制静默没给"不可见。
5. 单变量证明：变体腿与失败腿**同一存储输入、同一 fake 目录、同一真实路由**，仅 `pg.search_id` 置回 active 值 → added=2 → 3 条与 gold 事后一致。"看到空字段就认定根因"被这组对照排除；空参数→零行的因果以实际调用参数与行数记录为证。

pg 腿正确的原因同理但非运气豁免之外无附加条件：其 fused 来自真实 5.3 搜索运行（search_id=872d6893…、catalog_snapshot=4919…），路由天然可用。这与改进组2对照腿"发现恰好单文档"性质不同——本例 pg 的正确是**机制在场**，local 的失败是**机制接错层**。

## 次要缺陷（同一处必须一并处理，独立于主根因）

- **归属增补行的引用快照绑定为空**：`_doc_attribution_route` 的 citation 用 `result.catalog_snapshot_id`（local 回放为 `""`）。变体腿捞回后，两份归属 items 的 `citation.snapshot_id=""` 却 `citation_verified=True`（route 自赋布尔）——可审计性缺口：绑定到空快照的"已验证"。pg 存量腿因真值在场而未暴露。
- **零增补不降级**：见根因 4；即使实现修好捞回通道，"归属分支开启而增补为零"仍应显式 partial/ambiguous（含修改单请求未满足不得静默 complete），与改进组2"本路未确认≠全库缺失"的保守语义一致。
- 与改进组2正交：file_enum 跳身份门（评审已验收语义）；typed 晋升已停与本漏无关——005/local 用当前源码回放仍精确复现 1 条（表 1 行）。

## 已排除的假说（勿再当根因写）

- "语义检索没召回"：usable 已含两文档（各 verified+file_path，存量输入逐字段）。
- top-k/分页截断：members_total==processed，002 pagesize2 跨页 5/5；增补 SQL limit 参数（400）远大于行集且未触顶。
- 身份门误拒：file_enum 不走门；门相关反例均不涉及本腿。
- 归属路由码匹配/版本守卫缺陷：同一 route 同一行集在变体腿正确 emitted=2（9bb1/b423 title 含 `gb18466-2005` 复合 token，`05/2005` 版本守卫放行，均为真实实现执行）。
- 目录缺归属证据：两文档 title/name 证据存于 SHA 受保护的 gate-2 工件；`doc_type=standard`、self_code=None 逐字段 verbatim。
- rerank/精排缺席、预算耗尽、stale：四腿 enum `fail_stage=""`、coverage=complete、无预算告警（005 warning 仅"unknown metadata fields 存在"，与漏项无因果）。
- 第一轮晋升形状残留：当前代码回放（晋升已停）仍 1 条——失败不依赖旧形状。

## 最小实现建议（边界由主 agent 定；本组未动源码）

1. **归属增补与基集合同层同快照**：file_enum 完整集合的修改单/整合版捞回改为目录层（`env_rag.documents` 的 name/title 归属谓词或既有已验收归属判据的行内求值），与基集合共用同一 active snapshot、同一分页/stale 守卫；不再依赖（也不回填）任何 search_id。local 转换层的空 `pg.*` 字段保持原样——枚举责任不应伪装成"本路做过 PG 搜索"。
2. **增补进入判定与发布统计**：基集合与 related 集合的**去重并集**为最终集合；`attribution_branch=true` 时 `members_total/processed` 与 coverage 判定必须计入归属集合（零捞回且请求显式含修改单 → partial/ambiguous + 原因，禁静默 complete）。后两份绝不落回 top-k 通道。
3. **归属行引用必须绑当前 workspace+active snapshot**（修空快照；citation_verified 只由真实目录行复读支持）。
4. **发现对照不回填**：local 自己发现中已验证的归属候选可与枚举增补**交叉印证**（同 doc_id、同归属判据），但发现本身不构成目标授权（改进组2语义不回退）；不引入 gold/PG 其它腿输入。

### 成对验收（实现代次应覆盖，owning 入口）

- 含修改单完整并集：base 1 + related 2 = 3 交付、complete、引用逐条绑当前 workspace+active snapshot；
- 自身编号请求（同文档集、问题不含"含修改单"）：修改单不得混入（1 条）；
- 同号多版本全保留（001 形）：两版本均交付、独立引用；
- 年报/名称谓词分页（002 形 + 小 page_size）：跨页全集合、不依赖 top-k；
- 增补零结果 + 显式含修改单 → partial/ambiguous 且有原因，禁 complete-with-partial-set；
- 枚举中途 snapshot/stale/预算不足 → 不 complete（既有守卫形状保持）；
- local 不从 gold/pg 运行注入目标或补文档；本路零归属发现不伪报全库缺失。

## 证据工件与边界

- `diagnosis-replay.json`：六腿逐阶段（谓词与实参、归属调用参数与返回行数、enum 统计、发布 items、coverage、与存储一致性、gold 事后 missing/extra、模型 0）。
- `replays/`：六份发布态终报（answer-runtime-latest.json）。
- 证据标签：**第一轮真实已审失败**（存储 legs 与 inputs 逐字节）、**当前源码离线回放**（本驱动）、**构造参数对照**（searchid/pagesize 两变体，显式标注）；目录/search 行=存量产物读取（gate-2 replay/gold-source-proof verbatim，68a0 unknown_fields 存在性=存储 warning 佐证、字段名未入历史工件）。无任何现场数据库读取或冷生成冒充。
- 未覆盖旧运行/评分；未发布"真实召回提升"；未跑 505 全套（本组未改代码，交接 §交付与停止点允许）；`openspec validate --strict` 与工件校验、历史清单复算、敏感扫描见本目录其余文件。
- 停止点：诊断交付，主 agent 定实现边界；第二轮/6.2/6.3/Gate4 保持暂停；默认融合未切；file-004 待审、合成/单位/歧义类未纳入。
