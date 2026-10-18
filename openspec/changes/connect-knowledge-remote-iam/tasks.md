# I3分阶段任务
仅实施本仓库；首交checkbox全部未完成，完成实现与真实证据后才勾选。原PG检索change与Gate4状态保持。

## G0 输入与环境
- [x] 0.1 核对AGENTS、HEAD/diff、baseline.json及workspace原断言，按具体测试建立现时基线，不把633等历史计数当本轮结果。
- [x] 0.2 建独立IAM副本/客户端/资源/企业/人类与机器夹具、记录根和回环端口；实际探针冻结人类/机器/SSO形状及错误，原资料只读。
- [x] 0.3 固定显式tenant/resource/workspace映射和技术目录，列出所有query/generate/record/cache/source/document出口及实际发送点。

## G1 最小Bearer闭环
- [x] 1.1 实现local/remote provider、严格typed响应、异步连接/总deadline、错误/启动配置；local对IAM请求0，remote不fallback（K01–K03）。
- [x] 1.2 从真实机器内省精确许可生成不可变上下文，只读技术映射与就绪；单库受控后端正例及拒绝计数0（K04–K06）。

## G2 资料出口与实时撤销
- [x] 2.1 逐调用者接入query/generate、PG/LightRAG/网关模型、retry和最终输出/落盘守卫，处理sync→async调用链（K07/K08）。
- [x] 2.2 统一cache/records/list/detail/export/source/document的主体/企业/修订/语料边界，保留原真实source指纹与拒绝语义（K09/K10）。
- [ ] 2.3 实际只读PG与air/water实例验证精确workspace路由、元数据到来源一致；不初始化存储/重入库或更改检索算法（K11）。

## G3 人类与页面
- [x] 3.1 接remote人类会话/SSO/企业列表与CAS切换、server-only秘密及退出；机器无切企业，人类无企业不得查询（K12）。
- [ ] 3.2 现有8099页面在独立remote入口完成登录/选择/查询/记录/下载/刷新，添加scope/epoch守卫、401/403/409/503与CSRF/Origin处理（K13）。

## G4 回归与交付
- [ ] 4.1 完整离线测试和Ruff，对照nodeid保留旧失败；加本地/远程、机器/人类、同用户双企业、撤销/恢复/故障与缓存/文件屏障矩阵。
- [x] 4.2 完成最小真实只读检索/生成、保存原库指纹对比及费用账本；真实模型不可用的具体格明确受阻，不能替换配置模型声称完成。
- [x] 4.3 同条件身份/受控传输性能采样与无正向授权缓存证明、秘密/diff/产物检查、OpenSpec strict。
- [x] 4.4 输出docs/reviews/knowledge-remote-iam-acceptance.md、K01–K15映射、tasks实施备注、配置模板、运行入口和本地秘密位置/资源清单。交付待独立验收，不commit/push/merge/archive。


## 实施备注
- run_id: 见 .local/iam-acceptance/CURRENT_RUN_ID；G0 证据 00-g0-baseline.md + 00-baseline-nodeids.txt + g0-probes/。
- 独立 IAM 127.0.0.1:50200（PG 50232 / Redis 50279，自有容器 i3-pg17 / i3-redis7）；夹具经真实管理 API 创建。
- G1 完成：tests/test_remote_iam.py 44 项契约测试（用 G0 冻结的真实 IAM 响应做正例）；g1-live/results.json 29/29 真实 IAM 联通（sentinel 5099 证明拒绝=0 后端、正例确实到达数据边界）；g1-startup/ 四种启动行为。
- G2 完成：tests/test_remote_boundaries.py（13 项：撤销/ABA/生成中切企业/记录主体类型/文件命名空间/失败关闭）+ tests/test_remote_http.py（13 项真实 aiohttp 面）；g2-live/results.json 21/21 真实只读 PG（coastal 命名空间、doc→chunk→source 一致、同 id 跨库不合并、混合选择整体拒绝且后端 0）。
- G3 完成：g3-live/results.json 18/18（真实 SSO 303+ticket/state、重放/错 state 拒绝、A→B→A 新纪元）；g3-browser/（真实浏览器 18 步 + 6 截图：企业必选、查询 8 条证据、下载、A→B→A、CSRF 403、CAS 409、退出 401）；g3-sso-browser/（浏览器 SSO 落地→选企业→查询 8 条）；tests/test_remote_page.cjs 5 项。
- G4 完成：04-final-nodeids.txt 704 通过（基线 633 全保留，新增 71）；ruff 全绿；node 15 项通过；openspec validate --strict 通过；g4-live/perf.json 身份采样（1/10/30 并发）与原库只读指纹。
- 交付物：docs/reviews/knowledge-remote-iam-acceptance.md（K01–K15、真实/受控/未覆盖、资源与秘密清单、复跑入口、切换前置）；deployment/remote-iam.example.env 与 .mapping.example.json。
- 受阻（未标通过）：真实模型生成（模型网关 8787 未运行，0 次调用/0 费用）、route=lightrag 实例路径（实例容器网络地址失效，已修 env 未复测）；8099 切换与 I2 生产组合不在本轮授权。
- 过程事件：首启 50202 时未指定 --record-root，2 条远端记录落入本地记录根，已移出并加启动守卫（报告 §4.1）。
- 状态：待独立验收；未 commit/push/merge/archive。


