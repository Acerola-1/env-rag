"""HTTP surface for remote mode: K01/K07/K09/K13 upstream parts.

Boots the real aiohttp application with a remote provider backed by a scripted
IAM and a sentinel backend, then drives it with an aiohttp test client.  The
status codes, cookie handling, CSRF/Origin rules and the "refusal performs zero
backend work" invariant are all exercised end to end.
"""

from __future__ import annotations

import asyncio
import json

from aiohttp.test_utils import TestClient, TestServer

from env_rag_final.access import providers as P
from env_rag_final.access import remote as R
from env_rag_final.access.gateway import REMOTE_SESSION_COOKIE, KnowledgeService, Record
from env_rag_final.access.server import create_app
from tests.test_remote_boundaries import ScriptedIam
from tests.test_remote_iam import _probe
from tests.test_workspace_access import make_registry


def _service(tmp_path, payload=None, registry=None, tenant_id=None):
    registry = registry or make_registry(tmp_path)
    machine = payload or _probe("machine-sa-i3-air-knowledge")
    tenant_id = tenant_id or (machine.get("current_tenant") or {}).get("id")
    tenants = {}
    if tenant_id:
        tenants[tenant_id] = {"knowledge:lib:air": "air", "knowledge:lib:water": "water"}
    mapping = {"tenants": tenants or {_alpha_tenant(): {"knowledge:lib:air": "air"}}}
    config = R.RemoteConfig(
        iam_url="http://127.0.0.1:1",
        issuer=machine["issuer"],
        client_id="i3-know-client",
        client_secret="secret",
        mapping=R.parse_mapping(mapping),
    )
    iam = ScriptedIam(machine)
    provider = P.RemoteProvider(config=config, registry=registry, iam=iam)
    service = KnowledgeService(
        registry=registry,
        values={},
        record_root=tmp_path / "records",
        parsed_root=tmp_path / "parsed",
        auth_provider=provider,
        connect_factory=_never_connects,
    )
    return service, provider, iam


async def _never_connects():
    raise ConnectionRefusedError("sentinel backend is closed")


async def _client(service):
    app = create_app(service)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


_ALPHA_TENANT = None


def _alpha_tenant() -> str:
    global _ALPHA_TENANT
    if _ALPHA_TENANT is None:
        _ALPHA_TENANT = _probe("human-i3.dual-knowledge-after-select")["current_tenant"]["id"]
    return _ALPHA_TENANT


async def _async_value(value):
    return value


def test_health_is_public_and_reveals_nothing(tmp_path):
    async def scenario():
        service, _, _ = _service(tmp_path)
        client = await _client(service)
        try:
            response = await client.get("/health")
            assert response.status == 200
            assert await response.json() == {"status": "ok"}
        finally:
            await client.close()

    asyncio.run(scenario())


def test_machine_bearer_query_is_authorized_then_hits_the_sentinel(tmp_path):
    async def scenario():
        service, provider, iam = _service(tmp_path)
        client = await _client(service)
        try:
            response = await client.post(
                "/api/query",
                json={"workspace": "air", "question": "空气质量标准"},
                headers={"Authorization": "Bearer sa-token"},
            )
            # The sentinel backend refuses the connection: the request *was*
            # authorized (dispatch allowed) and fails as a service error.
            assert response.status in (500, 503)
            assert provider.iam.calls >= 1
        finally:
            await client.close()

    asyncio.run(scenario())


def test_wrong_library_is_refused_without_backend_work(tmp_path):
    async def scenario():
        service, provider, iam = _service(tmp_path)
        client = await _client(service)
        try:
            response = await client.post(
                "/api/query",
                json={"workspace": "coastal", "question": "q"},
                headers={"Authorization": "Bearer sa-token"},
            )
            assert response.status == 403
            assert (await response.json())["error"] == "unknown_workspace"
            assert service.backend_calls == []
        finally:
            await client.close()

    asyncio.run(scenario())


def test_mixed_selection_is_refused_whole(tmp_path):
    async def scenario():
        service, provider, iam = _service(tmp_path)
        client = await _client(service)
        try:
            response = await client.post(
                "/api/query",
                json={"workspaces": ["air", "water"], "question": "q"},
                headers={"Authorization": "Bearer sa-token"},
            )
            assert response.status == 403
            assert service.backend_calls == []
        finally:
            await client.close()

    asyncio.run(scenario())


def test_cross_site_post_is_refused(tmp_path):
    async def scenario():
        service, provider, iam = _service(tmp_path)
        client = await _client(service)
        try:
            response = await client.post(
                "/api/query",
                json={"workspace": "air", "question": "q"},
                headers={"Authorization": "Bearer sa-token", "Origin": "http://evil.example"},
            )
            assert response.status == 403
            assert (await response.json())["error"] == "bad_origin"
            assert provider.iam.calls == 0
        finally:
            await client.close()

    asyncio.run(scenario())


def test_iam_outage_returns_503_and_looks_like_a_service_problem(tmp_path):
    async def scenario():
        service, provider, iam = _service(tmp_path)
        iam.mode = "network"
        client = await _client(service)
        try:
            response = await client.post(
                "/api/query",
                json={"workspace": "air", "question": "q"},
                headers={"Authorization": "Bearer sa-token"},
            )
            assert response.status == 503
            assert (await response.json())["error"] == "upstream_unavailable"
        finally:
            await client.close()

    asyncio.run(scenario())


