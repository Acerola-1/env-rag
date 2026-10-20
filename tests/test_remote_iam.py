"""Remote (IAM) authorization contract: K01–K06.

Phases proven here:

* strict typed validation of the IAM reply shapes — the positive fixtures are
  the *actual* introspection replies frozen during G0
  (``.local/iam-acceptance/<run>/g0-probes``), so a passing test means the
  real IAM output still validates; the negative cases mutate those fixtures
  field by field;
* human and service-account replies are validated by separate functions and
  cannot be coerced into each other;
* ``local`` mode issues zero IAM requests and a remote misconfiguration fails
  at startup instead of falling back;
* explicit tenant mapping ∩ exact ``knowledge:lib:*:read`` permissions ∩
  technical readiness decides the workspace set; ``all`` never leaks an
  unmapped or unauthorized library, and an explicit mixed selection is
  refused as a whole.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from env_rag_final.access import auth as A
from env_rag_final.access import providers as P
from env_rag_final.access import remote as R
from env_rag_final.access.registry import load_registry

FIXTURE_ROOT = Path(__file__).parent / "fixtures/iam"


def _probe(name: str) -> dict:
    """Portable non-secret protocol fixture; never skip auth checks silently."""
    return json.loads((FIXTURE_ROOT / f"{name}.json").read_text(encoding="utf-8"))


def _issuer() -> str:
    machine = _probe("machine-sa-i3-air-knowledge")
    return machine["issuer"]


# ---------------------------------------------------------------------------
# K01 — local stays local, remote fails closed
# ---------------------------------------------------------------------------


def test_local_provider_never_calls_iam(tmp_path):
    registry = load_registry(tmp_path / "missing.json") if False else None
    # A local provider built from a real registry issues no network calls at
    # all: the only collaborator it has is the registry object itself.
    from tests.test_workspace_access import make_registry

    registry = make_registry(tmp_path)
    provider = P.LocalProvider(registry=registry)
    assert provider.mode == "local"
    assert not hasattr(provider, "iam")
    principal = provider.principal_for_request(bearer_token=_bearer_for(registry, "air-reader"))
    ctx = provider.authorize_request(principal, "air")
    assert ctx.mode == "local"
    assert ctx.workspaces == ("air",)
    assert ctx.permissions == frozenset()


def _bearer_for(registry, user: str) -> str:
    from env_rag_final.access.registry import hash_token

    principal = registry.principal(user)
    token = f"token-{user}"
    principal = type(principal)(
        user_id=principal.user_id,
        enterprise=principal.enterprise,
        display=principal.display,
        roles=principal.roles,
        password_hash=principal.password_hash,
        bearer_sha256=(hash_token(token),),
    )
    registry.principals[user] = principal
    return token


def test_unknown_mode_is_rejected():
    with pytest.raises(P.AuthProviderError):
        P.build_provider("hybrid")


def test_remote_config_fails_closed(tmp_path):
    with pytest.raises(ValueError):
        R.RemoteConfig.from_env({})
    values = {
        "ENV_RAG_IAM_URL": "not-a-url",
        "ENV_RAG_IAM_ISSUER": "air-agent-iam",
        "ENV_RAG_IAM_CLIENT_ID": "i3-know-client",
        "ENV_RAG_IAM_CLIENT_SECRET": "x",
        "ENV_RAG_IAM_MAPPING": str(tmp_path / "missing.json"),
    }
    with pytest.raises(ValueError):
        R.RemoteConfig.from_env(values)


def test_mapping_rejects_non_uuid_and_reserved_keys(tmp_path):
    with pytest.raises(ValueError):
        R.parse_mapping({"tenants": {"all": {"knowledge:lib:air": "air"}}})
    with pytest.raises(ValueError):
        R.parse_mapping({"tenants": {"default": {"knowledge:lib:air": "air"}}})
    with pytest.raises(ValueError):
        R.parse_mapping(
            {"tenants": {"f017c513-fcac-4d0d-9415-7c0bfa7b7335": {"agent:ops:read": "air"}}}
        )
    with pytest.raises(ValueError):
        R.parse_mapping({"tenants": {}})
    # A tenant may not declare the reserved physical namespace either.
    with pytest.raises(ValueError):
        R.parse_mapping(
            {"tenants": {"f017c513-fcac-4d0d-9415-7c0bfa7b7335": {"knowledge:lib:air": "default"}}}
        )
    # ... and a well-formed mapping round-trips.
    parsed = R.parse_mapping(
        {"tenants": {"f017c513-fcac-4d0d-9415-7c0bfa7b7335": {"knowledge:lib:air": "air"}}}
    )
    assert parsed["f017c513-fcac-4d0d-9415-7c0bfa7b7335"] == {"knowledge:lib:air": "air"}


# ---------------------------------------------------------------------------
# K02 — human / machine strict typing
# ---------------------------------------------------------------------------


def test_frozen_machine_reply_validates():
    payload = _probe("machine-sa-i3-air-knowledge")
    identity = R.validate_machine_identity(payload, expected_issuer=payload["issuer"])
    assert identity.principal_type == "service_account"
    assert identity.context_version is None
    assert identity.revisions is None
    assert identity.session_id is None
    assert identity.workspace_grants() == {"knowledge:lib:air": "air"}


def test_frozen_human_reply_validates():
    payload = _probe("human-i3.dual-knowledge-after-select")
    identity = R.validate_human_identity(payload, expected_issuer=payload["issuer"])
    assert identity.principal_type == "human"
    assert identity.tenant_code == "i3-alpha-env"
    assert identity.workspace_grants() == {
        "knowledge:lib:air": "air",
        "knowledge:lib:water": "water",
    }
    assert identity.revisions["session_ctx_version"] == identity.context_version


def test_human_before_selection_is_valid_but_unusable():
    payload = _probe("human-i3.dual-knowledge-before-select")
    identity = R.validate_human_identity(payload, expected_issuer=payload["issuer"])
    assert identity.context_usable is False
    assert identity.needs_tenant_selection is True
    assert identity.tenant_id is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(schema_version="iam.identity.v2"),
        lambda p: p.update(active="yes"),
        lambda p: p.update(audience="air-agent"),
        lambda p: p.update(issuer="some-other-issuer"),
        lambda p: p["principal"].update(type="service_account"),
        lambda p: p["principal"].update(realm="service"),
        lambda p: p["principal"].update(id="not-a-uuid"),
        lambda p: p["revisions"].update(user_auth_revision=True),
        lambda p: p.update(context_version=True),
        lambda p: p["revisions"].update(session_ctx_version=99),
        lambda p: p["session"].update(ctx_version=99),
        lambda p: p["membership"].update(tenant_id="00000000-0000-4000-8000-000000000000"),
        lambda p: p["user"].update(status="disabled"),
        lambda p: p.update(unknown_extra="x"),
        lambda p: p.update(platform_roles=[{"code": 3}]),
    ],
)
def test_human_reply_mutations_reject(mutate):
    payload = copy.deepcopy(_probe("human-i3.dual-knowledge-after-select"))
    mutate(payload)
    with pytest.raises(R.IdentityRejected):
        R.validate_human_identity(payload, expected_issuer=_issuer())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(schema_version="iam.identity.v1"),
        lambda p: p.update(audience="iam-admin"),
        lambda p: p["principal"].update(type="human"),
        lambda p: p["principal"].update(realm="workforce"),
        lambda p: p.update(user={"id": p["principal"]["id"]}),
        lambda p: p.update(session={"id": p["principal"]["id"]}),
        lambda p: p.update(membership={"id": p["principal"]["id"]}),
        lambda p: p.update(revisions={"user_auth_revision": 0}),
        lambda p: p.update(credential_revision=True),
        lambda p: p.update(credential_id="cred-1"),
        lambda p: p.update(credential_expires_at="yesterday"),
        lambda p: p.update(service_account_revision=0),
        lambda p: p.update(permissions=["knowledge:lib:air:read", 5]),
        lambda p: p.update(extra=1),
    ],
)
def test_machine_reply_mutations_reject(mutate):
    payload = copy.deepcopy(_probe("machine-sa-i3-air-knowledge"))
    mutate(payload)
    with pytest.raises(R.IdentityRejected):
        R.validate_machine_identity(payload, expected_issuer=_issuer())


def test_human_reply_cannot_be_validated_as_machine_and_vice_versa():
    human = _probe("human-i3.dual-knowledge-after-select")
    machine = _probe("machine-sa-i3-air-knowledge")
    with pytest.raises(R.IdentityRejected):
        R.validate_machine_identity(human, expected_issuer=_issuer())
    with pytest.raises(R.IdentityRejected):
        R.validate_human_identity(machine, expected_issuer=_issuer())


def test_inactive_envelope_rejects_and_does_not_leak():
    reason = R.validate_inactive(
        {
            "schema_version": "iam.introspection.v1",
            "active": False,
            "reason": "invalid_or_revoked",
            "evaluated_at": "2026-10-16T00:00:00Z",
        }
    )
    assert reason == "invalid_or_revoked"
    with pytest.raises(R.IdentityRejected):
        R.validate_payload(
            {
                "schema_version": "iam.introspection.v1",
                "active": False,
                "reason": "invalid_or_revoked",
                "evaluated_at": "2026-10-16T00:00:00Z",
                "user": {"account": "leak"},
            },
            expected_issuer=_issuer(),
        )
    with pytest.raises(R.RemoteProtocolError):
        R.validate_payload({"schema_version": "iam.something.v9"}, expected_issuer=_issuer())


def test_unknown_schema_is_a_protocol_error_not_an_identity_decision():
    with pytest.raises(R.RemoteProtocolError):
        R.validate_payload({"schema_version": "iam.other.v1", "active": True}, expected_issuer="x")


# ---------------------------------------------------------------------------
# K03 — failure closes, no positive cache
# ---------------------------------------------------------------------------


class _FakeIam:
    """Deterministic IAM stub: queue exact (status, payload) replies."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    async def introspect(self, subject_token, *, audience=None, operation=None):
        self.calls += 1
        self.operation = operation
        status, payload = self.replies.pop(0)
        if status == "network":
            raise R.RemoteUnavailable("identity service unreachable")
        if status == "timeout":
            raise R.RemoteDeadlineError("identity check timed out")
        if status == "conflict":
            raise R.ConflictError("context changed")
        if status == "http403":
            raise R.RemoteUnavailable("consumer client is not authorized for this audience")
        if status != 200:
            raise R.RemoteProtocolError(f"HTTP {status}")
        return payload


