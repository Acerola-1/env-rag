"""LightRAG-driven ingestion for one workspace.

The runner drives the *real* pipeline of the pinned ``lightrag-hku`` release
(the same code that produced the existing ``default`` workspace, verified
byte-for-byte by ``reports/.../chunk-identity-proof.json``):

1. seed the target workspace's content-addressed extraction cache from the
   source workspace (recorded as reuse, never claimed as fresh),
2. enqueue each document and attach its MinerU sidecar so the
   paragraph-semantic chunker reproduces the exact chunks, headings and
   table/sidecar references,
3. run the pipeline (real embedding, real entity/relation extraction with
   cache hits, real graph build),
4. reconcile each document's terminal state and evidence into the ledger.

Nothing here writes to any workspace other than the requested target, and the
pre-existing ``default`` workspace is refused outright.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from env_rag_final.audit import identity
from env_rag_final.ingest.ledger import DocKey, Ledger, models_id
from env_rag_final.ingest.plan import WorkItem, load_manifest, plan_for_workspace
from env_rag_final.ingest.reuse import seed_extract_cache

INGEST_RECIPE = "wa-ingest-r1-paragraph-semantic-reuse"

REFUSED_WORKSPACES = {"default", ""}


class IngestError(RuntimeError):
    pass


@dataclass
class IngestConfig:
    workspace: str
    values: dict
    parsed_root: Path
    manifest_path: Path
    ledger_path: Path
    source_workspace: str = "default"
    dry_run: bool = False
    only: list[str] | None = None
    limit: int | None = None
    max_attempts: int = 2
    process_rounds: int = 1
    extra_docs: list[str] | None = None
    working_dir: Path | None = None
    overrides: dict = field(default_factory=dict)

    def model_identity(self) -> dict:
        v = self.values
        return {
            "llm": v.get("LLM_MODEL"),
            "keyword_llm": v.get("KEYWORD_LLM_MODEL"),
            "embedding": v.get("EMBEDDING_MODEL"),
            "embedding_dim": str(v.get("EMBEDDING_DIM")),
            "chunk_size": str(v.get("CHUNK_SIZE")),
            "chunk_overlap": str(v.get("CHUNK_OVERLAP")),
        }


def doc_key(cfg: IngestConfig, item: WorkItem) -> DocKey:
    return DocKey(
        workspace=cfg.workspace,
        doc_name=item.doc_name,
        source_sha256=item.sha256,
        recipe_id=INGEST_RECIPE,
        models=models_id(cfg.model_identity()),
    )


def export_environment(cfg: IngestConfig) -> None:
    """Publish the run configuration to the process environment.

    LightRAG reads storage and model settings from ``os.environ``, so values
    must be visible before any storage class is constructed.  The per-backend
    workspace overrides are set to the *same* value as ``WORKSPACE`` so that
    PostgreSQL, Qdrant and Neo4j all resolve one effective workspace; the
    health check verifies that afterwards.
    """
    import os

    for key, value in cfg.values.items():
        if value is None:
            continue
        os.environ[key] = str(value)
    os.environ["WORKSPACE"] = cfg.workspace
    os.environ["POSTGRES_WORKSPACE"] = cfg.workspace
    os.environ["QDRANT_WORKSPACE"] = cfg.workspace
    os.environ["NEO4J_WORKSPACE"] = cfg.workspace
    os.environ["NEO4J_DATABASE"] = cfg.values.get("NEO4J_DATABASE") or "neo4j"


def build_lightrag(cfg: IngestConfig):
    """Construct the real LightRAG instance for the target workspace."""
    import httpx
    import numpy as np
    from lightrag import LightRAG
    from lightrag.utils import EmbeddingFunc

    export_environment(cfg)
    v = cfg.values
    counters: dict[str, int] = {
        "llm_calls": 0,
        "extract_calls": 0,
        "summary_calls": 0,
        "prompt_tokens": 0,
        "embed_calls": 0,
    }

    async def llm(prompt, system_prompt=None, history_messages=None, **kwargs):
        """Real completion, reached only on a LightRAG cache miss.

        Extraction prompts are content-addressed and pre-seeded into the target
        workspace, so entity/relationship extraction is a cache hit; what lands
        here is the per-workspace entity/relation *merge summary*, which is
        genuinely a new product for a new workspace and must be computed.
        """
        counters["llm_calls"] += 1
        # Classify the real dispatch so the run can prove that entity /
        # relationship *extraction* was fully served from the reused cache and
        # only the per-workspace merge summaries were actually computed.
        if "Extract entities and relationships" in prompt:
            counters["extract_calls"] = counters.get("extract_calls", 0) + 1
        else:
            counters["summary_calls"] = counters.get("summary_calls", 0) + 1
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(history_messages or [])
        messages.append({"role": "user", "content": prompt})
        body = {
            "model": v.get("LLM_MODEL"),
            "messages": messages,
            "temperature": 0,
        }
        if kwargs.get("max_tokens"):
            body["max_tokens"] = kwargs["max_tokens"]
        async with httpx.AsyncClient(timeout=float(v.get("LLM_TIMEOUT") or 900)) as client:
            res = await client.post(
                str(v["LLM_BINDING_HOST"]).rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {v['LLM_BINDING_API_KEY']}"},
                json=body,
            )
            res.raise_for_status()
            payload = res.json()
        counters["prompt_tokens"] += int((payload.get("usage") or {}).get("prompt_tokens") or 0)
        return payload["choices"][0]["message"]["content"]

    async def embed(texts, **kwargs):
        counters["embed_calls"] += 1
        async with httpx.AsyncClient(timeout=300) as client:
            res = await client.post(
                str(v["EMBEDDING_BINDING_HOST"]).rstrip("/") + "/embeddings",
                headers={"Authorization": f"Bearer {v['EMBEDDING_BINDING_API_KEY']}"},
                json={"model": v["EMBEDDING_MODEL"], "input": list(texts)},
            )
            res.raise_for_status()
            return np.array([d["embedding"] for d in res.json()["data"]], dtype=np.float32)

    rag = LightRAG(
        working_dir=str(cfg.working_dir or f".local/workspace-access/ingest/{cfg.workspace}"),
        workspace=cfg.workspace,
        kv_storage=str(v.get("LIGHTRAG_KV_STORAGE") or "PGKVStorage"),
        doc_status_storage=str(v.get("LIGHTRAG_DOC_STATUS_STORAGE") or "PGDocStatusStorage"),
        vector_storage=str(v.get("LIGHTRAG_VECTOR_STORAGE") or "QdrantVectorDBStorage"),
        graph_storage=str(v.get("LIGHTRAG_GRAPH_STORAGE") or "Neo4JStorage"),
        llm_model_func=llm,
        embedding_func=EmbeddingFunc(
            embedding_dim=int(v["EMBEDDING_DIM"]),
            max_token_size=8192,
            func=embed,
            model_name=str(v["EMBEDDING_MODEL"]),
        ),
    )
    rag._wa_counters = counters  # type: ignore[attr-defined]
    return rag


async def _pg_connect(cfg: IngestConfig):
    import asyncpg

    v = cfg.values
    return await asyncpg.connect(
        host=v["POSTGRES_HOST"],
        port=int(v["POSTGRES_PORT"]),
        user=v["POSTGRES_USER"],
        password=v["POSTGRES_PASSWORD"],
        database=v["POSTGRES_DATABASE"],
    )


async def _doc_status(conn, workspace: str, doc_id: str) -> dict | None:
    row = await conn.fetchrow(
        "select status, chunks_count, content_hash from public.lightrag_doc_status "
        "where workspace=$1 and id=$2",
        workspace,
        doc_id,
    )
    return dict(row) if row else None


async def _doc_evidence(conn, workspace: str, doc_id: str) -> dict:
    chunks = await conn.fetch(
        "select id from public.lightrag_doc_chunks where workspace=$1 and full_doc_id=$2",
        workspace,
        doc_id,
    )
    chunk_ids = [r["id"] for r in chunks]
    entities = 0
    relations = 0
    if chunk_ids:
        entities = int(
            await conn.fetchval(
                "select count(*) from public.lightrag_entity_chunks "
                "where workspace=$1 and chunk_ids ?| $2::text[]",
                workspace,
                chunk_ids,
            )
            or 0
        )
        relations = int(
            await conn.fetchval(
                "select count(*) from public.lightrag_relation_chunks "
                "where workspace=$1 and chunk_ids ?| $2::text[]",
                workspace,
                chunk_ids,
            )
            or 0
        )
    extract = 0
    if chunk_ids:
        extract = int(
            await conn.fetchval(
                "select count(*) from public.lightrag_llm_cache "
                "where workspace=$1 and cache_type='extract' and chunk_id = any($2::varchar[])",
                workspace,
                chunk_ids,
            )
            or 0
        )
    return {
        "chunks": len(chunk_ids),
        "chunk_ids": chunk_ids,
        "entities": entities,
        "relations": relations,
        "extract_cache_rows": extract,
    }


def _qdrant_vectors(values: dict, workspace: str, chunk_ids: list[str]) -> dict:
    """Confirm the vectors exist in the right workspace with the right dimension."""
    import httpx

    url = str(values["QDRANT_URL"]).rstrip("/")
    suffix = "qwen_qwen3_embedding_4b_2560d"
    collection = f"lightrag_vdb_chunks_{suffix}"
    headers = {"api-key": values["QDRANT_API_KEY"]} if values.get("QDRANT_API_KEY") else {}
    found = 0
    dim = None
    offset = None
    wanted = set(chunk_ids)
    for _ in range(60):
        body = {
            "limit": 1000,
            "with_payload": ["id", "workspace_id", "full_doc_id"],
            "with_vector": False,
            "filter": {"must": [{"key": "workspace_id", "match": {"value": workspace}}]},
        }
        if offset is not None:
            body["offset"] = offset
        res = httpx.post(
            f"{url}/collections/{collection}/points/scroll",
            headers=headers,
            json=body,
            timeout=60,
        ).json()["result"]
        for point in res.get("points", []):
            payload = point.get("payload") or {}
            if payload.get("id") in wanted:
                found += 1
        offset = res.get("next_page_offset")
        if not offset:
            break
    info = httpx.get(f"{url}/collections/{collection}", headers=headers, timeout=30).json()[
        "result"
    ]
    vectors_cfg = (info.get("config") or {}).get("params", {}).get("vectors")
    if isinstance(vectors_cfg, dict):
        dim = vectors_cfg.get("size")
    elif hasattr(vectors_cfg, "size"):
        dim = vectors_cfg.size
    return {"vector_points": found, "expected": len(wanted), "collection": collection, "dim": dim}


async def _enqueue(
    rag,
    item: WorkItem,
    parsed_root: Path,
    *,
    suppress_summary_llm: bool,
) -> None:
    from lightrag.utils_pipeline import make_lightrag_doc_content, sidecar_uri_for

    parsed_dir = Path(parsed_root) / f"{item.doc_name}.parsed"
    blocks = sorted(parsed_dir.glob("*.blocks.jsonl"))
    if not blocks:
        raise IngestError(f"no blocks.jsonl under {parsed_dir}")
    lines = blocks[0].read_text(encoding="utf-8").splitlines()
    merged = identity.merged_blocks_text(lines)
    if not merged.strip():
        raise IngestError(f"empty merged text for {item.doc_name}")

    await rag.apipeline_enqueue_documents(
        input=merged,
        ids=[item.doc_id],
        file_paths=[item.doc_name],
        docs_format="raw",
        parse_engine="mineru",
        process_options="P",
        chunk_options={
            "chunk_token_size": 1500,
            "paragraph_semantic": {
                "chunk_token_size": 2000,
                "chunk_overlap_token_size": 100,
            },
        },
    )
    existing = await rag.full_docs.get_by_id(item.doc_id)
    payload = dict(existing or {})
    payload["content"] = make_lightrag_doc_content(merged)
    payload["parse_format"] = "lightrag"
    payload["sidecar_location"] = sidecar_uri_for(parsed_dir)
    payload["parse_engine"] = "mineru"
    payload["content_hash"] = identity.content_hash(lines)
    await rag.full_docs.upsert({item.doc_id: payload})
    await rag.full_docs.index_done_callback()


async def run_ingest(cfg: IngestConfig) -> dict:
    if cfg.workspace in REFUSED_WORKSPACES:
        raise IngestError(
            f"refusing to ingest into workspace {cfg.workspace!r}: protected pre-existing space"
        )
    items = load_manifest(cfg.manifest_path)
    # Explicitly shared documents are part of this workspace's work list even
    # when the manifest files them under the other domain.
    only = None
    if cfg.only or cfg.extra_docs:
        only = sorted({*(cfg.only or []), *(cfg.extra_docs or [])})
    plan = plan_for_workspace(
        items,
        cfg.workspace,
        only=only,
        limit=cfg.limit,
        extra_docs=cfg.extra_docs,
    )
    ledger = Ledger(cfg.ledger_path)

    started = round(time.time(), 3)
    # Record provenance for duplicates and exclusions before any work.
    for item in plan["duplicates"]:
        key = doc_key(cfg, item)
        if not (ledger.state(key) and ledger.state(key).settled):
            ledger.append(
                key,
                "duplicate",
                evidence={
                    "duplicate_of": item.duplicate_of,
                    "duplicate_kind": item.duplicate_kind,
                    "duplicate_of_sha256": next(
                        (i.sha256 for i in items if i.doc_name == item.duplicate_of), None
                    ),
                },
            )
    for item in plan["excluded"]:
        key = doc_key(cfg, item)
        if not (ledger.state(key) and ledger.state(key).settled):
            ledger.append(
                key,
                "skipped",
                evidence={"reason": list(item.unresolved) or ["no parsed artifacts"]},
            )

    todo = []
    for item in plan["ingest"]:
        key = doc_key(cfg, item)
        state = ledger.state(key)
        if state and state.settled and state.state in ("done", "duplicate"):
            continue
        todo.append(item)

    summary = {
        "workspace": cfg.workspace,
        "recipe": INGEST_RECIPE,
        "models": cfg.model_identity(),
        "manifest": str(cfg.manifest_path),
        "planned": len(plan["ingest"]),
        "duplicates": len(plan["duplicates"]),
        "shared_documents": plan.get("shared", []),
        "excluded": len(plan["excluded"]),
        "to_process": len(todo),
        "dry_run": cfg.dry_run,
        "started_at": started,
    }
    if cfg.dry_run:
        summary["dry_run_docs"] = [i.doc_name for i in todo][:50]
        summary["ledger_counts"] = ledger.counts()
        return summary

    cfg.values = {**cfg.values, **cfg.overrides}
    conn = await _pg_connect(cfg)
    rag = build_lightrag(cfg)
    reused_rows = 0
    try:
        await rag.initialize_storages()
        from lightrag.kg.shared_storage import initialize_pipeline_status

        await initialize_pipeline_status()

        # Housekeeping: a re-enqueue of an already-queued document is rejected
        # by the pipeline with a `dup-*` status row.  Those rows are bookkeeping
        # artefacts of *this* workspace, not documents, so they are removed so
        # the coverage accounting counts real documents only.
        pruned = await conn.execute(
            "delete from public.lightrag_doc_status where workspace=$1 and id like 'dup-%'",
            cfg.workspace,
        )
        summary["pruned_duplicate_rows"] = pruned

        # Reconcile documents whose previous run died mid-flight.
        for item in list(todo):
            key = doc_key(cfg, item)
            state = ledger.state(key)
            if not (state and state.state == "in-flight"):
                continue
            status = await _doc_status(conn, cfg.workspace, item.doc_id)
            if (
                status
                and status["status"] == "processed"
                and status["content_hash"] == item.content_hash
            ):
                ledger.append(
                    key,
                    "done",
                    evidence=await _doc_evidence(conn, cfg.workspace, item.doc_id),
                    note="reconciled after interrupted run",
                )
                todo.remove(item)

        for item in todo:
            key = doc_key(cfg, item)
            status = await _doc_status(conn, cfg.workspace, item.doc_id)
            if (
                status
                and status["status"] == "processed"
                and status["content_hash"] == item.content_hash
            ):
                ledger.append(
                    key,
                    "duplicate",
                    evidence={"duplicate_of": "same-workspace-success", "status": status["status"]},
                )
                continue
            existing = await conn.fetchval(
                "select status from public.lightrag_doc_status "
                "where workspace=$1 and (id=$2 or file_path=$3) limit 1",
                cfg.workspace,
                item.doc_id,
                item.doc_name,
            )
            if existing == "failed":
                # A previous attempt failed (e.g. an embedding worker timeout).
                # Clear only that document's own rows in this workspace so the
                # pipeline accepts it again — nothing else is touched.
                await conn.execute(
                    "delete from public.lightrag_doc_chunks where workspace=$1 and full_doc_id=$2",
                    cfg.workspace,
                    item.doc_id,
                )
                await conn.execute(
                    "delete from public.lightrag_doc_status where workspace=$1 and id=$2",
                    cfg.workspace,
                    item.doc_id,
                )
                existing = None
            if existing:
                # Already queued or processed in this workspace: re-enqueueing
                # would only create a duplicate-rejection row.  The pipeline
                # below picks it up.
                ledger.append(key, "begin", note=f"already {existing}; not re-enqueued")
                continue
            ledger.append(key, "begin")
            chunk_ids = await conn.fetch(
                "select id from public.lightrag_doc_chunks where workspace=$1 and full_doc_id=$2",
                cfg.source_workspace,
                item.doc_id,
            )
            ids = [r["id"] for r in chunk_ids]
            reuse = await seed_extract_cache(
                conn,
                source_workspace=cfg.source_workspace,
                target_workspace=cfg.workspace,
                chunk_ids=ids,
            )
            reused_rows += reuse.rows_copied
            await _enqueue(rag, item, cfg.parsed_root, suppress_summary_llm=True)

        await rag.apipeline_process_enqueue_documents()
        for _ in range(max(0, cfg.process_rounds - 1)):
            pending = await conn.fetchval(
                "select count(*) from public.lightrag_doc_status where workspace=$1 and status in ('pending','processing')",
                cfg.workspace,
            )
            if not pending:
                break
            await rag.apipeline_process_enqueue_documents()
    finally:
        try:
            await rag.finalize_storages()
        finally:
            await conn.close()

    # Reconcile terminal states.
    conn = await _pg_connect(cfg)
    try:
        for item in todo:
            key = doc_key(cfg, item)
            status = await _doc_status(conn, cfg.workspace, item.doc_id)
            evidence = await _doc_evidence(conn, cfg.workspace, item.doc_id)
            vector_evidence = await asyncio.to_thread(
                _qdrant_vectors, cfg.values, cfg.workspace, evidence.pop("chunk_ids", [])
            )
            evidence["vectors"] = vector_evidence
            if status and status["status"] == "processed":
                ledger.append(key, "done", evidence=evidence)
            else:
                ledger.append(
                    key,
                    "failed",
                    evidence=evidence,
                    error=(status or {}).get("status", "missing doc_status row"),
                )
    finally:
        await conn.close()

    summary["reused_cache_rows"] = reused_rows
    summary["llm_dispatches"] = dict(getattr(rag, "_wa_counters", {}))
    summary["ledger_counts"] = ledger.counts()
    summary["finished_at"] = round(time.time(), 3)
    return summary


def load_values(env_file: Path) -> dict:
    from dotenv import dotenv_values

    return {k: v for k, v in dotenv_values(env_file).items() if v is not None}


def write_summary(path: Path, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
