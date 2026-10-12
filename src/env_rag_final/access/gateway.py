"""Knowledge API: the single authenticated entry point for knowledge access.

Boundary rules enforced here:

* every read passes through :func:`authorize` **before** any database query,
  model call or file read; a rejected request performs zero backend work and
  leaks no library names, counts or content,
* the client only expresses intent (``workspace`` / ``workspaces`` / ``all``),
  never authority,
* LightRAG instances are reached only with the internal instance credential;
  the instance endpoints are not exposed to clients,
* records are private to their creator and re-authorized on every read, so a
  revoked grant, a policy revision or a different principal cannot reach them.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from env_rag_final.access.auth import (
    AuthContext,
    Forbidden,
    NotAvailable,
    Unauthenticated,
    authenticate,
)
from env_rag_final.access.registry import Principal, Registry, load_registry

SESSION_COOKIE = "wa_session"
CSRF_HEADER = "X-RAG-Token"
INTERNAL_HEADER = "X-Internal-Key"
SESSION_TTL_SECONDS = 12 * 3600

# Retrieval modes exposed to clients, mapped to the LightRAG query modes.
NATIVE_MODES = ("naive", "local", "global", "hybrid", "mix")
MAX_TOP_K = 50


@dataclass
class Session:
    session_id: str
    user_id: str
    csrf: str
    created_at: float
    policy_revision: str


@dataclass
class Record:
    record_id: str
    user_id: str
    enterprise: str
    policy_revision: str
    workspaces: list[str]
    created_at: float
    question: str
    route: str
    status: str
    payload: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


class RecordStore:
    """Durable, owner-scoped record store under a git-ignored directory."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._memory: dict[str, Record] = {}

    def _path(self, record_id: str) -> Path:
        return self.root / f"{record_id}.json"

    def save(self, record: Record) -> None:
        self._memory[record.record_id] = record
        tmp = self._path(record.record_id).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record.as_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self._path(record.record_id))

    def get(self, record_id: str) -> Record | None:
        record = self._memory.get(record_id)
        if record is not None:
            return record
        path = self._path(record_id)
        if not path.exists():
            return None
        record = Record(**json.loads(path.read_text(encoding="utf-8")))
        self._memory[record_id] = record
        return record

    def owned(self, ctx: AuthContext) -> list[Record]:
        out: list[Record] = []
        for path in sorted(self.root.glob("*.json"), reverse=True):
            try:
                record = self.get(path.stem)
            except Exception:
                continue
            if record is None:
                continue
            if (
                record.user_id == ctx.user_id
                and record.enterprise == ctx.enterprise
                and record.policy_revision == ctx.policy_revision
                and set(record.workspaces) <= set(ctx.workspaces)
            ):
                out.append(record)
        return out


def record_id_for(*parts: object) -> str:
    payload = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return "wa-" + hashlib.sha256(payload.encode()).hexdigest()[:20]


