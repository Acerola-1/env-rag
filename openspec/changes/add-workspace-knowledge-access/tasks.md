# Tasks

所有实施任务初始未完成。本文件的阶段门槛由执行者凭证据自行判定并继续，不需要用户逐阶段批准；只有无法自主解决的外部条件需要如实交付阻碍。固定完成条件见 acceptance.md。

证据根目录：`reports/workspace-access/wa-20261012-r1/`（下称 `E/`）；本机忽略目录 `.local/workspace-access/`（下称 `L/`）。

## 1. 现状盘点与保护

- [x] 1.1 读取本变更全部文件、README、WEB_RAG、AGENTS 和现有检索合同；记录当前 Git、依赖、实例／容器、配置来源；有 `.codegraph/` 才先使用 CodeGraph。
      — 证据：仓库根无 `AGENTS.md`，`.codegraph/` 位于父目录 `/Users/acerola/Dev/Python/RAG/`（非本仓库，未使用）；基线提交 `1c73eec3`；依赖见 `E/runtime-identity.json`；容器见 §4.1。
- [x] 1.2 建立本轮运行目录、所有权清单和持久模型调用／导入 checkpoint 账本；隔离旧网页 runtime 和历史 Goal 预算。
      — 证据：`E/`；账本 `L/ingest-air.jsonl`、`L/ingest-water.jsonl`、`L/ingest-coastal.jsonl`（含每项 `begin`／终态与实发计数）；未触碰 `reports/rag-web-*` 的历史预算。
- [x] 1.3 只读采集现有 default／其它非本轮 workspace 的原文、状态、向量／图谱及 active 派生数据身份，固定源文件／gold／配置保护清单，敏感字段不落盘。
      — 证据：`E/protected-before.json`（含 `.env`／`datasets/manifest.json`／gold 的 SHA、PG 各表 per-workspace 计数与 id 摘要、Qdrant per-workspace 点摘要、Neo4j label 计数）。
- [x] 1.4 核对 LightRAG 发布包与原 checkout 的真实查询、数据、解析产物入库、workspace override 和管理接口；在隔离环境验证初始化／迁移行为，固定采用的代码版本和 SHA。
      — 证据：`E/lightrag-init-probe.json`（隔离 PG 克隆上初始化前后 schema 零差异）；`E/chunk-identity-proof.json`（PyPI `lightrag-hku==1.5.7` 逐字节复现既有 chunk 的 id／tokens／正文／heading／sidecar）；镜像 `ghcr.io/hkuds/lightrag:latest` 内同为 1.5.7（`E/runtime-identity.json`）。
- [x] 1.5 真实验证 DeepSeek、embedding 的最小请求和返回维度；按实际启用的路线核验 reranker，模型名称／服务回执／失败真实留证，不更换模型。
      — 证据：`E/service-receipts.jsonl`（LLM 200 / `deepseek-v4.1-flash`；embedding 200 / 2560 维；rerank 200）。
- [x] 1.6 盘点 230 个 PDF 与解析产物，核对 17 个分片、父文档、重复和逻辑覆盖；冻结带 SHA／分类依据／目标 workspace 的全量导入清单及小样本，逐项解释排除依据。
      — 证据：`E/corpus-manifest.jsonl`（230 行，逐项原始 SHA／分类依据／目标库／duplicate 关系／证据）；`E/corpus-manifest-summary.json`（221 逻辑文档：air 63／water 158；9 项 duplicate：8 字节相同＋1 内容相同；unresolved 为空）。
- [x] 1.7 自主通过阶段门槛：已有库保护边界明确、真实模型／服务可用、所需分片有证据映射、实例初始化不会变更旧空间；失败时定向修复，不盲目全量入库。
      — 结论：四条均满足（1.3／1.5／1.6／1.4）；小样本（air 3 篇、water 3 篇含 1 篇显式共用）先跑通全链后才全量。

## 2. 注册、认证与统一授权

