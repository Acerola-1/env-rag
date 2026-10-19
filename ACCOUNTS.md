# 账号与凭据

当前网关为 http://127.0.0.1:8099 ，身份唯一权威是Java IAM19100。原本地演示账号源已退役；账号、企业、成员和角色均在IAM管理。

现有air-reader、water-reader、dual-reader、no-access、beta-reader、coastal-reader保留迁移后的明确权限。机器使用IAM签发的独立凭据，不复用人类口令；no-access是无资料授权对照账号。

本机实际口令和机器凭据仅保存在`.local/remote-iam-live/credentials.md`（0600，Git忽略），不得写入公开文档。技术目录中的workspace不授予任何权限。运行方式见[正式环境](docs/CURRENT-RUNTIME.md)。
