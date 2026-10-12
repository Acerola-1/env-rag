# WORKSPACE-ACCESS — 知识库 workspace 权限交付说明

本文件说明如何启动、登录、入库、新增知识库、恢复与回滚，并给出本轮实际验收的
访问地址、凭据位置与限制。固定验收条件见
`openspec/changes/add-workspace-knowledge-access/acceptance.md`。

## 1. 交付内容一览

| 组件 | 位置 | 说明 |
| --- | --- | --- |
| Knowledge API（网关） | `python -m env_rag_final.access`（默认 `127.0.0.1:8099`） | 唯一面向客户端的知识入口：认证、授权、检索、生成、记录、引用、下载 |
| LightRAG air 实例 | 容器 `lightrag-air`，`127.0.0.1:9622` | 固定 `WORKSPACE=air`，共享 PG／Qdrant／Neo4j |
| LightRAG water 实例 | 容器 `lightrag-water`，`127.0.0.1:9623` | 固定 `WORKSPACE=water` |
| workspace 注册表 | `.local/workspace-access/registry.json`（忽略，模板见 `deployment/workspaces.example.json`） | workspace、主体、角色授权、policy revision |
| 主体凭据 | `.local/workspace-access/credentials.json`（0600，忽略） | 示例主体口令与 bearer token |
| 实例内部凭据 | `.local/workspace-access/instance-keys.json`（0600，忽略） | 只有网关使用 |
| 入库清单 | `reports/workspace-access/wa-20261012-r1/corpus-manifest.jsonl` | 230 份 PDF 的 SHA、分类依据、目标库、duplicate 关系 |
| 入库账本 | `.local/workspace-access/ingest-<workspace>.jsonl` | 逐项 checkpoint，可恢复 |
| 验收证据 | `reports/workspace-access/wa-20261012-r1/` | 矩阵、浏览器记录、快照对比、报告 |

容器启动方式沿用现场 Apple Container（`scripts/wa_instances.sh`）；另有
`deployment/docker-compose.workspaces.yml` 模板供有 Docker 的环境使用。

## 2. 启动与停止

```bash
# 共享存储（现场既有容器）
container system start            # 若容器服务未运行
container start lightrag-postgres
container start lightrag-qdrant
container start lightrag-neo4j

# 两个 LightRAG 实例（首次会创建，之后为启动）
bash scripts/wa_instances.sh start
bash scripts/wa_instances.sh status
bash scripts/wa_instances.sh health

# 生成实例环境文件（含密钥，写入忽略目录）
.venv/bin/python scripts/wa_instance_env.py

# Knowledge API
.venv/bin/python -m env_rag_final.access --port 8099
curl -s http://127.0.0.1:8099/health

# 停止
bash scripts/wa_instances.sh stop
```

实例与网关都只绑定回环地址。`lightrag-*` 实例需要内部 API key 才能查询，客户端
拿不到的路径（见 §6）。

## 3. 登录与示例主体

浏览器打开 <http://127.0.0.1:8099>，输入主体与口令。CLI／Agent 使用 bearer：

```bash
TOKEN=$(python3 -c "import json;print(json.load(open('.local/workspace-access/credentials.json'))['dual-reader']['bearer'])")
curl -s -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"workspace":"all","question":"空气质量标准与地表水环境质量标准","route":"pg"}' \
  http://127.0.0.1:8099/api/query | head -c 400
```

示例主体（口令与 bearer 只保存在本机 `.local/workspace-access/credentials.json`）：

| 主体 | 企业 | 角色 | 授权知识库 |
| --- | --- | --- | --- |
| `air-reader` | alpha-env | air-reader | air |
| `water-reader` | alpha-env | water-reader | water |
| `dual-reader` | alpha-env | environment-reader | air, water |
| `no-access` | alpha-env | guest | （无） |
| `beta-reader` | beta-env | air-reader | water |

`beta-reader` 说明角色名在企业范围内解释：同名角色在 `beta-env` 授予的是 water。

## 4. 入库／恢复／增量

