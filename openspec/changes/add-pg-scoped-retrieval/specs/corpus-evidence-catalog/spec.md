## Purpose

为环境知识库提供可审计的语料边界和原文定位目录，使检索结果能够追溯到正确工作区、文档及解析分块快照，并区分完整、缺失、歧义与过期的证据关系，支持后续独立检索和融合。

## ADDED Requirements

### Requirement: Auditable corpus scope

系统 SHALL 提供文档、解析产物、chunks 和处理状态的对应清单，区分有效、缺失、失败和未确认记录，记录统计时刻和输入指纹。审计 MUST 保持已有语料及存储结构不变，敏感连接凭据不得进入报告。

#### Scenario: Parsed artifact has no stored chunks
- **WHEN** 发现解析产物没有对应的可读 chunks
- **THEN** 清单标记缺失及已知依据，不计入可检索文档，不自动重新导入

#### Scenario: Status rows do not equal searchable documents
- **WHEN** 处理状态表同时包含 processed 和 failed 记录
- **THEN** 分别统计状态记录和有可读 chunks 的文档，以身份对应结果声明有效语料范围

### Requirement: Evidence identity and snapshot isolation

目录 SHALL 使用明确的 workspace、实际文档和 chunk 身份及来源快照，验证原始哈希的含义。系统 MUST 在解析或分块来源变化时报告过期关系，不允许旧定位指向新内容而声称验证通过。

#### Scenario: Same chunk ID in two workspaces
- **WHEN** 两个 workspace 存在相同 chunk ID
- **THEN** 它们被视为不同证据，查询只读取指定 workspace 的匹配快照

#### Scenario: Source changes after catalog build
- **WHEN** 来源指纹与已发布目录快照不一致
- **THEN** 系统返回 stale 状态并要求重建，不返回 complete

### Requirement: Metadata with provenance

文档目录 SHALL 区分自身编号与引用编号，分开记录发布、实施和统计期间，并为字段保存来源及置信状态。无法确定的值 MUST 保留 unknown，不根据最新年份推断现行效力。

#### Scenario: Standard cites another standard
- **WHEN** 文档正文引用其他标准编号
- **THEN** 引用编号不能使该文档匹配“文档自身编号”等值查询

### Requirement: Verifiable many-to-many structure mapping

系统 SHALL 保存章节／条款／逻辑表格的有序原始单元及其到 chunks 的多对多关系，附原始定位和匹配依据。未确认关系 MUST 标记歧义或部分覆盖；同表号不得跨文档或章节自动合并。

#### Scenario: Two table fragments share one chunk
- **WHEN** 一张逻辑表的两个物理片段位于同一个 chunk
- **THEN** 两个片段均被保留并按原始顺序读取，chunk 去重不丢失表格片段

#### Scenario: One block spans several chunks
- **WHEN** 一个原始 block 分布在多个 chunks
- **THEN** 目录保留全部映射，单个命中不能被认定为完整条款

### Requirement: Rebuildable catalog publication

目录和搜索视图 SHALL 支持同输入幂等构建，只有引用核验完成的 build 才可发布；失败构建 MUST 保留失败状态且不替换可用活动版本。清理仅能作用于本应用拥有的派生对象。

#### Scenario: Build fails before publication
- **WHEN** 构建出现未解决引用或写入失败
- **THEN** 原活动 build 保持可用，新 build 不作为完整版本查询
