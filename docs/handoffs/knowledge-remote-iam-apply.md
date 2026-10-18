# I3匿名实施提示词（标准OpenSpec apply）

请在 /Users/acerola/Dev/Python/RAG/env-rag-final 实施OpenSpec change connect-knowledge-remote-iam。你是本轮匿名实施者，不写模型/供应商名称、不读取历史模型身份/评分映射；没有编号就写“本轮I3实施”。只授权本仓库实现、测试和自有隔离环境联调；保留待独立验收的diff，不commit、push、merge或archive。

使用客户端的标准OpenSpec实施工作流（通常为/opsx:apply connect-knowledge-remote-iam），不使用goal模式。先读取openspec status和openspec instructions apply --change connect-knowledge-remote-iam --json，按其中contextFiles与本包范围实施；CLI负责提供工作流上下文，不会自动完成产品改动。进度统一写tasks.md，不另建goal或checkpoint文件。

## 先读固定输入，按阶段定位源码
阅读AGENTS.md、WORKSPACE-ACCESS.md及本change的proposal/design/tasks/acceptance/spec；baseline.json先看HEAD/已有改动摘要，文件hash在G0核对；contract.md先读共同段、SSO与I3段，跳过I2专属票据桥接/数据迁移段。源码入口是src/env_rag_final/access，不是早期8091的web。不要先读取整个仓库；按G0–G4阶段读取对应方法、调用者与测试。

目标是为现有8099网关增加明确remote模式，真实IAM人类/服务账号→精确tenant/资源/workspace→真实检索/生成/记录/来源/文件，支持即时回收与失败关闭；local原有行为不回退。现有8099、air/water实例与资料不得被覆盖，另起独立remote入口。

## 顺序和已冻结设计
按G0→G1→G2→G3→G4自主实现和修复；先真实IAM单库Bearer加受控后端，再扩展真实只读存储/全部出口，最后接人类页面与完整回归。正常工程决定不逐项询问；每个checkbox须实现和证据同时成立，不凭解释或截图数量勾选。

- local/remote是启动配置，remote不能调用local principals/grants授权或在故障后自动兜底；local不得因IAM不可用而失败。
- human与service_account分开验证；机器的user/session/membership/revisions为null，不能套人类schema或伪造修订。active=true不是资源许可，必须精确knowledge读码与企业映射一致。
- 显式(tenant UUID,resource code)到workspace映射；技术registry保留namespace/实例/就绪作用，与本地主体授权分开。all只展开有权且就绪库，显式混合含无权项整体拒绝。
- 每个query/generate/record/cache/export/source/document与网关新发送/retry边界都复核；同步改异步须逐调用者await。缓存已有答案也不能免授权，输出/落盘不写到新企业。
- 只向LightRAG注入原instance key，不透传IAM主体/内部client。保持source指纹、实际namespace、只读查询及历史记录隔离，不重入库、不改Gate4/精排/融合。
- 人类会话/SSO按contract.md实际303+ticket/state协议，应用cookie秘密仅服务端，多企业必须明确选择；A→B→A和退出换账号迟到结果拒绝，机器无切企业。

如工具支持子智能体，可将严格客户端/契约测试、gateway边界、页面分别分工；主实施者独占共享AuthContext/配置/映射和最终整合，避免多人同时修改相同文件。无子智能体则顺序完成，不能虚报委派或把子报告当最终验收。

## 验证和交付
严格按K01–K15提供正例/负例及实际后端增量0证据，覆盖local/remote、人类/机器、同用户双企业、撤销/重新开通/永久吊销、故障、缓存和来源文件。用当前测试建立nodeid基线；不继承历史“633通过”等计数，不删断言、弱化来源检查或扩大skip。真实IAM/受控服务/真实PG与LightRAG/实际配置模型/浏览器分层标注。保留配置模型，真实调用最小样本并记录费用；缺凭据的格写具体阻塞，其他独立工作继续。

保护正式public/rag库、MinerU和原PDF/解析产物，查询不初始化存储，不全局prune/重建卷；新测试写只在自有schema/workspace/记录根。IAM与Agent源码只读，使用独立IAM副本，不修改共享49103或另一个并行实施者的数据。

进度与续接位置只在本change/tasks.md末尾维护短“实施备注”；证据追加到.local/iam-acceptance/<run_id>/，报告不含任何秘密。实施/验证/外部等待分别实测，Token未知写未采集。最终docs/reviews/knowledge-remote-iam-acceptance.md列改动、K矩阵、基线/新增失败、实际地址与秘密文件位置、资源所有权/原库指纹、真实与受控范围、尚未完成与正式切换前置。首交状态“待独立验收”，不自封通过、不覆盖历史报告。
