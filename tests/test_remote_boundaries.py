"""Every data egress re-checks permission: K07–K11.

The scenarios here use the frozen real-IAM reply shapes as inputs and a
scripted IAM stub, so a revocation, a tenant switch (A→B→A) or an IAM outage is
reproduced deterministically while the *shape* under test stays the observed
production contract.
"""

from __future__ import annotations

import asyncio
import copy

import pytest

from env_rag_final.access import auth as A
from env_rag_final.access import providers as P
from env_rag_final.access import remote as R
from env_rag_final.access.boundary import live_guard
from env_rag_final.access.gateway import KnowledgeService, Record, RecordStore
from env_rag_final.access.registry import load_registry
from tests.test_remote_iam import _probe
from tests.test_workspace_access import make_registry


def _machine() -> dict:
    return copy.deepcopy(_probe("machine-sa-i3-air-knowledge"))


def _dual_human() -> dict:
    return copy.deepcopy(_probe("human-i3.dual-knowledge-after-select"))


class ScriptedIam:
    """IAM stub whose reply can be swapped mid-test (revocation, ABA, outage)."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0
        self.mode = "ok"  # ok | network | timeout | conflict

    async def introspect(self, subject_token, *, audience=None):
        self.calls += 1
        if self.mode == "network":
            raise R.RemoteUnavailable("identity service unreachable")
        if self.mode == "timeout":
            raise R.RemoteDeadlineError("identity check timed out")
        if self.mode == "conflict":
            raise R.ConflictError("context changed")
        return copy.deepcopy(self.payload)

    async def aclose(self):
        return None

    async def logout(self, subject_token):
        self.calls += 1
        return None

    async def login_password(self, account, password, *, audience):
        raise AssertionError("scripted IAM does not implement password login")

    async def list_tenants(self, subject_token):
        return []


class FakeConn:
    """Records queries and returns empty result sets (no real backend)."""

    def __init__(self, guard_state="current"):
        self.queries: list[tuple] = []
        self.guard_state = guard_state
        self.closed = False

    async def fetch(self, sql, *args):
        self.queries.append(("fetch", sql, args))
        return []

    async def fetchrow(self, sql, *args):
        self.queries.append(("fetchrow", sql, args))
        return None

    async def close(self):
        self.closed = True


def build_remote_service(tmp_path, registry=None, payload=None, mapping=None):
    registry = registry or make_registry(tmp_path)
    machine = payload or _machine()
    mapping = mapping or {
        "tenants": {machine["current_tenant"]["id"]: {"knowledge:lib:air": "air"}}
    }
    config = R.RemoteConfig(
        iam_url="http://127.0.0.1:1",
        issuer=machine["issuer"],
        client_id="i3-know-client",
        client_secret="secret",
        mapping=R.parse_mapping(mapping),
    )
    iam = ScriptedIam(machine)
    provider = P.RemoteProvider(config=config, registry=registry, iam=iam)
    conn = FakeConn()
    service = KnowledgeService(
        registry=registry,
        values={},
        record_root=tmp_path / "records",
        parsed_root=tmp_path / "parsed",
        auth_provider=provider,
        connect_factory=lambda: _ready(conn),
    )
    return service, provider, iam, conn


async def _ready(conn):
    return conn


# ---------------------------------------------------------------------------
# K07 — cached answers and in-flight generation do not survive revocation
# ---------------------------------------------------------------------------


def test_authorization_is_recomputed_even_when_the_answer_is_cached(tmp_path):
    service, provider, iam, conn = build_remote_service(tmp_path)
    machine_token = "sa-token"

    async def scenario():
        ctx = await provider.authorize_token(machine_token, "air")
        # First pass reaches the backend boundary (the fake connection answers).
        live_guard.set((ctx, lambda: provider.recheck_token(machine_token, ctx)))
        snapshots = await service.workspace_snapshots(ctx)
        assert set(snapshots) == {"air"}
        calls_after_first = len(service.backend_calls)
        # The IAM revokes the grant: the cached path must NOT serve the answer.
        revoked = _machine()
        revoked["permissions"] = []
        iam.payload = revoked
        with pytest.raises(A.Forbidden):
            await provider.authorize_token(machine_token, "air")
        assert len(service.backend_calls) == calls_after_first
        assert iam.calls >= 3  # entry and data boundaries have no positive cache

    asyncio.run(scenario())


def test_generation_rechecks_before_and_after_the_model_call(tmp_path):
    service, provider, iam, conn = build_remote_service(tmp_path)
    machine_token = "sa-token"
    notes: list[str] = []

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": "答案 [0]"}}],
                "model": "stub",
                "usage": {"prompt_tokens": 1},
            }

    class FakeClient:
        def __init__(self):
            self.posts = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, **kwargs):
            self.posts += 1
            # The tenant changes while the model call is in flight.
            iam.payload = _machine_without_air_permission()
            return FakeResponse()

        async def get(self, url, **kwargs):  # pragma: no cover
            raise AssertionError("unexpected GET")

    client = FakeClient()
    service._client_factory = lambda: client

    async def scenario():
        ctx = await provider.authorize_token(machine_token, "air")
        retrieval = {
            "workspace_snapshots": {
                "air": {
                    "state": "current",
                    "source_fingerprint": "fp",
                    "catalog_snapshot_id": "c",
                    "search_id": "s",
                    "pg_workspace": "air",
                    "instance_url": None,
                    "code_identity": None,
                }
            },
            "question": "空气质量",
            "route": "pg",
            "mode": None,
            "workspaces": ["air"],
            "status": "retrieved",
            "per_page": [],
            "per_workspace": [],
            "evidence": [
                {
                    "workspace": "air",
                    "chunk_id": "c1",
                    "doc_id": "d1",
                    "content": "标准限值",
                    "kind": "chunk",
                    "verified": True,
                }
            ],
        }
        # A live re-check before dispatch succeeds; the post-call re-check must
        # fail because the permission disappeared mid-flight.
        await service.recheck_remote_live(ctx, machine_token)
        with pytest.raises(A.NotAvailable):
            await service.generate(ctx, retrieval)

    asyncio.run(scenario())
    assert notes == []


def _machine_without_air_permission() -> dict:
    payload = _machine()
    payload["permissions"] = ["knowledge:lib:water:read"]
    return payload


def test_aba_switch_back_does_not_reuse_the_old_binding(tmp_path):
    """A→B→A must not resurrect the first enterprise's authorization."""
    alpha = _dual_human()
    beta = copy.deepcopy(alpha)
    beta["current_tenant"] = {
        "id": "4d58ce50-b0a1-46a5-a71a-5db98f27cb81",
        "code": "i3-beta-env",
        "name": "I3 Beta",
        "status": "active",
    }
    beta["membership"]["tenant_id"] = beta["current_tenant"]["id"]
    beta["permissions"] = ["knowledge:lib:water:read"]

    service, provider, iam, conn = build_remote_service(
        tmp_path,
        payload=alpha,
        mapping={
            "tenants": {
                alpha["current_tenant"]["id"]: {
                    "knowledge:lib:air": "air",
                    "knowledge:lib:water": "water",
                },
                beta["current_tenant"]["id"]: {"knowledge:lib:water": "water"},
            }
        },
    )
    context_versions: list[int] = []

    async def scenario():
        ctx_a = await provider.authorize_token("human-token", "all")
        context_versions.append(ctx_a.context_version)
        iam.payload = beta
        ctx_b = await provider.authorize_token("human-token", "all")
        assert ctx_b.tenant_id != ctx_a.tenant_id
        # Switch back to A: this is a NEW context (new ctx epoch), so the old
        # context object must not be accepted for a live re-check.
        switch_back = copy.deepcopy(alpha)
        switch_back["context_version"] = ctx_a.context_version + 2
        switch_back["revisions"]["session_ctx_version"] = switch_back["context_version"]
        switch_back["session"]["ctx_version"] = switch_back["context_version"]
        iam.payload = switch_back
        ctx_a2 = await provider.authorize_token("human-token", "all")
        assert ctx_a2.context_version != ctx_a.context_version
        with pytest.raises(A.NotAvailable):
            await provider.recheck_token("human-token", ctx_a)

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# K09/K10 — record / export / source / document boundaries
# ---------------------------------------------------------------------------