## 2026-10-17 独立验收与 Codex 接管备注
- 首交已冻结，模型原始成绩 60/100、88 分钟，未独立通过；后续补修不归实施模型。
- 首交 704、原版 633 均独立复跑通过；首交缺私有探针时专项 61 跳过。现有专项已改为仓库内无秘密协议夹具。
- Codex 补齐数据发送/回送/落盘实时守卫、完整人类/机器代次与记录缓存绑定、真实 CAS 与旧标签页、SSO 一次性状态、应用 cookie 隔离、原生下载链接。
- 当前离线 723 项通过；页面 18 项通过；真实 IAM/PG/新网关模型 1 次生成与实际 usage、SSO HTTP 完整链和重放、900 次身份性能采样已完成，见接管报告。
- 2.3 未闭合：air/water LightRAG 实例停止，未启动可能初始化共享存储的服务来冒充只读验证；coastal PG 不替代这项。
- 3.2 未闭合：独立浏览器桌面、企业选择与键盘已验；本轮 390×844 和双标签完整矩阵未独立重做，不沿用作者截图直接判通过。
- 4.1 保留未闭合：离线及受控屏障通过；此前真实机器凭据测试的审批阻塞已在用户明确授权后解除，真实生命周期/发送屏障26/26通过；其他实际依赖故障、资源开通回收/恢复及文件竞争格未全闭合。
- 新入口 50202 使用既有 SSO 精确注册；评审记录根与 gateway-50202.env 在 .local/iam-acceptance/reviewer-20261017/，原 .env 未覆盖。
- 完整 K 矩阵尚未通过，不 commit/push/merge/archive。


## 2026-10-17 用户明确授权后的补充
- 已在隔离IAM50200创建唯一专用机器账号，仅coastal单库读/knowledge受众；真实IAM/只读PG/受控HTTP模型26项全部通过。
- 覆盖永久撤销、全部数据出口下游0、新凭据恢复/旧凭据不复活、旧记录与旧上下文拒绝、真实发送前/后撤销及正向生成落盘。
- 新签发4枚凭据全部撤销并读回revoked；原3个机器账号和凭据元数据相同；新秘密扫描零命中，付费模型新增调用0。
- 本次无需改产品源码。首交60分/88分钟不变；2.3/3.2/4.1其余保留项不提前勾选。
- 证据与范围见docs/reviews/knowledge-remote-iam-takeover.md的授权补测章节。


## 2026-10-18 后续用户放行与提交

用户在后续会话明确接受I2/I3并授权I4实际切库与三仓提交；之前“未commit/未启用”是历史时刻，不撤销用户后续授权。8099现已remote到新IAM，六个原人类与六个机器精确权限/记录根隔离复验；专项90与页面12项通过。详见docs/handoffs/i4-live-deployment.md。旧未覆盖格不因后续接受而伪造证据或自动勾选，原首交60分/88分钟不变；本次不归档此完整矩阵。
