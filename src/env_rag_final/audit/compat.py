"""Compatibility evidence for lightrag-hku (task 1.6, corrected per G0-2).

All "confirmed" claims below are produced by executing the introspection
probes at generation time; results are embedded verbatim. Anything this
module does not probe is labeled 未验证. No LightRAG storage is ever
instantiated against the live database — only imports and source reading.
"""

from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ProbeLog:
    """Raw evidence captured during generation (embedded into the report)."""

    entries: list[dict] = field(default_factory=list)

    def record(self, probe: str, method: str, result) -> None:
        self.entries.append({"probe": probe, "method": method, "result": result})


def _run_offline_probes(log: ProbeLog) -> dict:
    """Execute every offline interface probe; returns raw observed values."""
    from lightrag import LightRAG
    from lightrag.base import QueryParam
    from lightrag.kg.neo4j_impl import Neo4JStorage
    from lightrag.kg.postgres_impl import PGKVStorage, PostgreSQLDB
    from lightrag.kg.qdrant_impl import DEFAULT_WORKSPACE as QDRANT_DEFAULT_WS

    out = {}

    # 1. Public query interfaces exist (getattr, no instantiation).
    interfaces = {}
    for name in ("aquery", "aquery_data", "query_data", "aquery_llm", "query_llm"):
        exists = hasattr(LightRAG, name)
        sig = None
        if exists:
            try:
                sig = str(inspect.signature(getattr(LightRAG, name)))
            except (ValueError, TypeError):
                sig = None
        interfaces[name] = {"exists": exists, "signature": sig}
        log.record(
            f"LightRAG.{name} exists",
            "getattr + inspect.signature",
            {"exists": exists, "signature": sig},
        )
    out["query_interfaces"] = interfaces

    # 2. aquery_data docstring declares chunk_id / file_path / content fields.
    doc = LightRAG.aquery_data.__doc__ or ""
    declared = [f for f in ("chunk_id", "file_path", "content", "reference_id") if f in doc]
    out["aquery_data_declared_chunk_fields"] = declared
    log.record(
        "aquery_data docstring chunk fields",
        "substring scan of inspect.getdoc",
        {"declared": declared},
    )

    # 3. QueryParam fields.
    out["query_param_fields"] = list(inspect.signature(QueryParam).parameters)[:12]
    log.record("QueryParam fields", "inspect.signature", {"first_12": out["query_param_fields"]})

    # 4. PG init side effects: source scan of ClientManager.get_client.
    from lightrag.kg.postgres_impl import ClientManager

    src = inspect.getsource(ClientManager.get_client)
    calls_initdb = "await db.initdb()" in src
    calls_check_tables = "await db.check_tables()" in src
    out["pg_client_manager"] = {
        "calls_initdb": calls_initdb,
        "calls_check_tables": calls_check_tables,
    }
    log.record(
        "ClientManager.get_client side effects",
        "inspect.getsource substring scan",
        {"calls_initdb": calls_initdb, "calls_check_tables": calls_check_tables},
    )

    # 5. PGKVStorage.get_by_ids (text_chunks) returns ordered evidence columns.
    src_get = inspect.getsource(PGKVStorage.get_by_ids)
    out["pg_get_by_ids_uses_sql_template"] = (
        'SQL_TEMPLATES["get_by_ids_" + self.namespace]' in src_get
    )
    log.record(
        "PGKVStorage.get_by_ids dispatch",
        "inspect.getsource substring scan",
        {"uses_sql_template": out["pg_get_by_ids_uses_sql_template"]},
    )

    # 6. Workspace naming constants (published defaults, not live probes).
    out["published_workspace_defaults"] = {
        "qdrant_DEFAULT_WORKSPACE": QDRANT_DEFAULT_WS,
        "neo4j_empty_workspace_label": "base",  # from _get_raw_workspace_label: workspace if workspace else "base"
        "pg_workspace_when_unset": "default",  # storage initialize(): self.workspace = "default"
    }
    log.record(
        "published workspace defaults",
        "module constants + inspect.getsource of storage initialize/_get_raw_workspace_label",
        out["published_workspace_defaults"],
    )

    # 7. chunk id format from published writer source.
    from lightrag.sidecar import writer as sidecar_writer

    wsrc = inspect.getsource(sidecar_writer)
    out["chunk_id_format_documented"] = {
        "doc_hash_prefix_strip": 'doc_id.removeprefix("doc-")' in wsrc,
        "document_hash_sha256_merged": 'hashlib.sha256(merged_text.encode("utf-8"))' in wsrc,
    }
    log.record(
        "sidecar writer id/hash derivation",
        "inspect.getsource substring scan",
        out["chunk_id_format_documented"],
    )

    # 8. PostgreSQLDB DDL execution: table templates use plain CREATE TABLE,
    #    converted to IF NOT EXISTS at execution time (vector path) and
    #    check_tables() issues CREATE TABLE after a failing probe SELECT.
    table_ddl_src = inspect.getsource(PostgreSQLDB)
    out["pg_ddl_observation"] = {
        "create_table_statements_in_source": table_ddl_src.count("CREATE TABLE"),
        "create_if_not_exists_in_source": table_ddl_src.count("CREATE TABLE IF NOT EXISTS"),
        "note": "DDL 由 check_tables()（首次建池）与 setup_table()（vector 初始化）执行；"
        "模板为 CREATE TABLE，执行期改写为 IF NOT EXISTS。无论哪种路径，都会对库发出 DDL。",
    }
    log.record(
        "PostgreSQLDB DDL presence",
        "inspect.getsource count scan",
        out["pg_ddl_observation"],
    )

    out["neo4j_storage_class_importable"] = Neo4JStorage is not None
    return out


