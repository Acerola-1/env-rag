# Workspace Access Control

## ADDED Requirements

### Requirement: Trusted principal authentication

Knowledge API SHALL 在任何知识读取前验证服务器可校验的主体凭据，得到用户、企业和角色。系统 MUST 拒绝未认证或无效凭据；客户端角色、企业参数和 CSRF token MUST NOT 被当作主体身份。

#### Scenario: Client forges a privileged role
- **WHEN** 大气读者提交角色为双库管理员或伪造企业参数
- **THEN** 系统仍按其已认证主体计算授权，不能访问 water，拒绝前不调用检索或模型

#### Scenario: Request lacks authentication
- **WHEN** 请求未携带合法主体凭据
- **THEN** 知识查询、记录和来源读取均拒绝，不返回知识内容

### Requirement: Server-owned workspace grants

系统 SHALL 将企业／角色映射到注册 workspace 集合，与 workspace 资料分类分离。角色名称 MUST 在企业范围内解释；新角色组合已有 workspace SHALL 不要求重新入库。请求包含未知／无权 workspace MUST 整体拒绝；all SHALL 只展开当前授权集合，禁止回退 default。

#### Scenario: Partially authorized selection
- **WHEN** 仅有 air 权限的主体请求 air 和 water
- **THEN** 整个请求拒绝，不能仅返回 air 冒充双库结果

#### Scenario: Combined role reuses existing libraries
- **WHEN** 为主体配置 air 和 water 的组合授权
- **THEN** 主体可访问两个现有知识库，无需复制资料或新建角色专用实例

### Requirement: Authorization on every read surface

查询、澄清、生成、chunk／文档、图谱证据、PDF／解析正文、记录列表／详情、导出和缓存读取 SHALL 使用同一授权上下文，并在使用已有对象前验证当前权限。外部 lookup MUST NOT 为错误诊断查询未授权 workspace 或泄漏其资料存在性。

#### Scenario: Cross-workspace source URL
- **WHEN** 大气主体提交真实水记录 ID 或 PDF／chunk URL
- **THEN** 系统拒绝读取，不返回水资料名称、正文或可下载文件

#### Scenario: Permission is revoked after retrieval
- **WHEN** 已生成双库记录的主体失去 water 权限
- **THEN** 旧记录读取、生成、导出和来源下载均拒绝，旧授权代次的缓存不可复用

### Requirement: Private records and authorization-aware caches

本轮查询记录 SHALL 默认只对创建者开放，绑定企业、workspace 集合、授权代次和来源快照。缓存键 MUST 包含主体／企业、授权代次、知识库与快照以及查询参数；系统 SHALL 在命中缓存之前执行授权。

#### Scenario: Another user guesses a record ID
- **WHEN** 另一用户即使拥有相同 workspace 权限也请求他人的私有记录
- **THEN** 系统返回统一不可访问响应，不泄漏记录内容

#### Scenario: Identical question under different grants
- **WHEN** 水读者询问与大气读者相同的问题和参数
- **THEN** 系统不得返回另一主体的答案、记录、引用或缓存证据

### Requirement: Internal service boundary

LightRAG 实例的查询、文件、图谱和管理接口 SHALL 仅供授权内部调用；客户端 MUST NOT 能通过直接实例端口绕过 Knowledge API。普通读者凭据 MUST NOT 获得入库、删除或配置写权限。

#### Scenario: Reader calls instance management endpoint
- **WHEN** 普通读者绕过网关直接访问实例的查询或管理端点
- **THEN** 网络／实例认证拒绝或接口无公开可达路径，不发生检索或管理操作
