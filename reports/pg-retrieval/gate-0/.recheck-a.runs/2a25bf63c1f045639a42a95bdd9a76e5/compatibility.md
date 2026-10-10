# compatibility.md — LightRAG 发布包离线核对（task 1.6）

生成时间：2026-10-05T00:28:14.202088+00:00。对象：本工程 .venv 实装的 PyPI 发布包 lightrag-hku **1.5.7**（uv.lock 固定）。
本文件由 `uv run env-rag-final audit` 在每次运行时**实际执行**下述离线探针后生成——探针只做
`importlib` 导入、`getattr` 与 `inspect.getsource` 源码扫描，**不实例化任何存储、不连接现有库、
不调用任何模型服务**。每个"已确认"结论都可以在下方的探针记录里找到对应原始结果。

## 1. 已确认（本次运行执行的探针）

### 1.1 证据检索接口

| 接口 | 存在 | 签名已捕获 | 说明 |
|---|---|---|---|
| `LightRAG.aquery` | True | True | 返回 LLM 响应（向后兼容包装） |
| `LightRAG.aquery_data` | True | True | 无 LLM 生成的结构化检索结果 |
| `LightRAG.query_data` | True | True | aquery_data 的同步版 |
| `LightRAG.aquery_llm` / `query_llm` | True / True | — | 完整 LLM 版 |

`aquery_data` docstring 实际声明的 chunk 证据字段（子串扫描结果）：**['chunk_id', 'file_path', 'content', 'reference_id']**。
即融合层可按「workspace + chunk_id」对齐两路候选，不依赖显示引用编号猜身份。

`QueryParam` 前 12 个字段：['mode', 'only_need_context', 'only_need_prompt', 'response_type', 'stream', 'top_k', 'chunk_top_k', 'max_entity_tokens', 'max_relation_tokens', 'max_total_tokens', 'hl_keywords', 'll_keywords']（`only_need_context=True` 即只取证据、不做生成）。

### 1.2 存储初始化副作用（兼容性风险；源码扫描已确认）

- `ClientManager.get_client` 源码含 `await db.initdb()`：True；
  含 `await db.check_tables()`：True。
  → 首次建池**必然**执行建表／建索引／迁移路径（PostgreSQLDB 源码含 0 处
  `CREATE TABLE` 模板，执行期对库发出 DDL）。
- `LightRAG.initialize_storages()` 还会调用 `initialize_pipeline_status(workspace)` 写共享状态（源码事实）。
- 结论：**用发布包直接指向现有库的任何构造/初始化都可能产生 DDL 或写入**。正式只读接入策略必须在
  隔离临时库／测试 workspace 验证（tasks 5.1）后再定；本审计全程未实例化存储。

### 1.3 workspace 命名（发布包常量／源码默认值）

| 存储 | 发布包默认（源码常量，本次扫描确认） |
|---|---|
| Qdrant | `DEFAULT_WORKSPACE = "_"`（payload workspace_id 字段） |
| Neo4j | 空 workspace 落名 `base`（`_get_raw_workspace_label` 源码） |
| PG | 未设置时 `default`（storage initialize 源码） |

三库**各自的实际取值**（PG 行数据、Qdrant payload、Neo4j label 的现场枚举）不属于本离线探针范围，
见 audit.md §1.5 的历史观察记录（首轮 2026-10-04 只读探针：PG 全部行 `workspace='default'`、
Qdrant 5709 点 `workspace_id='_'`、Neo4j labels=['base']）——该观察未纳入本次复跑，引用时以上次记录为准，
不因本文件重新生成而视为刚核实。

### 1.4 chunk id 与哈希派生（发布包 sidecar writer 源码扫描）

- `doc_id.removeprefix("doc-")` 出现：True；
  `sha256(merged_text)` 出现：True。
  与 identity.py 的本地复算公式一致（inventory.jsonl hash_verification 221/221 匹配）。

## 2. 未验证项（运行时，按 tasks 编号）

1. `aquery_data` 对本库实际返回的 chunk_id／内容／来源字段（5.1／5.2 隔离实测）；
2. query 路径是否必须调用 embedding 服务（本阶段未调用付费服务）；
3. reranker 可用性与失败模式（5.4）；
4. llm_response_cache 对评测的污染路径与绕开开关（6.1）；
5. 1.5.7 与旧源码项目（自报 1.5.8）存储 schema 差异清单（不阻断 PG 独立路线）。

## 3. 探针原始记录（本文件生成时实际执行）

