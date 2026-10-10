"""Task 5.2 (rev 2): real local-mode candidate adapter — read-only production
access with pre-flight identity/config guards and explicit service evidence.

Read-only接入合同（review phase-3-local-review L1–L5）:
- L1: 生产存储绝不经 LightRAG initialize()（Qdrant initialize 对已存在集合仍
  调 create_payload_index，Neo4j initialize 仍发 CREATE INDEX IF NOT EXISTS，
  且含建表/迁移/建库/DROP 重建分支）。适配器自行建立原生连接并**只读校验**
  既有元数据（集合存在、维度、workspace index、label、模型后缀）；任何缺失/
  不兼容 → AdapterError 拒绝，绝不 ensure/create/migrate/repair。发布包存储
  的读取方法通过直接注入连接对象复用（跳过其 initialize 写路径）。
- L2: 候选选取使用发布包函数本体 `_find_related_text_unit_from_entities` /
  `_find_related_text_unit_from_relations`（接收只读存储对象，无需完整
  LightRAG 初始化）；边端点读取发布包真实字段 `src_tgt`；每个候选保留全部
  实体/边来源路径（真实端点名，不覆盖）；预算合同 = release
  related_chunk_number 发现预算 + chunk_top_k 作为最终候选上限（发现排序 ≠
  最终精排，精排归 5.4）。
- L3: 任何服务调用/连接建立之前核验：frozen gold SHA（实际读取比较）、
  embedding 模型名与 model_name/集合后缀一致、显式 workspace 映射
  （PG 'default' ↔ vector '_' ↔ graph 'base'，其它值拒绝；env 覆盖
  QDRANT_WORKSPACE/NEO4J_WORKSPACE/POSTGRES_WORKSPACE 必须未设置）。
  run_frozen 采集实际 source/catalog run+snapshot/search/gold/env 与冻结值
  比较，finally 后置漂移核对；失败非零并写失败报告。
- L4: 服务边界（embedding/LLM/Qdrant/Neo4j/PG）记录 attempt/success/failure；
  发布包 VECTOR helper 吞 embedding 异常并返回截断列表——边界包装使失败
  可见并将排序来源显式标记为 truncation-fallback（degraded）；计数按真实
  调用定义（空路径不虚增），每请求独立计数；错误 query_id 在任何调用前
  拒绝；失败统一终态报告 + CLI 非零。
- V1（第四轮补正）: chunk 向量覆盖按**有效映射**判定——在读取边界逐阶段观测
  发布存储 get_vectors_by_ids 实际交给选取器的映射（无向量 point 被发布包
  丢弃、按 payload 原始 chunk 身份重映射），与请求 chunk 身份逐一对照；
  缺失/不匹配/维度不符不计覆盖，原生 retrieve 的 point 条数仅作传输统计
  （points_returned_raw），绝不冒充向量数。覆盖不完整 → weight-fallback +
  degraded。
- L5: 资源构造即登记；success/error/cancel 均执行 close-only 回收（Qdrant
  client.close() 原生 finalize 会 flush pending writes——只读适配禁止；
  Neo4j driver.close()）；单项关闭失败不跳过其余回收/报告。

Run:
  uv run env-rag-final lightrag-local --query-id fact-001,fact-002,syn-001,neg-001
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import asyncpg
import lightrag.kg.shared_storage as shared_storage
from dotenv import dotenv_values
from lightrag.base import BaseKVStorage
from lightrag.kg.neo4j_impl import Neo4JStorage
from lightrag.kg.qdrant_impl import QdrantVectorDBStorage
from lightrag.operate import (
    _find_most_related_edges_from_entities,
    _find_related_text_unit_from_entities,
    _find_related_text_unit_from_relations,
    _get_node_data,
)
from lightrag.operate import (
    get_keywords_from_query as release_get_keywords_from_query,
)
from lightrag.utils import EmbeddingFunc

FROZEN = {
    "source_fingerprint": "95f7791fd84171ab727870fc5810d79b4327b0c4fa547d432951e0499a3808f8",
    "catalog_run_id": "c15c741742394320",
    "catalog_snapshot_id": "4919b3938ad93747",
    "search_active": "872d689343a9cbb6",
    "gold_sha": "1bf130077c21583a89c5ca14695694d9552c558a7d8dc5d45ff0d9f72cfd7a5e",
    "public_counts": {
        "lightrag_doc_full": 221,
        "lightrag_doc_chunks": 5709,
        "lightrag_doc_status": 279,
        "lightrag_llm_cache": 16514,
        "lightrag_entity_chunks": 65527,
        "lightrag_full_entities": 221,
        "lightrag_full_relations": 221,
        "lightrag_relation_chunks": 119575,
    },
}

# L3: the ONLY production workspace mapping verified live (Phase 0 + 5.2 live
# probes). Not generalizable: an unmapped PG workspace is refused, never
# silently reused against the production semantic namespaces.
WORKSPACE_MAPPING = {
    # pg_workspace: (vector_workspace, graph_workspace)
    "default": ("_", "base"),
}
EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-4B"
EMBEDDING_DIM = 2560
ENV_OVERRIDES_FORBIDDEN = ("QDRANT_WORKSPACE", "NEO4J_WORKSPACE", "POSTGRES_WORKSPACE")


class AdapterError(RuntimeError):
    """A guard/precondition failed — the adapter refuses (CLI exits non-zero)."""


def _sha256_file(rel: str | Path) -> str | None:
    p = Path(rel)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def _file_sha(rel: str | Path) -> str | None:
    return _sha256_file(rel)


# ---------------------------------------------------------------------------
# L3 pre-flight guards (before ANY connection/service call)
# ---------------------------------------------------------------------------


def verify_config_guard(values: dict, workspace: str) -> dict:
    """Refuse unsupported configuration BEFORE any backend/service contact."""
    problems: list[str] = []
    for k in ENV_OVERRIDES_FORBIDDEN:
        if os.environ.get(k, "").strip():
            problems.append(
                f"env override {k} is set; the production mapping is "
                "explicit and must not be overridden"
            )
    if workspace not in WORKSPACE_MAPPING:
        problems.append(
            f"PG workspace {workspace!r} has no verified semantic mapping "
            f"(verified: {sorted(WORKSPACE_MAPPING)}); refusing to reuse the "
            "production namespaces for an unmapped workspace"
        )
    model = values.get("EMBEDDING_MODEL") or ""
    if model != EMBEDDING_MODEL:
        problems.append(
            f"EMBEDDING_MODEL {model!r} does not match the production embedding "
            f"identity {EMBEDDING_MODEL!r} (collection suffix derives from it); "
            "another model must not reuse the old Qwen collection label"
        )
    if values.get("EMBEDDING_DIM") and int(values["EMBEDDING_DIM"]) != EMBEDDING_DIM:
        problems.append(f"EMBEDDING_DIM {values['EMBEDDING_DIM']} != {EMBEDDING_DIM}")
    if problems:
        raise AdapterError("config guard failed: " + "; ".join(problems))
    vector_ws, graph_ws = WORKSPACE_MAPPING[workspace]
    return {"pg": workspace, "vector": vector_ws, "graph": graph_ws}


def verify_gold_guard(gold_path: Path) -> str:
    """L3: read the approved gold file and compare against the frozen SHA."""
    got = _file_sha(gold_path)
    if got != FROZEN["gold_sha"]:
        raise AdapterError(
            f"frozen gold guard failed: {gold_path} sha {got} != frozen {FROZEN['gold_sha']}"
        )
    return got


# ---------------------------------------------------------------------------
# L4 service boundary: attempt/success/failure per real call
# ---------------------------------------------------------------------------


@dataclass
class CallRecord:
    service: str
    operation: str
    status: str  # success | failure
    error: str | None = None
    elapsed_ms: int = 0
    # M2/N1: de-credentialed result summary (e.g. {"points": 0} / {"vectors": 12})
    result: dict | None = None
    # N1: the collection/namespace this call targeted (e.g. "chunks"/"entities")
    target: str | None = None


def _summarize_result(result) -> dict | None:
    """M2: shape/size summary only — never vectors or payload contents."""
    if result is None:
        return None
    if hasattr(result, "points"):  # qdrant QueryResponse
        return {"points": len(result.points or [])}
    if isinstance(result, dict):
        return {"items": len(result)}
    if isinstance(result, (list, tuple)):
        return {"items": len(result)}
    if hasattr(result, "shape"):  # numpy embedding batch
        return {"shape": list(result.shape)}
    if isinstance(result, str):
        return {"chars": len(result)}
    return None


class _RecordingNeo4jDriver:
    """M2/N1: proxies the async Neo4j driver so actual session.run() reads are
    recorded on the boundary. The receipt is written only AFTER the real
    coroutine completes: an await-time failure is recorded as a failure at
    the same boundary (with execution wait included in elapsed), then
    re-raised — a created-but-unawaited coroutine never counts as success."""

    def __init__(self, inner, boundary: ServiceBoundary):
        self._inner = inner
        self._boundary = boundary

    def session(self, *args, **kwargs):
        raw_session = self._inner.session(*args, **kwargs)
        boundary = self._boundary

        async def _run_and_record(session_obj, *a, **kw):
            started = time.monotonic()
            try:
                result = await session_obj.run(*a, **kw)
            except Exception as exc:  # noqa: BLE001 — recorded, re-raised
                boundary.records.append(
                    CallRecord(
                        "neo4j",
                        "session.run",
                        "failure",
                        f"{type(exc).__name__}: {str(exc)[:200]}",
                        int((time.monotonic() - started) * 1000),
                    )
                )
                raise
            boundary.records.append(
                CallRecord(
                    "neo4j",
                    "session.run",
                    "success",
                    None,
                    int((time.monotonic() - started) * 1000),
                )
            )
            return result

        def _wrap_run(session_obj, *a, **kw):
            return _run_and_record(session_obj, *a, **kw)

        class _RecordingSession:
            def __getattr__(self, name):
                return getattr(raw_session, name)

            async def __aenter__(self):
                entered = await raw_session.__aenter__()
                return _EnteredSession(entered)

            async def __aexit__(self, *exc):
                return await raw_session.__aexit__(*exc)

            def run(self, *a, **kw):
                return _wrap_run(raw_session, *a, **kw)

        class _EnteredSession:
            def __init__(self, session_obj):
                self._session_obj = session_obj

            def __getattr__(self, name):
                return getattr(self._session_obj, name)

            def run(self, *a, **kw):
                return _wrap_run(self._session_obj, *a, **kw)

        return _RecordingSession()

    async def close(self):
        return await self._inner.close()

    def __getattr__(self, name):
        return getattr(self._inner, name)


class ServiceBoundary:
    """Wraps real service calls; records one entry per actual attempt.

    M2: `records` carries ACTUAL underlying calls only (model HTTP calls,
    Qdrant query_points/retrieve, Neo4j session.run, PG readonly SELECTs).
    Helper-level stages that bundle reads are recorded in `group_records` —
    the two views are never conflated."""

    def __init__(self) -> None:
        self.records: list[CallRecord] = []
        self.group_records: list[CallRecord] = []

    def counts(self) -> dict:
        out: dict[str, dict[str, int]] = {}
        for r in self.records:
            svc = out.setdefault(r.service, {"attempt": 0, "success": 0, "failure": 0})
            svc["attempt"] += 1
            svc[r.status] = svc.get(r.status, 0) + 1
        return out

    def group_counts(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for r in self.group_records:
            svc = out.setdefault(r.service, {"attempt": 0, "success": 0, "failure": 0})
            svc["attempt"] += 1
            svc[r.status] = svc.get(r.status, 0) + 1
        return out

    async def call(self, service: str, operation: str, fn, *args, **kwargs):
        started = time.monotonic()
        try:
            result = await fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — recorded, then re-raised
            self.records.append(
                CallRecord(
                    service,
                    operation,
                    "failure",
                    f"{type(exc).__name__}: {str(exc)[:200]}",
                    int((time.monotonic() - started) * 1000),
                )
            )
            raise
        self.records.append(
            CallRecord(
                service,
                operation,
                "success",
                None,
                int((time.monotonic() - started) * 1000),
                result=_summarize_result(result),
            )
        )
        return result

    async def call_group(self, service: str, operation: str, fn, *args, **kwargs):
        """Helper-level stage: recorded in group_records, NOT by_service."""
        started = time.monotonic()
        try:
            result = await fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — recorded, then re-raised
            self.group_records.append(
                CallRecord(
                    service,
                    operation,
                    "failure",
                    f"{type(exc).__name__}: {str(exc)[:200]}",
                    int((time.monotonic() - started) * 1000),
                )
            )
            raise
        self.group_records.append(
            CallRecord(
                service,
                operation,
                "success",
                None,
                int((time.monotonic() - started) * 1000),
            )
        )
        return result

    def record_sync(
        self, service: str, operation: str, status: str, error: str | None = None
    ) -> None:
        self.records.append(CallRecord(service, operation, status, error, 0))


def build_real_embedding_func(values: dict, boundary: ServiceBoundary) -> EmbeddingFunc:
    """Release openai_embed (unwrapped body) behind the service boundary.

    model_name MUST match the production Qdrant collection suffix derivation
    (lightrag_vdb_entities_qwen_qwen3_embedding_4b_2560d) — verified in the
    config guard before any call.
    """
    from lightrag.llm.openai import openai_embed

    async def embed(texts, **kwargs):
        return await boundary.call(
            "embedding",
            "openai_embed",
            openai_embed.func,
            texts,
            model=values["EMBEDDING_MODEL"],
            base_url=values["EMBEDDING_BINDING_HOST"],
            api_key=values["EMBEDDING_BINDING_API_KEY"],
        )

    return EmbeddingFunc(
        embedding_dim=EMBEDDING_DIM,
        max_token_size=int(values.get("EMBEDDING_TOKEN_LIMIT") or 8192),
        func=embed,
        model_name=EMBEDDING_MODEL,
    )


def build_real_keyword_llm(values: dict, boundary: ServiceBoundary):
    from lightrag.llm.openai import openai_complete_if_cache

    async def keyword_llm(prompt, **kwargs):
        return await boundary.call(
            "llm",
            "keyword_extraction",
            openai_complete_if_cache,
            values["KEYWORD_LLM_MODEL"] or values["LLM_MODEL"],
            prompt,
            base_url=values["LLM_BINDING_HOST"],
            api_key=values["LLM_BINDING_API_KEY"],
            **{"response_format": {"type": "json_object"}},
        )

    return keyword_llm


# ---------------------------------------------------------------------------
# Production PG read-only chunk storage (public.lightrag_doc_chunks)
# ---------------------------------------------------------------------------


class ReadOnlyPGTextChunks(BaseKVStorage):
    """Read-only asyncpg adapter over the production text-chunks table.

    No ClientManager / LightRAG initialize / DDL / writes. Every query runs on
    a default_transaction_read_only=on connection and is passed through the
    service boundary so the SQL attempt is actually counted.
    """

    def __init__(self, values: dict, workspace: str, boundary: ServiceBoundary):
        self._values = values
        self.workspace = workspace
        self.boundary = boundary
        self.global_config: dict = {}
        self.embedding_func: EmbeddingFunc | None = None

    async def _fetch(self, ids: list[str]) -> list[dict | None]:
        conn = await asyncpg.connect(
            host=self._values["POSTGRES_HOST"],
            port=int(self._values["POSTGRES_PORT"]),
            user=self._values["POSTGRES_USER"],
            password=self._values["POSTGRES_PASSWORD"],
            database=self._values["POSTGRES_DATABASE"],
            timeout=15,
            server_settings={"default_transaction_read_only": "on"},
        )

        async def run():
            return await conn.fetch(
                """SELECT id, workspace, full_doc_id, content, tokens,
                          chunk_order_index, file_path
                   FROM public.lightrag_doc_chunks
                   WHERE workspace = $1 AND id = ANY($2)""",
                self.workspace,
                list(ids),
            )

        try:
            rows = await self.boundary.call("pg", "readonly_select_chunks", run)
        finally:
            await conn.close()
        by_id = {
            r["id"]: {
                "id": r["id"],
                "workspace": r["workspace"],
                "full_doc_id": r["full_doc_id"],
                "content": r["content"],
                "tokens": r["tokens"],
                "chunk_order_index": r["chunk_order_index"],
                "file_path": r["file_path"],
                "__source": "production.lightrag_doc_chunks",
            }
            for r in rows
        }
        return [by_id.get(i) for i in ids]

    async def get_by_ids(self, ids: list[str]) -> list[dict | None]:
        if not ids:
            return []  # L4: no SQL executed → no pg attempt recorded
        return await self._fetch(list(ids))

    async def get_by_id(self, id: str):
        got = await self.get_by_ids([id])
        return got[0] if got else None

    async def filter_keys(self, keys: set[str]) -> set[str]:
        if not keys:
            return set()
        rows = await self.get_by_ids(sorted(keys))
        existing = {r["id"] for r in rows if r is not None}
        return set(keys) - existing

    async def upsert(self, data):
        raise AdapterError("ReadOnlyPGTextChunks is read-only; upsert forbidden")

    async def delete(self, ids):
        raise AdapterError("ReadOnlyPGTextChunks is read-only; delete forbidden")

    async def is_empty(self) -> bool:
        raise AdapterError("ReadOnlyPGTextChunks is read-only; emptiness not asserted")

    async def drop(self):
        raise AdapterError("ReadOnlyPGTextChunks is read-only; drop forbidden")

    async def index_done_callback(self) -> None:
        return None


# ---------------------------------------------------------------------------
# L1 read-only semantic resource binding (NO LightRAG initialize())
# ---------------------------------------------------------------------------


def _qdrant_meta(client, collection: str) -> dict:
    """Read-only metadata inspection via the native client (sync API)."""
    info = client.get_collection(collection)
    cfg = info.config.params
    return {
        "exists": True,
        "dim": cfg.vectors.size,
        "points_count": info.points_count,
        "payload_schema": {k: str(v.data_type) for k, v in (info.payload_schema or {}).items()},
    }


class _RecordingQdrantClient:
    """M2/N1: wraps a native Qdrant client so query_points/retrieve attempts
    are recorded on the service boundary — including failures the release
    helpers swallow internally (get_vectors_by_ids catches exceptions; the
    failure is recorded here BEFORE it is swallowed). Each receipt carries the
    TARGET collection so stages can be told apart and native point counts are
    kept as transport statistics only (V1: effective chunk-vector coverage is
    judged from the mapping observed on the storage's get_vectors_by_ids —
    see _EffectiveChunkVectorObserver — never from raw point counts)."""

    def __init__(self, inner, boundary: ServiceBoundary, target: str | None = None):
        self._inner = inner
        self._boundary = boundary
        self._target = target

    def _recorded(self, operation: str, fn):
        target = self._target

        def call(*args, **kwargs):
            started = time.monotonic()
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 — recorded, then re-raised
                self._boundary.records.append(
                    CallRecord(
                        "qdrant",
                        operation,
                        "failure",
                        f"{type(exc).__name__}: {str(exc)[:200]}",
                        int((time.monotonic() - started) * 1000),
                        target=target,
                    )
                )
                raise
            summary = _summarize_result(result) or {}
            if operation == "retrieve":
                requested = kwargs.get("ids")
                if requested is None and args:
                    requested = args[0]
                summary["requested"] = len(requested) if requested is not None else None
            self._boundary.records.append(
                CallRecord(
                    "qdrant",
                    operation,
                    "success",
                    None,
                    int((time.monotonic() - started) * 1000),
                    result=summary,
                    target=target,
                )
            )
            return result

        return call

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if name in ("query_points", "retrieve") and callable(attr):
            return self._recorded(name, attr)
        return attr

    def close(self):
        return self._inner.close()


def _usable_chunk_vector(vector) -> bool:
    """V1: a chunk vector the release picker can actually use.

    The picker computes cosine similarity against the query embedding, so a
    None or wrong-width vector is not usable coverage; the release
    get_vectors_by_ids() itself drops points whose vector is None before the
    mapping ever reaches the picker."""
    if vector is None:
        return False
    try:
        return len(vector) == EMBEDDING_DIM
    except TypeError:
        return False


class _EffectiveChunkVectorObserver:
    """V1: observes the mapping the release chunks storage hands to the picker
    (get_vectors_by_ids), so vector coverage is judged on EFFECTIVE vectors
    keyed by the REQUESTED chunk identity — per stage and per collection —
    never on raw transport point counts.

    For every observed call it records: requested count, effective (matched
    and usable) count, bounded missing/mismatched/unusable samples with
    totals, the raw point count of the retrieve traffic in that window
    (transport statistic only) and whether the call is complete. A call is
    complete only when every requested id came back with a usable vector and
    no foreign id was mapped in (the release helper aborts to WEIGHT whenever
    the mapping does not line up with the requested chunk identity)."""

    def __init__(self, boundary: ServiceBoundary):
        self._boundary = boundary
        self.calls: list[dict] = []
        self.stage: str | None = None

    def bind(self, storage) -> bool:
        getter = getattr(storage, "get_vectors_by_ids", None)
        if not callable(getter):
            return False
        observer = self

        async def observed_get_vectors(ids):
            requested = [str(i) for i in ids]
            before = len(observer._boundary.records)
            mapping = await getter(ids)
            window = observer._boundary.records[before:]
            raw_points = sum(
                (r.result or {}).get("items", 0)
                for r in window
                if r.service == "qdrant" and r.operation == "retrieve" and r.status == "success"
            )
            retrieve_failed = any(
                r.service == "qdrant" and r.operation == "retrieve" and r.status == "failure"
                for r in window
            )
            observer._record(requested, mapping, raw_points, retrieve_failed)
            return mapping

        try:
            storage.get_vectors_by_ids = observed_get_vectors
        except Exception:  # noqa: BLE001 — observer is additive; never break reads
            return False
        return True

    def _record(self, requested, mapping, raw_points: int, retrieve_failed: bool) -> None:
        norm = {str(k): v for k, v in mapping.items()} if isinstance(mapping, dict) else {}
        req = set(requested)
        matched = req & set(norm)
        usable = {k for k in matched if _usable_chunk_vector(norm[k])}
        missing = sorted(req - set(norm))
        mismatched = sorted(set(norm) - req)
        unusable = sorted(matched - usable)
        self.calls.append(
            {
                "stage": self.stage or "unlabeled",
                "collection": "chunks",
                "vectors_requested": len(req),
                "vectors_effective": len(usable),
                "vectors_missing_total": len(missing),
                "vectors_missing": missing[:5],
                "vectors_mismatched_total": len(mismatched),
                "vectors_mismatched": mismatched[:5],
                "vectors_unusable_total": len(unusable),
                "vectors_unusable": unusable[:5],
                "points_returned_raw": raw_points,
                "retrieve_failed": retrieve_failed,
                "complete": bool(req) and not missing and not mismatched and not unusable,
            }
        )


def bind_qdrant_readonly(
    namespace: str,
    workspace: str,
    embedding: EmbeddingFunc,
    values: dict,
    boundary: ServiceBoundary,
) -> QdrantVectorDBStorage:
    """Bind a release QdrantVectorDBStorage for READS ONLY.

    Sets the storage's internal connection/lock fields directly — the release
    initialize() is NEVER called (it would submit create_payload_index and
    contain create/migrate branches). The collection must already exist with
    the expected vector dim and workspace payload index; otherwise refuse.

    M3: the native client is owned from its creation — any failure while
    constructing the storage, reading metadata or binding locks closes it
    before the error propagates. On success it transfers to the caller.
    """
    # import through the release storage module so any patched client class
    # (test doubles) applies; the release module imports QdrantClient itself.
    from lightrag.kg import qdrant_impl as _qdrant_module

    expected_collection = (
        f"lightrag_vdb_{namespace}_"
        + EMBEDDING_MODEL.lower().replace("/", "_").replace("-", "_").replace(".", "_")
        + f"_{EMBEDDING_DIM}d"
    )
    # When la.QdrantVectorDBStorage has been replaced by a test double, the
    # double IS the connection owner — skip native client construction and
    # metadata verification (production always uses the real release class,
    # which is always fully verified below).
    using_release_class = QdrantVectorDBStorage is _qdrant_module.QdrantVectorDBStorage
    client = None
    if using_release_class:
        client = _qdrant_module.QdrantClient(
            url=values["QDRANT_URL"],
            api_key=values.get("QDRANT_API_KEY") or None,
            timeout=15,
        )
    try:
        storage = QdrantVectorDBStorage(
            namespace=namespace,
            workspace=workspace,
            global_config={
                "embedding_batch_num": 32,
                "vector_db_storage_cls_kwargs": {"cosine_better_than_threshold": 0.2},
            },
            embedding_func=embedding,
            meta_fields=[],
        )
        if not using_release_class:
            # test double: bind as-is, no native client, no metadata verification
            storage._initialized = True
            return storage
        if storage.final_namespace != expected_collection:
            raise AdapterError(
                f"derived collection {storage.final_namespace!r} != expected "
                f"production collection {expected_collection!r}"
            )
        # read-only metadata verification — missing/incompatible REFUSES, no
        # create. collection_exists + get_collection are pure reads;
        # create_payload_index / recreate_collection / update_collection are
        # never touched.
        try:
            exists = client.collection_exists(storage.final_namespace)
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(
                f"collection existence check failed for {storage.final_namespace!r} "
                f"({type(exc).__name__}: {str(exc)[:120]}); refusing to create"
            ) from exc
        if not exists:
            raise AdapterError(
                f"production collection {storage.final_namespace!r} does not exist; "
                "refusing to create (initialize would submit writes)"
            )
        if hasattr(client, "get_collection"):
            # full dim/index verification on the real client; a test double may
            # omit this read API — the existence check above already ran.
            try:
                info = client.get_collection(storage.final_namespace)
            except Exception as exc:  # noqa: BLE001
                raise AdapterError(
                    f"production collection {storage.final_namespace!r} not readable "
                    f"({type(exc).__name__}: {str(exc)[:120]}); refusing to create"
                ) from exc
            dim = info.config.params.vectors.size
            if dim != EMBEDDING_DIM:
                raise AdapterError(
                    f"collection {storage.final_namespace!r} dim {dim} != {EMBEDDING_DIM}"
                )
            if "workspace_id" not in (info.payload_schema or {}):
                raise AdapterError(
                    f"collection {storage.final_namespace!r} lacks the workspace_id "
                    "payload index; refusing to create it (initialize would submit "
                    "a write)"
                )
        # bind read paths onto the storage WITHOUT calling initialize(); the
        # client is wrapped so native read calls land on the service boundary
        recorded_client = _RecordingQdrantClient(client, boundary, target=namespace)
        storage._client = recorded_client
        storage._initialized = True
        from lightrag.kg.shared_storage import get_namespace_lock

        storage._flush_lock = get_namespace_lock(
            namespace=storage.final_namespace, workspace=storage.effective_workspace
        )
        return storage
    except BaseException:
        # M3: every failure after client creation closes it before propagating.
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001 — teardown best effort
                pass
        raise


def bind_neo4j_readonly(
    workspace: str, embedding: EmbeddingFunc, values: dict, boundary: ServiceBoundary
) -> Neo4JStorage:
    """Bind a release Neo4JStorage for READS ONLY (no initialize/DDL).

    M3: the driver is owned from creation; a failure while constructing/
    binding closes it before propagating. When Neo4JStorage has been replaced
    by a test double, the double IS the connection owner — no real driver is
    created (mirrors the Qdrant binding)."""
    from lightrag.kg import neo4j_impl as _neo4j_module

    using_release_class = Neo4JStorage is _neo4j_module.Neo4JStorage
    if not using_release_class:
        return Neo4JStorage(
            namespace="chunk_entity_relation",
            workspace=workspace,
            global_config={},
            embedding_func=embedding,
        )
    from neo4j import AsyncGraphDatabase

    # N3: construct the storage FIRST — a failing constructor must not acquire
    # a driver at all (nothing to leak, nothing to fire-and-forget close).
    storage = Neo4JStorage(
        namespace="chunk_entity_relation",
        workspace=workspace,
        global_config={},
        embedding_func=embedding,
    )
    # the driver is acquired only once the storage exists; everything after
    # this point is plain attribute assignment (cannot fail), so an acquired
    # driver is always returned to the caller's lifecycle — no detached
    # task/close path is needed or used.
    driver = AsyncGraphDatabase.driver(
        values["NEO4J_URI"],
        auth=(values["NEO4J_USERNAME"], values["NEO4J_PASSWORD"]),
        connection_timeout=15,
    )
    storage._driver = _RecordingNeo4jDriver(driver, boundary)
    storage._DATABASE = values.get("NEO4J_DATABASE") or "neo4j"
    return storage


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    chunk_id: str
    workspace: str
    full_doc_id: str
    file_path: str | None
    content_head: str
    content_len: int
    verified: bool
    verify_error: str | None = None
    reached_via: list[str] = field(default_factory=list)
    similarity_order: int | None = None
    source_type: str | None = None


@dataclass
class LocalCandidateResult:
    query: str
    mode: str
    workspace: str
    query_id: str | None
    started_at: str
    finished_at: str
    keywords: dict
    entities: list[dict]
    relations: list[dict]
    candidates: list[Candidate]
    service_calls: dict
    call_records: list[dict]
    sorting_sources: dict
    degraded: list[str]
    errors: list[str]
    identity: dict


class LocalCandidateAdapter:
    """Runs the release local-mode candidate path over production backends."""

    def __init__(self, values: dict, workspace: str = "default"):
        self.values = values
        self.workspace = workspace
        self.boundary = ServiceBoundary()
        self._chunk_store: ReadOnlyPGTextChunks | None = None
        # L4: per-request counters used by the assembly layer (isolated
        # from the boundary's per-call records; not shared across fetches)
        self.service_call_counters: dict = {}

    async def _read_chunks(self, ids: list[str]) -> list[dict]:
        """Read-back hook: (workspace, chunk_id) production row lookup.

        Uses the ReadOnlyPGTextChunks instance bound on self._chunk_store by
        fetch(); tests may override this method entirely (fake rows)."""
        return [r for r in await self._chunk_store.get_by_ids(ids) if r is not None]

    async def fetch(
        self,
        query: str,
        top_k: int = 10,
        chunk_top_k: int = 10,
        query_id: str | None = None,
        frozen_gold_sha: str | None = None,
    ) -> LocalCandidateResult:
        started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        degraded: list[str] = []
        errors: list[str] = []
        sorting_sources: dict = {}

        # M2: every fetch gets a FRESH service ledger — reusing one adapter
        # for a second request must not mix records/counters with the first.
        self.boundary = ServiceBoundary()
        self.service_call_counters = {}

        # ---- L3 guards BEFORE any connection/service call -------------------
        mapping = verify_config_guard(self.values, self.workspace)
        if frozen_gold_sha is not None:
            if frozen_gold_sha != FROZEN["gold_sha"]:
                raise AdapterError(
                    f"frozen gold sha mismatch: {frozen_gold_sha} != {FROZEN['gold_sha']}"
                )

        resources: list = []  # L5: every owned connection registered at creation
        shared_storage.initialize_share_data(workers=1)
        try:
            embedding = build_real_embedding_func(self.values, self.boundary)
            keyword_llm = build_real_keyword_llm(self.values, self.boundary)

            # ---- L1: read-only binding (metadata verified, no initialize) ---
            qdrant_entities = bind_qdrant_readonly(
                "entities", mapping["vector"], embedding, self.values, self.boundary
            )
            resources.append(("qdrant_entities", qdrant_entities))
            qdrant_chunks = bind_qdrant_readonly(
                "chunks", mapping["vector"], embedding, self.values, self.boundary
            )
            resources.append(("qdrant_chunks", qdrant_chunks))
            # V1: observe the EFFECTIVE mapping the release chunks storage hands
            # to the picker (post-filter/mapping), not raw transport counts.
            vector_observer = _EffectiveChunkVectorObserver(self.boundary)
            vector_observer.bound = vector_observer.bind(qdrant_chunks)
            neo4j_graph = bind_neo4j_readonly(
                mapping["graph"], embedding, self.values, self.boundary
            )
            resources.append(("neo4j_graph", neo4j_graph))
            # L1 verification: the bound graph label must be the production one
            if neo4j_graph.workspace != mapping["graph"]:
                raise AdapterError(
                    f"graph workspace {neo4j_graph.workspace!r} != verified "
                    f"production label {mapping['graph']!r}"
                )

            text_chunks = ReadOnlyPGTextChunks(
                self.values, workspace=self.workspace, boundary=self.boundary
            )
            self._chunk_store = text_chunks  # bound for the _read_chunks hook
            text_chunks.global_config = {
                # release defaults: kg_chunk_pick_method VECTOR, budget 5
                "kg_chunk_pick_method": "VECTOR",
                "related_chunk_number": 5,
                "tokenizer": None,  # release backfill uses tokenizer only when set
            }
            text_chunks.embedding_func = embedding

            # ---- release local pipeline (real LLM/embedding/reads) -----------
            query_param = _SimpleQueryParam(top_k=top_k, chunk_top_k=chunk_top_k)
            config = _pipeline_global_config(keyword_llm, embedding)
            hl_kw, ll_kw = await release_get_keywords_from_query(query, query_param, config, None)
            if not ll_kw:
                ll_kw = [query]

            node_datas, use_relations = await self.boundary.call_group(
                "neo4j",
                "get_node_data",
                _get_node_data,
                ", ".join(ll_kw),
                neo4j_graph,
                qdrant_entities,
                query_param,
            )
            _ = _find_most_related_edges_from_entities  # read via node_datas path

            # ---- L2: provenance (reviewed extension, no extra service calls)
            # + release chunk-data selection. Provenance comes from the REAL
            # src_tgt endpoints/source_id; the SELECTION is done entirely by
            # the release _find_related_text_unit_* functions (M2: no
            # duplicated VECTOR discovery request in the assembly helper).
            assembly_ids, reached_via, assembly_notes = await _assemble_candidates(
                node_datas,
                use_relations,
                query,
                query_param,
                embedding,
                qdrant_chunks,
                neo4j_graph,
                self.service_call_counters,
                text_chunks,
                select=False,  # M2: production selection is done by the release
                # functions below — no duplicated VECTOR discovery request
            )
            degraded.extend(assembly_notes)

            chunk_tracking: dict = {}
            entity_chunks: list[dict] = []
            relation_chunks: list[dict] = []
            if node_datas:
                vector_observer.stage = "entities"
                entity_chunks = await self.boundary.call_group(
                    "pg",
                    "find_related_text_unit_entities",
                    _find_related_text_unit_from_entities,
                    node_datas,
                    query_param,
                    text_chunks,
                    neo4j_graph,
                    query=query,
                    chunks_vdb=qdrant_chunks,
                    chunk_tracking=chunk_tracking,
                )
            if use_relations:
                vector_observer.stage = "relations"
                relation_chunks = await self.boundary.call_group(
                    "pg",
                    "find_related_text_unit_relations",
                    _find_related_text_unit_from_relations,
                    use_relations,
                    query_param,
                    text_chunks,
                    entity_chunks=entity_chunks,
                    query=query,
                    chunks_vdb=qdrant_chunks,
                    chunk_tracking=chunk_tracking,
                )
            vector_observer.stage = None

            # M2/N1/V1: the chunk ordering is only "vector-similarity" when a
            # REAL vector ranking produced it. Judgement is per-STAGE and
            # per-COLLECTION, and on the EFFECTIVE mapping the release storage
            # handed to the picker (V1): missing vectors, original-identity
            # mismatches and unusable widths are not coverage, no matter how
            # many points the transport returned. The release helpers swallow
            # embedding/Qdrant errors and fall back — every degradation must be
            # visible:
            #   * embedding/qdrant attempt failed      -> truncation fallback
            #   * chunk selection without complete effective vector coverage
            #     on the CHUNKS collection             -> weight fallback
            embed_failures = [
                r
                for r in self.boundary.records
                if r.service == "embedding" and r.status == "failure"
            ]
            qdrant_failures = [
                r for r in self.boundary.records if r.service == "qdrant" and r.status == "failure"
            ]
            entity_chunk_ids = {
                cid.strip()
                for e in node_datas
                if e.get("source_id")
                for cid in e["source_id"].split("¤")
                if cid.strip()
            }
            # V1: coverage comes from the observed EFFECTIVE mapping per stage;
            # the raw transport point count is reported separately and never
            # named or used as a vector count.
            observed_calls = vector_observer.calls
            vectors_requested = sum(c["vectors_requested"] for c in observed_calls)
            vectors_effective = sum(c["vectors_effective"] for c in observed_calls)
            points_returned_raw = sum(c["points_returned_raw"] for c in observed_calls)
            missing_total = sum(c["vectors_missing_total"] for c in observed_calls)
            mismatched_total = sum(c["vectors_mismatched_total"] for c in observed_calls)
            unusable_total = sum(c["vectors_unusable_total"] for c in observed_calls)
            need_chunk_vectors = bool(entity_chunk_ids)
            # FULL effective coverage is required: the release picker aborts to
            # WEIGHT on any missing/mismatched identity, so partial coverage is
            # also a fallback. A CHUNKS pick that never observed the storage's
            # get_vectors_by_ids mapping cannot be vouched for either.
            if need_chunk_vectors:
                vector_backed = bool(observed_calls) and all(c["complete"] for c in observed_calls)
            else:
                vector_backed = True
            sorting_sources["chunk_pick_vectors"] = {
                "expected_chunks": len(entity_chunk_ids),
                "observer_bound": bool(getattr(vector_observer, "bound", False)),
                "observed_calls": [
                    {
                        "stage": c["stage"],
                        "collection": c["collection"],
                        "vectors_requested": c["vectors_requested"],
                        "vectors_effective": c["vectors_effective"],
                        "missing_total": c["vectors_missing_total"],
                        "missing_sample": c["vectors_missing"],
                        "mismatched_total": c["vectors_mismatched_total"],
                        "mismatched_sample": c["vectors_mismatched"],
                        "unusable_total": c["vectors_unusable_total"],
                        "unusable_sample": c["vectors_unusable"],
                        "points_returned_raw": c["points_returned_raw"],
                        "retrieve_failed": c["retrieve_failed"],
                        "complete": c["complete"],
                    }
                    for c in observed_calls
                ],
                "vectors_requested": vectors_requested,
                "vectors_effective": vectors_effective,
                "missing_total": missing_total,
                "mismatched_total": mismatched_total,
                "unusable_total": unusable_total,
                "points_returned_raw": points_returned_raw,
                "vector_backed": bool(vector_backed),
            }
            if embed_failures or qdrant_failures:
                sorting_sources["chunk_pick"] = "truncation-fallback"
                degraded.append(
                    f"{len(embed_failures)} embedding / {len(qdrant_failures)} qdrant "
                    "call(s) failed; the release VECTOR helper's order is a "
                    "fallback, not a similarity ranking (degraded)"
                )
            elif entity_chunks and not vector_backed:
                detail = (
                    f"requested={vectors_requested}, effective={vectors_effective}, "
                    f"missing={missing_total}, mismatched={mismatched_total}, "
                    f"unusable={unusable_total}"
                )
                sorting_sources["chunk_pick"] = "weight-fallback"
                degraded.append(
                    "chunk candidates were selected without complete effective "
                    f"vector coverage on the CHUNKS collection ({detail} → release "
                    "WEIGHT fallback); not a vector-similarity ordering"
                )
            else:
                sorting_sources["chunk_pick"] = "vector-similarity"

            # ---- L2 budget: chunk_top_k caps the FINAL candidate list --------
            # Release-selected chunk data comes first, then assembly/evidence
            # ids (edge-only provenance) — never deduplicating away different
            # version or path sources: each id keeps ALL its reached_via.
            ordered_ids: list[str] = []
            seen: set[str] = set()
            for chunk in entity_chunks + relation_chunks:
                cid = chunk.get("chunk_id")
                if cid and cid not in seen:
                    seen.add(cid)
                    ordered_ids.append(cid)
            extra = [cid for cid in assembly_ids if cid not in seen]
            ordered_ids.extend(extra)
            final_ids = ordered_ids[:chunk_top_k]

            # ---- PG read-back + identity verification ------------------------
            chunk_rows = await self._read_chunks(final_ids)
            rows_by_id = {r["id"]: r for r in chunk_rows if r is not None}
            candidates: list[Candidate] = []
            for order, chunk_id in enumerate(final_ids):
                row = rows_by_id.get(chunk_id)
                via = reached_via.get(chunk_id, [])
                if row is None:
                    degraded.append(
                        f"chunk {chunk_id} not found in production lightrag_doc_chunks "
                        f"(workspace={self.workspace}); candidate rejected"
                    )
                    candidates.append(
                        Candidate(
                            chunk_id=chunk_id,
                            workspace=self.workspace,
                            full_doc_id="",
                            file_path=None,
                            content_head="",
                            content_len=0,
                            verified=False,
                            verify_error="missing-in-production-pg",
                            reached_via=via,
                            similarity_order=order,
                        )
                    )
                    continue
                expected_doc = chunk_id.rsplit("-chunk-", 1)[0]
                if row["full_doc_id"] != expected_doc:
                    degraded.append(
                        f"chunk {chunk_id} full_doc_id {row['full_doc_id']} does not "
                        "match the id-derived document; candidate rejected"
                    )
                    candidates.append(
                        Candidate(
                            chunk_id=chunk_id,
                            workspace=row["workspace"],
                            full_doc_id=row["full_doc_id"],
                            file_path=row["file_path"],
                            content_head=(row["content"] or "")[:80],
                            content_len=len(row["content"] or ""),
                            verified=False,
                            verify_error="full_doc_id-mismatch",
                            reached_via=via,
                            similarity_order=order,
                        )
                    )
                    continue
                candidates.append(
                    Candidate(
                        chunk_id=row["id"],
                        workspace=row["workspace"],
                        full_doc_id=row["full_doc_id"],
                        file_path=row["file_path"],
                        content_head=(row["content"] or "")[:80],
                        content_len=len(row["content"] or ""),
                        verified=True,
                        reached_via=via,
                        similarity_order=order,
                        source_type="entity"
                        if any(c.get("chunk_id") == chunk_id for c in entity_chunks)
                        else (
                            "relation"
                            if any(c.get("chunk_id") == chunk_id for c in relation_chunks)
                            else "discovery-evidence"
                        ),
                    )
                )

            # M2/L4: two separate views of the SAME ledger —
            #   * by_service: per-service attempt/success/failure of the
            #     ACTUAL underlying calls (HTTP/Qdrant reads/SQL/model calls),
            #     each recorded at the real boundary;
            #   * groups: helper-level stages that aggregate/bundle calls
            #     (neo4j batch helpers, PG selection helpers). Never conflated:
            #     a group is not an HTTP request.
            flat = dict(self.service_call_counters)  # isolation per request
            flat.setdefault("embedding_requests", 0)
            flat.setdefault("llm_requests", 0)
            flat.setdefault("qdrant_queries", 0)
            flat.setdefault("neo4j_reads", 0)
            flat.setdefault("pg_readonly_queries", 0)
            # real underlying attempts, from the boundary records
            by_service = self.boundary.counts()
            flat["qdrant_queries"] = by_service.get("qdrant", {}).get("attempt", 0)
            flat["embedding_requests"] = by_service.get("embedding", {}).get("attempt", 0)
            flat["llm_requests"] = by_service.get("llm", {}).get("attempt", 0)
            flat["pg_readonly_queries"] = sum(
                1
                for r in self.boundary.records
                if r.service == "pg" and r.operation == "readonly_select_chunks"
            )
            flat["by_service"] = by_service
            flat["groups"] = self.boundary.group_counts()
            flat["neo4j_reads"] = flat["groups"].get("neo4j", {}).get("attempt", 0)
            service_calls = flat

            return LocalCandidateResult(
                query=query,
                mode="local",
                workspace=self.workspace,
                query_id=query_id,
                started_at=started,
                finished_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                keywords={"high_level": hl_kw, "low_level": ll_kw},
                entities=node_datas,
                relations=use_relations,
                candidates=candidates,
                service_calls=service_calls,
                call_records=[vars(r) | {} for r in self.boundary.records],
                sorting_sources=sorting_sources,
                degraded=degraded,
                errors=errors,
                identity={
                    "pg_workspace": self.workspace,
                    "vector_workspace": mapping["vector"],
                    "graph_workspace": mapping["graph"],
                    "embedding_model": self.values.get("EMBEDDING_MODEL"),
                    "collections": [
                        qdrant_entities.final_namespace,
                        qdrant_chunks.final_namespace,
                    ],
                },
            )
        finally:
            # ---- M3/N3 close-only cleanup: every owned resource, no flush ----
            # Branch by NATIVE-HANDLE OWNERSHIP, not by close success:
            #   * a resource with our _client/_driver handle is closed via that
            #     handle ONLY — the release Qdrant finalize() (which flushes)
            #     is NEVER called on it, not even when close() itself failed;
            #   * a resource without a native handle (test double) is released
            #     via its finalize, which is its only release path.
            # A non-empty pending write queue is refused (recorded) and the
            # connection still closes; close errors never skip the remaining
            # resources, post-guard or terminal report.
            close_errors = []
            for name, resource in resources:
                pending_docs = getattr(resource, "_pending_vector_docs", None)
                pending_dels = getattr(resource, "_pending_vector_deletes", None)
                pending = (pending_docs or {}) or (pending_dels or set())
                if pending:
                    close_errors.append(
                        f"{name}: pending write queue not empty; refusing flush "
                        "(production writes forbidden) but closing the connection"
                    )
                client = getattr(resource, "_client", None)
                driver = getattr(resource, "_driver", None)
                owns_native_handle = client is not None or driver is not None
                if client is not None:
                    try:
                        client.close()
                        resource._client = None
                    except Exception as exc:  # noqa: BLE001 — record, keep closing
                        close_errors.append(f"{name}: {type(exc).__name__}: {exc}")
                if driver is not None:
                    try:
                        await driver.close()
                        resource._driver = None
                    except Exception as exc:  # noqa: BLE001 — record, keep going
                        close_errors.append(f"{name}: {type(exc).__name__}: {exc}")
                if not owns_native_handle and hasattr(resource, "finalize"):
                    # non-native owner (no client/driver we created): finalize
                    # is its only release path and cannot flush production
                    # (it holds no production connection).
                    try:
                        await resource.finalize()
                    except Exception as exc:  # noqa: BLE001 — record, keep going
                        close_errors.append(f"{name}: {type(exc).__name__}: {exc}")
            try:
                shared_storage.finalize_share_data()
            except Exception as exc:  # noqa: BLE001 — teardown best effort
                close_errors.append(f"shared_storage: {exc}")
            if close_errors:
                degraded.extend(f"resource close error: {e}" for e in close_errors)


class _SimpleQueryParam:
    """QueryParam subset the release functions actually read on this path."""

    def __init__(self, top_k: int = 10, chunk_top_k: int = 10):
        self.top_k = top_k
        self.chunk_top_k = chunk_top_k
        self.mode = "local"
        self.max_entity_tokens = 6000
        self.max_relation_tokens = 8000
        self.max_total_tokens = 32000
        self.hl_keywords = []
        self.ll_keywords = []


# ---------------------------------------------------------------------------
# L2 documented extension: provenance tracking only
#
# The production candidate SELECTION is done entirely by the release functions
# (_find_related_text_unit_from_entities/_from_relations) in fetch(). This
# helper has two modes:
#   select=False (production fetch): provenance/evidence ONLY — it never
#     requests embeddings/vectors (M2: the release functions do the one real
#     selection, no duplicated discovery query);
#   select=True (default, reviewed contract surface): additionally performs
#     the release VECTOR selection with WEIGHT fallback, recording swallowed
#     embedding failures in `notes` (first-review contract).
# Common guarantees:
#   * edge endpoints are read from the release `src_tgt` field (never
#     source/target) — every distinct edge keeps its own provenance entry;
#   * occurrence counting spans ALL entities/edges BEFORE any sorting (the
#     release "count fully, then sort" semantics);
#   * the FINAL candidate budget (chunk_top_k) is enforced by fetch().
# ---------------------------------------------------------------------------


async def _assemble_candidates(
    entities,
    edges,
    query,
    query_param,
    embedding,
    chunks_vdb,
    knowledge_graph_inst,
    service_calls,
    text_chunks,
    select: bool = True,
):
    from lightrag.constants import DEFAULT_RELATED_CHUNK_NUMBER, GRAPH_FIELD_SEP
    from lightrag.utils import split_string_by_multi_markers

    notes: list[str] = []
    tracking: dict[str, list[str]] = {}

    # provenance from real native endpoints — every entity/edge keeps its own
    # entry; later entities/edges never overwrite earlier ones.
    for entity in entities:
        if entity.get("source_id"):
            for cid in split_string_by_multi_markers(entity["source_id"], [GRAPH_FIELD_SEP]):
                tracking.setdefault(cid, []).append(f"entity:{entity.get('entity_name')}")
    for edge in edges:
        if edge.get("source_id"):
            src_tgt = edge.get("src_tgt") or (
                edge.get("src_id"),
                edge.get("tgt_id"),
            )
            label = f"edge:{src_tgt[0]}|{src_tgt[1]}"
            for cid in split_string_by_multi_markers(edge["source_id"], [GRAPH_FIELD_SEP]):
                tracking.setdefault(cid, []).append(label)

    # Evidence ordering: count occurrences across ALL entities first, then
    # sort (release semantics).
    occurrence: dict[str, int] = {}
    for entity in entities:
        if entity.get("source_id"):
            for cid in split_string_by_multi_markers(entity["source_id"], [GRAPH_FIELD_SEP]):
                occurrence[cid] = occurrence.get(cid, 0) + 1
    evidence_ids = sorted(occurrence, key=lambda c: occurrence[c], reverse=True)
    for edge in edges:
        if edge.get("source_id"):
            for cid in split_string_by_multi_markers(edge["source_id"], [GRAPH_FIELD_SEP]):
                if cid not in occurrence:
                    occurrence[cid] = 1
                    evidence_ids.append(cid)

    if not select:
        return evidence_ids, tracking, notes

    # ---- reviewed-contract selection path (first-review surface) ------------
    from lightrag.utils import pick_by_vector_similarity, pick_by_weighted_polling

    entities_with_chunks = []
    for entity in entities:
        if entity.get("source_id"):
            chunks = split_string_by_multi_markers(entity["source_id"], [GRAPH_FIELD_SEP])
            if chunks:
                entities_with_chunks.append(
                    {"entity_name": entity.get("entity_name"), "chunks": chunks}
                )
    if not entities_with_chunks:
        return evidence_ids, tracking, notes
    # Step 2-3: dedup + full occurrence count, then sort
    entity_occurrence: dict[str, int] = {}
    for info in entities_with_chunks:
        deduped = []
        for chunk_id in info["chunks"]:
            entity_occurrence[chunk_id] = entity_occurrence.get(chunk_id, 0) + 1
            if entity_occurrence[chunk_id] == 1:
                deduped.append(chunk_id)
        info["chunks"] = deduped
        info["sorted_chunks"] = sorted(
            deduped, key=lambda c: entity_occurrence.get(c, 0), reverse=True
        )
    max_related_chunks = DEFAULT_RELATED_CHUNK_NUMBER
    if text_chunks is not None:
        cfg = getattr(text_chunks, "global_config", None)
        if cfg:
            max_related_chunks = cfg.get("related_chunk_number") or DEFAULT_RELATED_CHUNK_NUMBER
    num_of_chunks = int(max_related_chunks * len(entities_with_chunks) / 2)
    recorded_embedding = embedding
    if embedding is not None:

        async def recorded_embed(texts, **kwargs):
            try:
                return await embedding(texts, **kwargs)
            except Exception as exc:  # noqa: BLE001 — record, then re-raise
                notes.append(
                    f"embedding call inside VECTOR pick failed "
                    f"({type(exc).__name__}: {str(exc)[:120]}); the release "
                    "helper's result is a truncation fallback, not a similarity "
                    "ranking (degraded)"
                )
                raise

        recorded_embedding = recorded_embed
    selected: list[str] = []
    try:
        selected = await pick_by_vector_similarity(
            query=query,
            text_chunks_storage=text_chunks,
            chunks_vdb=chunks_vdb,
            num_of_chunks=num_of_chunks,
            entity_info=entities_with_chunks,
            embedding_func=recorded_embedding,
            query_embedding=None,
        )
        if not selected:
            notes.append("VECTOR selection returned nothing; WEIGHT fallback")
    except Exception as exc:  # noqa: BLE001 — recorded, fallback explicit
        notes.append(f"VECTOR selection failed ({type(exc).__name__}: {exc}); WEIGHT fallback")
    if not selected:
        selected = pick_by_weighted_polling(entities_with_chunks, max_related_chunks)
    seen = set(selected)
    for edge in edges:
        if not edge.get("source_id"):
            continue
        for cid in split_string_by_multi_markers(edge["source_id"], [GRAPH_FIELD_SEP]):
            if cid not in seen:
                seen.add(cid)
                selected.append(cid)
    return selected, tracking, notes


def _pipeline_global_config(keyword_llm, embedding) -> dict:
    from lightrag.prompt import PROMPTS
    from lightrag.utils import TiktokenTokenizer

    return {
        "role_llm_funcs": {"keyword": keyword_llm, "query": keyword_llm},
        "tokenizer": TiktokenTokenizer(),
        "_resolved_summary_language": "Chinese",
        "addon_params": {"language": "Chinese"},
        "llm_cache_identity": None,
        "PROMPTS": PROMPTS,
    }


# ---------------------------------------------------------------------------
# frozen-gold run entry (L3 real identity guards + L4 failure terminal state)
# ---------------------------------------------------------------------------

DEFAULT_RUN = ["fact-001", "fact-002", "syn-001", "neg-001"]
GOLD_PATH = Path("reports/pg-retrieval/gate-2/review-r5/gold-approved.json")


async def _capture_production_identity(values: dict) -> dict:
    """Read-only capture of the frozen identity components (L3)."""
    from env_rag_final.compat_runtime import (
        _identity_mismatch,
        capture_production_identity,
    )

    identity = await capture_production_identity(values, "local-runtime")
    problems = _identity_mismatch(identity)
    return {"identity": identity, "problems": problems, "matches_frozen": not problems}


async def run_frozen(report_dir: Path, queries: list[str] | None = None) -> dict:
    """Run the adapter over a frozen-gold subset with real identity guards.

    M1: the actual gold/source/catalog/search/env identity is captured and
    compared BEFORE any fetch; the post-guard compares EVERY field against
    the before-capture (including the .env byte SHA) and the terminal report
    — success or failure — is written AFTER the post-guard and resource
    cleanup, carrying identity_after / identity_after_error, the original
    error, completed results and failure call records. No finished_at on
    failure; the original error is never overwritten.
    """
    values = dict(dotenv_values(".env"))
    report: dict = {
        "task": "5.2 real local candidate adapter (rev 2, read-only, guarded)",
        "release": "lightrag-hku 1.5.7",
        "frozen_contract": FROZEN,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    report_dir.mkdir(parents=True, exist_ok=True)

    def _write_terminal() -> None:
        """M1: the ONE terminal writer — called after post-guard + cleanup."""
        stamp = time.strftime("%Y%m%dT%H%M%S")
        body = json.dumps(report, ensure_ascii=False, indent=1) + "\n"
        (report_dir / f"local-runtime-{stamp}.json").write_text(body, encoding="utf-8")
        (report_dir / "local-runtime-latest.json").write_text(body, encoding="utf-8")

    async def _write_failure(stage: str, detail) -> None:
        report["failure"] = {"stage": stage, "detail": detail}
        _write_terminal()

    # ---- pre-flight local guards (BEFORE any backend read/service call) -----
    # M1: unknown query ids and the local gold/config checks come first so bad
    # input never causes even the identity capture to run.
    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    by_id = {q["query_id"]: q for q in gold["questions"]}
    for c in gold.get("counter_examples", []):
        cid = c.get("counter_id")
        if cid and cid not in by_id:
            by_id[cid] = {
                "query_id": cid,
                "question": c.get("question") or c.get("query") or "",
                "workspace": "default",
                "target_docs": [],
                "counter": {
                    "type": c.get("type"),
                    "expected_status": c.get("expected_status"),
                },
            }
    wanted = queries or DEFAULT_RUN
    unknown = [q for q in wanted if q not in by_id]
    if unknown:
        await _write_failure("unknown-query-id", unknown)
        raise AdapterError(f"unknown query ids (rejected before any call): {unknown}")
    gold_sha = verify_gold_guard(GOLD_PATH)
    report["gold_sha_verified"] = gold_sha

    # ---- pre-flight identity guard (BEFORE any service/backend call) -------
    try:
        pre = await _capture_production_identity(values)
    except Exception as exc:  # noqa: BLE001
        await _write_failure("identity-capture", f"{type(exc).__name__}: {exc}")
        raise AdapterError("pre-flight identity capture failed") from exc
    report["identity_before"] = {
        "matches_frozen": pre["matches_frozen"],
        "problems": pre["problems"],
        "counts": pre["identity"]["public_counts"],
        "source_fingerprint": pre["identity"]["source_fingerprint"],
        "catalog_active": pre["identity"]["catalog_active"],
        "search_active": pre["identity"]["search_active"],
        "gold_sha": pre["identity"]["gold_sha"],
        "env_sha": pre["identity"]["env_sha"],
    }
    if not pre["matches_frozen"]:
        await _write_failure("identity-before", pre["problems"])
        raise AdapterError("pre-flight identity mismatch: " + "; ".join(pre["problems"]))

    results = []
    fetch_error = None
    failed_query_id: str | None = None
    failed_adapter = None
    try:
        for qid in wanted:
            q = by_id[qid]
            adapter = LocalCandidateAdapter(values, workspace=q.get("workspace") or "default")
            failed_adapter = adapter
            failed_query_id = qid
            res = await adapter.fetch(q["question"], query_id=qid, frozen_gold_sha=gold_sha)
            failed_adapter = None
            failed_query_id = None
            results.append(_result_to_json(res, q))
    except Exception as exc:  # noqa: BLE001 — unified failure terminal state
        fetch_error = f"{type(exc).__name__}: {exc}"
    finally:
        # ---- M1 post-guard: capture then compare EVERY field before/after ---
        post = None
        post_error = None
        try:
            post = await _capture_production_identity(values)
        except Exception as exc:  # noqa: BLE001
            post_error = f"{type(exc).__name__}: {exc}"
            report["identity_after_error"] = post_error
        if post is not None:
            report["identity_after"] = {
                "matches_frozen": post["matches_frozen"],
                "problems": post["problems"],
                "counts": post["identity"]["public_counts"],
                "source_fingerprint": post["identity"]["source_fingerprint"],
                "catalog_active": post["identity"]["catalog_active"],
                "search_active": post["identity"]["search_active"],
                "gold_sha": post["identity"]["gold_sha"],
                "env_sha": post["identity"]["env_sha"],
            }
            # M1: field-by-field drift against the BEFORE capture — a .env
            # byte change with everything else identical must still refuse.
            drift = _identity_drift(pre["identity"], post["identity"])
            if drift:
                report["identity_drift"] = drift

        # ---- M1 unified terminal: write AFTER post-guard, then refuse -------
        if fetch_error is not None:
            report["results"] = results  # completed results are preserved
            # N2: serialize the FAILING request's actual service receipts so
            # the terminal report carries e.g. the llm/failure record. A
            # pre-flight rejection (no adapter/fetch started) reports an
            # explicit zero-call ledger instead of fabricating records.
            if failed_adapter is not None and getattr(failed_adapter, "boundary", None) is not None:
                boundary = failed_adapter.boundary
                report["failure_service_records"] = {
                    "query_id": failed_query_id,
                    "call_records": [vars(r) for r in boundary.records],
                    "group_records": [vars(r) for r in boundary.group_records],
                    "by_service": boundary.counts(),
                    "groups": boundary.group_counts(),
                }
            else:
                report["failure_service_records"] = {
                    "query_id": None,
                    "call_records": [],
                    "group_records": [],
                    "by_service": {},
                    "groups": {},
                    "note": "failure occurred before/without an adapter fetch",
                }
            await _write_failure("fetch", fetch_error)
        elif post_error:
            report["results"] = results
            await _write_failure("identity-after-capture-error", post_error)
        elif report.get("identity_drift"):
            report["results"] = results
            await _write_failure("identity-after-drift", report["identity_drift"])
        elif report.get("identity_after") and not report["identity_after"]["matches_frozen"]:
            report["results"] = results
            await _write_failure("identity-after", report["identity_after"]["problems"])

    if fetch_error is not None:
        raise AdapterError(f"fetch failed (terminal report written): {fetch_error}")
    if report.get("identity_after_error"):
        raise AdapterError(f"post-guard capture failed: {report['identity_after_error']}")
    if report.get("identity_drift"):
        raise AdapterError("post-guard identity drift: " + "; ".join(report["identity_drift"]))
    if report.get("identity_after") and not report["identity_after"]["matches_frozen"]:
        raise AdapterError(
            "post-guard identity mismatch: " + "; ".join(report["identity_after"]["problems"])
        )

    report["results"] = results
    report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    _write_terminal()
    jsonl = "\n".join(json.dumps(r, ensure_ascii=False) for r in results) + "\n"
    (report_dir / "local-candidates-latest.jsonl").write_text(jsonl, encoding="utf-8")
    return report


def _identity_drift(before: dict, after: dict) -> list[str]:
    """M1: field-by-field before/after drift (including .env byte SHA)."""
    drift: list[str] = []
    if before.get("public_counts") != after.get("public_counts"):
        drift.append(
            f"counts changed: {before.get('public_counts')} -> {after.get('public_counts')}"
        )
    if before.get("source_fingerprint") != after.get("source_fingerprint"):
        drift.append("source fingerprint changed during run")
    if before.get("catalog_active") != after.get("catalog_active"):
        drift.append(
            f"catalog active changed: {before.get('catalog_active')} -> "
            f"{after.get('catalog_active')}"
        )
    if before.get("search_active") != after.get("search_active"):
        drift.append(
            f"search active changed: {before.get('search_active')} -> {after.get('search_active')}"
        )
    if before.get("gold_sha") != after.get("gold_sha"):
        drift.append("gold SHA changed during run")
    if before.get("env_sha") != after.get("env_sha"):
        drift.append(f".env sha changed: {before.get('env_sha')} -> {after.get('env_sha')}")
    return drift


def _result_to_json(res: LocalCandidateResult, gold_q: dict) -> dict:
    target_ids = {t["doc_id"] for t in gold_q.get("target_docs", [])}
    return {
        "query_id": res.query_id,
        "query": res.query,
        "mode": res.mode,
        "workspace": res.workspace,
        "started_at": res.started_at,
        "finished_at": res.finished_at,
        "keywords": res.keywords,
        "entities_top": [
            {"entity_name": e.get("entity_name"), "rank": e.get("rank")} for e in res.entities[:8]
        ],
        "relations_count": len(res.relations),
        "candidates": [
            {
                "chunk_id": c.chunk_id,
                "workspace": c.workspace,
                "full_doc_id": c.full_doc_id,
                "doc_id_verified": c.full_doc_id in target_ids,
                "file_path": c.file_path,
                "content_head": c.content_head,
                "verified": c.verified,
                "verify_error": c.verify_error,
                "reached_via": c.reached_via,
                "similarity_order": c.similarity_order,
                "source_type": c.source_type,
            }
            for c in res.candidates
        ],
        "service_calls": res.service_calls,
        "call_records": res.call_records,
        "sorting_sources": res.sorting_sources,
        "identity": res.identity,
        "degraded": res.degraded,
        "errors": res.errors,
        "targets": sorted(target_ids),
        "counter": gold_q.get("counter"),
    }
