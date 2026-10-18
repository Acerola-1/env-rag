## ADDED Requirements

### Requirement: 显式远程授权与local独立
Knowledge API SHALL 在启动时明确选择local或remote，remote仅使用IAM身份及有效许可，local SHALL 不依赖IAM网络。

#### Scenario: remote不可用
- **WHEN** 已成功主体再次核验遇到IAM网络或协议故障
- **THEN** 返回503且新检索/模型/文件调用为0，不读取local账号兜底

#### Scenario: 明确local
- **WHEN** 使用local配置启动
- **THEN** 原注册表和既有local断言保持，IAM请求数为0

### Requirement: 人类与机器严格分型
消费方 MUST 验证knowledge受众、issuer、schema和主体一致性；机器 SHALL 使用固定企业及凭据字段而不伪造人类会话/四修订。

#### Scenario: 合法单库机器
- **WHEN** IAM返回有效service_account且有当前企业air精确读码
- **THEN** 可访问显式映射的air库，无人类membership/session

#### Scenario: 不合法的成功HTTP
- **WHEN** HTTP200包含错受众、主体或非法修订字段
- **THEN** 严格拒绝且不访问任何资料后端

### Requirement: 显式资源映射与完整选择
Knowledge API SHALL 根据实时精确读码、tenant/resource/workspace映射与技术就绪集合授权，MUST NOT 根据local角色或模糊前缀扩大范围。

#### Scenario: 全部知识库选择
- **WHEN** 请求all
- **THEN** 只展开当前有权且就绪的库，无权库不出现在结果或枚举信息中

#### Scenario: 混合显式请求
- **WHEN** 请求包含一个合法库和一个无权或未知库
- **THEN** 整体拒绝，下游调用0，不静默裁剪或回退default

### Requirement: 每个数据出口实时复核
网关 SHALL 在新检索、生成、重试、缓存命中、记录/导出和来源文件读取前核验，并在回送/落盘前确保原上下文仍有效。

#### Scenario: 缓存后回收
- **WHEN** 相同请求已有缓存但IAM权限随后回收
- **THEN** 缓存不产生许可，读取拒绝且不泄漏旧内容

#### Scenario: 生成期间切企业
- **WHEN** 生成在旧上下文启动而输出前用户切企业或授权失效
- **THEN** 不把结果回送或写入新企业，已在飞请求不被描述为可追溯撤回

### Requirement: 保持真实workspace与资料归属
remote接入 MUST 保留原技术namespace、chunk/doc/source关联、语料版本与只读资料边界，不改变检索算法或Gate4判定。

#### Scenario: 相同chunk编号
- **WHEN** air与water具有相同chunk_id
- **THEN** 仍按workspace及来源身份分别验证，不合并或串读

#### Scenario: 未授权文件
- **WHEN** 请求其他workspace或旧语料版本的PDF/解析片段
- **THEN** 读取前拒绝且不返回文件内容

### Requirement: 浏览器上下文与秘密隔离
remote人类会话 SHALL 仅以受控应用cookie承载，IAM token和实例key MUST NOT 出现在JS存储、普通记录、URL残留或证据中。

#### Scenario: 双企业切换
- **WHEN** 用户A→B→A或退出换账号且旧请求迟到
- **THEN** 页面和记录不接受旧结果，旧写拒绝，机器无切企业功能

#### Scenario: SSO回调
- **WHEN** 回调state错误、已消费或回调地址不匹配
- **THEN** 拒绝；正常兑换仅服务端执行并清理一次性ticket URL

### Requirement: 可独立评审的阶段交付
实施 SHALL 保留当前基线、逐阶段证据、实际运行来源及正式切换保留项，不更改匿名评估标准。

#### Scenario: 实施交付
- **WHEN** 本轮提交验收结果
- **THEN** 报告按K01–K15列实证，区分真实IAM/存储/模型/浏览器与受控测试，并保留local完整回归
