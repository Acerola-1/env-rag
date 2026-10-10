# 改进组3：目录层完整文件并集 — 实施报告

交接：`handoff-phase-4-improvement-3-file-enumeration-implementation.md`。全程 0 真实网络/模型/数据库/写库/探测；不跑第二轮；诊断目录、已审运行/评分、改进组1/2、全部旧冻结/gold/.env/配置锚逐字节保持。

## 一句话结论

**归属捞回与基集合同层同快照，并集统一统计/引用/完整性**：file-enum-005/local 的原存储输入（`search_id=""` 依旧）在当前源码离线 owning 回放中交付完整 3 份（base 1 + 相关 2），三份引用全部绑定真实 workspace+active snapshot 并经独立目录行复读背书；填入真实 search_id 的变体腿与空值腿结果**逐字段相同**——修复不靠、也不可能靠 PG 索引身份；pg 对照 3 份保持，001 两版本 2 份、002 年报 5 份（含 page_size=2 跨页变体）全部保持；全工程 **523**、改进组1/2 冻结 **18**、评分冻结 **35**、评分自测 6+10+12/13（同一细类标签观察，非阻断）、新矩阵 **18/18**。

## 改动（允许面内）

| 文件 | 内容 |
|---|---|
| `search/query.py` | 抽取出可复用的行内判据原语 `own_identity_tokens` / `attribution_judgement`：逐 (code,version) **分支**判定 name/title 携带——`attributed`（携带且目录身份不满足该分支=真相关证据）/`canonical`（标准本体自身，永不作为相关证据）/`version_mismatch`/`stated_conflict`（版本不符不串号）/`similar_prefix`（近似前缀只审计不归属）。`_doc_attribution_route` 本体控制流与输出**逐字不变**，仅 name/title token 计算改用同一原语（关键词检索路由行为未改）。 |
| `enumerate_/doc_enum.py` | 新 `enumerate_attributed_documents`：**同 workspace、同 active catalog snapshot、同 source 指纹**的目录元数据全量分页扫描（`env_rag.documents`，不读任何 search 层，填入的引用/citation 来自扫描行自身），匹配集内容 token（含逐分支判据）逐页+末页后+返回前复核；预算 `max_pages*page_size` 达到即显式 partial/BUDGET——绝不截断后 complete。`verify_publication_snapshot`：base+related 合并之后的发布窗口后置守卫（active 切换/来源变化→stale）。`publish_token`：最终发布并集（含来源路径与归属判据）的内容 token。 |
| `search/expand.py` | `_expand_documents` 归属段重写：相关集合改由目录层扫描承担（`search_id` 有无值均不参与）；(workspace,snapshot,doc_id) **去重并集**——重叠项一份发布、`sources` 双路径保留；trace 分列 `base_total/processed/coverage`、`related_total/processed/matches/evidence/coverage`、`overlap_evidence/overlap_canonical`、`attribution_added`（新增数与匹配数分开）、`union_*`、`related_excluded`（版本冲突/前缀近似逐条审计）、`related_request_note`；`members_total/processed` 改为**最终并集**语义；组合覆盖=最劣分支，显式含修改单而相关证据 0 → 至少 partial（“未确认相关文件”，不是全库缺失断言）；**证据非零+新增 0（去重重叠）仍可 complete**；无编号可归属的相关请求→显式 ambiguous 拒发布相关集。 |
| `answer.py` | `_render_with_docs` file_enum 分支：发布条目逐条经同一守卫连接**独立复读目录行**（`_DOC_META_SQL`：存在、workspace/snapshot/doc_id/doc_name 一致）才保持 `citation_verified`，否则降 False+flag——自赋布尔与空快照引用从此无法进入 complete；`attribution` 标记识别目录层来源。 |
| `tests/test_phase4_improvement3_union_enumeration.py` | 新矩阵 18 项（下节）。 |
| `tests/test_gate2_acceptance.py / _rereview.py` | 旧非冻结 fake 仅补发布守卫的只读 `corpus_runs` 响应（原搜索状态响应逐字保留；未知 SQL 仍 raise）——既有断言零改动零放宽。 |

evaluation.py **未动**（`a42d5c68` 与验收态相同）；LocalCandidateAdapter/fusion/rerank/正文表格验证器/目录 schema/提示词/模型策略未动；未新写 GB 正则（复用 normalize_code/_version_matches/tokenizer 渲染）。