def test_missing_credentials_are_401(tmp_path):
    async def scenario():
        service, provider, iam = _service(tmp_path)
        client = await _client(service)
        try:
            response = await client.post("/api/query", json={"workspace": "air", "question": "q"})
            assert response.status == 401
            assert provider.iam.calls == 0
        finally:
            await client.close()

    asyncio.run(scenario())


def test_me_reports_mode_tenant_and_workspaces(tmp_path):
    async def scenario():
        machine = _probe("machine-sa-i3-air-knowledge")
        service, provider, iam = _service(tmp_path)
        client = await _client(service)
        try:
            response = await client.get("/api/me", headers={"Authorization": "Bearer sa-token"})
            assert response.status == 200
            body = await response.json()
            assert body["mode"] == "remote"
            assert body["principal_type"] == "service_account"
            assert body["enterprise"] == machine["current_tenant"]["id"]
            # the machine credential holds exactly the air read code
            assert [w["id"] for w in body["workspaces"]] == ["air"]
        finally:
            await client.close()

    asyncio.run(scenario())


def test_human_login_logout_flow_keeps_the_iam_token_server_side(tmp_path):
    async def scenario():
        payload = _probe("human-i3.dual-knowledge-after-select")
        service, provider, iam = _service(tmp_path, payload=payload)
        login_payload = {
            "access_token": "human-subject-token",
            "identity": {"user": {"display_name": "I3 双库读者"}},
        }

        async def fake_login(account, password, audience):
            assert audience == "knowledge"
            return login_payload

        provider.iam.login_password = fake_login
        provider.iam.list_tenants = lambda token: _async_value(
            [
                {
                    "tenant_id": payload["current_tenant"]["id"],
                    "code": "i3-alpha-env",
                    "name": "A",
                    "status": "active",
                    "member_status": "active",
                    "is_owner": False,
                }
            ]
        )
        client = await _client(service)
        try:
            response = await client.post(
                "/api/login", json={"account": "i3.dual", "password": "pw"}
            )
            assert response.status == 200
            body = await response.json()
            assert "subject_token" not in json.dumps(body)
            assert "human-subject-token" not in json.dumps(body)
            assert body["tenant"] == payload["current_tenant"]["id"]
            assert body["display"] == "I3 双库读者"
            cookie = response.cookies.get(REMOTE_SESSION_COOKIE)
            assert cookie is not None and cookie.value
            me = await client.get("/api/me")
            assert me.status == 200
            assert (await me.json())["display"] == "I3 双库读者"
            bad = await client.post("/api/logout")
            assert bad.status == 403
            good = await client.post("/api/logout", headers={"X-RAG-Token": body["csrf"]})
            assert good.status == 200
            after = await client.get("/api/me")
            assert after.status == 401
        finally:
            await client.close()

    asyncio.run(scenario())


def test_human_without_tenant_selection_is_forbidden(tmp_path):
    async def scenario():
        service, provider, iam = _service(
            tmp_path,
            payload=_probe("human-i3.dual-knowledge-before-select"),
            tenant_id=_alpha_tenant(),
        )
        client = await _client(service)
        try:
            response = await client.post(
                "/api/query",
                json={"workspace": "air", "question": "q"},
                headers={"Authorization": "Bearer human-token"},
            )
            assert response.status == 403
            assert (await response.json())["error"] == "tenant_selection_required"
            assert service.backend_calls == []
        finally:
            await client.close()

    asyncio.run(scenario())


def test_records_require_a_matching_principal_type(tmp_path):
    async def scenario():
        machine = _probe("machine-sa-i3-air-knowledge")
        service, provider, iam = _service(tmp_path, payload=machine)
        service.records.save(
            Record(
                record_id="wa-human",
                user_id=machine["principal"]["id"],
                enterprise=machine["current_tenant"]["id"],
                policy_revision=service.registry.revision,
                workspaces=["air"],
                created_at=0.0,
                question="q",
                route="pg",
                status="retrieved",
                payload={"retrieval": {}},
                principal_type="human",
                tenant_id=machine["current_tenant"]["id"],
                mode="remote",
            )
        )
        client = await _client(service)
        try:
            response = await client.get(
                "/api/records/wa-human", headers={"Authorization": "Bearer sa-token"}
            )
            assert response.status == 404
        finally:
            await client.close()

    asyncio.run(scenario())


def test_switch_tenant_requires_a_session_and_csrf(tmp_path):
    async def scenario():
        service, provider, iam = _service(tmp_path)
        client = await _client(service)
        try:
            response = await client.post(
                "/api/switch-tenant", json={"tenant_id": "x", "expected_ctx_version": 1}
            )
            assert response.status == 401
        finally:
            await client.close()

    asyncio.run(scenario())


def test_local_mode_has_no_switch_endpoint_and_no_iam(tmp_path):
    async def scenario():
        registry = make_registry(tmp_path)
        provider = P.LocalProvider(registry=registry)
        service = KnowledgeService(
            registry=registry,
            values={},
            record_root=tmp_path / "records",
            parsed_root=tmp_path / "parsed",
            auth_provider=provider,
            connect_factory=_never_connects,
        )
        client = await _client(service)
        try:
            response = await client.post(
                "/api/switch-tenant", json={"tenant_id": "x", "expected_ctx_version": 1}
            )
            assert response.status == 404
            assert not hasattr(provider, "iam")
        finally:
            await client.close()

    asyncio.run(scenario())
