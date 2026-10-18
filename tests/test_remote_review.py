"""Independent acceptance regressions: actual handler, dispatch and scope edges."""

import asyncio
from dataclasses import replace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from env_rag_final.access import remote as R
from env_rag_final.access.auth import AccessError, NotAvailable
from env_rag_final.access.boundary import live_guard
from env_rag_final.access.gateway import REMOTE_SESSION_COOKIE, Record
from env_rag_final.access.server import create_app
from tests.test_remote_boundaries import _dual_human, build_remote_service


def test_query_revocation_during_backend_never_returns_or_saves(tmp_path):
    async def run():
        s, p, iam, _ = build_remote_service(tmp_path)

        async def snapshots(ctx):
            await s.check_context(ctx)
            return {w: {"state": "current"} for w in ctx.workspaces}

        async def evidence(ctx, ws, q, **kw):
            s._note("pg:" + ws)
            iam.payload["permissions"] = []
            return {"workspace": ws, "status": "retrieved", "items": []}

        s.workspace_snapshots = snapshots
        s.pg_evidence = evidence
        async with TestClient(TestServer(create_app(s))) as c:
            r = await c.post(
                "/api/query",
                json={"workspace": "air", "question": "q"},
                headers={"Authorization": "Bearer fixture"},
            )
            assert r.status in (403, 404, 409)
            assert list(s.records.root.glob("*.json")) == []
            assert iam.calls >= 2

    asyncio.run(run())


@pytest.mark.parametrize(
    "field", ["user_auth_revision", "tenant_auth_revision", "membership_revision"]
)
def test_all_human_revisions_invalidate_original_context(tmp_path, field):
    async def run():
        s, p, iam, _ = build_remote_service(tmp_path, payload=_dual_human())
        ctx = await p.authorize_token("fixture", "air")
        iam.payload["revisions"][field] += 1
        if field == "membership_revision":
            iam.payload["membership"]["revision"] += 1
        with pytest.raises(AccessError):
            await p.recheck_token("fixture", ctx)

    asyncio.run(run())


def test_machine_revision_and_credential_are_cache_and_record_boundaries(tmp_path):
    async def run():
        s, p, iam, _ = build_remote_service(tmp_path)
        ctx = await p.authorize_token("fixture", "air")
        record = Record(
            "r",
            ctx.user_id,
            ctx.enterprise,
            ctx.policy_revision,
            ["air"],
            0,
            "q",
            "pg",
            "retrieved",
            principal_type=ctx.principal_type,
            mode="remote",
            auth_binding=ctx.auth_binding(),
        )
        s.records.save(record)
        assert s._record_for(ctx, "r") is record
        for changed in (
            replace(ctx, credential_revision=ctx.credential_revision + 1),
            replace(ctx, service_account_revision=ctx.service_account_revision + 1),
        ):
            assert changed.cache_key() != ctx.cache_key()
            assert not s.records.owned(changed)
            with pytest.raises(NotAvailable):
                s._record_for(changed, "r")
        iam.payload["service_account_revision"] += 1
        with pytest.raises(NotAvailable):
            await p.recheck_token("fixture", ctx)

    asyncio.run(run())


def test_next_data_send_after_revocation_is_zero(tmp_path):
    async def run():
        s, p, iam, conn = build_remote_service(tmp_path)
        ctx = await p.authorize_token("fixture", "air")
        guard = live_guard.set((ctx, lambda: p.recheck_token("fixture", ctx)))
        try:
            iam.payload["permissions"] = []
            with pytest.raises(AccessError):
                await s.document_row(ctx, "air", "d")
            assert conn.queries == []
        finally:
            live_guard.reset(guard)

    asyncio.run(run())


def test_direct_remote_operations_without_request_scope_are_closed(tmp_path):
    async def run():
        s, p, iam, conn = build_remote_service(tmp_path)
        ctx = await p.authorize_token("fixture", "air")
        with pytest.raises(NotAvailable):
            await s.workspace_snapshots(ctx)
        assert conn.queries == []

    asyncio.run(run())


def test_cas_version_and_epoch_survive_refresh_and_stale_tab_is_refused(tmp_path):
    async def run():
        s, p, iam, _ = build_remote_service(tmp_path, payload=_dual_human())
        identity = await p.introspect("fixture")
        session = p._new_session(identity, "fixture", "csrf")
        assert p.session_view(session)["context_version"] == identity.context_version
        async with TestClient(TestServer(create_app(s))) as c:
            c.session.cookie_jar.update_cookies({REMOTE_SESSION_COOKIE: session["session_id"]})
            me = await (await c.get("/api/me")).json()
            assert me["context_version"] == identity.context_version
            before = iam.calls
            r = await c.post(
                "/api/query",
                json={"workspace": "air", "question": "q"},
                headers={"X-RAG-Token": "csrf", "X-RAG-Context": "old-tab"},
            )
            assert r.status == 409
            assert iam.calls == before

    asyncio.run(run())


