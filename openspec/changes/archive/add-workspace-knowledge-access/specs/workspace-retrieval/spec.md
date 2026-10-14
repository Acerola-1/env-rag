# Workspace Retrieval

## ADDED Requirements

### Requirement: Explicit scoped retrieval context

PG 和 LightRAG 查询 SHALL 使用授权后的显式 workspace 上下文。原文、候选、范围成员、来源和快照 SHALL 保留其 workspace 身份；新 workspace MUST 使用已验证的 PG／向量／图谱有效映射，禁止复用旧 default 空间作为回退。

#### Scenario: Air query finds water-only terminology
- **WHEN** air 主体查询只存在于 water 资料的目标
- **THEN** 系统在 air 中返回缺失／无证据或合法的相关证据，不能读 water 或 default 补答

### Requirement: Independent workspace source and build identity

系统 SHALL 按每个 workspace 的登记资料及解析产物计算 source、catalog、search 身份和 stale 状态。相同文档被复制到不同 workspace 时，构建身份／主键 MUST 不冲突。目标库变化 MUST NOT 使未变化的另一库失效。

#### Scenario: Identical corpus is built in two workspaces
- **WHEN** air 和 water 各自构建包含同一份真实资料的目录和搜索索引
- **THEN** 两库均可发布 active 构建，无全局 search_id 冲突或互相覆盖

#### Scenario: One workspace is updated
- **WHEN** water 新增或更新资料并重新构建索引
- **THEN** air 的原有身份与查询保持可用，water 的旧缓存／索引身份显式失效

### Requirement: Authorized multi-workspace evidence fusion

系统 SHALL 分别检索请求中所有已授权 workspace 后合并证据，并最多进行一次答案生成。原始去重身份 SHALL 包含 workspace 和真实文档／chunk ID；合并已证明同版本同内容的展示项 SHALL 保留全部合法来源。

#### Scenario: Same chunk identifier exists in both libraries
- **WHEN** 双库结果有相同 chunk ID 的两个来源
- **THEN** 来源互不覆盖；若合并重复内容，所有授权来源仍可定位，不同版本不得误合并

#### Scenario: Combined question needs both domains
- **WHEN** 双库主体提出同时需要大气和水资料的问题
- **THEN** 系统分别取得两库证据并统一生成，不拼接两份已生成答案冒充融合

### Requirement: Preserve retrieval mode and complete range contracts

系统 SHALL 保留 PG、LightRAG naive／local／global／hybrid／mix 及对应 PG 组合的实际模式与证据。已确认范围 SHALL 完整有序读取，不由 top-k 定义全集；引用 SHALL 绑定实际授权来源与版本，生成 MUST NOT 升级不完整覆盖。

#### Scenario: Confirmed table exceeds top-k
- **WHEN** 已确认表格范围成员超过发现 top-k
- **THEN** 系统读取全部可验证成员，缺续片时保留 partial／ambiguous，不截断后标 complete

### Requirement: Visible partial service failure

单库或一路服务失败 SHALL 明确报告失败 workspace／模式与覆盖状态。合法可用证据可返回，但系统 MUST NOT 静默改查 default、遗漏失败库或将权限拒绝降级为成功。

#### Scenario: Water instance is unavailable
- **WHEN** 双库查询中 water 实例不可用而 air 可用
- **THEN** 系统标明 water 失败和结果不完整，不能宣称两个知识库均查询成功
