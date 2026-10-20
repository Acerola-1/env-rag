"""Knowledge user delegation consumption: strict schema and operation isolation."""

from __future__ import annotations

import asyncio
import copy
import json

import httpx
import pytest

from env_rag_final.access import remote as R
from env_rag_final.access.auth import Forbidden
from env_rag_final.access.remote import (
    IamClient,
    IdentityRejected,
    RemoteConfig,
    RemoteProtocolError,
    validate_knowledge_delegation,
    validate_payload,
)

SESSION = "01940000-0000-4000-8000-000000000004"
TENANT = "01940000-0000-4000-8000-000000000002"
USER = "01940000-0000-4000-8000-000000000001"
MEMBERSHIP = "01940000-0000-4000-8000-000000000003"


def _identity_payload() -> dict:
    return {
        "schema_version": "iam.identity.v1",
        "active": True,
        "issuer": "air-agent-iam",
        "audience": "knowledge",
        "principal": {"type": "human", "id": USER, "realm": "workforce"},
        "user": {
            "id": USER,
            "account": "reader",
            "display_name": "Reader",
            "status": "active",
        },
        "session": {
            "id": SESSION,
            "ctx_version": 2,
            "created_at": "2026-10-20T00:00:00Z",
            "expires_at": "2026-10-21T00:00:00Z",
            "absolute_expires_at": "2026-10-27T00:00:00Z",
            "idle_expires_at": "2026-10-21T00:00:00Z",
        },
        "current_tenant": {
            "id": TENANT,
            "code": "tenant-a",
            "name": "Tenant A",
            "status": "active",
        },
        "membership": {
            "id": MEMBERSHIP,
            "tenant_id": TENANT,
            "department_id": None,
            "status": "active",
            "revision": 3,
        },
        "platform_roles": [],
        "tenant_roles": [],
        "permissions": ["knowledge:lib:air:read"],
        "revisions": {
            "user_auth_revision": 4,
            "tenant_auth_revision": 5,
            "membership_revision": 3,
            "session_ctx_version": 2,
        },
        "context_version": 2,
        "platform_admin": False,
        "context_usable": True,
        "needs_tenant_selection": False,
        "evaluated_at": "2026-10-20T00:00:00Z",
    }


def _delegation_payload(operation: str = "query") -> dict:
    return {
        "schema_version": R.DELEGATION_SCHEMA,
        "active": True,
        "issuer": "air-agent-iam",
        "audience": "knowledge",
        "operation": operation,
        "identity": _identity_payload(),
        "delegation": {
            "issuing_client_id": "air-agent-i4",
            "source_audience": "langgraph-runtime",
            "source_session_id": SESSION,
            "operation": operation,
            "expires_at": "2026-10-20T00:00:30Z",
        },
        "evaluated_at": "2026-10-20T00:00:00Z",
    }


def test_delegation_is_validated_and_keeps_auth_binding_operation_free() -> None:
    identity = validate_knowledge_delegation(
        _delegation_payload(), expected_issuer="air-agent-iam", expected_operation="query"
    )
    assert identity.principal_type == "human"
    assert identity.delegation_operation == "query"
    assert identity.delegation["issuing_client_id"] == "air-agent-i4"
    assert identity.permissions == frozenset({"knowledge:lib:air:read"})


def test_operation_mismatch_is_forbidden() -> None:
    with pytest.raises(Forbidden):
        validate_knowledge_delegation(
            _delegation_payload("query"),
            expected_issuer="air-agent-iam",
            expected_operation="source:read",
        )


def test_non_knowledge_permission_in_delegation_is_rejected() -> None:
    payload = _delegation_payload()
    payload["identity"]["permissions"] = ["knowledge:lib:air:read", "agent:business:basic-qa:use"]
    with pytest.raises(RemoteProtocolError):
        validate_knowledge_delegation(
            payload, expected_issuer="air-agent-iam", expected_operation="query"
        )


def test_unknown_field_is_rejected() -> None:
    payload = _delegation_payload()
    payload["extra"] = True
    with pytest.raises((RemoteProtocolError, IdentityRejected)):
        validate_knowledge_delegation(
            payload, expected_issuer="air-agent-iam", expected_operation="query"
        )


def test_inactive_delegation_is_subject_rejection_not_protocol() -> None:
    payload = {
        "schema_version": R.DELEGATION_SCHEMA,
        "active": False,
        "reason": "permission_denied",
        "evaluated_at": "2026-10-20T00:00:00Z",
    }
    with pytest.raises(IdentityRejected):
        validate_payload(
            payload,
            expected_issuer="air-agent-iam",
            expected_operation="query",
        )


def test_iam_client_sends_operation_only_for_delegation_tokens() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=_delegation_payload())

    config = RemoteConfig(
        iam_url="http://127.0.0.1:19100",
        issuer="air-agent-iam",
        client_id="knowledge-i4",
        client_secret="x" * 32,
        mapping={TENANT: {"knowledge:lib:air": "air"}},
    )

    async def run():
        client = IamClient(config, transport=httpx.MockTransport(handler))
        try:
            await client.introspect("kdl_delegation", operation="query")
            await client.introspect("human-token", operation="query")
        finally:
            await client.aclose()

    asyncio.run(run())
    assert seen[0]["operation"] == "query"
    assert "operation" not in seen[1]
    assert copy.deepcopy(seen[0])["audience"] == "knowledge"


def test_source_digest_uses_rfc8785_number_and_utf16_key_order():
    import hashlib

    import rfc8785

    from env_rag_final.access.gateway import knowledge_source_digest

    item = {
        "workspace": "air",
        "doc_id": "F-A",
        "chunk_id": "shared",
        "kind": "chunk",
        "content": "中文\n原文",
        "location": None,
    }
    snapshot = {"source_fingerprint": "v1", "ratio": 1.0, "\U0001f600": "a", "\ue000": "b"}
    descriptor = {
        "schema_version": "knowledge.source.v1",
        **item,
        "source_version": "v1",
        "workspace_snapshot": snapshot,
    }
    assert (
        knowledge_source_digest(item, snapshot)
        == hashlib.sha256(rfc8785.dumps(descriptor)).hexdigest()
    )
    assert knowledge_source_digest(
        {**item, "workspace": "water"}, snapshot
    ) != knowledge_source_digest(item, snapshot)
    with pytest.raises(ValueError):
        knowledge_source_digest(item, {**snapshot, "ratio": float("nan")})
