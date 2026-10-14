# Design

## Context

2026-10-12 规划依据是当前工作区源码和本机配置，不是旧报告中的数据量或模型名称：

- 基线整理提交为 `2a395bc9`；581 个 Python 测试及 6 个前端选择测试已验证通过。Python 全套中的本机 HTTP 测试因沙箱监听限制单独在允许监听的环境补验。
- `catalog/schema.py`、`search/query.py`、`search/expand.py` 和 SourceAdapter 已使用 workspace；融合使用 `(workspace, chunk_id)`。
- `Question.prepare()` 只接受 default；web service、native backend、多处文件和记录校验写死 default。local adapter 只验证 `default → vector '_' / graph 'base'`。
- 主、关键词、查询模型均配置 `deepseek-v4.1-flash`；embedding 为 `Qwen/Qwen3-Embedding-4B`、2560 维；reranker 为 `Qwen/Qwen3-Reranker-4B`。用户确认保持现有模型。这里只确认配置，服务可用性要在执行时真实核验。
- KV／doc status 为 PG，向量为 Qdrant，图谱为 Neo4j。workspace 是逻辑隔离，不等于不同数据库账号的强隔离。
- 项目依赖锁定 PyPI LightRAG；网页启动器把相邻 `LightRAG` checkout 加入导入路径。两种来源不可混用，版本字符串不能代替实际代码、接口和存储兼容性证据。
- 仓库顶层有 230 个 PDF：60 个 air 前缀、153 个 water 前缀、17 个无前缀的分片 PDF；有 222 个 `.parsed` 目录。文件数、逻辑文档数、既有入库数不是同一概念。规划阶段未成功连接现有 PG，不把历史 221／5709 作为当前验收分母。

## Goals / Non-Goals

**Goals:** 完成可真实使用的 air／water 示例、可信后端授权、单／多知识库查询、可恢复入库和网页验收；已有 default 受保护；第三个 workspace 可由配置和入库命令扩展。

**Non-Goals:** 不扩大为通用企业 IAM、在线账号后台、计费、细粒度文档 ACL、RLS、全库检索收益评测或新的存储选型。权限是粗粒度知识库访问；第三个 workspace 只需用本轮专属小样本证明扩展，不做第三次全量入库。

## Decisions

### 1. 角色与 workspace 分离

建立显式注册表（建议版本化 JSON／YAML，格式可由实施者选择）：

- workspace：稳定 ID、中文名称、对应 LightRAG 内部地址、PG／Qdrant／Neo4j 的明确有效命名空间、解析产物根、状态和实例代码身份。
- principal：用户 ID、企业 ID、角色集合；认证凭据引用放在本机忽略配置／环境中。
- role grant：角色映射到允许访问的 workspace ID 集合。不同企业可拥有相同角色名，映射必须按企业命名空间解释。
- policy revision：授权变更使旧上下文／缓存不再复用。

初始示例：`air-reader → {air}`、`water-reader → {water}`、`environment-reader → {air,water}`；另有无知识库授权主体。新增角色组合已有知识库无需复制资料。

请求指定 workspace／workspace 集合只是选择意图；服务器计算合法范围。指定任一未知或无权 workspace 时整体拒绝，不静默裁掉、回退 default 或变成全库。`all` 只能展开为当前主体的授权集合；空集合拒绝。ID 仅用服务器注册值，不拼接用户输入进 SQL、数据库名称或文件路径。

### 2. 一个授权入口，两个固定 workspace 的 LightRAG 实例

```text
浏览器／Agent／MCP 客户端
       │ 认证凭据 + 知识库选择
       ▼
Knowledge API（认证、授权、记录与来源读取）
       ├─ 共享 PG 检索器 ── 按有效 workspace 查 PG／派生目录
       ├─ LightRAG air 服务 ── workspace 固定 air
       └─ LightRAG water 服务 ─ workspace 固定 water
                  │
            共用 PG / Qdrant / Neo4j
```

两个 LightRAG 实例各自管理连接池；共享的是存储服务，不要求跨进程共享同一连接对象。配置 WORKSPACE 及后端 override 时必须证明有效值一致，尤其 `POSTGRES_WORKSPACE`、`QDRANT_WORKSPACE`、`NEO4J_WORKSPACE` 的优先级。不得把新实例指向旧 vector `_`／graph `base`。

网关是唯一供客户端使用的知识入口。LightRAG 的查询、上传、删除、配置和图谱管理端口均处于内部网络／回环范围并使用实例凭据。普通读者没有入库／管理权限。现有仅本机的旧对照模式允许保持，但它的未认证 API 不能作为新网关的公开旁路；default 不在示例读者授权范围。

最小认证采用服务器验证的会话或 opaque bearer token，CLI／Agent 可用后者；浏览器可提供简单登录换取安全会话。凭据来自本机忽略配置，认证主体不能由 `X-Role`、企业参数或网页下拉框直接声明。现有 X-RAG-Token 是 CSRF 保护，不能代替用户身份。新功能可用单独 knowledge 服务模式／端口承载，以保留旧本机对照测试和预算合同。

