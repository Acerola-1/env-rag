# connect-knowledge-remote-iam 验收报告（本轮 I3 实施）

状态：**待独立验收**（本轮不 commit / push / merge / archive，不切换 8099，不改共享 IAM 与正式资料库）。
实施者：本轮 I3 实施（未提供编号）。
运行标识：`i3-20261016-224525-local`（见 `.local/iam-acceptance/CURRENT_RUN_ID`）。
产品起点：`1aa52b04976a94ad6e969775ced07cf1828ca81e`（dev）。

## 1. 改动清单

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `src/env_rag_final/access/remote.py` | 新增 | IAM 严格分型校验（human/machine 分离）、显式映射解析、500ms 总预算客户端、失败关闭错误语义 |
| `src/env_rag_final/access/providers.py` | 新增 | `LocalProvider`（原注册表语义，0 IAM 请求）与 `RemoteProvider`（核验、映射∩就绪、会话、SSO、CAS 切企业、逐边界复核） |
| `src/env_rag_final/access/auth.py` | 改 | `AuthContext` 变为显式模式上下文（mode/principal_type/tenant/permissions/context_version/directory_version），保留 local 旧构造兼容与 `cache_key` 前三元组语义 |
| `src/env_rag_final/access/gateway.py` | 改 | `check_context`/`workspace_snapshots` 异步化并逐调用者 await；记录增加主体类型/企业/目录/权限；拒绝 `default` 命名空间与未授权库 |
| `src/env_rag_final/access/server.py` | 改 | 模式化 HTTP 面：remote 登录/退出/企业列表/CAS 切企业/SSO start+callback；401/403/404/409/503 分类；生成前后与文件读取边界复核；`/api/me` 支持未选企业状态 |
| `src/env_rag_final/access/__main__.py` | 改 | `ENV_RAG_AUTH_MODE=local\|remote` 启动固定；remote 缺配置即失败退出，不回落 local |
| `src/env_rag_final/access/static/app.js`/`index.html` | 改 | remote 企业必选、epoch/generation 守卫、SSO 入口、刷新恢复会话（`/api/me` 引导）、错误码文案（含 503/409） |
| `tests/test_remote_iam.py` | 新增 | K01–K06 契约（用 G0 冻结的真实 IAM 响应做正例，逐字段变异做反例）45 项 |
| `tests/test_remote_boundaries.py` | 新增 | K07–K11 数据出口边界 13 项 |
| `tests/test_remote_http.py` | 新增 | 真实 aiohttp 面 13 项 |
| `tests/test_remote_page.cjs` | 新增 | 页面契约 5 项（企业必选、迟到结果、令牌不入 JS、错误映射） |
| `tests/test_workspace_access_races.cjs` | 改 | 适配页面启动时 `/api/me` 引导：该请求在夹具中直接 401，断言与场景未变 |
| `deployment/remote-iam.example.env`、`deployment/remote-iam.mapping.example.json` | 新增 | remote 配置模板（仅字段形状） |
| `src/env_rag_final/access/__main__.py`（守卫） | 改 | remote 模式禁止使用本地默认记录根（见 §4.1） |

差异规模：7 个已跟踪文件改动（+813 / −162 行）、6 个新测试/配置/模块文件。`git diff` 保留原样待独立验收。

## 2. K01–K15 结果矩阵

图例：**实测**=本轮真实运行；**离线**=仓库内可离线复跑；**受控**=脚本化 IAM/哨兵后端；**未覆盖**=明确未做。

