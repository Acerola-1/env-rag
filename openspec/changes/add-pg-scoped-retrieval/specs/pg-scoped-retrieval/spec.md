## Purpose

提供基于 PostgreSQL 的文档条件定位、中文关键词候选和完整目标范围读取，让文件清单、正文条目及表格条目均能从明确范围内的原始证据产生，并向调用者准确报告覆盖程度和来源。

## ADDED Requirements

### Requirement: Exact document constraints

检索 SHALL 规范化并匹配文档自身编号，遵守指定 workspace、版本和已确认条件。不存在或歧义的目标 MUST 显式返回缺失或候选待确认状态，不自动替换为近似编号或不同年份。

#### Scenario: Requested version is absent
- **WHEN** 用户指定的标准版本未入库
- **THEN** 系统说明目标缺失，不用另一个版本回答该版本的问题

### Requirement: Consistent Chinese lexical retrieval

关键词检索 SHALL 在索引和查询两侧使用一致且版本化的中文处理规则，返回实际证据身份和排序信息。规则变更 MUST 能识别旧索引并要求重建；查询放宽不得移除明确的版本和工作区约束。

#### Scenario: Long Chinese question contains a known concept
- **WHEN** 查询包含“医疗机构污水”的已知中文概念及提问用语
- **THEN** 相关概念能用于词项匹配，而不是依赖整句与正文逐字相同

### Requirement: Complete bounded reading

目标范围确认后，系统 SHALL 读取全部有序成员及必要续页，范围覆盖不受候选 top-k 限制。超时、缺片或预算不足 MUST 返回部分覆盖与未完成范围，不静默截断。

#### Scenario: Scope exceeds candidate budget
- **WHEN** 目标章节的成员数多于候选 top-k
- **THEN** 系统分批读完目标范围，不把 top-k 的命中数当作全部成员数

#### Scenario: Continuation fragment is missing
- **WHEN** 逻辑表的续表关系或成员无法核验
- **THEN** 结果标记 partial 或 ambiguous，不根据序号猜测缺失条目

### Requirement: Enumeration across carriers

系统 SHALL 支持文件、正文和表格枚举，每项附可验证来源。文件枚举声明库内范围、匹配条件、未知元数据和分页覆盖；正文按完整范围抽取；表格保留合并单元格、单位及必要注释，禁止无依据补项。

#### Scenario: File list requires multiple pages
- **WHEN** 满足明确条件的文件超过单页容量
- **THEN** 读取全部匹配页并报告总量，同时不把匹配集合宣称为所有语义相关文件

#### Scenario: Definition enumerates places in prose
- **WHEN** 目标条款以正文而非表格列出场所
- **THEN** 从完整条款提取各项，每项引用该条款原文

### Requirement: Explicit coverage and verifiable citations

结果 SHALL 记录来源快照、目标范围、已读成员、条目原文引用与 complete／partial／ambiguous／stale 状态。complete MUST 仅用于已验证目标范围覆盖；不能表示原 PDF 无解析遗漏或全库无语义漏召回。

#### Scenario: Extraction budget ends early
- **WHEN** 已定位范围尚未全部抽取而预算耗尽
- **THEN** 返回已完成项、处理量及剩余范围，覆盖状态为 partial