@pytest.mark.parametrize(
    "mutation",
    [
        lambda x: x.update(platform_admin="yes"),
        lambda x: x.update(evaluated_at="invalid"),
        lambda x: x["membership"].update(revision=999),
        lambda x: x["revisions"].update(extra=2),
        lambda x: x["session"].update(expires_at="2000-01-01T00:00:00Z"),
    ],
)
def test_protocol_faults_fail_closed_as_503(tmp_path, mutation):
    async def run():
        s, p, iam, _ = build_remote_service(tmp_path, payload=_dual_human())
        mutation(iam.payload)
        with pytest.raises(R.RemoteProtocolError):
            await p.authorize_token("fixture", "air")
        assert s.backend_calls == []

    asyncio.run(run())


@pytest.mark.parametrize("withdraw_at", ["before_send", "after_send", "never"])
def test_actual_generation_boundary_counts_and_output_guard(tmp_path, withdraw_at):
    """Execute the real generate function, including an actual controlled post."""

    async def run():
        s, p, iam, _ = build_remote_service(tmp_path)
        ctx = await p.authorize_token("fixture", "air")
        calls = []

        async def snapshots(current):
            await s.check_context(current)
            return {"air": {"state": "current"}}

        s.workspace_snapshots = snapshots

        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {"content": "answer [0]"}}], "model": "controlled"}

        class Client:
            async def __aenter__(self):
                if withdraw_at == "before_send":
                    iam.payload["permissions"] = []
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, *args, **kw):
                calls.append("model")
                if withdraw_at == "after_send":
                    iam.payload["permissions"] = []
                return Response()

        s._client_factory = Client
        s.values = {"LLM_BINDING_HOST": "http://controlled", "LLM_BINDING_API_KEY": "fixture"}
        retrieval = {
            "workspace_snapshots": {"air": {"state": "current"}},
            "question": "q",
            "workspaces": ["air"],
            "status": "retrieved",
            "per_workspace": [],
            "evidence": [{"workspace": "air", "content": "verified source", "verified": True}],
        }
        reset = live_guard.set((ctx, lambda: p.recheck_token("fixture", ctx)))
        try:
            if withdraw_at == "never":
                result = await s.generate(ctx, retrieval)
                assert result["status"] == "success"
            else:
                with pytest.raises(AccessError):
                    await s.generate(ctx, retrieval)
            assert len(calls) == (0 if withdraw_at == "before_send" else 1)
        finally:
            live_guard.reset(reset)

    asyncio.run(run())


def test_sso_state_is_server_owned_and_consumed_before_exchange(tmp_path):
    from urllib.parse import parse_qs, urlsplit

    async def run():
        s, p, _, _ = build_remote_service(tmp_path)
        p.config.sso_client_id = "configured-client"
        p.config.sso_callback = "http://127.0.0.1:50202/api/sso/callback"
        exchanged = []

        async def exchange(ticket, callback, state):
            exchanged.append(ticket)
            return {"session_id": "opaque-app-handle"}

        p.sso_login = exchange
        async with TestClient(TestServer(create_app(s))) as c:
            response = await c.get("/api/sso/start", allow_redirects=False)
            state = parse_qs(urlsplit(response.headers["Location"]).query)["state"][0]
            assert state == response.cookies["rag_remote_sso_state"].value
            path = "/api/sso/callback?ticket=controlled-ticket&state=" + state
            response = await c.get(path, allow_redirects=False)
            assert response.status == 302
            # Even with a copied browser cookie and a different ticket, a used
            # application state must never invoke another exchange.
            c.session.cookie_jar.update_cookies({"rag_remote_sso_state": state})
            response = await c.get(
                path.replace("controlled-ticket", "different-ticket"), allow_redirects=False
            )
            assert response.status == 403
            assert len(exchanged) == 1

    asyncio.run(run())


def test_browser_download_uses_epoch_query_without_custom_headers(tmp_path):
    async def run():
        s, p, iam, _ = build_remote_service(tmp_path, payload=_dual_human())
        ident = await p.introspect("fixture")
        session = p._new_session(ident, "fixture", "csrf")
        async with TestClient(TestServer(create_app(s))) as c:
            c.session.cookie_jar.update_cookies({REMOTE_SESSION_COOKIE: session["session_id"]})
            before = iam.calls
            # Unknown record stays 404 (after authentication); epoch query is
            # context binding only and never creates an authentication token.
            response = await c.get("/api/export/absent?ctx=" + session["tenant_epoch"])
            assert response.status == 404
            assert iam.calls > before
            response = await c.get("/api/export/absent?ctx=stale-tab")
            assert response.status == 409

    asyncio.run(run())


def test_plain_source_download_preserves_chinese_encoding(tmp_path):
    from types import SimpleNamespace

    async def run():
        s, p, iam, _ = build_remote_service(tmp_path)

        async def current(ctx, record_id):
            return SimpleNamespace(payload={"retrieval": {}})

        async def validate(ctx, value):
            return None

        s.current_record = current
        s.validate_retrieval = validate
        s.record_chunk = lambda *args: {"content": "中文法规原文", "workspace": "air"}
        async with TestClient(TestServer(create_app(s))) as c:
            response = await c.get(
                "/api/source/r/0/text", headers={"Authorization": "Bearer fixture"}
            )
            assert response.status == 200
            assert response.charset == "utf-8"
            assert await response.text() == "中文法规原文"

    asyncio.run(run())
