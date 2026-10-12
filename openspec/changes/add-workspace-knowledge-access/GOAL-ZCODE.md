# Z Code GOAL

把下面内容作为 Z Code 的 Goal 输入。目标以本目录的固定验收条件为准；仓库里旧网页的 `--usage-mode goal` 是历史模型预算模式，与 Z Code 的 GOAL 执行模式不同，不要混用。

---

在当前 env-rag-final 仓库持续实施 OpenSpec 变更 `add-workspace-knowledge-access`，直到交付并真实验收：大气 air／水资料 water 两个独立 LightRAG 实例，共用现有 PostgreSQL、Qdrant、Neo4j；一个先认证授权的 Knowledge API、共享 PG 检索和可使用网页。大气、水、双库及无权主体的访问符合权限矩阵；支持单库和全部已授权库查询、完整范围读取、生成、引用／文件下载、私有记录和导出。冻结清单中的大气／水资料全部导入或有证明的同库 duplicate，第三个 workspace 能只靠配置和入库扩展。

先完整阅读 `openspec/changes/add-workspace-knowledge-access/` 下的 proposal.md、design.md、tasks.md、acceptance.md 和全部 specs，再核实当前代码、AGENTS.md、配置和运行服务；存在 `.codegraph/` 时先使用 CodeGraph。代码基线已整理提交，不再清理或改写历史成果。遵循 README、WEB_RAG、DESIGN、UX-CONTRACT 和已验收的完整范围／来源核验合同。

沿用当前模型配置：DeepSeek v4.1 flash（`deepseek-v4.1-flash`）、Qwen3 embedding 4B／2560 维，实际启用的现有 Qwen reranker；不换 HY3，不静默换模型。先做最小真实服务／初始化兼容探针，再小样本入库，通过后自主完成冻结的全量清单。230 个 PDF 中包含 17 个无 air／water 前缀的分片，必须核对父文档／分类和逻辑覆盖，不只靠文件名前缀、不漏分片、不为过关缩清单。

授权你完成本 Goal 所需代码、配置模板、测试、部署脚本、本机新增两实例及专属试验库、真实入库／embedding／图谱构建和必要模型问答；复用现有凭据和服务。先估算工作量并持久记录实发调用，控制并发、有限重试，复用经过身份验证的现有解析／中间结果；不要全量反复重跑，也不要套用旧网页已耗尽的 Goal 预算。沿用现场容器运行方式；macOS 使用 Apple Container 时不擅自切换容器平台，另提供 Docker Compose 模板。

角色与知识库分开：服务器把企业／角色映射到允许的 workspace。客户端只能选择已授权范围；无权／未知库整体拒绝，不能回退 default。权限必须覆盖检索、生成、旧记录、缓存、图谱证据、导出、chunk／文档和 PDF／解析正文，不能只隐藏网页选项。内部实例接口不能成为越权旁路。副本跨库合法，同库幂等；相同资料两库的 snapshot／search 构建键不能碰撞；每库指纹与更新独立，旧混合图谱不能只改标签就算拆分完成。

保持已有 default 和其它非本轮空间、源资料、gold、历史报告／预算、现有 `.env` 与相邻 LightRAG checkout 不变；新运行配置和凭据放忽略目录，只写本轮明确拥有的 workspace／派生数据。先在隔离环境查明初始化／迁移行为，不直接初始化旧生产空间、不清库、不重建既有卷、不执行全局 prune。代码来源固定并真实核验，不能把本地定制 API 当作发布包默认能力。

你负责完整的调查→实现→真实试入库→全量导入→网页／服务／越权验收→定向修复→复验→交付循环。阶段门槛自行依据证据判定，通过后继续，不要求我逐批转发或批准。不要停在计划、CLI、静态页、容器健康或单元测试。实际浏览器必须验证登录／切库／查询／生成／引用／下载／记录／错误状态；原始 HTTP 必须验证伪造 workspace、跨库对象 ID、撤权和直接实例旁路。mock／fixture 只算离线测试，不算真实验收。

`acceptance.md` 的 7 条交付结果和固定矩阵全部通过，已有回归、必要新增测试、Ruff／格式、Git diff 和 OpenSpec strict 通过后，才能宣告 Goal 达成。不得删弱化旧测试、换题凑成功、伪造 model receipt、读取旧答案充当新生成或把 partial 升级 complete。只定向复验有变更／失败的部分，不无限追加需求或全面重做检索质量评测。

最终交付 WORKSPACE-ACCESS.md、可重复启动／停止、登录、入库／恢复／更新／新增库／回滚说明、本轮脱敏验收矩阵和真实证据，以及本地代码提交；不 push、不对公网部署。报告 commit、实际访问地址、凭据的本机文件位置和限制。只有全部固定条件确实满足才报告达成；持续不可用的外部服务／缺失凭据／无法证明的来源归属要报告精确阻碍、已完成工作和最小恢复动作，不能冒充成功。
