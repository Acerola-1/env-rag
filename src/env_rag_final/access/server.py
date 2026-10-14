"""HTTP surface of the Knowledge API (aiohttp, loopback only).

Every handler resolves the authenticated principal, authorizes the requested
knowledge libraries and only then touches a backend.  The response to a refused
request never names a library, a count or a document — it is a plain status.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from urllib.parse import quote

from aiohttp import web

from env_rag_final.access.auth import (
    ALL,
    AccessError,
    Forbidden,
    NotAvailable,
    Unauthenticated,
    authorize,
)
from env_rag_final.access.gateway import (
    CSRF_HEADER,
    SESSION_COOKIE,
    KnowledgeService,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _json_error(status: int, code: str, message: str) -> web.Response:
    return web.json_response({"error": code, "message": message}, status=status)


@web.middleware
async def access_middleware(request: web.Request, handler):
    response = None
    try:
        response = await handler(request)
    except Unauthenticated as exc:
        response = _json_error(exc.status, exc.code, "authentication required")
    except Forbidden as exc:
        response = _json_error(
            exc.status, exc.code, "the requested knowledge scope is not permitted"
        )
    except NotAvailable as exc:
        response = _json_error(exc.status, exc.code, "not available")
    except AccessError as exc:  # pragma: no cover - defensive
        response = _json_error(exc.status, exc.code, "access denied")
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'"
    )
    return response


@web.middleware
async def trust_boundary(request: web.Request, handler):
    # A changed registry means a new policy revision: reload it before the
    # request is authorized so revocations take effect immediately.
    service = request.app.get("service")
    if service is not None:
        service.maybe_reload_registry()
    host = request.host.split(":")[0]
    if host not in ("localhost", "127.0.0.1"):
        return _json_error(403, "host_not_allowed", "loopback access only")
    if request.method == "POST":
        origin = request.headers.get("Origin")
        if origin:
            expected = f"{request.scheme}://{request.host}"
            if origin != expected:
                return _json_error(403, "bad_origin", "cross-site request refused")
    return await handler(request)


def _bind(service: KnowledgeService) -> None:
    pass


def create_app(service: KnowledgeService) -> web.Application:
    app = web.Application(middlewares=[access_middleware, trust_boundary])
    app["service"] = service

    def ctx_for(request: web.Request):
        svc: KnowledgeService = request.app["service"]
        session_id = request.cookies.get(SESSION_COOKIE)
        bearer = None
        header = request.headers.get("Authorization", "")
        if header.lower().startswith("bearer "):
            bearer = header[7:].strip()
        principal = svc.principal_for_request(session_id=session_id, bearer=bearer)
        session = svc.session_for(session_id)
        # CSRF protects state-changing requests; read-only GETs are guarded by
        # the SameSite=Strict session cookie, the loopback host check and CSP.
        if session is not None and request.method == "POST":
            supplied = request.headers.get(CSRF_HEADER, "")
            if not supplied or not secrets.compare_digest(supplied, session.csrf):
                raise Forbidden("missing or invalid CSRF token", code="bad_csrf")
        return principal

    async def index(request: web.Request) -> web.Response:
        return web.FileResponse(STATIC_DIR / "index.html")

    async def static_file(request: web.Request) -> web.Response:
        name = request.match_info["name"]
        if "/" in name or name.startswith("."):
            raise web.HTTPNotFound()
        path = STATIC_DIR / name
        if not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    async def login(request: web.Request) -> web.Response:
        svc: KnowledgeService = request.app["service"]
        body = await request.json()
        session = svc.login(str(body.get("user_id") or ""), str(body.get("password") or ""))
        principal = svc.registry.principal(session.user_id)
        payload = {
            "user_id": session.user_id,
            "display": principal.display if principal else session.user_id,
            "csrf": session.csrf,
            "workspaces": [
                svc.registry.workspace(w).as_dict()
                for w in svc.registry.allowed_workspaces(principal)
            ],
        }
        response = web.json_response(payload)
        response.set_cookie(
            SESSION_COOKIE, session.session_id, httponly=True, samesite="Strict", path="/"
        )
        return response

    async def logout(request: web.Request) -> web.Response:
        svc: KnowledgeService = request.app["service"]
        session_id = request.cookies.get(SESSION_COOKIE)
        if session_id:
            session = svc.session_for(session_id)
            if session is not None:
                supplied = request.headers.get(CSRF_HEADER, "")
                if not supplied or not secrets.compare_digest(supplied, session.csrf):
                    raise Forbidden("missing or invalid CSRF token", code="bad_csrf")
        svc.logout(session_id)
        response = web.json_response({"ok": True})
        response.del_cookie(SESSION_COOKIE, path="/")
        return response

    async def me(request: web.Request) -> web.Response:
        svc: KnowledgeService = request.app["service"]
        principal = ctx_for(request)
        allowed = svc.registry.allowed_workspaces(principal)
        session = svc.session_for(request.cookies.get(SESSION_COOKIE))
        return web.json_response(
            {
                "user_id": principal.user_id,
                "display": principal.display,
                "enterprise": principal.enterprise,
                "roles": list(principal.roles),
                "csrf": session.csrf if session else None,
                "policy_revision": svc.registry.revision,
                "workspaces": [svc.registry.workspace(w).as_dict() for w in allowed],
            }
        )

    async def query(request: web.Request) -> web.Response:
        svc: KnowledgeService = request.app["service"]
        principal = ctx_for(request)
        body = await request.json()
        selection = body.get("workspace")
        if selection is None and "workspaces" in body:
            selection = body["workspaces"]
        if selection == ALL:
            selection = ALL
        ctx = authorize(svc.registry, principal, selection)
        top_k = body.get("top_k")
        top_k = 20 if top_k is None else max(1, min(50, int(top_k)))
        retrieval = await svc.retrieve(
            ctx,
            str(body.get("question") or ""),
            route=str(body.get("route") or "pg"),
            mode=body.get("mode"),
            top_k=top_k,
            expand=bool(body.get("expand", True)),
        )
        record_id = (
            __import__("hashlib")
            .sha256(
                json.dumps(
                    [
                        ctx.user_id,
                        ctx.enterprise,
                        ctx.policy_revision,
                        list(ctx.workspaces),
                        retrieval["question"],
                        retrieval["route"],
                        retrieval["mode"],
                        top_k,
                    ],
                    sort_keys=True,
                ).encode()
            )
            .hexdigest()[:20]
        )
        from env_rag_final.access.gateway import Record, record_id_for

        saved_id = None
        if not body.get("no_record"):
            saved_id = record_id_for(
                record_id,
                retrieval["evidence_sha256"],
                retrieval["workspace_snapshots"],
                bool(body.get("expand", True)),
            )
            svc.records.save(
                Record(
                    record_id=saved_id,
                    user_id=ctx.user_id,
                    enterprise=ctx.enterprise,
                    policy_revision=ctx.policy_revision,
                    workspaces=list(ctx.workspaces),
                    created_at=__import__("time").time(),
                    question=retrieval["question"],
                    route=retrieval["route"],
                    status=retrieval["status"],
                    payload={"retrieval": retrieval},
                )
            )
        return web.json_response(
            {
                "user_id": ctx.user_id,
                "record_id": saved_id,
                "workspaces": list(ctx.workspaces),
                "policy_revision": ctx.policy_revision,
                "result": retrieval,
            }
        )

    async def generate(request: web.Request) -> web.Response:
        svc: KnowledgeService = request.app["service"]
        principal = ctx_for(request)
        body = await request.json()
        record_id = str(body.get("record_id") or "")
        # Authorization happens before the record (and therefore the evidence)
        # is touched at all.
        ctx = authorize(svc.registry, principal, body.get("workspace") or ALL)
        record = await svc.current_record(ctx, record_id)
        retrieval = record.payload.get("retrieval") or {}
        generation = await svc.generate(ctx, retrieval)
        record.payload["generation"] = generation
        svc.records.save(record)
        return web.json_response({"record_id": record.record_id, "generation": generation})

    async def records(request: web.Request) -> web.Response:
        svc: KnowledgeService = request.app["service"]
        principal = ctx_for(request)
        ctx = (
            authorize(svc.registry, principal, ALL)
            if svc.registry.allowed_workspaces(principal)
            else None
        )
        if ctx is None:
            return web.json_response({"records": []})
        owned = svc.records.owned(ctx)
        try:
            live = await svc.workspace_snapshots(ctx) if owned else {}
        except NotAvailable:
            live = {}

        def requires_query(record):
            retrieval = record.payload.get("retrieval", {})
            expected = retrieval.get("workspace_snapshots") or {}
            return (
                not expected
                or any(
                    live.get(w, {}).get("state") != "current" or live.get(w) != expected.get(w)
                    for w in record.workspaces
                )
                or any(
                    block.get("mode") and not block.get("instance_identity")
                    for block in retrieval.get("per_workspace", [])
                )
            )

        return web.json_response(
            {
                "records": [
                    {
                        "record_id": r.record_id,
                        "question": r.question,
                        "route": r.route,
                        "status": r.status,
                        "workspaces": r.workspaces,
                        "created_at": r.created_at,
                        "has_generation": "generation" in r.payload,
                        "requires_fresh_query": requires_query(r),
                    }
                    for r in owned
                ]
            }
        )

    async def record_detail(request: web.Request) -> web.Response:
        svc: KnowledgeService = request.app["service"]
        principal = ctx_for(request)
        ctx = authorize(svc.registry, principal, ALL)
        record = await svc.current_record(ctx, request.match_info["rid"])
        return web.json_response(record.as_dict())

    async def export(request: web.Request) -> web.Response:
        svc: KnowledgeService = request.app["service"]
        principal = ctx_for(request)
        ctx = authorize(svc.registry, principal, ALL)
        record = await svc.current_record(ctx, request.match_info["rid"])
        body = json.dumps(record.as_dict(), ensure_ascii=False, indent=1)
        return web.Response(
            body=body.encode(),
            content_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{record.record_id}.json"'},
        )

    async def source(request: web.Request) -> web.Response:
        svc: KnowledgeService = request.app["service"]
        ctx = authorize(svc.registry, ctx_for(request), ALL)
        rid = request.match_info["rid"]
        record = await svc.current_record(ctx, rid)
        try:
            index = int(request.match_info["index"])
        except ValueError:
            raise NotAvailable("not available") from None
        item = svc.record_chunk(ctx, rid, index)
        kind = request.match_info["kind"]
        if kind == "text":
            body = (item.get("content") or "").encode()
        else:
            body = await svc.document_source(ctx, item, kind)
        await svc.validate_retrieval(ctx, record.payload["retrieval"])
        return web.Response(
            body=body,
            content_type="application/pdf" if kind == "pdf" else "text/plain",
            headers={
                "Content-Disposition": "attachment; filename*=UTF-8''"
                + quote(item.get("doc_name") or "source.pdf")
            }
            if kind == "pdf"
            else None,
        )

    async def document(request: web.Request) -> web.Response:
        svc: KnowledgeService = app["service"]
        ctx = authorize(svc.registry, ctx_for(request), ALL)
        record = await svc.current_record(ctx, request.match_info["rid"])
        kind = request.match_info["kind"]
        for item in record.payload["retrieval"].get("evidence", []):
            if item.get("doc_id") == request.match_info["doc_id"]:
                body = await svc.document_source(
                    ctx, item, "document-text" if kind == "text" else kind
                )
                await svc.validate_retrieval(ctx, record.payload["retrieval"])
                return web.Response(
                    body=body, content_type="application/pdf" if kind == "pdf" else "text/plain"
                )
        raise NotAvailable("not available")

    async def health(request: web.Request) -> web.Response:
        # Public liveness reveals no knowledge-library identities.
        return web.json_response({"status": "ok"})

    app.add_routes(
        [
            web.get("/", index),
            web.get("/health", health),
            web.get("/static/{name}", static_file),
            web.post("/api/login", login),
            web.post("/api/logout", logout),
            web.get("/api/me", me),
            web.get("/api/workspaces", me),
            web.post("/api/query", query),
            web.post("/api/generate", generate),
            web.get("/api/records", records),
            web.get("/api/records/{rid}", record_detail),
            web.get("/api/export/{rid}", export),
            web.get("/api/source/{rid}/{index}/{kind}", source),
            web.get("/api/document/{rid}/{doc_id}/{kind}", document),
        ]
    )
    return app