| ID | 正向控制 | 反例（必须拒绝/保持） | 证据 | 结论 |
| --- | --- | --- | --- | --- |
| K01 | local 启动、原 633 基线全部保持；remote 有效配置启动 | 非法模式退出 1；remote 缺 IAM URL/映射文件退出 1 | `g1-startup/local.log`、`remote-missing.log`、`bad-mode.log`、`remote-badmap.log`；`test_remote_iam.py::test_unknown_mode_is_rejected` | 通过 |
| K02 | 真实机器/人类响应通过严格校验 | 错 schema/issuer/audience/主体类型、bool 修订、机器套人类字段、人类套机器字段、非 UUID、未知字段全部拒绝 | 45 项契约测试；正例取自 `.local/iam-acceptance/<run>/g0-probes/*.json`（真实 IAM 响应冻结） | 通过 |
| K03 | IAM 恢复后同一凭据再次成功 | IAM 网络故障→503、每请求 1 次核验（无正向缓存）、超时→503 且后端 0 | `g1-live/results.json` 29/29；`g4-live/perf.json.sequential.per_operation_calls=1.0`、`authorization_calls.per_request=1.0`；`test_remote_boundaries.py::test_iam_timeout_maps_to_503...` | 通过 |
| K04 | 机器精确读码→映射库（air/water/beta） | 无权库、无映射库、错受众、客户端未注册受众、垃圾令牌均拒绝且后端 0 | `g1-live/results.json`；`g2-live/results.json`（water 机器在 coastal-only 映射下 403） | 通过 |
| K05 | 显式映射∩技术就绪生成工作区集合 | 未映射资源不产生授权；`default`/保留命名空间、非 UUID 键、重复资源映射在加载期拒绝 | `test_remote_iam.py::test_mapping_rejects_non_uuid_and_reserved_keys`、`test_unmapped_resource_yields_no_access`；`g2-live` 中映射外知识库不可见 | 通过 |
| K06 | `all` 只展开有权且就绪库 | 显式混合（有权+无权/未映射）整体 403、不裁剪；无库主体 `all` 403 | `test_remote_iam.py::test_selection_all_expands_only_granted_and_ready`；`g2-live`「explicit coastal+air」403 且后端增量 0 | 通过 |
| K07 | 查询/生成在真实 PG 上工作 | 撤销后缓存命中也不放行（每入口重新核验）；生成中切企业则结果不回送、不落盘 | 13 项边界测试（`test_authorization_is_recomputed_even_when_the_answer_is_cached`、`test_generation_rechecks_before_and_after_the_model_call`、`test_cached_flag_does_not_bypass_checks`）；HTTP 面 `test_iam_outage_returns_503...` | 通过（受控 IAM 注入） |
| K08 | 撤销后无许可、重新开通后恢复 | 永久吊销/停用/过期不复活；A→B→A 后旧上下文拒绝 | `test_revoked_machine_cannot_revive_and_reopen_restores_access`、`test_aba_switch_back_does_not_reuse_the_old_binding`；`g3-live/results.json`（真实 IAM 状态变化 + 新纪元） | 通过 |
| K09 | 本人当前企业记录/缓存/导出可读 | 同名不同主体类型/企业/模式不可命中；读记录重新复核来源 | `test_record_store_owned_filters_by_principal_type_and_tenant`、`test_record_reuse_requires_the_same_principal_type_and_tenant`、HTTP 面 `test_records_require_a_matching_principal_type`；`g2-live`（真实记录 保存→复读→导出无凭据残留） | 通过 |
| K10 | 证据全文/文档/PDF 合法读取 | 其他库、遍历 id、缺清单指纹即 404，读取前拒绝 | `test_source_files_are_guarded_by_workspace_and_registry`；`g2-live`（`document id` 同值跨库不合并、未授权命名空间 404）；浏览器实测证据全文 6113 B、导出 110 KB | 通过（PDF 下载依赖冻结清单，真实 PDF 读取仅在授权记录内） |
| K11 | 真实 PG 只读检索正确路由（coastal 命名空间） | 不回 default、不初始化存储、只读连接拒绝写 | `g2-live/results.json` 21/21；`g4-live/perf.json.corpus_fingerprint.read_only_enforced=true` | 通过（PG 路由）；LightRAG 实例路径未覆盖，见 §5 |
| K12 | 真实 IAM 人类会话、SSO 303+ticket/state、企业选择 | 未选企业不得查询；错 state/重放 ticket/未注册回调拒绝；机器无切企业 | `g3-live/results.json` 18/18（真实 303、state 原样、重放 401、错 state 401、未注册回调 400）；`g3-sso-browser/sso-browser-log.json`（SSO 落地→企业必选→查询 8 条）；HTTP 面 `test_human_without_tenant_selection_is_forbidden` | 通过 |
| K13 | 桌面 1280×900 与 390×844 登录/选择/查询/记录/下载/刷新 | 迟到结果不串（epoch/generation 守卫）、无 CSRF 403、切企业 CAS 409、IAM 故障 503、未认证 401 | `g3-browser/browser-log.json` + 6 张截图；`test_remote_page.cjs` 5 项；`g3-sso-browser/sso-after-login.png` | 通过（Origin 伪造由浏览器剥离，服务端跨站拒绝见 HTTP 面测试） |
| K14 | 703 项离线通过、Ruff 全绿、node 15 项通过、OpenSpec strict 通过 | 未删断言、未弱化来源检查、未扩大 skip；基线 633 项全部保留 | `00-baseline-nodeids.txt`（633）→`04-final-nodeids.txt`（703，新增 70，丢失 0）；`ruff check`/`format --check`；`openspec validate --strict` | 通过 |
| K15 | 差异/秘密/性能/资源清单齐全 | 正式 PG/Qdrant/Neo4j 只读；token/内部密钥不入报告与页面；未用 helper 延迟冒充端到端 | §3 性能表、§4 资源与秘密、`corpus_fingerprint`、`test the IAM token never enters page state or storage` | 通过 |

