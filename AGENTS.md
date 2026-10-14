# AGENTS.md

给在本仓库工作的 AI/人类协作者的约定。先读 [README.md](README.md) 了解项目，本文件只讲规则。

## 当前事实（不要被历史资料误导）

- **当前网页入口是 8099**：`python -m env_rag_final.access`（登录、分库授权）。`src/env_rag_final/web/`（8091）是无登录的历史对照工具，启动还依赖仓库外的隔壁 LightRAG checkout，不要把两者混为一谈。
- 演示账号以根目录 [ACCOUNTS.md](ACCOUNTS.md) 为准；本机可读凭据是 `.local/workspace-access/credentials.md`（Markdown，由 `scripts/wa_bootstrap_registry.py` 生成）。脚本读写凭据统一走 `scripts/wa_credentials.py`，不要再引入 JSON 凭据文件。
- Gate 4 未通过、默认融合未启用；不要宣称融合优于 local。历史结论在 `reports/` 与 `assets/`，引用时必须注明“历史”，不能当成当前状态。

## 常用命令

```bash
uv run env-rag-final doctor --connections            # 只读连通检查
PYTHONDONTWRITEBYTECODE=1 uv run pytest tests -q
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
```

Python 3.12；依赖用 uv 管理并锁定在 `uv.lock`，正式 LightRAG 依赖是 PyPI 的 `lightrag-hku`（1.5.x），不要改成引用本地源码。

## 数据与安全边界（硬性）

- 正式 PG 的 `public`/`rag` 库与 MinerU 产物**只读**；可写结构仅限自有 `env_rag` schema 和自有 workspace（air/water/...）。禁止全局 prune、删库、重建既有卷。
- 不在代码里实例化 LightRAG 存储去连接现有库；查询路径不做存储初始化。
- `.env` 不修改、凭据不落盘到 `reports/`；历史报告里若混入凭据，按 `.gitignore` 已有的单独排除方式处理。
- 所有服务与网页只绑定 `127.0.0.1`；网关拒绝跨站提交，源文件 API 只接受白名单来源，不接受任意本机路径。
- 模型/embedding/rerank 是真实计费调用：测试默认不得触发；需要真实调用时显式标注并最小化次数。评测相关产物不能进答案缓存作弊。

## 结果语义（沿用，不许“降级表述”）

- `complete` 只针对已确认范围的清单完整性；`retrieved`/HTTP 200/`success` 都不等于答案正确。
- `stale/partial/ambiguous/missing` 不调用答案模型；缺版本不用邻居版本替代；引用必须能回到来源连续片段。
- 精排失败保原序并记录真实回执，不伪造分数；枚举完整集合不受 top-k 截断。

## 文件组织约定

- `assets/` 只放**已结束探究线索**的叙述文档（旧网页、PG 检索研究、维护记录），附 `assets/README.md` 索引；移动文档时同步修复引用（注意 `src/env_rag_final/access/snapshot.py` 的 `PROTECTED_FILES` 清单）。
- `reports/` 是逐轮证据，按代次目录自组织，不混合覆盖、不手改；新克隆不保证包含全部本地审计缓存。
- OpenSpec：完成并验收后的变更移入 `openspec/changes/archive/`；`add-pg-scoped-retrieval` 因 6.2–6.5/Gate 4 未完成，**不归档**。
- `.local/` 全部本机状态，不进 Git；新增本机文件默认放那里。
- 不写 `__pycache__`（测试用 `PYTHONDONTWRITEBYTECODE=1`），不提交 `.DS_Store`。

## 提交

提交信息面向公开仓库，不写真实主机名、绝对路径或凭据。用户未明确要求时不要替用户 commit。
