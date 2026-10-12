"""Original checkout query bodies with read-only bindings, no LightRAG init.

Semantics: kg_query/naive_query(mode=...) + only_need_prompt; the returned
prompt/raw_data are retained and one later HTTP generation uses THAT prompt.
No /query/data + second /query retrieval. Native prompt, mode routing, context
selection are untouched; cache=None and rerank=False are explicit deviations
from a potentially cached/reranked server default, shared by comparisons.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import time
from dataclasses import asdict
from pathlib import Path

import asyncpg
import httpx
import numpy as np
from lightrag import QueryParam, operate
from lightrag.kg import shared_storage
from lightrag.prompt import load_user_prompt_prefix_source
from lightrag.utils import EmbeddingFunc

from env_rag_final import local_adapter as la

from .budget import BudgetExhausted, Ledger, check_embedding_batch

MODES = ("naive", "local", "global", "hybrid", "mix")
ROOT = Path(__file__).resolve().parents[3]
NATIVE_ROOT = ROOT.parent / "LightRAG"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def safe_error(exc, values):
    # Messages can contain bearer tokens, DSNs and corpus values. Expose the
    # exception class, not arbitrary provider content. Raw HTTP evidence below
    # contains only status/usage/model and actual model text on success.
    return {"error_type": type(exc).__name__}


class NativeTextChunks(la.ReadOnlyPGTextChunks):
    """Also retain actual heading/sidecar fields used by the original query."""

    async def _fetch(self, ids):
        v = self._values
        conn = await asyncpg.connect(
            host=v["POSTGRES_HOST"],
            port=int(v["POSTGRES_PORT"]),
            user=v["POSTGRES_USER"],
            password=v["POSTGRES_PASSWORD"],
            database=v["POSTGRES_DATABASE"],
            timeout=15,
            server_settings={"default_transaction_read_only": "on", "statement_timeout": "30000"},
        )
        try:
            rows = await self.boundary.call(
                "pg",
                "readonly_select_chunks",
                conn.fetch,
                """SELECT c.id,c.workspace,c.full_doc_id,c.content,c.tokens,c.chunk_order_index,
                          c.file_path,c.heading,c.sidecar,d.doc_name
                   FROM public.lightrag_doc_chunks c
                   JOIN public.lightrag_doc_full d ON d.workspace=c.workspace AND d.id=c.full_doc_id
                   WHERE c.workspace=$1 AND c.id=ANY($2)""",
                self.workspace,
                list(ids),
            )
            by_id = {r["id"]: dict(r) for r in rows}
            for row in by_id.values():
                for key in ("heading", "sidecar"):
                    if isinstance(row.get(key), str):
                        row[key] = json.loads(row[key])
            return [by_id.get(i) for i in ids]
        finally:
            await conn.close()


class NativeBackend:
    def __init__(self, values: dict, ledger: Ledger):
        self.values = values
        self.ledger = ledger

    async def completion(self, messages, request_id, *, keyword=False, extra=False):
        keys = ["keyword"] if keyword else ["answer"] + (["extra_answer"] if extra else [])
        model = (
            self.values.get("KEYWORD_LLM_MODEL") or self.values["LLM_MODEL"]
            if keyword
            else self.values.get("QUERY_LLM_MODEL") or self.values["LLM_MODEL"]
        )
        url = self.values["LLM_BINDING_HOST"].rstrip("/") + "/chat/completions"
        payload = {"model": model, "messages": messages, "temperature": 0, "stream": False}
        if keyword:
            payload["response_format"] = {"type": "json_object"}
        self.ledger.reserve(keys, request_id, "chat.completions")
        start = time.monotonic()
        receipt = {
            "model": model,
            "operation": "keyword" if keyword else "answer",
            "request_messages_sha256": sha(json.dumps(messages, ensure_ascii=False)),
        }
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                self.ledger.issued(keys, request_id, "chat.completions")
                r = await client.post(
                    url,
                    json=payload,
                    headers={"Authorization": "Bearer " + self.values["LLM_BINDING_API_KEY"]},
                )
                receipt["http_status"] = r.status_code
                r.raise_for_status()
                data = r.json()
                text = data["choices"][0]["message"]["content"]
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("empty model response")
                receipt.update(status="success", usage=data.get("usage"), response_sha256=sha(text))
                return text, receipt
        except Exception as exc:
            receipt.update(status="failure", **safe_error(exc, self.values))
            setattr(exc, "web_receipt", receipt)
            raise
        finally:
            receipt["elapsed_ms"] = round((time.monotonic() - start) * 1000)

    async def retrieve(self, query, mode, request_id, *, top_k=20):
        if mode not in MODES:
            raise ValueError("unknown native retrieval mode")
        # Tests may call contract helpers using the installed release. Live use
        # is refused unless the launcher selected the actual original checkout.
        path = Path(inspect.getfile(operate)).resolve()
        if path != (NATIVE_ROOT / "lightrag/operate.py").resolve():
            raise RuntimeError("请用 python -m env_rag_final.web 启动原 checkout 接入")
        mapping = la.verify_config_guard(self.values, "default")
        self.ledger.reserve(["retrieval"], request_id, mode)
        boundary = la.ServiceBoundary()
        keyword_receipts = []
        budget_refusals = []

        async def embed(texts, **kwargs):
            try:
                check_embedding_batch(texts)
                self.ledger.reserve(["embedding"], request_id, "embeddings")
            except BudgetExhausted:
                budget_refusals.append("embedding")
                raise

            async def io():
                async with httpx.AsyncClient(timeout=60) as client:
                    self.ledger.issued(["embedding"], request_id, "embeddings")
                    r = await client.post(
                        self.values["EMBEDDING_BINDING_HOST"].rstrip("/") + "/embeddings",
                        headers={
                            "Authorization": "Bearer " + self.values["EMBEDDING_BINDING_API_KEY"]
                        },
                        json={"model": self.values["EMBEDDING_MODEL"], "input": texts},
                    )
                    r.raise_for_status()
                    rows = sorted(r.json()["data"], key=lambda x: x["index"])
                    if [x["index"] for x in rows] != list(range(len(texts))):
                        raise ValueError("embedding identity mismatch")
                    vectors = np.asarray([x["embedding"] for x in rows], dtype=float)
                    if vectors.shape != (len(texts), 2560) or not np.isfinite(vectors).all():
                        raise ValueError("embedding dimension/value mismatch")
                    return vectors

            return await boundary.call("embedding", "embeddings", io)

        async def keyword(prompt, **kwargs):
            messages = [{"role": "user", "content": prompt}]
            if kwargs.get("system_prompt"):
                messages.insert(0, {"role": "system", "content": kwargs["system_prompt"]})
            try:
                text, receipt = await self.completion(messages, request_id, keyword=True)
                keyword_receipts.append(receipt)
                return text
            except Exception as exc:
                keyword_receipts.append(getattr(exc, "web_receipt", safe_error(exc, self.values)))
                raise

        embedding = EmbeddingFunc(
            embedding_dim=2560, max_token_size=8192, func=embed, model_name=la.EMBEDDING_MODEL
        )
        cfg = la._pipeline_global_config(keyword, embedding)
        cfg.update(
            enable_llm_cache=False,
            enable_content_headings=self.values.get("ENABLE_CONTENT_HEADINGS", "true").lower()
            == "true",
            kg_chunk_pick_method=self.values.get("KG_CHUNK_PICK_METHOD") or "VECTOR",
            related_chunk_number=int(self.values.get("RELATED_CHUNK_NUMBER") or 5),
            user_prompt_prefix=load_user_prompt_prefix_source(),
        )
        resources = []
        shared_storage.initialize_share_data(workers=1)
        start = time.monotonic()
        output = None
        try:
            storages = {}
            for namespace in (
                ["chunks"] if mode == "naive" else ["entities", "relationships", "chunks"]
            ):
                storage = la.bind_qdrant_readonly(
                    namespace, mapping["vector"], embedding, self.values, boundary
                )
                resources.append(storage)
                storages[namespace] = storage
            graph = None
            if mode != "naive":
                graph = la.bind_neo4j_readonly(mapping["graph"], embedding, self.values, boundary)
                resources.append(graph)
            chunks = NativeTextChunks(self.values, "default", boundary)
            chunks.global_config = cfg
            chunks.embedding_func = embedding
            param = QueryParam(
                mode=mode,
                top_k=top_k,
                chunk_top_k=top_k,
                only_need_prompt=True,
                stream=False,
                enable_rerank=False,
                max_total_tokens=32000,
                max_entity_tokens=int(self.values.get("MAX_ENTITY_TOKENS") or 6000),
                max_relation_tokens=int(self.values.get("MAX_RELATION_TOKENS") or 8000),
            )
            self.ledger.issued(["retrieval"], request_id, mode)
            if mode == "naive":
                result = await operate.naive_query(
                    query, storages["chunks"], param, cfg, hashing_kv=None, text_chunks_db=chunks
                )
            else:
                result = await operate.kg_query(
                    query,
                    graph,
                    storages["entities"],
                    storages["relationships"],
                    chunks,
                    param,
                    cfg,
                    hashing_kv=None,
                    chunks_vdb=storages["chunks"],
                )
            if budget_refusals or any(
                e["status"] == "refused" and e["request_id"] == request_id
                for e in self.ledger.snapshot()["events"]
            ):
                raise BudgetExhausted("底层回退吞掉了预算拒绝；本题仍作为预算失败发布")
            raw = result.raw_data if result and result.raw_data else {"data": {}}
            original_chunks = (raw.get("data") or {}).get("chunks") or []
            ids = [c["chunk_id"] for c in original_chunks]
            physical = await chunks.get_by_ids(ids)
            verified = []
            for c, row in zip(original_chunks, physical, strict=True):
                if not row or row["workspace"] != "default" or row["content"] != c["content"]:
                    raise ValueError("native chunk/source identity mismatch")
                verified.append(
                    {
                        **c,
                        "workspace": "default",
                        "doc_id": row["full_doc_id"],
                        "doc_name": row.get("doc_name"),
                        "heading": row.get("heading"),
                        "content_sha256": sha(row["content"]),
                        "verified": True,
                        "sources": [mode],
                        "stage": "native_context",
                    }
                )
            data = raw.get("data") or {}
            output = {
                "mode": mode,
                "chunks": verified,
                "entities": data.get("entities") or [],
                "relations": data.get("relationships") or [],
                "raw_data": raw,
                "native_prompt": result.content if result else None,
                "elapsed_ms": round((time.monotonic() - start) * 1000),
                "receipts": [asdict(r) for r in boundary.records] + keyword_receipts,
                "provenance": {
                    "operate_path": str(path),
                    "operate_sha256": sha(path.read_text()),
                    "api": "naive_query" if mode == "naive" else "kg_query",
                    "deviations": [
                        "readonly bindings",
                        "cache disabled",
                        "rerank disabled",
                        "same-record deferred generation",
                        "temperature=0",
                    ],
                },
            }
            return output
        except Exception as exc:
            setattr(
                exc, "native_receipts", [asdict(r) for r in boundary.records] + keyword_receipts
            )
            raise
        finally:
            for resource in reversed(resources):
                handle = getattr(resource, "_client", None) or getattr(resource, "_driver", None)
                if handle is not None:
                    try:
                        closed = handle.close()
                        if inspect.isawaitable(closed):
                            await closed
                    except Exception as exc:
                        boundary.record_sync("cleanup", "close-only", "failure", type(exc).__name__)
            if output is not None:
                output["receipts"] = [asdict(r) for r in boundary.records] + keyword_receipts
                output["degraded"] = [r for r in output["receipts"] if r.get("status") == "failure"]