### 性能与身份开销（真实 IAM，暖连接，受控传输）

并发 1/10/30 各 100×3（受 IAM 内部端点 600/60s 限流约束以 8 rps 采样）：

| 并发 | P50 (ms) | P95 (ms) | P99 (ms) | 错误 |
| --- | --- | --- | --- | --- |
| 1 | 12.2–14.0 | 15.0–17.9 | 15.5–22.1 | 0 |
| 10 | 10.9–11.6 | 13.6–36.1 | 15.0–324.4 | 2× `RemoteDeadlineError`（>500ms 预算，失败关闭→503） |
| 30 | 9.9–10.4 | 12.1–12.8 | 12.6–29.0 | 0 |

连续 50 次：**每操作 1.000 次 IAM 调用**（均值 6.9 ms）；受保护请求 5 次 → 5 次核验（**正向授权零缓存**）。真实检索/模型未做重复压测；模型调用次数见 §5。

## 3. 真实 / 受控 / 未覆盖范围

- **真实**：隔离 IAM（自有副本 `8da8ba1` + 自有 PG/Redis 容器 + 501xx 段端口）、真实 PostgreSQL 只读语料（air 63 / water 159 / coastal 1 篇 `lightrag_doc_full`）、真实浏览器（Edge CDP，桌面与 390×844）、真实 SSO 303/ticket/state 协议。
- **受控**：失败关闭与"后端增量 0"用哨兵后端（关闭端口 5099，`ConnectionRefusedError` 证明授权已放行但到不了数据面）与脚本化 IAM（注入撤销/切企业/网络故障）；这些场景的**响应形状**仍取自 G0 冻结的真实 IAM 响应。
- **未覆盖 / 受阻**：
  1. **真实模型生成**：模型网关 `127.0.0.1:8787` 本轮未运行，`/api/generate` 的真实调用未发生（0 次、0 费用）。复跑命令：启动该网关后执行 §5 的 `g2_live_harness.py --generate`（脚本已留位）。配置模型名未替换（仍为 `deepseek-v4.1-flash`）。
  2. **LightRAG 实例路径**：`air`/`water` 容器在容器网络重排后，实例自身配置指向的宿主/存储地址失效（已修正 `.local/workspace-access/env/lightrag-*.env` 的宿主地址，未改镜像与数据）；`route=lightrag`/`pg+lightrag` 与实例身份校验未在本轮 remote 证据中出现。已确认共享 PG/Qdrant/Neo4j 容器仍在运行且语料未变。
  3. **8099 正式切换、历史账号/记录迁移、与 I2 的生产组合**：不在本轮授权内，未做。
  4. `tenant_epoch`/CSRF 轮换仅在自有 IAM 语义下验证；真实生产 IAM 的客户端注册清单需在切换前另行核对。