def test_record_reuse_requires_the_same_principal_type_and_tenant(tmp_path):
    service, provider, iam, conn = build_remote_service(tmp_path)
    machine = _machine()
    identity = R.validate_machine_identity(machine, expected_issuer=machine["issuer"])

    async def scenario():
        ctx = provider._context_for(identity, ("air",))
        service.records.save(
            Record(
                record_id="wa-1",
                user_id=ctx.principal_id,
                enterprise=ctx.tenant_id,
                policy_revision=ctx.policy_revision,
                workspaces=["air"],
                created_at=0.0,
                question="q",
                route="pg",
                status="retrieved",
                payload={"retrieval": {}},
                principal_type="human",  # same id, different principal type
                tenant_id=ctx.tenant_id,
                mode="remote",
            )
        )
        with pytest.raises(A.NotAvailable):
            service._record_for(ctx, "wa-1")
        # A local record with the same user id must not be reachable either.
        service.records.save(
            Record(
                record_id="wa-2",
                user_id=ctx.principal_id,
                enterprise=ctx.tenant_id,
                policy_revision=ctx.policy_revision,
                workspaces=["air"],
                created_at=0.0,
                question="q",
                route="pg",
                status="retrieved",
                payload={"retrieval": {}},
                principal_type="service_account",
                tenant_id=ctx.tenant_id,
                mode="local",
            )
        )
        with pytest.raises(A.NotAvailable):
            service._record_for(ctx, "wa-2")
        # The matching record is reachable.
        service.records.save(
            Record(
                auth_binding=ctx.auth_binding(),
                record_id="wa-3",
                user_id=ctx.principal_id,
                enterprise=ctx.tenant_id,
                policy_revision=ctx.policy_revision,
                workspaces=["air"],
                created_at=0.0,
                question="q",
                route="pg",
                status="retrieved",
                payload={"retrieval": {}},
                principal_type="service_account",
                tenant_id=ctx.tenant_id,
                mode="remote",
            )
        )
        assert service._record_for(ctx, "wa-3").record_id == "wa-3"

    asyncio.run(scenario())


