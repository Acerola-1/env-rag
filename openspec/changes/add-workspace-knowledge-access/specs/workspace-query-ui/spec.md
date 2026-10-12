# Workspace Query UI

## ADDED Requirements

### Requirement: Authorized knowledge selection

网页 SHALL 显示已认证主体及服务器返回的授权知识库，仅一个库时可自动选中，多个库支持单库或全部合法库选择。无权限 SHALL 显示明确状态；前端隐藏选项 MUST NOT 替代后端授权。

#### Scenario: Air reader opens knowledge selector
- **WHEN** 大气读者登录网页
- **THEN** 只显示 air，无法通过提交修改后的 water 参数获得资料

### Requirement: Context-safe workspace switching

切换知识库或身份 SHALL 隔离旧结果、澄清上下文、生成对象和未完成请求。切换本身 MUST NOT 发起模型请求；迟到响应 MUST NOT 被当作新选择的结果显示。

#### Scenario: Slow request finishes after switching
- **WHEN** 用户切换知识库后先前查询才返回
- **THEN** 页面不以该响应覆盖当前知识库的结果，也不继续旧记录生成或下载

### Requirement: Workspace-aware evidence and records

网页 SHALL 保留普通问答／对照选择语义，提供合法库查询、检索后生成、完整清单、chunk／图谱证据、引用、PDF／解析文本、私有历史记录和导出。每份证据 SHALL 标示来源 workspace，访问 MUST 遵守当前权限。

#### Scenario: Authorized dual-library answer is displayed
- **WHEN** 双库主体查询并生成需要两库证据的回答
- **THEN** 页面可分别定位 air／water 的实际来源，完整范围与模型总结分开显示

### Requirement: Honest readiness and error states

网页 SHALL 明确显示未授权、无权限、未就绪、stale、单库失败、生成失败及 partial／ambiguous。页面 MUST NOT 把失败降级隐藏、把生成成功当作完整范围证明或用 default 自动补答。

#### Scenario: Selected library is not ready
- **WHEN** 所选库未完成入库或没有 current 索引
- **THEN** 页面显示该库未就绪，不调用其它无权库，也不展示旧库结果冒充成功

### Requirement: Real browser verification

交付 SHALL 在实际运行网页中验证登录、知识库选择、查询、生成、引用／下载、记录／导出、错误状态及窄屏／键盘基本操作。静态 DOM 检查 MUST NOT 被当作实际浏览器验收。

#### Scenario: Reader switches identity and opens old download
- **WHEN** 浏览器从双库主体退出并以大气主体登录，再访问旧水资料来源链接
- **THEN** 页面／后端拒绝重新读取，界面不恢复旧受限记录并留下现场验收证据