### 3. 请求上下文贯穿所有读取

在授权成功后构造不可变上下文：principal、enterprise、policy_revision、已选择的合法 workspace 集合和每库快照。把它传到查询、展开、生成、记录、导出、PDF／解析文本、文档／chunk 定位及澄清后续请求。

记录至少绑定主体和企业、授权代次、workspace 集合、每库 source/catalog/search 身份及内容哈希。本轮默认记录仅创建者可见；每次读取再检查当前授权，不仅在创建时检查。权限撤销后不能通过旧 record ID、来源 URL 或缓存读取原数据。未经认证／授权拒绝发生在检索、模型调用和文件读取前，响应不泄漏被拒文档名称、内容、命中数或其他 workspace 存在性。

旧 SourceAdapter 跨 workspace 诊断仅可在内部离线审计使用；知识 API 的外部 lookup 不为诊断查询未授权 workspace，返回统一缺失／拒绝响应。

### 4. 单／多 workspace 检索

PG 继续使用现有 workspace 条件、快照和完整范围读取，不重写算法。问答入口、CLI 构建入口及 stale 检查显式传递 workspace；移除 default 限制时替换为注册表／授权校验，不删掉校验。

LightRAG 使用各固定 workspace 实例的真实查询／数据接口或等效已核对的原生适配器。接口必须保留真实 chunk、实体、边、模式及来源；不能以最后的自然语言答案伪装检索候选。原生模式及 PG+对应模式的可选项继续遵守现有产品合同。

多个已授权库分别检索，再合并证据、排序，最多一次答案生成。隔离身份始终使用 `(workspace, doc_id/chunk_id)`；相同 chunk ID 的不同 workspace 不能覆盖。证实同逻辑文档、同版本、同正文哈希的重复证据可在展示／模型上下文合并，保留全部授权来源；不能只凭内容相似误合并版本。

每个库单独维护 source／catalog／search 身份。当前全局 parsed artifact 指纹和全库计数探针需要为新 workspace 改成注册清单及其产物范围，避免 water 更新导致 air 失效或外泄全库信息；保留旧 default 回归口径。若完全相同资料被复制到两个 workspace，也要验证 snapshot/search build ID 不碰撞：`search_builds.search_id` 当前是全局主键，而现有 index 身份计算不包含 workspace，需补齐复合身份或显式 workspace 纳入构建 ID，并做受控兼容迁移。

任一路服务故障可返回已完成的合法证据，但显式列出失败 workspace／路由，不能标成双库完整成功。权限错误不属于可降级的检索失败。top-k 仍只限制发现，不能截断确认范围、续表或文件全集；模型不能升级 partial／ambiguous／stale。

缓存键至少含主体／企业、授权代次、workspace 集合、每库快照、问题、策略／模式及影响上下文的参数。先授权再访问缓存；不共享不同主体的最终答案／记录。新运行状态放入忽略的本机目录，不能重新消费／重置旧 Goal 预算。

### 5. 冻结分类与分片清单，先小样本再全量

执行者自行调查本地语料、PG 只读来源和 MinerU `_manifest`／blocks／tables，形成机器可读导入清单。每项包含原始相对路径和 SHA、逻辑文档身份、分类依据、目标 workspace、原始／分片关系、产物定位和状态。

air／water 前缀是初始分类依据；17 个“分片”必须通过解析元数据、内容、来源清单或原始 PDF 对照确定所属父文档／领域。无法证明的项公开列为未解决，不猜测归属。副本／分片不是可以悄悄缩小分母的理由：证明重复可记 `duplicate` 指向已导入身份；必要分片必须全部保留，逻辑覆盖完整。确实不属于 air／water 的材料可按内容证据排除并留依据。清单冻结后不得因导入困难删项。

先选至少 2 份大气和 2 份水资料，包含可独立核验的表格／条款和一份人为显式配置到两库的真实共用资料，验证解析定位、chunk、embedding、实体／关系、图谱、PG 目录和索引整链。共用资料仅用于证明允许跨库重复，不宣称现实业务分类。

先验证复用路径，优先复用已有 PDF／MinerU 产物、可证明身份正确的 chunks、embedding 与 chunk 级抽取结果。不得用只导入 merged text 的捷径丢失表格／sidecar 身份。现有合并图谱不能按标签直接拆开；在目标 workspace 内按其文档证据重建／重新汇聚实体与边，或用经过来源裁剪和同等验证的迁移。所有缓存复用记录来源、模型、参数、SHA 和复用事实，不能伪称 fresh。

小样本验收通过后自动继续完成冻结 air／water 清单。本轮允许使用既有模型凭据进行必要抽取、embedding、总结／精排与真实问答，不需要用户逐批批准。先估算 chunk／调用量并写持久账本，限制并发和有限重试；服务错误按原因修复，避免全量重跑和无界重试。用户没有指定金额／次数上限，不能擅自套用旧 40／60 次 Goal 预算导致目标天然无法完成；配置或平台的实际硬限制必须遵守。

### 6. 入库、初始化和更新的所有权边界