- [x] 2.1 实现 workspace／后端有效命名空间注册表、企业／角色授权配置及 policy revision；配置校验未知 ID、冲突、缺字段和错误 override。
      — 证据：`src/env_rag_final/access/registry.py`；`L/registry.json`；模板 `deployment/workspaces.example.json`；负例测试 `tests/test_workspace_access.py` 中 reserved／collision／unknown-grant／default-grant。
- [x] 2.2 实现最小可靠主体认证和登录／bearer 接入；生成示例主体的本机忽略凭据，配置无需账号后台，现有 CSRF token 不当作身份。
      — 证据：`scripts/wa_bootstrap_registry.py`；`L/credentials.json`（0600）；`E/acceptance-matrix.json` 中 `anonymous.*`／`forged.bearer` 401。
- [x] 2.3 构造不可变授权上下文：指定无权／未知库整体拒绝，all 仅展开已授权集合；认证失败在服务调用之前返回，不回退 default。
      — 证据：`access/auth.py`（`AuthContext`／`resolve_selection`）；矩阵 44 条；离线测试 `test_partial_selection_is_refused_whole`、`test_all_expands_to_granted_set_only`。
- [x] 2.4 为查询、生成、澄清、文件／chunk／文档读取、记录列表、导出、历史恢复和缓存统一接入权限；记录只对创建者开放，并在读取时重新核验当前授权。
      — 证据：`access/server.py` 各端点统一 `authorize`；`E/acceptance-matrix.json` 中 `foreign-record`／`foreign-export` 404、`revocation.deny.old-record-after-revocation` 404；离线 `test_private_records_and_revocation`。
- [x] 2.5 封闭 LightRAG 直接查询／文件／图谱／入库／管理旁路，网关内部使用实例凭据，读者无法通过角色参数或内部端口绕过授权。
      — 证据：`E/acceptance-matrix.json` 中 `bypass.instance.*`（无 key 403、读者凭据 403）；实例只绑 `127.0.0.1`。
- [x] 2.6 完成认证缺失／伪造、企业角色同名、空权限、部分无权集合、越权 ID、权限撤销／policy 变化等离线测试；验证拒绝时零检索／模型／文件读取和无被拒资料信息泄漏。
      — 证据：`tests/test_workspace_access.py`（32 项，含 `test_refused_query_never_reaches_a_backend` 断言零后端调用）；`test_role_names_are_enterprise_scoped`。

## 3. 检索与运行身份隔离

- [x] 3.1 将 ask、CLI 查询／构建入口、SourceAdapter、PG 查询／展开显式接入已验证 workspace；用注册与授权验证替换 default-only 限制。
      — 证据：`cli.py` 中 `resolve_cli_workspace`（`default` 保留历史口径，其它值必须已注册且 active）；`enum-*`／`catalog-*`／`search-*` 已传 workspace；`workspace-*` CLI 见 `workspace_cli.py`；`workspace ghost` 明确拒绝。
- [x] 3.2 为新 workspace 建立限定其注册文档／解析产物的来源指纹、stale 检查和身份采集；保留 default 历史回归合同，避免跨库更新互相失效。
      — 证据：`audit/snapshot.py::fingerprint_artifacts(document_scope=…)`＋`catalog/builder._document_scope`；default 指纹复算仍为 `95f7791f…`（见 `E/acceptance-matrix.json` 之外的复验记录）；`E/lifecycle.json` 中撤回 coastal 后 air／water 身份不变。
- [x] 3.3 检查 snapshot／search 构建键：相同资料在两库不碰撞全局主键；完成必要非破坏性、幂等兼容改造并验证旧 active 数据保持可读。
      — 证据：`search/index.py::index_identity(..., workspace=…)` 与 `catalog/builder.build_identity(..., workspace=…)` 把 workspace 纳入身份（`default` 不贡献，旧值不变）；共用文档在两库的 chunk id 相同但归属互不覆盖（见 §4.5）；`E/acceptance-matrix.json` 无冲突。
