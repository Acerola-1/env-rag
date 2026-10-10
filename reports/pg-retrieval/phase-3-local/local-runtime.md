# 5.2 真实 local 候选适配验证（local-runtime 报告）

日期：2026-10-06。任务：实现并实测调用发布包**真实 local 语义链路**的候选适配器，验证 PG 来源映射与只读接入。5.1 的 fixture/naive 结论不作为真实 local 通过依据；本轮全部候选来自生产 Qdrant/Neo4j 语义检索 + 生产 PG 只读回读 + 真实 embedding/keyword-LLM 服务请求。**不进行答案生成、不做 5.3 融合/5.4 精排，语义质量评测归 Gate 3。**

复跑入口：

```
uv run env-rag-final lightrag-local --query-id fact-001,fact-002,syn-001,neg-001 --report-dir reports/pg-retrieval/phase-3-local
```

产物：`local-runtime-latest.json`（完整请求/关键词/实体/候选/调用计数）、`local-candidates-latest.jsonl`（逐题 JSONL）、`local-manifest.json`（SHA 与前后核对）。

## 1. 实际后端身份（本轮只读盘点，先于实现确认）

| 后端 | .env 配置 | 生产实际状态（只读探测） |
| --- | --- | --- |
| PostgreSQL 17（Apple 容器 lightrag-postgres） | PG KV/Status | 八表 221/5709/279/16514/65527/221/221/119575；catalog run/snapshot `c15c741742394320`/`4919b3938ad93747`；search `872d689343a9cbb6`；源指纹 `95f7791fd84171ab…`；PG 两张 graph 表 0 行（保持未知来源，不用于 local） |
| Qdrant（lightrag-qdrant 容器，本轮启动） | QdrantVectorDBStorage | 3 集合：chunks 5709 点（2560d Cosine）、entities 65526、relationships 119574；payload `workspace_id='_'`；workspace_id keyword index 已存在 |
| Neo4j 5（lightrag-neo4j 容器，本轮启动） | Neo4JStorage | label `base`：66069 节点 / 121819 关系；entity_id RANGE 索引与 `entity_id_fulltext_idx_base` FULLTEXT 索引均已存在（ONLINE） |
| Embedding 服务 | openai binding, `Qwen/Qwen3-Embedding-4B`, 2560d | 端点可达；模型在 /models 列表；集合名后缀 `qwen_qwen3_embedding_4b_2560d` 与模型派生后缀一致 |
| LLM 服务 | openai binding, `deepseek-v4.1-flash`（keyword 用 `KEYWORD_LLM_MODEL`） | 端点可达；模型在列表 |

启动说明：lightrag-qdrant 与 lightrag-neo4j 容器在本轮开始时处于 stopped 状态（开发栈随宿主机重启未拉起；`.env` 头部注释即为该栈的重启脚本）。以 `container start` 拉起（无数据改动，卷 lightrag_qdrant/lightrag_data 持久数据原样挂载）；这是服务可用性操作，不是存储初始化。

## 2. 适配器实现（src/env_rag_final/local_adapter.py）

**只读接入策略**（继承 5.1 合同，未放宽）：

- 正式 PG 绝不实例化 ClientManager/任何 LightRAG 存储 initialize（首建池即 initdb/check_tables 库级 DDL）。chunk 内容读取用显式 asyncpg 连接（`default_transaction_read_only=on`）直查 `public.lightrag_doc_chunks`（5.1 已核实的公开表）。
- 语义半边使用发布包真实存储类：`QdrantVectorDBStorage`（entities/chunks 集合，workspace="" → 生产 `workspace_id='_'`）+ `Neo4JStorage`（workspace="" → 生产 `base` label）。二者的 `initialize()` 在生产后端为 no-op——workspace_id payload index 与 entity_id 两索引已存在（`CREATE … IF NOT EXISTS` 幂等），已逐一核对源码与现场；不创建集合/索引/约束/数据库。
- 真实服务调用：release `openai_embed`（经 `.func` 调用未包装本体，避免 1536d 双重装饰校验误伤生产 2560d 向量）+ release `openai_complete_if_cache`（keyword 提取）。`hashing_kv=None` → 零缓存读写（`utils.handle_cache` 对 None 直接返回），原 `lightrag_llm_cache` 16,514 行不读不写。
- local 链路复用发布包函数本体：`operate.get_keywords_from_query`（真实 LLM 提取 hl/ll 关键词）→ `operate._get_node_data`（entities VDB 查询 + Neo4j 批量节点/度/边读取）→ `_find_most_related_edges_from_entities` → chunk-id 组装（source_id 拆分/去重/计数排序 + `utils.pick_by_vector_similarity` 经真实 chunks 集合，WEIGHT 兜底同 release）→ PG 只读回读。适配器仅替换 KV 层为只读 PG 适配器（`ReadOnlyPGTextChunks`：upsert/delete/drop/is_empty 全部显式拒绝），不复制不绕过 release 逻辑。