## 4. 资源所有权、秘密位置与原库指纹

- **自有容器**：`i3-pg17`（127.0.0.1:50232，卷 `i3-pg17-data`）、`i3-redis7`（127.0.0.1:50279，卷 `i3-redis7-data`）；IAM 服务 127.0.0.1:50200；remote 网关 127.0.0.1:50202（本轮另起，不占用 8099）。
- **只读引用**：`lightrag-postgres`/`lightrag-qdrant`/`lightrag-neo4j`（正式语料容器，仅读；本轮未对其执行写、prune、drop、TRUNCATE 或卷重建）。
- **秘密位置（均 0600，位于 git 忽略目录）**：`.local/iam-acceptance/<run>/credentials.md`（夹具口令与机器 bearer）、`iam-env/.env`（IAM 与消费者客户端秘密）、`iam-env/remote-mapping*.json`、`iam-env/*.sql`。报告与页面不含任何秘密；浏览器实测断言 `localStorage`/页面状态中无 `access_token`/`subject_token`。
- **原库指纹**（`g4-live/perf.json`，只读事务）：
  - air：doc_full 63 行 / 7,509,987 B / md5 `4b73fd45…`；chunks 1949 行 / 7,523,792 B / md5 `706bf7ab…`；status 63 行。
  - water：doc_full 159 行 / 12,231,104 B / md5 `557b3194…`；chunks 3765 行 / 12,363,985 B / md5 `6e8d6232…`；status 159 行。
  - coastal：doc_full 1 行 / 15,739 B / md5 `d10ed6cb…`；chunks 8 行 / 15,716 B / md5 `fddcd864…`；status 1 行。
  - 与本轮 G0 首次读取的行数一致；`read_only_enforced=true`（连接无法建表）。仓库内没有 2026-10-16 之前的逐行校验和基线可供逐字节对比，故此处给出**本轮首末一致 + 只读强制**，不宣称跨轮字节相等。
- **配置改动**：`.local/workspace-access/env/lightrag-{air,water,coastal}.env` 中的宿主地址由 `192.168.65.x` 更新为当前容器网络网关 `192.168.66.1`（备份见 `<run>/lightrag-air.env.bak`）；镜像、命名空间与语料未改。

### 4.1 过程记录：一次记录根越界（已修正）

首次启动 50202 remote 网关时未显式指定 `--record-root`，浏览器验收写入的 2 条远端记录落到了本地记录根 `.local/workspace-access/records/`。发现后已将这 2 个文件移出到 `.local/iam-acceptance/<run>/g3-browser/records-leaked-to-local-root/`（原内容保留，本地根恢复为 0 条本轮文件），并在 `__main__.py` 增加启动守卫：remote 模式使用默认本地记录根时直接拒绝启动（`ensure_isolated_record_root`，含回归测试）。后续 remote 启动命令见 §5。

## 5. 复跑与入口

