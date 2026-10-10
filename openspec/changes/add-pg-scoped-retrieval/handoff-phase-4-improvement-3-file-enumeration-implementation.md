# 改进组3：目录层完整文件并集（实施交接）

诊断已通过。**可直接开始本组代码改动，无需再次询问授权。** 0真实网络/数据库/模型/embedding/rerank请求、0写库/探测；不跑第二轮。诊断目录、已审运行/评分、改进组1/2、全部旧冻结/gold/.env/配置锚保持。

## 已确认缺陷

file-005/local已有两份修改单发现，但基础目录枚举仅1份；归属增补错误依赖search_documents+空search_id，结果0；统计仅基础1/1仍complete。补search_id的构造变体能捞回2份，却生成空snapshot引用并verified。修复责任在完整文件枚举，不伪装成local检索召回增益。

## 允许改动

默认`search/expand.py`文件枚举编排、`enumerate_/doc_enum.py`目录读取/集合守卫；必要时`answer.py`的文件发布/coverage/目录身份透传。可以在`search/query.py`或现有目录公共模块抽取已验收的**行内编号/版本归属判断**供复用，但不得更改原关键词检索路由行为、扩大候选或重建索引。evaluation.py/local_adapter/fusion/rerank、正文引用和模型策略不改；超范围先给根因。

## 一次性实现合同

### 1. 同层、同快照、完整读取

- 基础集合仍由完整强谓词/分页读取；显式归属请求的相关集合改走env_rag.documents目录元数据（name/title等已验收依据），同workspace、同active catalog snapshot、同source指纹。search_id空或有值都不影响这一步，不填入借来的PG索引身份。
- 可用受预算的目录全元数据扫描+应用侧已验收行内归属筛选，或等价可验证SQL；内部扫描不是把全库当答案。所有页都必须处理，不能LIMIT40/400或候选top-k限制related全集。读取预算达到上限显式partial，不能先截断再报complete。
- 若分两次读取，必须核对同一snapshot，且整个base+related→最终发布窗口有后置守卫；active切换/匹配内容变化/来源变化不得混代。已有分页token只保护base时不能充作related/最终并集的内容证明。

### 2. 归属不伪造身份、不串版本

- 复用已验收的显式请求谓词与doc自身name/title编号证据，不使用正文引用的编号、不凭候选标签或gold确认。不把unknown self_code写成标准编号。
- 多编号/年份按每个(code,version)分支分别确认再OR并集，不能把A标准的码与B标准的年份合成命中；无版本合同保留所有实际匹配版本，2/4位年份规范沿用已有规则。
- 自身编号请求明确关闭归属放宽。版本不符、相似前缀编号、无足够归属依据记录排除/未确认；不从别路运行/历史答案补集合。
- 显式含修改单/相关文件时，普通标准本体不能被简单算作相关项来假满足请求。相关项若已属于基集且有真实归属依据，可同时属于base与related；related匹配数与实际新增数必须分开。

### 3. 并集、引用和完整性同一份来源

- 以(workspace,snapshot,doc_id)去重并集，保留base/related两种匹配依据、原canonical元数据与引用；重叠项一份发布、来源路径不丢。
- trace与最终发布统计分列base_total/processed、related_total/processed、overlap、union_total/processed及分支完成状态；已有members_total/processed代表**最终匹配并集**，不能继续1/1掩盖实际发布3份。token绑定最终输出字段及归属依据。
- 引用workspace/doc_id/catalog snapshot必须非空且与真实读取一致，catalog_snapshot_id/source_snapshot_id从目录观测值填入、分开记录来源，不冒充PG搜索。verified由真实目录行身份/字段核对支持，不自赋布尔以修复空引用。
- base和related任一读取失败/stale/预算不足/归属未确认，最终不得complete。显式含修改单但related匹配0时保守partial/ambiguous，记录“未确认相关文件”与实际已完成读取情况，不伪报全库缺失。
- **attribution_added=0不等于related_matches=0**：related已在base去重后新增0，若归属匹配实际非零且读取完整，允许complete。不要通过无条件“新增0→partial”伤害完整并集。
- 原始discovery_candidates/usable保留为发现审计，不从枚举并集回填召回；已发现相关文件可交叉对账但不授权目标，也不是完整并集的分母。

## 必要验收（owning入口，先红后绿）

1. 当前四原样本+两个诊断参数对照经真实answer/枚举链路回放：005/local空search_id与PG同题各完整3份；search_id有/无/不相关值均不改变目录枚举结果，不能通过填真search_id修测试。local original inputs/gold仅事后核对。
2. 005三份引用逐条非空且当前workspace/snapshot/doc匹配；最终members_total=processed=3，base/related/union可独立复算，未知self_code如实保留。
3. 同数据“自身编号”只交付标准本体；同号多版本保留2份；年报page_size=2跨页仍5/5；发现top-k降至1或发现漏修改单，最终目录集合仍完整，不回填发现召回。
4. 显式归属实际零匹配→告警且不complete；另构造合法base/related重叠、related非零但新增0的正例→去重集合完整并可complete。不得用gold集合硬编码或全拒related达标。
5. 多(code,version)分支正负成对，防交叉年份、前缀相似码与错误版本；修改单归属依据来自目录name/title，正文提及不够。
6. related跨页中途变化、最后一页后active替换、同计数内容变化、related预算中止均非complete；base完整不能覆盖related失败，部分项及进度/未处理信息留可审。均用fake元数据/连接构造，不写现场库。
7. 改进组1/2及原目录/枚举/搜索/文件/预算/终态冻结保持。旧非冻结fake可补必要只读SQL/元数据响应，不改变既有语义或放宽断言；旧冻结文件不动。

先相关矩阵与必要回归，通过后一次全工程、35评分冻结及Ruff工作面/strict/diff/敏感扫描。历史冻结lint/格式与r3评分细类标签继续非阻断，不改旧目录、不更新旧锚、不加SHA豁免。

## 交付停止点

新目录`reports/pg-retrieval/phase-4-improvement-3/`：根因与改动说明、源码SHA前后、矩阵、目录并集逐项对账及引用独立回读、分支统计/预算/stale证据、原失败与新离线观察分列、历史清单复算。证据标存量元数据/fake目录/构造/离线owning，不宣称现场验证或真实增益。

诊断目录原样保留；不修file-004待审、合成/单位/其他歧义，不切默认策略，不发付费请求、不运行123/246腿，不勾6.2/6.3/Gate4。提交后停主agent工程复审；下次真实运行的配置锚由主agent另建。
