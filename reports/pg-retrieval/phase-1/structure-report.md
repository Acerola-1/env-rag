# Phase 1 结构目录报告（tasks 2.1–2.6，S1–S7 补正后）

生成时间：2026-10-05（第二轮）。active run=`c15c741742394320`，recipe=`phase-1-v4-single-active-snapshot-prune`，
snapshot_id=`4919b3938ad93747`。来源快照指纹与 Gate 0 冻结值一致
（`95f7791fd84171ab…`）。本轮原提交报告与manifest保留在phase-1-review/v4-submitted-*；当前数据与审查记录已更新。
本报告只覆盖结构目录；第 3 组枚举闭环、Gate 1 未开始。

## 0. 补正对照（S1–S7 → 修复与证据）

| 发现 | 修复 | 行为反例/实测证据 |
|---|---|---|
| S1 所有权 | `validate_schema_name` 只接受 `env_rag`（public／系统 schema／注入名在任何 SQL 前拒绝）；`teardown` 先查 schemata 存在性、再查 schema 内无外来表，两道检查后才 DROP；DDL 全部硬编码 env_rag（无参数替换） | fixture：`validate_schema_name("public")` 等抛错且 `conn.executed==[]`；含外来表的 schema teardown 抛 "ownership cannot be proven" 且无 DROP 语句；真实库执行 teardown（所有权核验通过）→ 全新 migrate → 重跑 0 条 DDL，public 计数不变 |
| S2 层级范围 | scopes 改为层级模型：父范围聚合全部后代叶范围成员（源顺序去重），缺失的中间父标题自动生成聚合范围（note 注明）；`persist_span_requirements` 把大 block 范围持久化为 `requires_span`（scopes.confirm_status + source_units.requires_span），不再是纯 warning | 实测：GB 3095 第 4 章成员=引言+4.1 块+4.2 块（排除第 5 章）；WHO Annex 4（373,295 字符/273 chunks）状态=requires_span，note 含"不得把整个 block 引用跨度当作完整范围"；GB 18466 4.1 单 block 跨 chunk 保持 confirmed（未被错误"修坏"）；真实 GB4915 修改单（4.2.1.1 无 4.2 标题）自动生成聚合父范围 |
| S3 元数据 | 标题循环跳过通用行（含空格间隔版）、"部分代替/代替…"行、纯编号行（含 2 位年份 GB 14554—93）；自身编号只取封面无限定词（代替/依据/引用/按照/参照/执行/参见）的独立编号行或"标准编号："声明；引用-only 文档 self_code=unknown；日期只在封面 25 行窗口内分别匹配；provenance 每字段带 line/quote/confidence；stats_period 列入 unknown | 实测：GB 18466 标题=医疗机构水污染物排放标准（不再误取"部分代替 GB 8978—1996"）、self=GB18466/2005；air-06 标题=恶臭污染物排放标准、self=GB14554/93；water-14（代替GB 4287—2012…行）标题正确；全库 0 个通用标题、0 个"代替"标题（首轮 1 个已消除）；标准文档 self_code 覆盖 52/64（其余 unknown 并注明"引用了其他标准但未声明自身编号"） |
| S4 构建守卫 | 产物指纹在快照前与 `_derive` 后各取一次，不一致抛 `SourceChangedError` 且不发布；`_derive` 遇无解析产物文档直接抛 `BuildVerificationError`（不静默跳过）；`_verify` 新增 link→chunk 归属校验（chunk 必须存在于同一快照、同 doc/workspace） | fixture：无产物文档 → "no readable parsed source" 拒绝发布；链接到未知 chunk → "links_to_unknown_chunks=1" 阻止发布；真实库构建全程 public 计数不变 |
| S5 构建身份 | snapshot_id=sha256(源指纹+RECIPE_ID)；发布时删除同 workspace 其他 snapshot 的目录行（单活动快照，修复 v3 重构后计数翻倍 442 的问题）；corpus_runs 保存 recipe_id+snapshot_id；发布用 `pg_advisory_xact_lock` 串行化 + `uq_cat_runs_active` 部分唯一索引（每 workspace 至多一个 active）；失败 run 保留 status=failed 供重试 | 实测教训：修复元数据算法后忘记升版 recipe → 构建被幂等跳过（复现了 S5 场景）→ 升版为 v3 后真正重建（新 snapshot a28f182e…）；测试断言 recipe 版本参与 build identity |
| S6 适配器 | 全部身份按组合键 (workspace,id) 查询，先查组合、miss 后才做跨 workspace 诊断（同 id 多 workspace 各自正确）；`read_chunks_ordered` 单连接单 REPEATABLE READ 快照返回 total+校验+页行，返回 `snapshot_epoch`，续页 epoch 不符抛 `SourceChangedError`；序号校验含 NULL/负数、重复、0..n-1 缺口 | fixture：同 id 双 workspace 双双命中；composite miss+他处存在→CrossWorkspaceError；gap [0,1,3]→OrderAnomalyError；epoch 变化→SourceChangedError；实测 GB8978 分页无重叠（保持自首轮） |
| S7 表格映射 | 内联 table 依据改为严格解析 `<table id="…">` 元素属性完整值（`extract_table_ids`）：正文提及、前缀相似 id、畸形片段都不产生链接 | fixture：纯文字提及/`<table id="tb-…-00011">`（前缀相似）/畸形片段 → 0 条 inline_table_id；真实单/双引号属性正确关联（air-03 chunk-002 实测 2 条真实链接保留） |