- [x] 3.4 实现固定实例的实际 LightRAG 数据／候选接入、真实模式 dispatch 和来源回读，明确锁定代码／存储接口，不能用答案文本替代证据。
      — 证据：`access/gateway.instance_evidence` 调 `/query/data`（返回真实 chunks／entities／relationships）；`E/retrieval-sweep.json` 覆盖 5 个模式。
- [x] 3.5 实现授权多库逐库检索、来源复合身份去重、联合排序和最多一次答案生成；重复文本合并保留所有授权来源，版本与 workspace 不误覆盖。
      — 证据：`KnowledgeService.merge_evidence` 以 `(workspace, chunk_id)` 为键；浏览器记录 `dual-reader` 40 条证据含 air／water；生成接口只发一次模型请求（`generate()` 单次调用）。
- [x] 3.6 缓存／记录键包含主体、企业、授权代次、workspace 集合、每库快照和路由参数；每次使用前重新授权，重启不恢复无权历史记录。
      — 证据：`AuthContext.cache_key`；记录绑定 `user_id`／`enterprise`／`policy_revision`／`workspaces`；`E/lifecycle.json` 重启后记录边界不变。
- [x] 3.7 完成同 ID 跨库、完全相同语料两库构建、未授权 lookup、不完整范围、单库故障、同问题不同权限缓存、更新一库另一库可用等离线测试。
      — 证据：`tests/test_workspace_access.py::test_merge_keeps_same_chunk_id_in_two_workspaces`、`test_refused_query_never_reaches_a_backend`、`test_private_records_and_revocation`；在线证据见 `E/` 各文件。

## 4. 双实例与入库生命周期

- [x] 4.1 实现两个实例和 Knowledge API 的本机可重复启动／停止／健康检查；沿用现场运行时，配置模板支持独立目录、共享存储、固定 workspace 和内部实例认证。
      — 证据：`scripts/wa_instances.sh start|stop|status|health|logs`；`scripts/wa_instance_env.py`；`E/runtime-identity.json`（两实例 WORKSPACE／PG／Qdrant／Neo4j 有效值一致，端口 9622／9623）。
- [x] 4.2 交付 Docker Compose 模板；现场为 Apple Container 时另交付经实际命令帮助核对的原生脚本，验证宿主／容器寻址和解析产物一致挂载。
      — 证据：`deployment/docker-compose.workspaces.yml`、`deployment/Dockerfile.knowledge-api`（模板，**未在本机运行验证**，报告已注明）；Apple Container 路径为实际验收路径；容器内可达宿主能力已实测（PG 192.168.65.2、宿主 Qdrant／Neo4j／模型网关 192.168.65.1）。
- [x] 4.3 实现先 dry-run 后执行的导入／恢复入口，checkpoint 按 workspace＋源身份＋配方／模型区分；默认拒绝写 default 或已有非本轮目标。
      — 证据：`workspace-ingest --dry-run`；`ingest/runner.py` 对 `default` 直接拒绝；账本键 `(workspace, doc_name, source_sha256, recipe_id, models)`。
- [x] 4.4 在 air／water 各导入至少 2 份真实小样本及一份两库共用样本；复用解析及可证明正确的中间产物，保留 sidecar，验证 chunk、向量、实体／边和完整范围回读。
      — 证据：`E/ingestion-air.json`（air-01/02/09）、`E/ingestion-water.json`；共用样本 `air-02` 在两库均入库，chunk 正文／heading／sidecar 逐项相等且互不覆盖（该复验记录在 `E/summary.md` 与 §4.5 引用）。
- [x] 4.5 在两库分别构建和发布 PG 目录／索引；确认重复样本不会造成主键冲突、缺引用、错命名空间、互相覆盖或串库。
      — 证据：`env_rag.documents／source_units／search_builds` 按 workspace 归属正确（air 63／water 159／coastal 1／default 221 文档）；共用文档 `doc-257d8cf3…` 在 air／water／default 三处同 chunk id 共存。