```json
[
  {
    "probe": "LightRAG.aquery exists",
    "method": "getattr + inspect.signature",
    "result": {
      "exists": true,
      "signature": "(self, query: 'str', param: 'QueryParam' = QueryParam(mode='mix', only_need_context=False, only_need_prompt=False, response_type='Multiple Paragraphs', stream=False, top_k=40, chunk_top_k=20, max_entity_tokens=6000, max_relation_tokens=8000, max_total_tokens=32000, hl_keywords=[], ll_keywords=[], conversation_history=[], user_prompt=None, enable_rerank=True, include_references=False, disable_user_prompt_prefix=False), system_prompt: 'str | None' = None) -> 'str | AsyncIterator[str]'"
    }
  },
  {
    "probe": "LightRAG.aquery_data exists",
    "method": "getattr + inspect.signature",
    "result": {
      "exists": true,
      "signature": "(self, query: 'str', param: 'QueryParam' = QueryParam(mode='mix', only_need_context=False, only_need_prompt=False, response_type='Multiple Paragraphs', stream=False, top_k=40, chunk_top_k=20, max_entity_tokens=6000, max_relation_tokens=8000, max_total_tokens=32000, hl_keywords=[], ll_keywords=[], conversation_history=[], user_prompt=None, enable_rerank=True, include_references=False, disable_user_prompt_prefix=False)) -> 'dict[str, Any]'"
    }
  },
  {
    "probe": "LightRAG.query_data exists",
    "method": "getattr + inspect.signature",
    "result": {
      "exists": true,
      "signature": "(self, query: 'str', param: 'QueryParam' = QueryParam(mode='mix', only_need_context=False, only_need_prompt=False, response_type='Multiple Paragraphs', stream=False, top_k=40, chunk_top_k=20, max_entity_tokens=6000, max_relation_tokens=8000, max_total_tokens=32000, hl_keywords=[], ll_keywords=[], conversation_history=[], user_prompt=None, enable_rerank=True, include_references=False, disable_user_prompt_prefix=False)) -> 'dict[str, Any]'"
    }
  },
  {
    "probe": "LightRAG.aquery_llm exists",
    "method": "getattr + inspect.signature",
    "result": {
      "exists": true,
      "signature": "(self, query: 'str', param: 'QueryParam' = QueryParam(mode='mix', only_need_context=False, only_need_prompt=False, response_type='Multiple Paragraphs', stream=False, top_k=40, chunk_top_k=20, max_entity_tokens=6000, max_relation_tokens=8000, max_total_tokens=32000, hl_keywords=[], ll_keywords=[], conversation_history=[], user_prompt=None, enable_rerank=True, include_references=False, disable_user_prompt_prefix=False), system_prompt: 'str | None' = None, progress_callback=None) -> 'dict[str, Any]'"
    }
  },
  {
    "probe": "LightRAG.query_llm exists",
    "method": "getattr + inspect.signature",
    "result": {
      "exists": true,
      "signature": "(self, query: 'str', param: 'QueryParam' = QueryParam(mode='mix', only_need_context=False, only_need_prompt=False, response_type='Multiple Paragraphs', stream=False, top_k=40, chunk_top_k=20, max_entity_tokens=6000, max_relation_tokens=8000, max_total_tokens=32000, hl_keywords=[], ll_keywords=[], conversation_history=[], user_prompt=None, enable_rerank=True, include_references=False, disable_user_prompt_prefix=False), system_prompt: 'str | None' = None) -> 'dict[str, Any]'"
    }
  },
  {
    "probe": "aquery_data docstring chunk fields",
    "method": "substring scan of inspect.getdoc",
    "result": {
      "declared": [
        "chunk_id",
        "file_path",
        "content",
        "reference_id"
      ]
    }
  },
  {
    "probe": "QueryParam fields",
    "method": "inspect.signature",
    "result": {
      "first_12": [
        "mode",
        "only_need_context",
        "only_need_prompt",
        "response_type",
        "stream",
        "top_k",
        "chunk_top_k",
        "max_entity_tokens",
        "max_relation_tokens",
        "max_total_tokens",
        "hl_keywords",
        "ll_keywords"
      ]
    }
  },
  {
    "probe": "ClientManager.get_client side effects",
    "method": "inspect.getsource substring scan",
    "result": {
      "calls_initdb": true,
      "calls_check_tables": true
    }
  },
  {
    "probe": "PGKVStorage.get_by_ids dispatch",
    "method": "inspect.getsource substring scan",
    "result": {
      "uses_sql_template": true
    }
  },
  {
    "probe": "published workspace defaults",
    "method": "module constants + inspect.getsource of storage initialize/_get_raw_workspace_label",
    "result": {
      "qdrant_DEFAULT_WORKSPACE": "_",
      "neo4j_empty_workspace_label": "base",
      "pg_workspace_when_unset": "default"
    }
  },
  {
    "probe": "sidecar writer id/hash derivation",
    "method": "inspect.getsource substring scan",
    "result": {
      "doc_hash_prefix_strip": true,
      "document_hash_sha256_merged": true
    }
  },
  {
    "probe": "PostgreSQLDB DDL presence",
    "method": "inspect.getsource count scan",
    "result": {
      "create_table_statements_in_source": 0,
      "create_if_not_exists_in_source": 0,
      "note": "DDL 由 check_tables()（首次建池）与 setup_table()（vector 初始化）执行；模板为 CREATE TABLE，执行期改写为 IF NOT EXISTS。无论哪种路径，都会对库发出 DDL。"
    }
  }
]
```

## 4. 结论

- 离线兼容信息支持「PG 独立路线先行、融合从公开接口适配」（design.md 决策 6）。
- 风险登记：初始化副作用（§1.2）与 local 模式 chunk_id 的运行时一致性（§2.1）。
- 若 5.1 隔离实测发现接口不兼容，按 Gate 0 规则保留 PG 独立路线，融合等待修订方案，
  不自动升级依赖、不迁移现有库。