def _provider(tmp_path, replies, mapping=None, registry=None):
    machine = _probe("machine-sa-i3-air-knowledge")
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
    iam = _FakeIam(replies)
    provider = P.RemoteProvider(config=config, registry=registry, iam=iam)
    return provider, iam


def test_remote_network_failure_maps_to_503_never_local(tmp_path):
    from tests.test_workspace_access import make_registry

    provider, iam = _provider(tmp_path, [("network", None)], registry=make_registry(tmp_path))
    with pytest.raises(R.RemoteUnavailable) as exc:
        import asyncio

        asyncio.run(provider.authorize_token("sa-token", "air"))
    assert exc.value.status == 503
    assert iam.calls == 1


def test_remote_does_not_cache_positive_authorization(tmp_path):
    from tests.test_workspace_access import make_registry

    machine = _probe("machine-sa-i3-air-knowledge")
    provider, iam = _provider(
        tmp_path,
        [(200, machine), (200, machine), ("network", None)],
        registry=make_registry(tmp_path),
    )

    async def scenario():
        first = await provider.authorize_token("sa-token", "air")
        second = await provider.authorize_token("sa-token", "air")
        assert first.cache_key("q") == second.cache_key("q")
        with pytest.raises(R.RemoteUnavailable):
            await provider.authorize_token("sa-token", "air")
        return first

    import asyncio

    ctx = asyncio.run(scenario())
    assert iam.calls == 3
    assert ctx.workspaces == ("air",)


