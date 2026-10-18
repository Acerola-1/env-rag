# 知识库访问界面约定

业务依据：[WORKSPACE-ACCESS.md](WORKSPACE-ACCESS.md) 与
[远程 IAM 设计](openspec/changes/connect-knowledge-remote-iam/design.md)。
所有权限由服务端决定；页面只表达选择。人类必须显式选择企业，机器不能切企业。
旧标签页、A→B→A、退出换账号及页面初始化的迟到响应不得重绘当前主体的数据。
来源与导出链接绑定发起页面的非秘密企业纪元，不能据旧链接借用新企业授权。

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Select/Listbox | access/static/index.html 原生 select | DESIGN.md 与远程 IAM 设计 | 企业、检索路径、模式 | 浏览器键盘、展开与 Escape |
| Form | access/static/app.js | 本文与远程 IAM 设计 | 登录、查询、切企业 | 页面竞态与真实 HTTP 测试 |
| Scrollbar | access/static/style.css | DESIGN.md / CSS 变量 | 全局继承 | 计算样式、窄屏 |
| Toast | access/static/index.html 的 status/alert | 本文 | 行内等待、拒绝、恢复指引 | 浏览器及页面错误码测试 |

无表格批选、日期、CRUD 删除及弹窗，不引入对应控件。
口令默认隐藏，允许密码管理器与粘贴；不在 URL、本地持久存储或普通记录中保存秘密。
登录与切企业防重复提交；401 提示登录，403 提示权限，409 提示重选，503 提示稍后重试。
app.js 的事件绑定是按钮动作的实际入口，静态 HTML 审计不能单独判定按钮无行为。