已有 default 和其它非本轮 workspace 的正文、向量、图谱、处理状态、缓存及 active 派生目录保持不变。它们的初末核验按 workspace 过滤，不能用新增数据后的全表计数比较声称旧库被改动。

先在本轮隔离数据库／workspace 探针验证 LightRAG 初始化，查明 DDL、自动迁移、图谱／集合建库和 legacy migration 行为；不能首次探针就让 initialize 连接旧生产命名空间。实际目标仍共享现有 PG／Qdrant／Neo4j；只允许已验证无旧数据变更的新增 workspace 写入及必要非破坏性创建。本轮派生 schema 的兼容迁移必须备份元数据、幂等执行，保留旧 default 的可读性；禁止 DROP 全库／全 schema、重建既有卷或修改历史表内容来适配新库。

导入 checkpoint 的幂等键包含 workspace、逻辑文档／源 SHA、解析及 chunk 配方、模型身份。重复导入同一内容不重复新增行／重做已持久确认成功的模型请求；不同 workspace 的同一内容合法。先持久化 pending，再记录实发及响应结果，原子提交已完成 checkpoint。调用发出后、响应落盘前崩溃属于 uncertain，不能宣称外部模型 exactly-once 或自动重复计费；先核对已有缓存／结果，无法确认时单独报告并按明确有界恢复策略处理。可证明的同库重复状态不能冒充失败，也不能无证据把真正失败改成 duplicate。成功、重复、缺产物、失败分开，重启继续未完成项；入库完成后再原子发布该库目录与搜索索引。

新增／更新／撤回在目标库内完成，然后使该库缓存失效并重建派生目录／索引；其它库保持可用。若同一资料在两库有副本，提供明确的同步操作和版本漂移诊断，不宣称自动同步。删除只针对本轮拥有的 workspace／运行记录；回滚停新实例、撤销新路由、按清单删除本轮目标数据，保留旧 default，禁止全局 prune。

### 7. 部署和扩展

先核实现场运行方式。macOS 当前若使用 Apple Container 则沿用其原生启动／停止脚本，使用实际帮助确认命令；不要为了这轮切换 Docker Desktop／Lima／Colima。另交付普通 Docker Compose 部署模板供有 Docker 的环境使用，但只对实际运行验证过的方式称“已验收”。不存在 `container compose`。

实例镜像／代码来源、embedding 模型与维度、PG schema 接口需固定并验证。优先使用项目锁定的发布包；确实依赖原 checkout 能力时，用显式来源配置和受控代码快照／只读挂载，把代码 hash 写进实例注册表，不修改相邻仓库、不漂移到 latest。不盲目切换来源造成存储不兼容。输入和解析产物用一致可解析路径挂载，容器内的本机回环地址不能误指宿主；连接和密钥由运行配置注入。

air／water 使用独立工作／输入目录、固定 workspace、内部 API 凭据、连接池和受控写并发。入口默认回环或现有内部网络，不对公网开放；配置和检查日志不得打印 API key、DSN、密码或完整环境。

用第三个 `workspace-extension-check`（或检测冲突后明确本轮唯一名）仅导入一份已有真实资料，配置角色授权，证明通过注册／入库／启动能查询且被其它读者拒绝；禁止为它新增 if/else 或复制检索代码。该验证完成后可只保留配置示例，按运行所有权清单清理目标试验库。

## Risks / Trade-offs

- 粗粒度 workspace 复制简单直观，但重复存储／抽取有成本，副本更新需显式同步；角色组合已有库优先于为每个角色复制资料。
- 两个实例仍共享数据库、模型和机器资源；限制并发，故障隔离不等于零资源竞争。
- 新图谱不保证与旧 LLM 图谱逐字一致；验收看正确 workspace、来源和可用链路，不伪造历史快照或要求重现旧基准分数。
- 本轮只证明应用层知识库权限。持有管理员数据库／服务器密钥的人不属于普通读者威胁边界，不宣称数据库强租户隔离。
- 外部服务持续不可用、凭据缺失或真正无法判定的分片归属属于可记录的外部阻碍；完成独立工作并列出精确未满足条件，不能用 fixture、换模型、缩清单或放宽验收宣布达成。

## Migration Plan

1. 初始盘点、默认库保护清单、源码／模型／服务兼容探针及分类清单。
2. 配置注册表和认证／授权上下文；补齐 PG／身份／文件／记录／缓存隔离及离线正负例。
3. 两个新实例和小样本入库，检查全链来源及空间隔离；通过后自动导入冻结全量清单。
4. 发布两库 PG 目录／索引，接入网页和单／多库检索，新增第三库扩展探针。
5. 执行 acceptance.md 的真实服务、浏览器、越权、重启／增量验收，定向修复并复验。
6. 交付部署／恢复／新增库说明、报告和新代码提交；不自动 push、不替换公网服务、不改旧 default。

## Open Questions

规划没有等待用户回答的产品决策。实际实例来源、服务地址、版本、分片映射和可复用抽取结果由执行时的有界探针确定；这些调查是 tasks 的工作，不是把计划再次交还用户的理由。
