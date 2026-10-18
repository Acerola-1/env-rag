# L3 首次交付独立评价（固定成绩）

评审日期：2026-10-17。Change：connect-knowledge-remote-iam。
用户提供模型标签 **deepseekv4.1flash**、首次实施耗时 **88 分钟**。
本轮身份已知，属于实名独立评价；不核验厂商版本，也不因历史排名调整分数。

## 结论与归属

**首次交付未通过，60/100。模型独立修复 0 轮；用户要求 Codex 直接接管补修。**
本文件固定首次成绩，后续修复和新增真实验证只写另一份接管报告。

| 维度 | 得分 | 独立依据 |
|---|---:|---|
| 契约正确性与业务可用 | 17/30 | local/remote、真实 IAM 登录/机器分型、显式库选择、页面框架成立；普通查询缺中途/回送复核，切企业版本回传和前端消费缺失；实际 LightRAG 路径未完成 |
| 权限和数据边界 | 14/25 | 精确权限交集、跨主体/企业/模式的基本记录隔离、只读 PG 设置有实现；四修订与机器账号代次丢失，凭据/会话未完整进入缓存记录边界，查询途中撤权仍落盘；remote 与 local 使用同名 cookie |
| 测试与验证可信度 | 10/20 | 原基线 633、首交 704 在相同允许监听环境复跑通过；独立 HTTP 反例证实测试未覆盖实际屏障；去掉私有探针后 71 项专项仅 10 通过/61 跳过；报告承认真实模型和实例未测，但任务全勾选不成立 |
| 可维护性与项目契合 | 12/15 | 复用现有网关、provider 分工、异步 HTTP 池与总 deadline 有价值；身份对象与记录字段不一致，check_context 注释声称实时复核而实现只有本地检查，存在重复/未接通辅助方法 |
| 范围控制与交付完整 | 7/10 | 独立端口、报告、部署模板基本齐全，未提交；主动记录记录根误写和未覆盖项；修改共享实例私有 env、K11 未实测却勾任务完成、运行说明有脚本名/参数偏差 |
| **总分** | **60/100** | 门槛未通过，分数仅用于解释本轮诊断 |

## 冻结与基线核对

- Git 基线：`1aa52b04976a94ad6e969775ced07cf1828ca81e`，dev，首交尚未提交。
- 首交全部可追踪/非忽略文件快照、hash 与 tracked diff：`.local/iam-acceptance/reviewer-20261017/first-delivery*`。先冻结后修改。
- baseline.json 的原产品文件均与 Git HEAD 匹配；规划 proposal/design/acceptance/contract/spec/提示词 hash 未改，仅 tasks 更新。
- 原版源码导出至独立目录。旧测试硬编码读取源码根 .env，补同源只读链接后 **633/633**；首次两次因缺隔离目录 .env 出现 9 失败属于配置差异，不记模型回归。
- 首交候选 **704/704**；第一次沙箱禁止监听造成 14 PermissionError，允许回环环境复跑全过，不扣模型分。
- 离开作者私有探针目录：专项 **10 passed / 61 skipped**，证据 `first-without-private-fixtures.log`。不能视为可在新 checkout 独立完成的离线合同套件。

## 可复现阻断

独立脚本与结果：`probe_first.py`、`first-counterexamples.json`，均位于上述忽略证据目录。

1. **撤权后的普通查询仍返回并落盘。** 真正 aiohttp `/api/query`，受控 PG 操作中把 IAM permissions 清空；结果 **HTTP 200、IAM 调用仅 1 次、保存记录 1 条**。首次 gateway.check_context 的 remote 分支只查 registry；普通 query 未调用 recheck_remote_live；不是安全扫描猜测。
2. **权威修订丢失。** 授权后只递增 human.user_auth_revision，recheck_token 仍允许；只递增 service_account_revision 同样仍允许。RemoteIdentity 有人类 revisions，但未进入 AuthContext，也未在 can_reuse_context 比较；机器账号代次校验后被丢弃。
3. **切企业 CAS 断链。** session_view、登录及 /api/me 均漏回 context_version；页面 applySession 也不消费该值，第一次切换后第二次仍可能回退到 1；switch 返回也不含版本。页面测试自行编造含 context_version 的返回，未覆盖真实协议。
4. **严格验证不完整。** membership.revision 与 revisions.membership_revision 不同、platform_admin 为字符串、evaluated_at 为 nonsense 均被接受；部分嵌套字段无精确键检查。畸形成功响应亦可能被报成用户 401，协议要求 503。
5. **记录/缓存作用域不足。** cache_key 漏 session_id、credential_id/revision、四修订与机器账号代次；Record 只比较模式/主体/租户/registry 与库集合，旧权限纪元可被复用。此项依据源码和后续针对性反例修复，未宣称已观察到跨其他用户泄露。
6. **cookie 按端口不隔离。** 新 remote 与既有 local 都使用 wa_session，无法依靠不同回环端口隔离浏览器会话。

## 已有价值及环境缺口

真实 IAM 人类/机器协议探针和不少边界已有实现，完整离线套件也保持绿；没有发现删掉旧断言以掩盖失败。
作者明确承认旧 8787 模型网关停用、LightRAG 容器不可用。新网关是用户在交付后提供，不能因此扣成作者虚报真实模型；但真实生成仍不能记为首交已通过。
K11/任务 2.3 要求实际 PG 与 LightRAG air/water，首交只给 coastal PG，报告又承认实例未覆盖，故 checkbox 不能认可完成。

## 稳定性、效率与运行性能

- 稳定性：基础回归通过，关键执行途中权限和会话时序未闭合；未独立完成，未获得模型返工样本。
- 实施效率：88 分钟来自用户。Token、工具次数、实际工作/外部等待拆分未知；不按跨任务耗时排名。诊断效率暂记 **3/5**。
- 运行性能：作者身份局部采样是作者证据，不当作完整业务性能；首次交付的独立完整业务负载性能未知。
- 评审者后续新增的新网关真实调用、独立反例、代码修补、浏览器和性能复测均不计实施模型成果。

后续见 [Codex 接管验证](knowledge-remote-iam-takeover.md)。首次 60 分保持不变；L2 仍在执行，不提前给 GLM 本轮分数。