## 验收对应（交接 §必要验收）

1. **四原样本+两变体经真实 answer/枚举链回放**（`union-reconcile.json`+6 份终态）：005/local 空 search_id → 3 份 complete、missing/extra 0；005/pg → 3 份保持；**search_id 空/真值/无关值三形结果逐字段相同**，且六腿 search_documents 读取次数=0（fake 对任何搜索层 SQL 直接 raise——填真 search_id 修不了任何东西，也无法再让它参与）。local 输入=自身存储 fused，PG 数据零注入，gold 仅事后。
2. **引用逐项**：005 三条 citation 全部 `kind=catalog_row`、workspace=default、snapshot=`4919b3938ad93747`、doc_id 匹配、`citation_verified+reverified=True`（answer 独立复读）；members_total=processed=3；base(1/1)/related(3 matched、2 evidence)/overlap_canonical=[本体] 可从问题分支×目录身份独立复算；`self_code=None` 如实保留、未冒认编号。
3. **自身编号只交付本体**（相关通道关闭）；**同号多版本 2 份全保**；**年报 page_size=2 跨页 5/5**；发现里已有相关文档不双计、发现 top-k 缺漏不影响目录并集（`_run_leg` 场景：usable 单块/两块均 3 份）。
4. **显式归属实际零证据→partial** + stage `related_request_note` 记录"未确认相关文件/非全库缺失"；**合法重叠正例**（2 位年号目录行同时满足基谓词与携带判据）→ related 非零、added 0、complete 保持；无编号相关请求→ambiguous 拒归属；无 gold 硬编码、无全拒 related。
5. **多分支成对**：GB3095-2012×GB8978-1996 交叉年份被 stated 冲突守卫拒绝入 excluded；前缀相似（GB1846 vs GB18466）不归属仅审计；归属判据只读 name/title 行内字段（正文引用不参与——判据函数根本不读正文）。
6. **失败模式全部非 complete**（真实守卫代码在 fake 元数据上）：related 预算截断→partial/BUDGET；末页后 active 替换→stale；同计数内容变化→内容 token 捕获 stale；base complete 不能掩盖 related stale（组合覆盖=最劣）；发布窗口后置守卫入 trace（`publication_guard`）；discovery 列表保持原审计不被并集回填。
7. **回归**：全工程 **523**（505+18 新）、改进组1 冻结 9+3、改进组2 冻结 6+自有 26、评分冻结 35、自测 6+10+12/13（r3 同一 `unsupported_declarations` 细类标签、整题 FAIL 不变、未动旧目录/旧锚）——旧冻结文件零改动。

## 先红后绿（如实记录）

红相=改进组3诊断代次已在**改动前代码**（answer `14c9673b`）上对同一批存储输入完成复现并作为已验收存量工件保留（`phase-4-improvement-3-diagnosis/diagnosis-replay.json`：005/local 1 条、`attribution_route_calls` 实参 `search_id_arg=""`、complete）——本组新矩阵的失败面即该已验收红相；新矩阵本身在改动后 18/18。**流程失误如实记录**：本组编辑前未捕获 `expand.py/query.py/doc_enum.py` 与两个旧测试文件的 before SHA（sha-before-after.json 中逐文件标注；answer/evaluation 的 before 有两处既有验收记录支撑），后值已全量记录、历史清单复算不受影响。

## 离线观察分列与边界

- 第一轮真实已审失败：存储 `legs/r1/local/file-enum-005/` 终报（1 条、complete）——未被改写。
- 当前源码离线回放：本目录 6 份终报+对账（3 份、complete、附加的分支统计为新发布形状）；相对第一轮的差异**仅是离线观察**（存储输入过新代码），不发布真实召回/质量增益。
- 构造：矩阵合成目录行（显式声明的 fixture 行）、变体腿（存储 fused 逐字段复制仅改 pg.search_id / 强制 page_size）；catalog 大集合=gate-2 SHA 受保护存量 221 行 verbatim（存量产物读取）；68a0 unknown_fields 存在性=存储 warning 佐证。
- 未修 file-004 待审、合成/单位/歧义类；未切默认策略；未跑 123/246 腿；未勾 6.2/6.3/Gate4；配置锚未自改（下次真实运行前由主 agent 另建）。

## 停止点

提交后停主 agent 工程复审。第二轮保持暂停。