def test_selection_all_expands_only_granted_and_ready(tmp_path):
    from tests.test_workspace_access import make_registry

    machine = _probe("machine-sa-i3-air-knowledge")
    provider, _ = _provider(tmp_path, [], registry=make_registry(tmp_path))
    identity = R.validate_machine_identity(machine, expected_issuer=machine["issuer"])

    async def scenario():
        assert provider.resolve_selection(identity, "all") == ("air",)
        # an explicit library the subject has no permission for is refused whole
        with pytest.raises(A.Forbidden) as exc:
            provider.resolve_selection(identity, ["air", "water"])
        assert exc.value.code == "unauthorized_workspace"
        with pytest.raises(A.Forbidden) as exc:
            provider.resolve_selection(identity, "unknown-lib")
        assert exc.value.code == "unknown_workspace"

    import asyncio

    asyncio.run(scenario())


def test_unmapped_resource_yields_no_access(tmp_path):
    from tests.test_workspace_access import make_registry

    machine = _probe("machine-sa-i3-air-knowledge")
    mapping = {"tenants": {machine["current_tenant"]["id"]: {"knowledge:lib:water": "water"}}}
    provider, _ = _provider(tmp_path, [], mapping=mapping, registry=make_registry(tmp_path))
    identity = R.validate_machine_identity(machine, expected_issuer=machine["issuer"])

    async def scenario():
        with pytest.raises(A.Forbidden) as exc:
            provider.resolve_selection(identity, "all")
        assert exc.value.code == "no_workspace"
        with pytest.raises(A.Forbidden):
            provider.resolve_selection(identity, "air")

    import asyncio

    asyncio.run(scenario())


def test_local_mode_registry_still_authorizes_the_same_way(tmp_path):
    from tests.test_workspace_access import make_registry

    registry = make_registry(tmp_path)
    provider = P.LocalProvider(registry=registry)
    principal = registry.principal("dual-reader")
    ctx = provider.authorize_request(principal, "all")
    assert sorted(ctx.workspaces) == ["air", "water"]
    with pytest.raises(A.Forbidden):
        provider.authorize_request(principal, ["air", "water", "unknown"])


def test_remote_refuses_the_local_record_root(tmp_path):
    """A remote process must name its own record root (isolation guard)."""
    from env_rag_final.access import __main__ as cli

    cli.ensure_isolated_record_root("local", cli.DEFAULT_RECORDS)  # local is fine
    with pytest.raises(SystemExit):
        cli.ensure_isolated_record_root("remote", cli.DEFAULT_RECORDS)
    cli.ensure_isolated_record_root("remote", tmp_path / "records")  # explicit root ok