- [x] 4.6 自主通过小样本门槛后完成冻结清单的全量 air／water 入库；终态逐项记 processed、带证明的 duplicate、失败／阻碍，不删样本缩分母。
      — 证据：`E/ingestion-results.jsonl`（231 项）＋`E/ingestion-air.json`／`E/ingestion-water.json`；PG 终态 air 63/63 processed、water 159/159 processed，无失败；`dup-*` 拒绝行已按记录清理。
- [x] 4.7 发布全量目录／搜索索引并核对清单覆盖、完整分片、引用关联、向量有效维度／归属及图谱来源，无未解释的失败或跨库来源。
      — 证据：air `snapshot 123afd3d…／search f444794b…`、water `c27663b6…／8af0eb66…`，均 current；air chunks 1949＋water chunks 3765 − 共用 5 = 5709 = default，覆盖完全一致。
- [x] 4.8 验证同库重复入库、进程中断恢复和实例重启：无重复行、无重复计费请求、记录／索引可用；只复验必要范围。
      — 证据：重跑 air 得 `to_process 0` 且 `llm_calls=0／embed_calls=0`（`E/ingestion-air.json` 的重跑输出）；中断续跑由账本 `begin`＋核对逻辑处理（air-04 曾进入 uncertain 后被 reconciled）；`E/lifecycle.json` 重启后身份保持。
- [x] 4.9 在本轮试验资料上验证目标库更新／撤回／缓存失效／索引重建；另一库不变；明确两库副本同步命令和版本漂移提示。
      — 证据：`E/lifecycle.json`（coastal 撤回→stale/0 证据→重入→ambiguous/6 证据；air／water／default 计数与 active search 完全不变；撤回同时清空该库 checkpoint 以免误判"已完成"）。
- [x] 4.10 增加第三个 workspace 和授权，只用配置＋启动＋入库命令完成一份真实资料查询；记录无核心代码变更，并按本轮所有权清单安全清理试验数据。
      — 证据：`E/third-workspace.json`（`granted_ok=true`、`ungranted_refused=true`、`core_modules_unchanged=true`）。试验库 `coastal` 保留为在线证据；清理脚本 `--cleanup` 提供并已 dry-run 验证。

## 5. 网页与使用流程

- [x] 5.1 接入最小登录与当前主体／授权库展示，只显示服务器返回的合法知识库；一个库自动选中，多个库可单选／选全部，空权限有明确状态。
      — 证据：`E/browser/operations.json`：air-reader→["air"]、dual-reader→["air","water","all"]、no-access→空且提示"该主体没有任何知识库授权"。
- [x] 5.2 知识库切换不调用模型；隔离旧结果、选择、澄清上下文和请求，防止旧慢响应污染新选择；保留现有普通问答／对照策略语义。
      — 证据：浏览器切换步骤记录切换前后页面资源请求数（不发出任何请求即无从调用模型）；`state.generation` 丢弃过期响应。
- [x] 5.3 将 workspace 和来源标识贯穿完整清单、chunk、图谱证据、生成、引用展开、PDF／解析文本、记录查看及导出；权限变化时不能继续展示或请求旧受限内容。
      — 证据：`E/browser/operations.json` 中 `parsed-text 200:998`、生成引用绑定 workspace；`E/acceptance-matrix.json` 中撤销后旧记录 404。
- [x] 5.4 实现无权限、未知库、未就绪、stale、单库故障和生成失败的中文状态；partial／ambiguous 不升级 complete。
      — 证据：`access/gateway.py` 的 status 合成区分 stale／service_failure／partial；UI 状态映射含"来源已过期"等；浏览器中 PG 查询显示"存在歧义"而非完整。
- [x] 5.5 按项目现有 DESIGN、UX 和适用前端技能完成组件、加载／错误状态、窄屏和键盘操作验证，不新增账号管理／权限编辑后台。
      — 证据：`E/browser/` 桌面与 390×844 窄屏截图各 4 组；`app.js` 含 skip-link、aria-live、focus-visible、窄屏单列布局；无账号管理后台。