```bash
# 冻结清单（可重复生成，确定性）
.venv/bin/python -m env_rag_final.cli workspace-manifest \
  --out reports/workspace-access/wa-20261012-r1/corpus-manifest.jsonl --default-pg

# 先 dry-run（只打印计划，不写任何后端）
.venv/bin/python -m env_rag_final.cli workspace-ingest --workspace air --dry-run

# 正式入库（可中断后重跑：已完成的项不会重复入库，也不会重复计费）
.venv/bin/python -m env_rag_final.cli workspace-ingest --workspace air --process-rounds 6 \
  --set EMBEDDING_TIMEOUT=300

# 发布该库的 PG 目录与搜索索引
.venv/bin/python -m env_rag_final.cli workspace-catalog --workspace air
.venv/bin/python -m env_rag_final.cli workspace-index  --workspace air

# 身份与就绪状态
.venv/bin/python -m env_rag_final.cli workspace-health --workspace air
.venv/bin/python -m env_rag_final.cli workspace-stale  --workspace air
```

恢复语义：账本用「先写 `begin`，完成再写终态」的写前日志。进程在 `begin` 之后、
终态之前中断的文档属于 **uncertain**：下次运行先在目标库核对 `doc_status`，确认
成功则记为 `done`（注明 reconciled），未成功则重新入库。外部模型调用不宣称
exactly-once。

重复与排除：清单里字节相同（`_001` 副本）或解析内容相同的项记为 `duplicate` 并
指向被保留的原文；无法证明归属的项记 `unresolved`（本轮为空）。

## 5. 新增第三个知识库（只用配置与入库）

1. 在 `.local/workspace-access/registry.json` 的 `workspaces` 增加一项，给出唯一
   的非保留命名空间（`pg_workspace`／`vector_workspace`／`graph_workspace`）、实例
   地址与 `instance_key_ref`；`grants` 里给某个角色分配它。
2. `.venv/bin/python scripts/wa_instance_env.py` 生成新实例环境文件，用
   `scripts/wa_instances.sh` 启动（把新库加入循环）。
3. `workspace-ingest --workspace <新库>` 入库真实资料，再 `workspace-catalog`／
   `workspace-index` 发布。
4. 提高 `revision` 使旧会话与缓存失效；网关会自动热加载注册表。

核心检索代码不需要改动：workspace 只出现在注册表、入库命令与实例配置里。

回滚：停止新实例 → 从注册表 `grants` 移除授权（revision 递增，旧记录立即不可读）
→ 按所有权清单删除该 workspace 的 `lightrag_*` 与 `env_rag.*` 行。**禁止**全局
prune、删库、重建既有卷；`default` 与本轮以外的空间不在此列。

## 6. 权限模型与不可绕过的边界

- 客户端只能表达**选择意图**（`workspace` / `workspaces` / `all`）。服务器用注册表
  计算合法集合；请求里出现任何未知或未授权的库，**整个请求拒绝**，不回退
  `default`，也不“挑其中有权的”。
- `X-Role`、企业参数、网页下拉框都不是身份；CSRF token 只是 CSRF 保护。
- 所有读取（查询、澄清、生成、chunk／文档、PDF／解析正文、记录列表／详情、导出、
  缓存）都走同一授权上下文；记录只对创建者开放，且**每次读取重新核验**当前授权。
- 拒绝发生在检索、模型调用与文件读取**之前**，响应不泄漏被拒库的名称、内容、
  计数或存在性。
- LightRAG 实例是内部面：查询／图／文件／管理接口都要求实例 key，且只绑回环。
  普通读者凭据直接访问实例会被拒绝（见浏览器／HTTP 验收记录）。

## 7. 已知限制

- 权限是**应用层粗粒度知识库授权**：持有数据库或服务器密钥的人不在普通读者威胁
  边界内，本轮不宣称数据库强租户隔离，也未启用 RLS。
- 浏览器已经把数据下载到用户设备后，撤销授权无法远程回收已有副本（本轮不宣称
  远程删除）。
- 图谱按各库自身文档证据重建，不保证与旧 `default` 图谱逐字一致。
- Docker Compose 模板未在本机实际运行验证，仅作为模板交付；本机实际验收的是
  Apple Container 路径。
- 本轮质量结论只覆盖权限与功能链路，不重新评测检索质量，也不宣称融合优于
  local。