```bash
# 1) 启动自有 IAM 基础设施（PG/Redis）
/usr/local/bin/container start i3-pg17 i3-redis7
# 2) 启动隔离 IAM（带自有 .env）
( cd .local/iam-acceptance/<run>/iam-src/server && \
  java -jar target/iam-server.jar ) &   # 需先 source <run>/iam-env/.env
# 3) remote 网关（独立记录根，不覆盖 8099）
ENV_RAG_AUTH_MODE=remote \
ENV_RAG_IAM_URL=http://127.0.0.1:50200 ENV_RAG_IAM_ISSUER=air-agent-iam \
ENV_RAG_IAM_CLIENT_ID=... ENV_RAG_IAM_CLIENT_SECRET=... \
ENV_RAG_IAM_MAPPING=.local/iam-acceptance/<run>/iam-env/remote-mapping-real.json \
.venv/bin/python -m env_rag_final.access --port 50202 --iam-mapping <同上> \
  --record-root .local/iam-acceptance/<run>/remote-records   # remote 必须显式指定

# 4) 证据复跑
.venv/bin/python .local/iam-acceptance/tools/g1_live_harness.py --env <run>/iam-env/.env --run-dir <run> \
  --registry .local/workspace-access/registry.json --out <run>/g1-live/results.json
.venv/bin/python .local/iam-acceptance/tools/g2_live_harness.py --env <run>/iam-env/.env --run-dir <run> \
  --registry .local/workspace-access/registry.json --values-env .env \
  --mapping <run>/iam-env/remote-mapping-real.json --out <run>/g2-live/results.json
.venv/bin/python .local/iam-acceptance/tools/g3_sso_harness.py --env <run>/iam-env/.env --run-dir <run> \
  --registry .local/workspace-access/registry.json --out <run>/g3-live/results.json
.venv/bin/python .local/iam-acceptance/tools/g3_browser_remote.py --base http://127.0.0.1:50202 \
  --run-dir <run> --out <run>/g3-browser
.venv/bin/python .local/iam-acceptance/tools/g4_evidence.py --env <run>/iam-env/.env --run-dir <run> \
  --registry .local/workspace-access/registry.json --values-env .env --out <run>/g4-live/perf.json
```

## 6. 尚未完成与正式切换前置

1. 真实模型生成（第 3 节 1 项）与 `route=lightrag` 实例路径（第 3 节 2 项）需在模型网关与实例恢复后补测；本报告不把这些格标为通过。
2. 正式 8099 切换、历史 UUID/记录映射、与 I2 的生产组合、SSO 客户端在生产 IAM 的注册，均需另行放行与核对。
3. 生产切换前建议：为 remote 记录根单独建目录并纳入备份；确认 IAM 客户端（introspection/SSO/被核验主体）三类凭据互不复用；将 `ENV_RAG_SSO_CALLBACK` 固定为正式回环地址。

## 7. 证据索引（sha256 前 16 位）

| 文件 | sha256(16) |
| --- | --- |
| `.local/iam-acceptance/i3-20261016-224525-local/00-baseline-nodeids.txt` | `a8a069b2923332f5` |
| `.local/iam-acceptance/i3-20261016-224525-local/04-final-nodeids.txt` | `fb18015197ebb471` |
| `.local/iam-acceptance/i3-20261016-224525-local/g1-live/results.json` | `f66c57d16acdd0a9` |
| `.local/iam-acceptance/i3-20261016-224525-local/g2-live/results.json` | `2392491440c50bc0` |
| `.local/iam-acceptance/i3-20261016-224525-local/g3-live/results.json` | `aca4f7893d855d2d` |
| `.local/iam-acceptance/i3-20261016-224525-local/g3-browser/browser-log.json` | `498a7ab582105613` |
| `.local/iam-acceptance/i3-20261016-224525-local/g3-sso-browser/sso-browser-log.json` | `6d6c664888e0edac` |
| `.local/iam-acceptance/i3-20261016-224525-local/g4-live/perf.json` | `a5813f79aca4fb9d` |
| `.local/iam-acceptance/i3-20261016-224525-local/provisioning.log` | `d60678600533d05c` |
| `.local/iam-acceptance/i3-20261016-224525-local/fixtures.json` | `ae236871012a1501` |