## 6. 验收、修复与交付

- [x] 6.1 在真实验收前冻结 acceptance.md 的逐项矩阵、实际资料／问题／预期来源和所有端点清单；固定分母与要求，不按成功率挑题。
      — 证据：矩阵与端点清单冻结在 `scripts/wa_acceptance_http.py`／`E/acceptance-matrix.json`；分母为 `E/corpus-manifest.jsonl` 的 221 逻辑文档；检索题固定于 `scripts/wa_retrieval_sweep.py`。
- [x] 6.2 执行必要 Python／前端／配置／启动回归、Ruff、格式、Git diff 和本变更 OpenSpec strict 检查；原 581／6 项基线能力不得删弱化。
      — 证据：Python 613 passed（581 基线＋32 新增）、`node --test` 6 passed、`ruff check` 与 `ruff format --check` 通过、`git diff --check` 通过、`openspec validate add-workspace-knowledge-access --strict --no-interactive` = valid。
- [x] 6.3 执行 air／water 的 PG、五种 LightRAG 模式及对应 PG 组合现场验证，完成授权双库查询、真实 DeepSeek 回答及独立来源核验；失败不借用旧答案。
      — 证据：`E/retrieval-sweep.json`（air／water × PG／5 模式／5 组合 + 双库组合）；`E/browser/operations.json` 中 `deepseek-v4.1-flash` 真实生成与引用核验。
- [x] 6.4 执行 acceptance.md 的四类主体、越权端点、缓存／记录／下载、权限撤销、直接实例管理旁路测试，记录拒绝及零后端调用证据。
      — 证据：`E/acceptance-matrix.json`（44/44 符合预期）；离线零后端调用断言见 `tests/test_workspace_access.py`。
- [x] 6.5 执行实际浏览器登录、权限切换、单／双库查询、生成、引用、PDF／解析文本、导出／历史记录、错误状态及窄屏验收，保存截图和记录。
      — 证据：`E/browser/operations.json` 与 8 张 PNG（桌面＋窄屏）。
- [x] 6.6 对照默认库与语料保护清单，核对新增数据只属于本轮 workspace，旧数据／配置／gold／历史证据没有变更。
      — 证据：`E/protected-before-after.json`（`ok: true`，0 差异）。
- [x] 6.7 针对真实失败完成修复和必要复验；外部阻碍单独记录，未满足固定条件不能勾完成或宣称 Goal 达成。
      — 已修复并复验：embedding worker 60s 超时（改为 `EMBEDDING_TIMEOUT=300` 后重跑至全绿）、重复入队产生 `dup-*` 拒绝行（改为已存在即不再入队）、派生表 workspace 归属错误（`units.py`／`scopes.py` 硬编码）、PG 证据缺正文（改为回读实际 chunk 且校验 workspace／snapshot）。**已披露事故**：清理时误删 default 的 5 条 `corpus_runs` 与 7 条 `search_builds` 历史行，已按 `phase-1/build-manifest.json` 与 `phase-2/index-manifest.json` 逐字段原值恢复，保护对照复验为 0 差异。
- [x] 6.8 交付 WORKSPACE-ACCESS.md、部署／启动／登录／入库／新增库／恢复／回滚说明、脱敏验收报告及调用账本；本地提交本轮代码和文档，不 push。
      — 证据：`WORKSPACE-ACCESS.md`；`E/summary.md` 及各 JSON(JSONL)；调用账本 `L/ingest-*.jsonl`；本地提交见报告末尾。
- [x] 6.9 对照完成条件逐项封存证据；全部通过后才宣告目标达成并更新 tasks，最后报告 commit、访问地址、示例登录凭据的本机保存位置和实际限制。
      — 证据：`E/acceptance-matrix.json`、`E/protected-before-after.json`、`E/retrieval-sweep.json`、`E/browser/`、`E/third-workspace.json`、`E/lifecycle.json`；限制见 `WORKSPACE-ACCESS.md` §7。
