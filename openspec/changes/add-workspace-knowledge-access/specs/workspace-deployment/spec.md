# Workspace Deployment

## ADDED Requirements

### Requirement: Fixed workspace independent instances

部署 SHALL 提供 air 和 water 两个固定 workspace 的独立 LightRAG 服务、一个 Knowledge API 和共享 PG 检索能力。两实例 SHALL 共用已配置存储服务，各自管理连接池及工作目录；workspace override 的实际优先级 MUST 经验证。

#### Scenario: Backend override conflicts with instance configuration
- **WHEN** air 实例的后端 override 使 PG／向量／图谱有效空间不一致
- **THEN** 启动／健康检查拒绝就绪，不允许带错映射服务查询

### Requirement: Reproducible compatible runtime

部署 SHALL 固定实际 LightRAG 代码来源、依赖、embedding 模型与维度、存储接口及可读取解析路径。已有 macOS 容器方式 SHALL 优先沿用；Docker Compose 模板与现场实际验收 SHALL 分开报告。密钥 MUST 仅由本机运行配置注入，不能进入镜像、Git、网页或报告。

#### Scenario: Local customized checkout differs from installed package
- **WHEN** 网页依赖本地定制接口而部署使用发布包
- **THEN** 实施者先验证兼容性或显式固定已验证代码快照／只读来源，不静默混用且不修改相邻仓库

### Requirement: Reuse current model configuration

新实例和网关 SHALL 沿用当前 `deepseek-v4.1-flash`、`Qwen/Qwen3-Embedding-4B` 及实际启用的现有 reranker 配置。模型服务 SHALL 在入库前真实核验，失败 MUST 可见，不静默切换 HY3 或其它候选模型。

#### Scenario: DeepSeek service rejects a request
- **WHEN** 当前配置模型请求失败
- **THEN** 记录真实错误并定向恢复／报告阻碍，不能换模型或 fixture 宣称原模型通过

### Requirement: Configuration-only workspace extension

新增 workspace SHALL 通过注册后端映射／实例、启动、导入资料和配置角色授权完成，MUST NOT 修改核心检索代码或新增知识库名硬编码。

#### Scenario: Third workspace is added
- **WHEN** 操作者注册本轮第三库、导入一份真实资料并授予示例角色
- **THEN** 授权主体可真实查询，原读者无授权则拒绝，核心检索代码无改动

### Requirement: Restart and ownership-aware recovery

系统 SHALL 提供可重复启动、停止、健康检查、恢复和按所有权回滚的命令。实例重启 MUST 保留数据／索引／授权边界，不通过重置旧账本增加预算，清理 MUST NOT 删除已有 default 或非本轮数据。

#### Scenario: New instances are restarted
- **WHEN** air、water 和网关停止后重新启动
- **THEN** 原知识库及授权查询仍可用，无重复入库、无越权记录恢复，也不修改旧 default