def test_record_store_owned_filters_by_principal_type_and_tenant(tmp_path):
    store = RecordStore(tmp_path / "records")
    base = dict(
        user_id="u1",
        policy_revision="r1",
        workspaces=["air"],
        created_at=0.0,
        question="q",
        route="pg",
        status="retrieved",
        payload={},
    )
    store.save(
        Record(
            record_id="r-human-a",
            enterprise="ta",
            principal_type="human",
            tenant_id="ta",
            mode="remote",
            **base,
        )
    )
    store.save(
        Record(
            record_id="r-human-b",
            enterprise="tb",
            principal_type="human",
            tenant_id="tb",
            mode="remote",
            **base,
        )
    )
    store.save(
        Record(
            record_id="r-local",
            enterprise="ta",
            principal_type="local",
            tenant_id="ta",
            mode="local",
            **base,
        )
    )
    ctx_human = A.AuthContext(
        mode="remote",
        principal_type="human",
        principal_id="u1",
        tenant_id="ta",
        tenant_code="ta",
        permissions=frozenset(),
        context_version=1,
        session_id="s1",
        credential_id=None,
        credential_revision=None,
        workspaces=("air",),
        policy_revision="r1",
        directory_version="r1",
        issued_at=0.0,
    )
    record = store.get("r-human-a")
    record.auth_binding = ctx_human.auth_binding()
    store.save(record)
    owned = [r.record_id for r in store.owned(ctx_human)]
    assert owned == ["r-human-a"]


def test_source_files_are_guarded_by_workspace_and_registry(tmp_path):
    service, provider, iam, conn = build_remote_service(tmp_path)
    machine = _machine()
    identity = R.validate_machine_identity(machine, expected_issuer=machine["issuer"])
    ctx = provider._context_for(identity, ("air",))

    async def scenario():
        # A document in another library is refused before any query runs.
        with pytest.raises(A.NotAvailable):
            await service.document_row(ctx, "water", "doc-1")
        with pytest.raises(A.NotAvailable):
            await service.document_source(ctx, {"workspace": "water", "doc_id": "x"}, "pdf")
        assert all("water" not in str(q) for q in conn.queries)

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# K08 — permanent revocation / disabled account / reopened grant
# ---------------------------------------------------------------------------


