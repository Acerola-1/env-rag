## Purpose

将 LightRAG 的语义发现能力与 PG 的条件、关键词和完整范围取证能力合并，在统一证据身份及版本约束下执行联合精排，并对枚举保留完整范围，向调用者公开兼容性与降级情况。

## ADDED Requirements

### Requirement: Public-interface compatibility

LightRAG 路径 SHALL 使用依赖发布包的公开接口，在接入前验证证据身份、字段和工作区兼容性。连接现有库 MUST 不产生未验证的自动迁移或写入；无法提供实际 chunk 身份时不得声称完成融合。

#### Scenario: Installed package cannot return usable chunk identities
- **WHEN** 发布包接口只提供无法可靠映射的显示引用
- **THEN** 记录兼容性失败，PG 独立路径可继续验证，融合不得猜测身份上线

### Requirement: Shared identity and joint reranking

两路候选 SHALL 按 workspace 和实际 chunk ID 去重，保留路径来源，并在合并后执行统一精排。文档版本对比 MUST 保留各目标版本独立证据，不能按相似文本跨版本合并。

#### Scenario: Both paths return the same chunk
- **WHEN** 两路返回同一 workspace 和快照下的同一 chunk
- **THEN** 精排只处理一次内容，同时保存两条召回路径的来源

### Requirement: Scope preservation after ranking

融合 SHALL 在确认目标范围后取回全部必要成员，不能因精排预算丢弃续表、条款尾部或比较中的一个目标版本。过长范围 MUST 分批处理或明确 partial。

#### Scenario: Reranker ranks a continuation low
- **WHEN** 续表属于已确认目标范围但精排分数较低
- **THEN** 系统仍保留该续表用于完整枚举

### Requirement: Visible degradation

精排、来源读取或单路检索失败 SHALL 显式记录失败阶段和降级状态。降级结果 MUST 不计作该路径或精排成功，且不得伪装完整目标范围已覆盖。

#### Scenario: Reranker authentication fails
- **WHEN** reranker 返回认证错误
- **THEN** 请求记录 degraded 和错误类型，评测不把回退顺序计为成功精排
