"""HTTP surface of the Knowledge API (aiohttp, loopback only).

Every handler resolves the authenticated principal, authorizes the requested
knowledge libraries and only then touches a backend.  The response to a refused
request never names a library, a count or a document — it is a plain status.

Two deployment modes share this surface:

* ``local`` — the original registry-backed flow: password login, ``wa_session``
  cookie, CSRF token, registry grants.
* ``remote`` — IAM-backed flow: the subject credential lives only in the
  server-side session store (humans) or in the current Bearer header
  (machines), every protected call re-runs a live introspection, and a failure
  closes the request instead of falling back to local data.
"""

from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from urllib.parse import quote

from aiohttp import web
from asyncpg import PostgresError

from env_rag_final.access.auth import (
    ALL,
    AccessError,
    Forbidden,
    NotAvailable,
    Unauthenticated,
)
from env_rag_final.access.gateway import (
    CSRF_HEADER,
    REMOTE_SESSION_COOKIE,
    SESSION_COOKIE,
    KnowledgeService,
)
from env_rag_final.access.providers import RemoteProvider
from env_rag_final.access.remote import (
    ConflictError,
    RemoteProtocolError,
    RemoteUnavailable,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _json_error(status: int, code: str, message: str) -> web.Response:
    return web.json_response({"error": code, "message": message}, status=status)


@web.middleware
async def access_middleware(request: web.Request, handler):
    from env_rag_final.access.boundary import live_guard

    reset = live_guard.set(None)
    response = None
    try:
        response = await handler(request)
    except Unauthenticated as exc:
        response = _json_error(exc.status, exc.code, "authentication required")
    except ConflictError as exc:
        # A stale context baseline is a conflict, not an outage.
        response = _json_error(exc.status, exc.code, "enterprise context changed; select again")
    except RemoteUnavailable as exc:
        # IAM / dependency failure is a service problem, not a logout.
        response = _json_error(exc.status, exc.code, "knowledge authorization unavailable")
    except Forbidden as exc:
        response = _json_error(
            exc.status, exc.code, "the requested knowledge scope is not permitted"
        )
    except NotAvailable as exc:
        response = _json_error(exc.status, exc.code, "not available")
    except AccessError as exc:  # pragma: no cover - defensive
        response = _json_error(exc.status, exc.code, "access denied")
    except (ConnectionError, OSError, PostgresError):
        response = _json_error(503, "backend_unavailable", "knowledge backend unavailable")
    except (ValueError, TypeError, json.JSONDecodeError):
        response = _json_error(400, "bad_request", "invalid request body")
    finally:
        live_guard.reset(reset)
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
    if service is not None and not service.is_remote:
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


def create_app(service: KnowledgeService) -> web.Application:
    app = web.Application(middlewares=[access_middleware, trust_boundary])
    app["service"] = service

    remote = service.provider if isinstance(service.provider, RemoteProvider) else None
    cookie_name = REMOTE_SESSION_COOKIE if remote else SESSION_COOKIE
    sso_states = {}

    async def close_provider(app):
        if remote is not None:
            await remote.aclose()

    app.on_cleanup.append(close_provider)

    async def _subject_credential(request: web.Request) -> str | None:
        """The in-flight subject credential: Bearer header, else session."""
        header = request.headers.get("Authorization", "")
        if header.lower().startswith("bearer "):
            token = header[7:].strip()
            if token:
                return token
        if remote is not None:
            session_id = request.cookies.get(cookie_name)
            session = remote.session_for(session_id)
            if session is not None:
                return session["subject_token"]
        return None

    async def ctx_for(request: web.Request, selection: object = ALL):
        """Resolve an authorized context; never touches a backend on refusal."""
        if remote is None:
            session_id = request.cookies.get(cookie_name)
            bearer = None
            header = request.headers.get("Authorization", "")
            if header.lower().startswith("bearer "):
                bearer = header[7:].strip()
            primary = service.principal_for_request(session_id=session_id, bearer=bearer)
            session = service.session_for(session_id)
            if session is not None and request.method == "POST":
                supplied = request.headers.get(CSRF_HEADER, "")
                if not supplied or not secrets.compare_digest(supplied, session.csrf):
                    raise Forbidden("missing or invalid CSRF token", code="bad_csrf")
            return service.authorize_for_request(primary, selection)

        credential = await _subject_credential(request)
        if not credential:
            raise Unauthenticated("credentials required")
        session_id = request.cookies.get(cookie_name)
        session = remote.session_for(session_id) if session_id else None
        if session is not None and request.method == "POST":
            supplied = request.headers.get(CSRF_HEADER, "")
            if not supplied or not secrets.compare_digest(supplied, session["csrf"]):
                raise Forbidden("missing or invalid CSRF token", code="bad_csrf")
        from env_rag_final.access.boundary import live_guard

        if session is not None:
            epoch = request.headers.get("X-RAG-Context", "") or (
                request.query.get("ctx", "") if request.method == "GET" else ""
            )
            if not epoch or not secrets.compare_digest(epoch, session["tenant_epoch"]):
                raise ConflictError("context changed")
        ctx = await remote.authorize_token(credential, selection)
        captured_epoch = session["tenant_epoch"] if session else None

        async def live_check():
            if session is not None:
                current = remote.session_for(session_id)
                if (
                    current is not session
                    or current["tenant_epoch"] != captured_epoch
                    or current["subject_token"] != credential
                ):
                    raise ConflictError("context changed")
            await remote.recheck_token(credential, ctx)

        live_guard.set((ctx, live_check))
        request["_credential"] = credential
        request["_session"] = session
        return ctx

    async def revalidate(request: web.Request, ctx) -> None:
        """Live re-check at a data boundary (remote) / registry check (local)."""
        await service.check_context(ctx)

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
        body = await request.json()
        if remote is None:
            session = service.login(str(body.get("user_id") or ""), str(body.get("password") or ""))
            principal = service.registry.principal(session.user_id)
            payload = {
                "user_id": session.user_id,
                "display": principal.display if principal else session.user_id,
                "csrf": session.csrf,
                "workspaces": [
                    service.registry.workspace(w).as_dict()
                    for w in service.registry.allowed_workspaces(principal)
                ],
            }
            response = web.json_response(payload)
            response.set_cookie(
                cookie_name,
                session.session_id,
                httponly=True,
                secure=request.secure,
                samesite="Strict",
                path="/",
            )
            return response

        account = str(body.get("account") or body.get("user_id") or "").strip()
        password = str(body.get("password") or "")
        session = await remote.login_human(account, password)
        response = web.json_response(
            {
                "mode": "remote",
                "user_id": session["principal_id"],
                "display": session["display"],
                "csrf": session["csrf"],
                "tenant": session["tenant"],
                "tenant_code": session["tenant_code"],
                "tenant_epoch": session["tenant_epoch"],
                "context_version": (remote.session_for(session["session_id"]) or {}).get(
                    "context_version"
                ),
                "tenants": session["tenants"],
                "workspaces": session["workspaces"],
            }
        )
        response.set_cookie(
            cookie_name,
            session["session_id"],
            httponly=True,
            secure=request.secure,
            samesite="Strict",
            path="/",
        )
        return response

    async def logout(request: web.Request) -> web.Response:
        session_id = request.cookies.get(cookie_name)
        if remote is None:
            if session_id:
                session = service.session_for(session_id)
                if session is not None:
                    supplied = request.headers.get(CSRF_HEADER, "")
                    if not supplied or not secrets.compare_digest(supplied, session.csrf):
                        raise Forbidden("missing or invalid CSRF token", code="bad_csrf")
            service.logout(session_id)
        else:
            if session_id:
                session = remote.session_for(session_id)
                if session is not None:
                    supplied = request.headers.get(CSRF_HEADER, "")
                    if not supplied or not secrets.compare_digest(supplied, session["csrf"]):
                        raise Forbidden("missing or invalid CSRF token", code="bad_csrf")
                await remote.logout(session_id)
        response = web.json_response({"ok": True})
        response.del_cookie(cookie_name, path="/")
        return response

    async def me(request: web.Request) -> web.Response:
        if remote is not None:
            # ``/api/me`` must be usable *before* an enterprise is chosen: it is
            # how the page learns which enterprises it may offer.  It therefore
            # introspects without resolving a workspace selection, and still
            # reveals nothing a machine could use for access.
            return await remote_me(request)
        ctx = await ctx_for(request, ALL)
        if remote is None:
            principal = service.registry.principal(ctx.principal_id)
            session = service.session_for(request.cookies.get(cookie_name))
            return web.json_response(
                {
                    "user_id": ctx.principal_id,
                    "display": principal.display if principal else ctx.principal_id,
                    "enterprise": ctx.tenant_id,
                    "roles": list(principal.roles) if principal else [],
                    "csrf": session.csrf if session else None,
                    "policy_revision": service.registry.revision,
                    "mode": "local",
                    "workspaces": [
                        service.registry.workspace(w).as_dict()
                        for w in service.registry.allowed_workspaces(principal)
                    ],
                }
            )
        raise web.HTTPInternalServerError()

    async def remote_me(request: web.Request) -> web.Response:
        credential = await _subject_credential(request)
        if not credential:
            raise Unauthenticated("credentials required")
        identity = await remote.introspect(credential)
        session = remote.session_for(request.cookies.get(cookie_name))
        if session is not None and (
            session["tenant"] != identity.tenant_id
            or session["context_version"] != identity.context_version
        ):
            session.update(
                tenant=identity.tenant_id,
                tenant_code=identity.tenant_code,
                context_version=identity.context_version,
                tenant_epoch=secrets.token_urlsafe(16),
                csrf=secrets.token_urlsafe(32),
            )
        tenant_id = identity.tenant_id
        workspaces = (
            [
                remote.registry.workspace(w).as_dict()
                for w in remote.allowed_workspaces(identity)
                if remote.registry.workspace(w) is not None
            ]
            if tenant_id
            else []
        )
        return web.json_response(
            {
                "user_id": identity.principal_id,
                "display": (session or {}).get("display") or identity.principal_id,
                "enterprise": tenant_id,
                "tenant": tenant_id,
                "tenant_code": identity.tenant_code,
                "tenant_epoch": (session or {}).get("tenant_epoch"),
                "context_version": identity.context_version,
                "tenants": (session or {}).get("tenants") or [],
                "roles": [],
                "csrf": (session or {}).get("csrf"),
                "policy_revision": service.registry.revision,
                "mode": "remote",
                "principal_type": identity.principal_type,
                "context_usable": identity.context_usable,
                "permissions": sorted(identity.permissions),
                "workspaces": workspaces,
            }
        )

    def _sso_settings():
        """SSO façade settings from the process environment (server-side only)."""
        import os

        client_id = (
            remote.config.sso_client_id or os.environ.get("ENV_RAG_SSO_CLIENT_ID", "").strip()
        )
        public_base = os.environ.get("ENV_RAG_PUBLIC_BASE", "").strip().rstrip("/")
        callback = remote.config.sso_callback or os.environ.get("ENV_RAG_SSO_CALLBACK", "").strip()
        if not callback and public_base:
            callback = public_base + "/api/sso/callback"
        return client_id, callback

    async def tenants(request: web.Request) -> web.Response:
        if remote is None:
            raise web.HTTPNotFound()
        credential = await _subject_credential(request)
        if not credential:
            raise Unauthenticated("credentials required")
        identity = await remote.introspect(credential)
        session = remote.session_for(request.cookies.get(cookie_name))
        return web.json_response(
            {
                "current": identity.tenant_id,
                "current_code": identity.tenant_code,
                "principal_type": identity.principal_type,
                "tenants": session["tenants"] if session else [],
                "workspaces": [
                    w.id
                    for w in (
                        service.registry.workspace(x) for x in remote.allowed_workspaces(identity)
                    )
                    if w
                ],
            }
        )

    async def sso_start(request: web.Request) -> web.Response:
        """Begin SSO: bind a one-shot state to this browser and redirect."""
        if remote is None:
            raise web.HTTPNotFound()
        client_id, callback = _sso_settings()
        if not client_id or not callback:
            raise RemoteProtocolError("SSO is not configured for this deployment")
        now = time.monotonic()
        for old, value in list(sso_states.items()):
            if value[0] <= now:
                sso_states.pop(old, None)
        state = secrets.token_urlsafe(24)
        sso_states[state] = (now + 120, callback)
        url = remote.sso_authorize_url(client_id=client_id, redirect_uri=callback, state=state)
        response = web.HTTPFound(url)
        response.set_cookie(
            "rag_remote_sso_state",
            state,
            httponly=True,
            secure=request.secure,
            samesite="Strict",
            path="/api/sso/callback",
        )
        return response

    async def sso_callback(request: web.Request) -> web.Response:
        """Finish SSO: one-shot state check, server-side exchange, cookie."""
        if remote is None:
            raise web.HTTPNotFound()
        supplied_state = request.query.get("state", "")
        expected_state = request.cookies.get("rag_remote_sso_state", "")
        ticket = request.query.get("ticket", "")
        if (
            not supplied_state
            or not expected_state
            or not secrets.compare_digest(supplied_state, expected_state)
        ):
            raise Forbidden("invalid or replayed SSO state", code="bad_sso_state")
        if not ticket:
            raise Forbidden("missing SSO ticket", code="bad_sso_ticket")
        client_id, callback = _sso_settings()
        pending = sso_states.pop(supplied_state, None)
        if pending is None or pending[0] <= time.monotonic() or pending[1] != callback:
            raise Forbidden("invalid or replayed SSO state", code="bad_sso_state")
        session = await remote.sso_login(ticket, callback, supplied_state)
        response = web.HTTPFound("/")
        response.del_cookie("rag_remote_sso_state", path="/api/sso/callback")
        response.set_cookie(
            cookie_name,
            session["session_id"],
            httponly=True,
            secure=request.secure,
            samesite="Strict",
            path="/",
        )
        return response

    async def switch_tenant(request: web.Request) -> web.Response:
        """Remote humans only: switch the IAM enterprise context via CAS."""
        if remote is None:
            raise web.HTTPNotFound()
        body = await request.json()
        session_id = request.cookies.get(cookie_name)
        session = remote.session_for(session_id)
        if session is None:
            raise Unauthenticated("credentials required")
        supplied = request.headers.get(CSRF_HEADER, "")
        if not supplied or not secrets.compare_digest(supplied, session["csrf"]):
            raise Forbidden("missing or invalid CSRF token", code="bad_csrf")
        updated = await remote.switch_tenant(
            session_id,
            str(body.get("tenant_id") or ""),
            body.get("expected_ctx_version"),
        )
        return web.json_response(updated)

    def _record_payload(ctx, retrieval, top_k, expand) -> dict:
        return {
            "record": None,
            "user_id": ctx.principal_id,
            "workspaces": list(ctx.workspaces),
            "policy_revision": ctx.policy_revision,
        }

    async def query(request: web.Request) -> web.Response:
        body = await request.json()
        selection = body.get("workspace")
        if selection is None and "workspaces" in body:
            selection = body["workspaces"]
        if selection == ALL:
            selection = ALL
        ctx = await ctx_for(request, selection)
        top_k = body.get("top_k")
        top_k = 20 if top_k is None else max(1, min(50, int(top_k)))
        retrieval = await service.retrieve(
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
                        ctx.auth_binding(),
                        ctx.mode,
                        ctx.principal_type,
                        ctx.principal_id,
                        ctx.tenant_id,
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
        await revalidate(request, ctx)
        from env_rag_final.access.gateway import Record, record_id_for

        saved_id = None
        if not body.get("no_record"):
            saved_id = record_id_for(
                record_id,
                retrieval["evidence_sha256"],
                retrieval["workspace_snapshots"],
                bool(body.get("expand", True)),
            )
            svc_records = service.records
            svc_records.save(
                Record(
                    record_id=saved_id,
                    user_id=ctx.principal_id,
                    enterprise=ctx.tenant_id,
                    policy_revision=ctx.policy_revision,
                    workspaces=list(ctx.workspaces),
                    created_at=__import__("time").time(),
                    question=retrieval["question"],
                    route=retrieval["route"],
                    status=retrieval["status"],
                    payload={"retrieval": retrieval},
                    principal_type=ctx.principal_type,
                    tenant_id=ctx.tenant_id,
                    directory_version=ctx.directory_version,
                    permissions=sorted(ctx.permissions),
                    mode=ctx.mode,
                    auth_binding=ctx.auth_binding() if ctx.mode == "remote" else {},
                )
            )
        return web.json_response(
            {
                "user_id": ctx.principal_id,
                "record_id": saved_id,
                "workspaces": list(ctx.workspaces),
                "policy_revision": ctx.policy_revision,
                "result": retrieval,
            }
        )

    async def generate(request: web.Request) -> web.Response:
        body = await request.json()
        record_id = str(body.get("record_id") or "")
        # Authorization happens before the record (and therefore the evidence)
        # is touched at all.
        ctx = await ctx_for(request, body.get("workspace") or ALL)
        record = await service.current_record(ctx, record_id)
        retrieval = record.payload.get("retrieval") or {}
        await revalidate(request, ctx)
        generation = await service.generate(ctx, retrieval)
        # The model answer must not be persisted if the context changed while
        # it was in flight.
        await revalidate(request, ctx)
        record.payload["generation"] = generation
        service.records.save(record)
        return web.json_response({"record_id": record.record_id, "generation": generation})

    async def records(request: web.Request) -> web.Response:
        ctx = await ctx_for(request, ALL)
        owned = service.records.owned(ctx)
        try:
            live = await service.workspace_snapshots(ctx) if owned else {}
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

        await revalidate(request, ctx)
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
        ctx = await ctx_for(request, ALL)
        record = await service.current_record(ctx, request.match_info["rid"])
        await revalidate(request, ctx)
        return web.json_response(record.as_dict())

    async def export(request: web.Request) -> web.Response:
        ctx = await ctx_for(request, ALL)
        record = await service.current_record(ctx, request.match_info["rid"])
        await revalidate(request, ctx)
        body = json.dumps(record.as_dict(), ensure_ascii=False, indent=1)
        return web.Response(
            body=body.encode(),
            content_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{record.record_id}.json"'},
        )

    async def source(request: web.Request) -> web.Response:
        ctx = await ctx_for(request, ALL)
        rid = request.match_info["rid"]
        record = await service.current_record(ctx, rid)
        try:
            index = int(request.match_info["index"])
        except ValueError:
            raise NotAvailable("not available") from None
        item = service.record_chunk(ctx, rid, index)
        kind = request.match_info["kind"]
        if kind == "text":
            body = (item.get("content") or "").encode()
        else:
            body = await service.document_source(ctx, item, kind)
        await service.validate_retrieval(ctx, record.payload["retrieval"])
        return web.Response(
            body=body,
            content_type="application/pdf" if kind == "pdf" else "text/plain",
            charset=None if kind == "pdf" else "utf-8",
            headers={
                "Content-Disposition": "attachment; filename*=UTF-8''"
                + quote(item.get("doc_name") or "source.pdf")
            }
            if kind == "pdf"
            else None,
        )

    async def document(request: web.Request) -> web.Response:
        ctx = await ctx_for(request, ALL)
        record = await service.current_record(ctx, request.match_info["rid"])
        kind = request.match_info["kind"]
        for item in record.payload["retrieval"].get("evidence", []):
            if item.get("doc_id") == request.match_info["doc_id"]:
                body = await service.document_source(
                    ctx, item, "document-text" if kind == "text" else kind
                )
                await service.validate_retrieval(ctx, record.payload["retrieval"])
                return web.Response(
                    body=body,
                    content_type="application/pdf" if kind == "pdf" else "text/plain",
                    charset=None if kind == "pdf" else "utf-8",
                )
        raise NotAvailable("not available")

    async def health(request: web.Request) -> web.Response:
        # Public liveness reveals no knowledge-library identities.
        return web.json_response({"status": "ok"})

    routes = [
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
    if remote is not None:
        routes.append(web.post("/api/switch-tenant", switch_tenant))
        routes.append(web.get("/api/tenants", tenants))
        routes.append(web.get("/api/sso/start", sso_start))
        routes.append(web.get("/api/sso/callback", sso_callback))
    app.add_routes(routes)
    return app
