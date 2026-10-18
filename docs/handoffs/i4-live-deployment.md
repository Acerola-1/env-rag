# I4 后续本机启用

用户此前已接受I2/I3，并另行授权真实切库、应用切流与Git提交。2026-10-18入口8099已启用remote IAM19100（实际PG19132/iam_identity）。三企业六人类从原注册表显式映射到canonical UUID，保留原口令/精确air、水、coastal权限，不按账号名称自动合并。六套独立机器凭据通过正式IAM API签发；新凭据清单位于`.local/remote-iam-live/credentials.md`，0600，不提交。

原`.local/workspace-access/registry.json`、本地凭据和历史记录保留。remote使用`.local/remote-iam-live/records`，不读取或覆盖local记录。显式mapping与部署环境同目录，现用`.env`已切remote；启动仅运行已切库配置，不初始化知识存储。

本次验证六个人类登录/选企业/精确知识范围、六个机器主体与无权限对照、新旧记录隔离，以及IAM依赖关闭和恢复。目标库迁移不包含文档PG、MinerU、Qdrant、Neo4j或LightRAG索引；不以本轮认证探针关闭I3历史LightRAG和完整浏览器等未测格。

当前用户放行/交付状态与首交60分、88分钟及旧评审补修状态分别保留。原模型报告、评分和未覆盖事项不覆盖。完整跨仓切换证据在IAM `docs/reviews/iam-i4-live-cutover.md`，复用启动入口在Agent `deployment/run_separated_local.py`。秘密与本机证据目录不提交。