class KnowledgeService:
    """Authorization-aware retrieval, generation and record access."""

    def __init__(
        self,
        *,
        registry: Registry,
        values: dict,
        record_root: Path,
        parsed_root: Path,
        pdf_root: Path | None = None,
        instance_keys: dict | None = None,
        client_factory=None,
        connect_factory=None,
    ):
        self.registry = registry
        self.values = values
        self.records = RecordStore(record_root)
        self.parsed_root = Path(parsed_root)
        self.pdf_root = Path(pdf_root) if pdf_root else None
        self.instance_keys = instance_keys or {}
        self.sessions: dict[str, Session] = {}
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=180))
        self._connect_factory = connect_factory
        self._cache: dict[tuple, dict] = {}
        self.backend_calls: list[str] = []

    # ---- backend plumbing --------------------------------------------
    async def _connect(self):
        if self._connect_factory is not None:
            return await self._connect_factory()
        import asyncpg

        v = self.values
        return await asyncpg.connect(
            host=v["POSTGRES_HOST"],
            port=int(v["POSTGRES_PORT"]),
            user=v["POSTGRES_USER"],
            password=v["POSTGRES_PASSWORD"],
            database=v["POSTGRES_DATABASE"],
        )

    def maybe_reload_registry(self) -> None:
        """Reload the registry when its file changes (policy revision bump).

        Sessions, cached answers and record authorization all key off the
        revision, so a reload is what makes a revocation take effect at once
        rather than only after a restart.
        """
        path = self.registry.source_path
        if not path:
            return
        try:
            mtime = os.stat(path).st_mtime_ns
        except OSError:
            return
        if mtime == getattr(self, "_registry_mtime", None):
            return
        try:
            reloaded = load_registry(path)
        except Exception:
            # A malformed registry must never silently widen access.
            self._registry_mtime = mtime
            return
        self.registry = reloaded
        self._registry_mtime = mtime
        # Sessions and derived state bound to the old revision are dropped.
        for session_id, session in list(self.sessions.items()):
            if session.policy_revision != reloaded.revision:
                self.sessions.pop(session_id, None)
        self._cache.clear()

    def _note(self, what: str) -> None:
        """Record a backend touch so refusal tests can prove 'zero calls'."""
        self.backend_calls.append(what)

    def _instance_headers(self, ws_id: str) -> dict:
        ws = self.registry.workspace(ws_id)
        if ws is None:
            raise NotAvailable("unknown library")
        ref = ws.instance_key_ref or ws_id
        key = self.instance_keys.get(ref)
        if not key:
            raise NotAvailable("library instance credential is not configured")
        return {"X-API-Key": key, "Content-Type": "application/json"}

    # ---- sessions -----------------------------------------------------
    def login(self, user_id: str, password: str) -> Session:
        principal = self.registry.principal_by_login(user_id, password)
        if principal is None:
            raise Unauthenticated("invalid credentials")
        session = Session(
            session_id=secrets.token_urlsafe(32),
            user_id=principal.user_id,
            csrf=secrets.token_urlsafe(32),
            created_at=time.time(),
            policy_revision=self.registry.revision,
        )
        self.sessions[session.session_id] = session
        return session

    def logout(self, session_id: str | None) -> None:
        if session_id:
            self.sessions.pop(session_id, None)

    def session_for(self, session_id: str | None) -> Session | None:
        if not session_id:
            return None
        session = self.sessions.get(session_id)
        if session is None:
            return None
        if time.time() - session.created_at > SESSION_TTL_SECONDS:
            self.sessions.pop(session.session_id, None)
            return None
        # A policy revision change invalidates every old session identity.
        if session.policy_revision != self.registry.revision:
            self.sessions.pop(session.session_id, None)
            return None
        return session

    def principal_for_request(self, *, session_id: str | None, bearer: str | None) -> Principal:
        session = self.session_for(session_id)
        if session is not None:
            return authenticate(self.registry, session_user=session.user_id)
        # A client-supplied role/enterprise header is deliberately NOT consulted.
        return authenticate(self.registry, bearer_token=bearer)

    # ---- retrieval ----------------------------------------------------
    async def pg_evidence(
        self, ctx: AuthContext, ws_id: str, question: str, *, top_k: int, expand: bool
    ) -> dict:
        from env_rag_final.search import query as query_mod

        self._note(f"pg:{ws_id}")
        conn = await self._connect()
        try:
            result = await query_mod.run_query(
                conn,
                question,
                top_k=top_k,
                expand=expand,
                workspace=ws_id,
                parsed_root=self.parsed_root,
                source_values=self.values,
            )
            payload = result.to_dict()
            candidates = payload.get("candidates", [])
            # The search layer returns citations, not bodies: read the cited
            # chunk rows back from the *authorized* workspace and reject any
            # citation whose workspace or snapshot does not match the active
            # build, so a source is only shown once it has been re-read.
            chunk_ids = [c.get("chunk_id") for c in candidates if c.get("chunk_id")]
            bodies: dict[str, str] = {}
            if chunk_ids:
                rows = await conn.fetch(
                    "select id, content from public.lightrag_doc_chunks "
                    "where workspace=$1 and id = any($2::varchar[])",
                    ws_id,
                    chunk_ids,
                )
                bodies = {r["id"]: r["content"] or "" for r in rows}
        finally:
            await conn.close()
        items = []
        for candidate in candidates:
            citation = candidate.get("citation") or {}
            cited_ws = citation.get("workspace")
            cited_snapshot = citation.get("snapshot_id")
            identity_ok = (cited_ws in (None, ws_id)) and (
                cited_snapshot in (None, payload.get("catalog_snapshot_id"))
            )
            chunk_id = candidate.get("chunk_id")
            body = bodies.get(chunk_id or "")
            items.append(
                {
                    "workspace": ws_id,
                    "chunk_id": chunk_id,
                    "doc_id": candidate.get("doc_id")
                    or citation.get("doc_id")
                    or candidate.get("full_doc_id"),
                    "content": body or "",
                    "heading": candidate.get("heading"),
                    "score": candidate.get("score"),
                    "kind": candidate.get("kind") or candidate.get("source_type") or "pg",
                    "verified": bool(candidate.get("citation_verified"))
                    and identity_ok
                    and bool(body),
                    "citation": citation,
                    "path": candidate.get("path"),
                }
            )
        return {
            "workspace": ws_id,
            "status": payload.get("status"),
            "search_id": payload.get("search_id"),
            "catalog_snapshot_id": payload.get("catalog_snapshot_id"),
            "source_snapshot_id": payload.get("source_snapshot_id"),
            "notes": payload.get("notes", []),
            "items": items,
            "raw": payload,
        }

    async def instance_evidence(
        self, ctx: AuthContext, ws_id: str, question: str, *, mode: str, top_k: int
    ) -> dict:
        ws = self.registry.workspace(ws_id)
        if ws is None or not ws.instance_url:
            raise NotAvailable(f"library {ws_id} has no running instance")
        self._note(f"instance:{ws_id}:{mode}")
        body = {"query": question, "mode": mode, "top_k": top_k}
        async with self._client_factory() as client:
            try:
                res = await client.post(
                    ws.instance_url.rstrip("/") + "/query/data",
                    headers=self._instance_headers(ws_id),
                    json=body,
                )
            except Exception as exc:
                return {
                    "workspace": ws_id,
                    "status": "service_failure",
                    "error": f"{type(exc).__name__}: {exc}",
                    "items": [],
                }
        if res.status_code != 200:
            return {
                "workspace": ws_id,
                "status": "service_failure",
                "error": f"HTTP {res.status_code}",
                "items": [],
            }
        payload = res.json()
        data = payload.get("data") or {}
        items = []
        for chunk in data.get("chunks") or []:
            items.append(
                {
                    "workspace": ws_id,
                    "chunk_id": chunk.get("chunk_id"),
                    "doc_id": chunk.get("full_doc_id") or chunk.get("doc_id"),
                    "content": chunk.get("content") or "",
                    "kind": "lightrag_chunk",
                    "verified": True,
                    "mode": mode,
                }
            )
        return {
            "workspace": ws_id,
            "status": payload.get("status") or "ok",
            "mode": mode,
            "items": items,
            "entities": data.get("entities") or [],
            "relationships": data.get("relationships") or [],
            "references": data.get("references") or [],
        }

    @staticmethod
    def merge_evidence(per_workspace: list[dict]) -> list[dict]:
        """Merge evidence keeping ``(workspace, chunk_id)`` identity.

        The same chunk id in two libraries never overwrites: both entries
        survive, each carrying its own workspace and origin path.
        """
        merged: dict[tuple, dict] = {}
        for block in per_workspace:
            for item in block.get("items", []):
                key = (item.get("workspace"), item.get("chunk_id"))
                entry = merged.setdefault(
                    key,
                    {
                        "workspace": item.get("workspace"),
                        "chunk_id": item.get("chunk_id"),
                        "doc_id": item.get("doc_id"),
                        "content": item.get("content") or "",
                        "paths": [],
                    },
                )
                entry["paths"].append(
                    {
                        "kind": item.get("kind"),
                        "mode": item.get("mode"),
                        "score": item.get("score"),
                        "verified": item.get("verified"),
                    }
                )
                if item.get("path") and item["path"] not in entry["paths"]:
                    entry["path"] = item["path"]
        return list(merged.values())

    async def retrieve(
        self,
        ctx: AuthContext,
        question: str,
        *,
        route: str = "pg",
        mode: str | None = None,
        top_k: int = 20,
        expand: bool = True,
    ) -> dict:
        if route not in ("pg", "lightrag", "pg+lightrag"):
            raise Forbidden(f"unknown route {route!r}", code="bad_route")
        if mode is not None and mode not in NATIVE_MODES:
            raise Forbidden(f"unknown mode {mode!r}", code="bad_mode")
        if route in ("lightrag", "pg+lightrag") and mode is None:
            raise Forbidden("lightrag routes require an explicit mode", code="mode_required")

        blocks: list[dict] = []
        for ws_id in ctx.workspaces:
            if route in ("pg", "pg+lightrag"):
                blocks.append(
                    await self.pg_evidence(ctx, ws_id, question, top_k=top_k, expand=expand)
                )
            if route in ("lightrag", "pg+lightrag"):
                blocks.append(
                    await self.instance_evidence(ctx, ws_id, question, mode=mode, top_k=top_k)
                )

        # A stale store and a broken service are different failures and are
        # reported differently: stale is an explicit readiness state, never
        # hidden and never downgraded to "complete".
        failures = [
            {"workspace": b["workspace"], "reason": b.get("error") or b.get("status")}
            for b in blocks
            if b.get("status") in ("service_failure", "error")
        ]
        stale = [
            {"workspace": b["workspace"], "reason": "stale"}
            for b in blocks
            if b.get("status") == "stale"
        ]
        statuses = [b.get("status") for b in blocks]
        if failures and len(failures) == len(blocks):
            status = "service_failure"
        elif failures:
            status = "partial"
        elif stale:
            status = "stale" if len(stale) == len(blocks) else "partial"
        elif any(s in ("ambiguous", "partial", "missing") for s in statuses):
            status = (
                "partial"
                if "partial" in statuses
                else next(s for s in statuses if s in ("ambiguous", "partial", "missing"))
            )
        else:
            status = "complete"
        evidence = self.merge_evidence(blocks)
        included = "".join(
            f"{item['workspace']}::{item['chunk_id']}::{item['content']}"
            for item in sorted(evidence, key=lambda i: (i["workspace"] or "", i["chunk_id"] or ""))
        )
        return {
            "question": question,
            "route": route,
            "mode": mode,
            "workspaces": list(ctx.workspaces),
            "status": status,
            "failures": failures,
            "stale": stale,
            "evidence": evidence,
            "per_workspace": blocks,
            "evidence_sha256": hashlib.sha256(included.encode()).hexdigest(),
        }

    # ---- generation ---------------------------------------------------
    async def generate(self, ctx: AuthContext, retrieval: dict) -> dict:
        """One model call, grounded strictly in the retrieved evidence."""
        evidence = retrieval.get("evidence") or []
        if not evidence:
            return {
                "status": "no_evidence",
                "answer": "",
                "citations": [],
                "model": None,
                "dispatches": 0,
            }
        context_parts = []
        for idx, item in enumerate(evidence):
            context_parts.append(
                f"[{idx}] library={item['workspace']} chunk={item['chunk_id']}\n{item['content'][:4000]}"
            )
        prompt = (
            "你是环境知识库助手。只能使用下面给出的资料回答，并以 [编号] 标注依据。"
            "若资料不足以回答，明确说明资料不足，不要补充外部知识。\n\n"
            + "\n\n".join(context_parts)
            + f"\n\n问题：{retrieval['question']}"
        )
        self._note("llm:answer")
        async with self._client_factory() as client:
            res = await client.post(
                str(self.values["LLM_BINDING_HOST"]).rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {self.values['LLM_BINDING_API_KEY']}"},
                json={
                    "model": self.values.get("QUERY_LLM_MODEL") or self.values.get("LLM_MODEL"),
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                },
            )
            res.raise_for_status()
            payload = res.json()
        answer = payload["choices"][0]["message"]["content"]
        # Verify each citation actually points at an evidence entry.
        citations = []
        for idx, item in enumerate(evidence):
            token = f"[{idx}]"
            if token in answer:
                citations.append(
                    {
                        "index": idx,
                        "workspace": item["workspace"],
                        "chunk_id": item["chunk_id"],
                        "doc_id": item.get("doc_id"),
                        "citation_verified": bool(item.get("content")),
                    }
                )
        return {
            "status": "complete" if citations else "unverified",
            "answer": answer,
            "citations": citations,
            "model": payload.get("model"),
            "usage": payload.get("usage"),
            "dispatches": 1,
            "evidence_count": len(evidence),
        }

    # ---- object access ------------------------------------------------
    def _record_for(self, ctx: AuthContext, record_id: str) -> Record:
        record = self.records.get(record_id)
        if record is None:
            raise NotAvailable("unknown object")
        if record.user_id != ctx.user_id or record.enterprise != ctx.enterprise:
            # Another principal's private record:统一不可访问，不泄漏存在性.
            raise NotAvailable("unknown object")
        if record.policy_revision != ctx.policy_revision:
            raise NotAvailable("unknown object")
        if not set(record.workspaces) <= set(ctx.workspaces):
            raise NotAvailable("unknown object")
        return record

    def record_chunk(self, ctx: AuthContext, record_id: str, index: int) -> dict:
        record = self._record_for(ctx, record_id)
        evidence = record.payload.get("retrieval", {}).get("evidence", [])
        if index < 0 or index >= len(evidence):
            raise NotAvailable("unknown object")
        item = evidence[index]
        # Re-check the *current* grant for the object's own workspace.
        if not ctx.allows(item["workspace"]):
            raise NotAvailable("unknown object")
        return item