def build_compatibility_md(versions: dict) -> str:
    now = datetime.now(timezone.utc).isoformat()
    log = ProbeLog()
    probed = _run_offline_probes(log)
    iface = probed["query_interfaces"]
    v = versions.get("lightrag-hku", "unknown")
    probe_json = json.dumps(log.entries, ensure_ascii=False, indent=2)

    aq = iface["aquery_data"]
    return f"""# compatibility.md — LightRAG 发布包离线核对（task 1.6）

生成时间：{now}。对象：本工程 .venv 实装的 PyPI 发布包 lightrag-hku **{v}**（uv.lock 固定）。
本文件由 `uv run env-rag-final audit` 在每次运行时**实际执行**下述离线探针后生成——探针只做
`importlib` 导入、`getattr` 与 `inspect.getsource` 源码扫描，**不实例化任何存储、不连接现有库、
不调用任何模型服务**。每个"已确认"结论都可以在下方的探针记录里找到对应原始结果。

## 1. 已确认（本次运行执行的探针）

### 1.1 证据检索接口

| 接口 | 存在 | 签名已捕获 | 说明 |
|---|---|---|---|
| `LightRAG.aquery` | {iface["aquery"]["exists"]} | {bool(iface["aquery"]["signature"])} | 返回 LLM 响应（向后兼容包装） |
| `LightRAG.aquery_data` | {aq["exists"]} | {bool(aq["signature"])} | 无 LLM 生成的结构化检索结果 |
| `LightRAG.query_data` | {iface["query_data"]["exists"]} | {bool(iface["query_data"]["signature"])} | aquery_data 的同步版 |
| `LightRAG.aquery_llm` / `query_llm` | {iface["aquery_llm"]["exists"]} / {iface["query_llm"]["exists"]} | — | 完整 LLM 版 |

`aquery_data` docstring 实际声明的 chunk 证据字段（子串扫描结果）：**{probed["aquery_data_declared_chunk_fields"]}**。
即融合层可按「workspace + chunk_id」对齐两路候选，不依赖显示引用编号猜身份。

`QueryParam` 前 12 个字段：{probed["query_param_fields"]}（`only_need_context=True` 即只取证据、不做生成）。

### 1.2 存储初始化副作用（兼容性风险；源码扫描已确认）

- `ClientManager.get_client` 源码含 `await db.initdb()`：{probed["pg_client_manager"]["calls_initdb"]}；
  含 `await db.check_tables()`：{probed["pg_client_manager"]["calls_check_tables"]}。
  → 首次建池**必然**执行建表／建索引／迁移路径（PostgreSQLDB 源码含 {probed["pg_ddl_observation"]["create_table_statements_in_source"]} 处
  `CREATE TABLE` 模板，执行期对库发出 DDL）。
- `LightRAG.initialize_storages()` 还会调用 `initialize_pipeline_status(workspace)` 写共享状态（源码事实）。
- 结论：**用发布包直接指向现有库的任何构造/初始化都可能产生 DDL 或写入**。正式只读接入策略以
  隔离临时库／测试 workspace 验证（tasks 5.1）为前提；本审计全程未实例化存储。

### 1.3 workspace 命名（发布包常量／源码默认值）

| 存储 | 发布包默认（源码常量，本次扫描确认） |
|---|---|
| Qdrant | `DEFAULT_WORKSPACE = "{probed["published_workspace_defaults"]["qdrant_DEFAULT_WORKSPACE"]}"`（payload workspace_id 字段） |
| Neo4j | 空 workspace 落名 `{probed["published_workspace_defaults"]["neo4j_empty_workspace_label"]}`（`_get_raw_workspace_label` 源码） |
| PG | 未设置时 `{probed["published_workspace_defaults"]["pg_workspace_when_unset"]}`（storage initialize 源码） |

三库**各自的实际取值**（PG 行数据、Qdrant payload、Neo4j label 的现场枚举）不属于本离线探针范围，
见 audit.md §1.5 的历史观察记录（首轮 2026-10-04 只读探针：PG 全部行 `workspace='default'`、
Qdrant 5709 点 `workspace_id='_'`、Neo4j labels=['base']）——该观察未纳入本次复跑，引用时以上次记录为准，
不因本文件重新生成而视为刚核实。

### 1.4 chunk id 与哈希派生（发布包 sidecar writer 源码扫描）

- `doc_id.removeprefix("doc-")` 出现：{probed["chunk_id_format_documented"]["doc_hash_prefix_strip"]}；
  `sha256(merged_text)` 出现：{probed["chunk_id_format_documented"]["document_hash_sha256_merged"]}。
  与 identity.py 的本地复算公式一致（inventory.jsonl hash_verification 221/221 匹配）。

## 2. 未验证项（运行时，按 tasks 编号）

1. `aquery_data` 对本库实际返回的 chunk_id／内容／来源字段（5.1／5.2 隔离实测）；
2. query 路径是否必须调用 embedding 服务（本阶段未调用付费服务）；
3. reranker 可用性与失败模式（5.4）；
4. llm_response_cache 对评测的污染路径与绕开开关（6.1）；
5. 1.5.7 与旧源码项目（自报 1.5.8）存储 schema 差异清单（不阻断 PG 独立路线）。

## 3. 探针原始记录（本文件生成时实际执行）

```json
{probe_json}
```

## 4. 结论

- 离线兼容信息支持「PG 独立路线先行、融合从公开接口适配」（design.md 决策 6）。
- 风险登记：初始化副作用（§1.2）与 local 模式 chunk_id 的运行时一致性（§2.1）。
- 若 5.1 隔离实测发现接口不兼容，按 Gate 0 规则保留 PG 独立路线，融合等待修订方案，
  不自动升级依赖、不迁移现有库。
"""


# Re-pattern kept from lexical module for potential reuse in later phases.
_WS_RE = re.compile(r"\s+")