## 1. 迁移与所有权（task 2.1）

`uv run env-rag-final catalog-migrate`（`src/env_rag_final/catalog/schema.py`）。对象清单：`env_rag` 内
`corpus_runs`（含 recipe_id/snapshot_id）、`documents`、`source_units`（含 requires_span）、
`unit_chunk_links`、`scopes`（含 parent_scope_id、requires_span 状态）、`scope_units`、`schema_migrations`。
迁移账本在应用 schema 内；重复运行 0 条 DDL。回退 `teardown` 双重核验（名称+外来表）后才 DROP，
真实库验证通过。**本库只支持 env_rag 一个 schema 名**，不支持任意 --schema 参数（已从 CLI 移除）。

## 2. 只读适配器（task 2.2）

`source.py`：组合键身份、单会话一致快照分页（epoch 防续页期间来源变化）、序号缺口校验、
count(*) 总数。GB 8978 实测 total=24、两页无重叠。

## 3. 目录与映射（tasks 2.3–2.5）

snapshot 4919b3938ad93747（recipe v4）：221 documents、12,269 units、16,783 links
（sidecar_ref 13,227 + inline_table_id 3,556）、**1,970 scopes / 14,557 scope_units**（层级聚合后）。
- requires_span scope 4 个（WHO Annex 3/4/6/9 大 block），涉及 unit 已标 requires_span=true。
- GB 3095 第 4 章成员=3 blocks（引言+4.1+4.2）；第 5 章不在内。
- 14 个空 sidecar chunk 仍无 sidecar_ref 链接（真实缺口）；inline 依据只来自真实 `<table id>` 元素。

## 4. 构建与发布（task 2.6）

流程：产物指纹(前) → REPEATABLE READ 快照 → 冻结指纹比对 → _derive → 产物指纹(后) →
(source+recipe) 幂等检查 → 写入 → 完整性+归属校验 → advisory lock 串行化发布。
失败 run（修复过程中 3 个）只保留 failed 状态行；active 唯一；旧 active 正常退役。
`catalog-stale` 返回 current。历史原文能力边界不变：目录只存 locator，来源/配方变化即 stale。

## 5. 验证与校验

- `uv run pytest tests/`：**63 项**通过（含 S5 单活动快照修剪回归）（16 项 Phase 0 fixture + 47 项 Phase 1，含 S1–S7 全部行为反例
  与 3 个真实语料案例：GB 18466 部分代替、air-06 两位年份、water-14 无空格代替行）。
- Ruff 检查/格式、`openspec validate --strict`、`git diff --check` 全部通过。
- 全部操作后 public 八张表计数与 Gate 0 冻结值逐一相同。

## 6. 已知边界

- 2 位年份 self_code_version（GB14554/93、GB11607/89）保留原始形态，规范化策略留给 Phase 2 编号查询时统一。
- 12 份标准文档 self_code=unknown（公告/修改单类无标准编号行），unknown_fields 如实记录。
- 逻辑表 scope（logical_table）与续表合并属 task 3.1；本阶段 scopes 只有 chapter/clause。
- 空 sidecar、部分引用、requires_span 作为显式输入带入第 3 组。

停在结构检查点：等待主 agent 复审；第 3 组与 Gate 1 未动。

## 7. 主 agent 复审补正（2026-10-05）

原提交报告作为 v4-submitted-structure-report.md 保留在 phase-1-review 中；当前计数来自只读现场查询。
分页 epoch 已改为文档及 chunks 的内容摘要；未变化的实际 GB8978 连续两页成功且 epoch 相同。
构建全流程使用每 workspace 会话锁，active 切换与旧快照目录修剪放在同一事务中；失败回滚保留旧 active 及其目录。
旧目录行会被修剪，retired run 仅保留账本，不能直接切回已删除旧目录；回退须重建目标配方或关闭新路径。
新增3项行为测试覆盖 token 内容变化、发布失败回滚及并发 staging 串行化，合计63项；发布失败测试为隔离模型，不冒充真实生产故障注入。
本轮主 agent 只读验证现有v4目录，没有再次teardown、migrate或build。复审只允许进入第3组，不表示完整枚举或问答质量已通过。