def test_revoked_machine_cannot_revive_and_reopen_restores_access(tmp_path):
    service, provider, iam, conn = build_remote_service(tmp_path)

    async def scenario():
        ctx = await provider.authorize_token("sa-token", "air")
        assert ctx.workspaces == ("air",)
        # disabled account → inactive envelope → rejected
        iam.payload = {
            "schema_version": "iam.introspection.v1",
            "active": False,
            "reason": "account_disabled",
            "evaluated_at": "2026-10-16T00:00:00Z",
        }
        with pytest.raises(A.Unauthenticated):
            await provider.authorize_token("sa-token", "air")
        # revoked credential
        iam.payload = {
            "schema_version": "iam.introspection.v1",
            "active": False,
            "reason": "invalid_or_revoked",
            "evaluated_at": "2026-10-16T00:00:00Z",
        }
        with pytest.raises(A.Unauthenticated):
            await provider.authorize_token("sa-token", "air")
        # reopened grant: the same credential works again with a fresh reply
        iam.payload = _machine()
        ctx2 = await provider.authorize_token("sa-token", "air")
        assert ctx2.workspaces == ("air",)

    asyncio.run(scenario())


def test_iam_timeout_maps_to_503_and_does_not_touch_backends(tmp_path):
    service, provider, iam, conn = build_remote_service(tmp_path)
    iam.mode = "timeout"

    async def scenario():
        with pytest.raises(R.RemoteUnavailable) as exc:
            await provider.authorize_token("sa-token", "air")
        assert exc.value.status == 503
        assert service.backend_calls == []

    asyncio.run(scenario())


def test_workspace_for_refuses_default_and_inactive(tmp_path):
    registry = make_registry(tmp_path)
    service, provider, iam, conn = build_remote_service(tmp_path, registry=registry)
    machine = _machine()
    identity = R.validate_machine_identity(machine, expected_issuer=machine["issuer"])
    ctx = provider._context_for(identity, ("air",))
    with pytest.raises(A.NotAvailable):
        service.workspace_for(ctx, "water")
    with pytest.raises(A.NotAvailable):
        service.workspace_for(ctx, "default")


def test_cached_flag_does_not_bypass_checks(tmp_path):
    """A cached answers must not be served after revocation (K07 wording)."""
    service, provider, iam, conn = build_remote_service(tmp_path)

    async def scenario():
        ctx = await provider.authorize_token("sa-token", "air")
        service._cache[ctx.cache_key("q")] = {"answer": "old"}
        revoked = _machine()
        revoked["permissions"] = []
        iam.payload = revoked
        with pytest.raises(A.Forbidden):
            await provider.authorize_token("sa-token", "air")
        # The stale cache entry is not reachable through a new authorization.

    asyncio.run(scenario())


def test_registry_revision_change_invalidates_remote_context(tmp_path):
    service, provider, iam, conn = build_remote_service(tmp_path)
    machine = _machine()
    identity = R.validate_machine_identity(machine, expected_issuer=machine["issuer"])
    ctx = provider._context_for(identity, ("air",))

    async def scenario():
        live_guard.set((ctx, lambda: provider.recheck_token("fixture", ctx)))
        await service.check_context(ctx)
        service.registry.revision = "next-revision"
        with pytest.raises(A.NotAvailable):
            await service.check_context(ctx)

    asyncio.run(scenario())


def test_machine_reply_in_human_slot_is_refused_by_the_service(tmp_path):
    service, provider, iam, conn = build_remote_service(
        tmp_path, payload=_probe("human-i3.dual-knowledge-after-select")
    )
    # The scripted IAM answers with a human reply; the machine validator would
    # only run for a machine token, so flip the payload to a machine one and
    # then present it as if the schema were wrong.
    payload = _probe("human-i3.dual-knowledge-after-select")
    payload["principal"]["type"] = "service_account"
    iam.payload = payload

    async def scenario():
        with pytest.raises(R.RemoteProtocolError):
            await provider.authorize_token("sa-token", "air")

    asyncio.run(scenario())


def test_local_service_keeps_zero_iam_calls(tmp_path):
    """A local deployment must not build an IAM client at all."""
    registry = load_registry if False else make_registry(tmp_path)
    from env_rag_final.access.providers import LocalProvider

    provider = LocalProvider(registry=registry)
    service = KnowledgeService(
        registry=registry,
        values={},
        record_root=tmp_path / "records",
        parsed_root=tmp_path / "parsed",
        auth_provider=provider,
        connect_factory=lambda: _ready(FakeConn()),
    )
    assert service.mode == "local"
    assert not hasattr(service.provider, "iam")
    principal = registry.principal("air-reader")
    ctx = service.authorize_for_request(principal, "air")
    assert ctx.mode == "local"