**服务调用清单（每查询实际发生）**：keyword LLM 1 次（`response_format=json_object`）；embedding 批 2 次（ll_keywords 文本 + chunks VECTOR pick 的查询向量）；Qdrant 查询 2 次（entities 检索 + chunks 向量选取）；Neo4j 批量读 1 组；PG 只读 SELECT 1 组。`service_calls` 计数器包裹在真实调用外围，测试断言 stub 路径计数为 0（调用计数只对应真实服务流量）。

**候选身份核验**（每个候选逐一执行）：按 `(workspace='default', chunk_id)` 回读生产 `lightrag_doc_chunks`；`full_doc_id` 必须等于 chunk id 的 `doc-<hash>` 前缀（来源 id 一致性）；`reference_id` 不用于身份。缺失 → `verify_error="missing-in-production-pg"` 显式拒绝；不匹配 → `full_doc_id-mismatch` 拒绝；`reached_via` 记录贡献该 chunk 的实体/边（来源映射证据，不靠标题猜测）。不同版本来源不做跨版本去重（syn-001 双版本候选并存，见 §3）。

## 3. 真实请求实测（冻结审核 gold 子集，4 题）

| query_id | 问题 | 目标 | 候选 | 命中目标文档 | 观察 |
| --- | --- | --- | --- | --- | --- |
| fact-001 | GB 3095-2012 二氧化硫年平均二级限值 | 1 | 20 | 2（air-02 chunk-000 等） | 实体 表1(基本项目浓度限值)/二级浓度限值/二氧化硫(SO₂) 排名 12 |
| fact-002 | GB 8978-1996 表1 总汞最高允许排放浓度 | 1 | 20 | 14（water-11 各 chunk） | 强命中 |
| syn-001 | GB 3095-2012 与 2026 PM2.5 年均差异 | 2 | 20 | 11，**两个目标版本都命中** | 跨版本来源并存未被去重 |
| neg-001（counter, absent_version） | GB 3095-1996 二级年均限值 | 0（期望 missing） | 19 | —（期望即无 1996 版） | 见下方诚实观察 |

汇总：79/79 候选通过 `(workspace, chunk_id)` 回读验证、0 伪造；服务调用合计 embedding 8 批/8 文本、LLM 4 次（keyword 提取，无答案生成）、Qdrant 8 次、Neo4j 4 组、PG 只读 4 组；0 次 answer LLM、0 缓存读写。

**诚实观察（记录为观测，不作为质量结论）**：neg-001（库内不存在 GB 3095-1996）的语义路径返回了 GB 3095-2012/2026 等相关标准 chunk——local 语义候选本身不带版本过滤，`expected_status=missing` 的版本严格性属于答案级/融合级合同（冻结 PG 关键词路径在 4.x 已实现严格版本缺失语义；5.3 融合时由 PG 路径承担该约束）。counter 期望原样保留在证据 JSONL（`counter.expected_status="missing"`），未修改 gold 迎合语义链路。

## 4. 前后只读核对（本轮开始与结束）

- 正式八表计数、源指纹 `95f7791fd84171ab…`、catalog/search active、gold SHA、`.env` 字节 SHA（`e3bf7597…`）前后一致；`lightrag_llm_cache` 仍 16,514 行（未读未写）。
- Qdrant 三集合点数前后一致（5709/65526/119574）；Neo4j `base` 节点 66,069、关系 121,819 前后一致。
- 发布包 lightrag-hku 1.5.7 按 RECORD 核对 Python 文件 0 差异；`.env` 未修改。
- 0 次会话终止、0 外来对象清理、0 DDL/DML 于生产库。

## 5. 测试与检查

- 全套 **228 passed**（原 220 + 新增 8 项 `tests/test_local_adapter.py`：只读存储写操作全部拒绝、get_by_ids 缺失返回 None、filter_keys 合同、full_doc_id 不匹配拒绝、缺失 chunk 降级、stub 路径服务计数为 0、embedding 双重装饰规避、keyword LLM 绑定 .env 配置）。
- Ruff check/format 全通过；OpenSpec strict 通过；凭据不落盘（报告/JSONL 仅含模型名、端点 URL 主机部分与内容样本）。
- 已知边界：`_assemble_candidates` 的 chunk-id 组装是 release `_find_text_chunks` 的同语义实现（release 版本与 text_chunks_db 耦合需要完整 LightRAG 初始化，违反只读合同）；两者的选择算法（VECTOR→WEIGHT 兜底）与预算一致，已在代码注释标明。**真实语义质量（命中率/排序）尚未评测，不宣称 Gate 3 通过。**
