"""Remote (IAM-backed) authorization for the Knowledge API.

This module implements the ``remote`` deployment mode: every authorization
decision comes from a live IAM introspection response, and a network or
protocol failure closes the request — it never falls back to the local
registry.  The frozen consumer contract lives in
``openspec/changes/connect-knowledge-remote-iam/contract.md``; the validator
here follows the *observed* IAM reply shapes recorded during G0
(``.local/iam-acceptance/<run>/g0-probes``).

Design rules enforced here:

* strict typed validation: wrong schema, wrong issuer/audience, non-UUID ids,
  boolean JSON where an integer is required, missing fields, unknown fields —
  all reject the subject (or the deployment fails at startup for config);
* human and service accounts are validated by *separate* functions: a machine
  reply must carry ``user/session/membership/revisions = null`` and must not be
  coerced into the human shape (and vice versa);
* ``active=true`` is authentication, not resource permission: knowledge
  libraries are derived from exact ``knowledge:lib:<code>:read`` codes combined
  with the explicit ``(tenant UUID, resource code) -> workspace`` mapping and
  the technical readiness directory;
* no positive authorization is cached across requests — metadata like the
  prepared statement cache is allowed, decisions are not;
* the total introspection budget defaults to 500 ms including queueing,
  connecting and reading; failures are bounded and never retried
  automatically.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass, replace
from pathlib import Path

import httpx

from env_rag_final.access.auth import (
    AuthContext,
    Forbidden,
    NotAvailable,
    Unauthenticated,
)

INTROSPECT_PATH = "/v1/internal/identity/introspect"
AUDIENCE = "knowledge"

HUMAN_SCHEMA = "iam.identity.v1"
MACHINE_SCHEMA = "iam.introspection.v1"

RESOURCE_READ_RE = re.compile(r"^knowledge:lib:(?P<code>[a-z][a-z0-9_-]{1,31}):read$")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_CREDENTIAL_ID_RE = re.compile(r"^sak_[0-9a-f]{32}$")

DEFAULT_DEADLINE_SECONDS = 0.5


class RemoteUnavailable(NotAvailable):
    """IAM, or the configured dependency, is not usable right now → 503.

    Distinguished from an authorization decision so that a service failure is
    never disguised as a logout (contract: 网络/协议错误、超时以 503 关闭).
    """

    status = 503
    code = "upstream_unavailable"


class IdentityRejected(Unauthenticated):
    """The IAM said the subject is invalid, or the reply failed strict checks."""


class RemoteProtocolError(RemoteUnavailable):
    """IAM answered with a malformed body or an unexpected status."""


def _is_uuid(value: object) -> bool:
    return isinstance(value, str) and bool(_UUID_RE.match(value))


def _is_int(value: object) -> bool:
    # bool is a subclass of int in Python and MUST NOT pass as an integer.
    return isinstance(value, int) and not isinstance(value, bool)


def _require(container: dict, key: str, where: str):
    if key not in container:
        raise IdentityRejected(f"{where}: missing field {key!r}")
    return container[key]


def _require_str(container: dict, key: str, where: str) -> str:
    value = _require(container, key, where)
    if not isinstance(value, str) or not value:
        raise IdentityRejected(f"{where}: field {key!r} must be a non-empty string")
    return value


def _require_int(container: dict, key: str, where: str, *, minimum: int = 0) -> int:
    value = _require(container, key, where)
    if not _is_int(value) or value < minimum:
        raise IdentityRejected(f"{where}: field {key!r} must be an integer >= {minimum}")
    return value


def _require_ts(container: dict, key: str, where: str) -> str:
    value = _require(container, key, where)
    if not isinstance(value, str) or not value:
        raise IdentityRejected(f"{where}: field {key!r} must be a timestamp string")
    return value


def _parse_ts(value: str) -> float | None:
    from datetime import datetime

    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
        return dt.timestamp() if dt.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


class RemoteDeadlineError(RemoteUnavailable):
    """The IAM call exceeded its total budget."""


# ---------------------------------------------------------------------------
# normalised identity
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RemoteIdentity:
    """Non-secret, immutable projection of a validated IAM reply.

    Deliberately excludes the raw subject token: that value lives only in the
    server-side session store (or in the single in-flight Bearer header), never
    in a context, a record or a log.
    """

    principal_type: str  # "human" | "service_account"
    principal_id: str
    tenant_id: str
    tenant_code: str
    permissions: frozenset[str]
    context_version: int | None
    revisions: dict | None
    session_id: str | None
    credential_id: str | None
    credential_revision: int | None
    audience: str
    issuer: str
    evaluated_at: str | None
    raw_digest: str
    context_usable: bool = True
    needs_tenant_selection: bool = False
    service_account_revision: int | None = None
    # Delegated knowledge identity (single-operation short-lived user delegation).
    # The random token id/expiry are deliberately excluded from auth_binding so
    # re-signing a new token for the same source session keeps record ownership.
    delegation: dict | None = None
    delegation_operation: str | None = None

    def workspace_grants(self) -> dict[str, str]:
        """Exact resource → library-code grants parsed from permissions."""
        grants: dict[str, str] = {}
        for code in self.permissions:
            m = RESOURCE_READ_RE.match(code)
            if m:
                grants[f"knowledge:lib:{m.group('code')}"] = m.group("code")
        return grants

    def as_dict(self) -> dict:
        return {
            "principal_type": self.principal_type,
            "principal_id": self.principal_id,
            "tenant_id": self.tenant_id,
            "tenant_code": self.tenant_code,
            "permissions": sorted(self.permissions),
            "context_version": self.context_version,
            "session_id": self.session_id,
            "credential_id": self.credential_id,
            "credential_revision": self.credential_revision,
        }


# ---------------------------------------------------------------------------
# strict validators
# ---------------------------------------------------------------------------

_HUMAN_IDENTITY_KEYS = {
    "schema_version",
    "active",
    "issuer",
    "audience",
    "principal",
    "user",
    "session",
    "current_tenant",
    "membership",
    "platform_roles",
    "tenant_roles",
    "permissions",
    "revisions",
    "context_version",
    "platform_admin",
    "context_usable",
    "needs_tenant_selection",
    "evaluated_at",
}
_MACHINE_IDENTITY_KEYS = {
    "schema_version",
    "active",
    "issuer",
    "audience",
    "principal",
    "user",
    "session",
    "membership",
    "current_tenant",
    "permissions",
    "service_account_revision",
    "credential_id",
    "credential_revision",
    "credential_expires_at",
    "overlap_until",
    "revisions",
    "evaluated_at",
}
_INACTIVE_KEYS = {"schema_version", "active", "reason", "evaluated_at"}


def _reject_unknown_keys(payload: dict, allowed: set[str], where: str) -> None:
    extra = set(payload) - allowed
    if extra:
        raise IdentityRejected(f"{where}: unexpected fields {sorted(extra)}")
    missing = allowed - set(payload)
    if missing:
        raise IdentityRejected(f"{where}: missing fields {sorted(missing)}")


def _validate_common(payload: dict) -> None:
    """Validate shared typed nested objects and timestamp representation."""
    _reject_unknown_keys(payload["principal"], {"type", "id", "realm"}, "principal")
    stamp = payload.get("evaluated_at")
    if not isinstance(stamp, str) or _parse_ts(stamp) is None:
        raise IdentityRejected("invalid evaluated_at")
    tenant = payload.get("current_tenant")
    if tenant is not None:
        if not isinstance(tenant, dict):
            raise IdentityRejected("invalid tenant")
        _reject_unknown_keys(tenant, {"id", "code", "name", "status"}, "tenant")
        _require_str(tenant, "code", "tenant")
        if not isinstance(tenant["name"], str):
            raise IdentityRejected("invalid tenant name")


def validate_human_identity(
    payload: dict, *, expected_issuer: str, expected_audience: str = AUDIENCE
) -> RemoteIdentity:
    """Validate an ``iam.identity.v1`` human reply.

    ``context_usable=false`` (未选择企业) is a *successful* reply that grants
    nothing: the caller must reject the request with 403, not treat it as a
    protocol error.
    """
    if not isinstance(payload, dict):
        raise IdentityRejected("human identity: payload must be an object")
    _reject_unknown_keys(payload, _HUMAN_IDENTITY_KEYS, "human identity")
    where = "human identity"
    if payload["schema_version"] != HUMAN_SCHEMA:
        raise IdentityRejected(f"{where}: unexpected schema_version")
    if payload["active"] is not True:
        raise IdentityRejected(f"{where}: active must be true here")
    issuer = _require_str(payload, "issuer", where)
    if issuer != expected_issuer:
        raise IdentityRejected(f"{where}: issuer mismatch")
    audience = _require_str(payload, "audience", where)
    if audience != expected_audience:
        raise IdentityRejected(f"{where}: audience mismatch")

    principal = _require(payload, "principal", where)
    if not isinstance(principal, dict) or principal.get("type") != "human":
        raise IdentityRejected(f"{where}: principal.type must be 'human'")
    if principal.get("realm") != "workforce":
        raise IdentityRejected(f"{where}: principal.realm must be 'workforce'")
    principal_id = principal.get("id")
    if not _is_uuid(principal_id):
        raise IdentityRejected(f"{where}: principal.id must be a UUID")

    _validate_common(payload)
    user = _require(payload, "user", where)
    if not isinstance(user, dict):
        raise IdentityRejected(f"{where}: user must be an object")
    _reject_unknown_keys(user, {"id", "account", "display_name", "status"}, "user")
    _require_str(user, "account", "user")
    if not isinstance(user["display_name"], str):
        raise IdentityRejected("invalid display name")
    if user.get("id") != principal_id:
        raise IdentityRejected(f"{where}: user.id must equal principal.id")
    if user.get("status") != "active":
        raise IdentityRejected(f"{where}: user.status must be 'active'")

    session = _require(payload, "session", where)
    if not isinstance(session, dict):
        raise IdentityRejected(f"{where}: session must be an object")
    _reject_unknown_keys(
        session,
        {"id", "ctx_version", "created_at", "expires_at", "absolute_expires_at", "idle_expires_at"},
        "session",
    )
    for field in ("created_at", "expires_at", "absolute_expires_at", "idle_expires_at"):
        value = session[field]
        if value is None and field == "idle_expires_at":
            continue
        if not isinstance(value, str) or _parse_ts(value) is None:
            raise IdentityRejected("invalid session timestamp")
        if field != "created_at" and _parse_ts(value) <= time.time():
            raise IdentityRejected("expired session")
    if not isinstance(payload["platform_admin"], bool):
        raise IdentityRejected("platform_admin must be boolean")
    session_id = session.get("id")
    if not _is_uuid(session_id):
        raise IdentityRejected(f"{where}: session.id must be a UUID")
    ctx_version = _require_int(payload, "context_version", where, minimum=1)
    session_ctx = _require_int(session, "ctx_version", where, minimum=1)
    if session_ctx != ctx_version:
        raise IdentityRejected(f"{where}: context_version != session.ctx_version")

    revisions = _require(payload, "revisions", where)
    if not isinstance(revisions, dict):
        raise IdentityRejected(f"{where}: revisions must be an object")
    _reject_unknown_keys(
        revisions,
        {
            "user_auth_revision",
            "tenant_auth_revision",
            "membership_revision",
            "session_ctx_version",
        },
        "revisions",
    )
    for key in (
        "user_auth_revision",
        "tenant_auth_revision",
        "membership_revision",
        "session_ctx_version",
    ):
        _require_int(revisions, key, where, minimum=0)
    if revisions["session_ctx_version"] != ctx_version:
        raise IdentityRejected(f"{where}: revisions.session_ctx_version mismatch")

    # A human who has not selected an enterprise yet is a *valid* identity that
    # carries no usable context: the caller distinguishes "needs selection"
    # (403 with guidance) from "usable context" (proceed).
    usable = payload.get("context_usable")
    needs_selection = payload.get("needs_tenant_selection")
    if not isinstance(usable, bool) or not isinstance(needs_selection, bool):
        raise IdentityRejected(f"{where}: usability flags must be booleans")
    if needs_selection:
        if usable:
            raise IdentityRejected(f"{where}: needs_tenant_selection with a usable context")
        if payload.get("current_tenant") is not None or payload.get("membership") is not None:
            raise IdentityRejected(f"{where}: selection pending but tenant context present")
        if payload.get("tenant_roles"):
            raise IdentityRejected(f"{where}: selection pending but tenant roles present")

    tenant = payload.get("current_tenant")
    if usable:
        if not isinstance(tenant, dict):
            raise IdentityRejected(f"{where}: current_tenant must be an object")
        tenant_id = tenant.get("id")
        if not _is_uuid(tenant_id):
            raise IdentityRejected(f"{where}: current_tenant.id must be a UUID")
        if tenant.get("status") != "active":
            raise IdentityRejected(f"{where}: current_tenant.status must be 'active'")

        membership = _require(payload, "membership", where)
        if not isinstance(membership, dict):
            raise IdentityRejected(f"{where}: membership must be an object")
        if not _is_uuid(membership.get("id")):
            raise IdentityRejected(f"{where}: membership.id must be a UUID")
        if membership.get("tenant_id") != tenant_id:
            raise IdentityRejected(f"{where}: membership.tenant_id mismatch")
        if membership.get("status") != "active":
            raise IdentityRejected(f"{where}: membership.status must be 'active'")
        _reject_unknown_keys(
            membership, {"id", "tenant_id", "department_id", "status", "revision"}, "membership"
        )
        if membership["department_id"] is not None and not _is_uuid(membership["department_id"]):
            raise IdentityRejected("invalid department id")
        _require_int(membership, "revision", where, minimum=1)
        if membership["revision"] != revisions["membership_revision"]:
            raise IdentityRejected("membership revision mismatch")
    else:
        if tenant is not None:
            raise IdentityRejected(f"{where}: unusable context must not carry a tenant")
        tenant_id = None

    permissions = _require(payload, "permissions", where)
    if not isinstance(permissions, list) or not all(isinstance(x, str) and x for x in permissions):
        raise IdentityRejected(f"{where}: permissions must be a list of strings")
    for key in ("platform_roles", "tenant_roles"):
        if not isinstance(payload[key], list):
            raise IdentityRejected("roles must be arrays")
        for role in payload[key]:
            if not isinstance(role, dict):
                raise IdentityRejected("invalid role")
            _reject_unknown_keys(role, {"code", "name"}, "role")
            if not isinstance(role["name"], str):
                raise IdentityRejected("invalid role name")
    for item in payload.get("platform_roles") or []:
        if not isinstance(item, dict) or not isinstance(item.get("code"), str):
            raise IdentityRejected(f"{where}: platform_roles entries must be objects")
    for item in payload.get("tenant_roles") or []:
        if not isinstance(item, dict) or not isinstance(item.get("code"), str):
            raise IdentityRejected(f"{where}: tenant_roles entries must be objects")

    return RemoteIdentity(
        principal_type="human",
        principal_id=principal_id,
        tenant_id=tenant_id,
        tenant_code=str(tenant.get("code") or "") if isinstance(tenant, dict) else "",
        permissions=frozenset(permissions),
        context_version=ctx_version,
        revisions={k: int(v) for k, v in revisions.items()},
        session_id=session_id,
        credential_id=None,
        credential_revision=None,
        audience=audience,
        issuer=issuer,
        evaluated_at=payload.get("evaluated_at")
        if isinstance(payload.get("evaluated_at"), str)
        else None,
        raw_digest=hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
        context_usable=usable,
        needs_tenant_selection=needs_selection,
    )


def validate_machine_identity(
    payload: dict, *, expected_issuer: str, expected_audience: str = AUDIENCE
) -> RemoteIdentity:
    """Validate an ``iam.introspection.v1`` service-account reply."""
    if not isinstance(payload, dict):
        raise IdentityRejected("machine identity: payload must be an object")
    _reject_unknown_keys(payload, _MACHINE_IDENTITY_KEYS, "machine identity")
    where = "machine identity"
    if payload["schema_version"] != MACHINE_SCHEMA:
        raise IdentityRejected(f"{where}: unexpected schema_version")
    if payload["active"] is not True:
        raise IdentityRejected(f"{where}: active must be true here")
    issuer = _require_str(payload, "issuer", where)
    if issuer != expected_issuer:
        raise IdentityRejected(f"{where}: issuer mismatch")
    audience = _require_str(payload, "audience", where)
    if audience != expected_audience:
        raise IdentityRejected(f"{where}: audience mismatch")

    principal = _require(payload, "principal", where)
    if not isinstance(principal, dict) or principal.get("type") != "service_account":
        raise IdentityRejected(f"{where}: principal.type must be 'service_account'")
    if principal.get("realm") != "service":
        raise IdentityRejected(f"{where}: principal.realm must be 'service'")
    principal_id = principal.get("id")
    if not _is_uuid(principal_id):
        raise IdentityRejected(f"{where}: principal.id must be a UUID")

    _validate_common(payload)
    # Machines have no session, no membership and no four-revision tuple; a
    # reply carrying any of them is not a machine identity and MUST NOT be
    # coerced into one.
    for key in ("user", "session", "membership", "revisions"):
        if payload.get(key) is not None:
            raise IdentityRejected(f"{where}: {key} must be null for service accounts")

    tenant = _require(payload, "current_tenant", where)
    if not isinstance(tenant, dict):
        raise IdentityRejected(f"{where}: current_tenant must be an object")
    tenant_id = tenant.get("id")
    if not _is_uuid(tenant_id):
        raise IdentityRejected(f"{where}: current_tenant.id must be a UUID")
    if tenant.get("status") != "active":
        raise IdentityRejected(f"{where}: current_tenant.status must be 'active'")

    _require_int(payload, "service_account_revision", where, minimum=1)
    credential_id = _require_str(payload, "credential_id", where)
    if not _CREDENTIAL_ID_RE.match(credential_id):
        raise IdentityRejected(f"{where}: credential_id has an unexpected format")
    _require_int(payload, "credential_revision", where, minimum=1)
    expires_at = _require_ts(payload, "credential_expires_at", where)
    expires_ts = _parse_ts(expires_at)
    if expires_ts is None:
        raise IdentityRejected(f"{where}: credential_expires_at must parse")
    if expires_ts <= time.time():
        raise IdentityRejected(f"{where}: credential already expired")
    overlap = payload.get("overlap_until")
    if overlap is not None:
        if not isinstance(overlap, str):
            raise IdentityRejected(f"{where}: overlap_until must be a string or null")
        if _parse_ts(overlap) is None:
            raise IdentityRejected(f"{where}: overlap_until must parse")

    permissions = _require(payload, "permissions", where)
    if not isinstance(permissions, list) or not all(isinstance(x, str) and x for x in permissions):
        raise IdentityRejected(f"{where}: permissions must be a list of strings")

    return RemoteIdentity(
        service_account_revision=payload["service_account_revision"],
        principal_type="service_account",
        principal_id=principal_id,
        tenant_id=tenant_id,
        tenant_code=str(tenant.get("code") or ""),
        permissions=frozenset(permissions),
        context_version=None,
        revisions=None,
        session_id=None,
        credential_id=credential_id,
        credential_revision=int(payload["credential_revision"]),
        audience=audience,
        issuer=issuer,
        evaluated_at=payload.get("evaluated_at")
        if isinstance(payload.get("evaluated_at"), str)
        else None,
        raw_digest=hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
    )


def validate_inactive(payload: dict) -> str:
    """Validate the ``active=false`` envelope and return its reason code."""
    if not isinstance(payload, dict):
        raise RemoteProtocolError("inactive envelope: payload must be an object")
    _reject_unknown_keys(payload, _INACTIVE_KEYS, "inactive envelope")
    if payload["schema_version"] != MACHINE_SCHEMA:
        raise IdentityRejected("inactive envelope: unexpected schema_version")
    if payload["active"] is not False:
        raise IdentityRejected("inactive envelope: active must be false")
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason:
        raise IdentityRejected("inactive envelope: reason must be a non-empty string")
    return reason


# --- knowledge user delegation -------------------------------------------

DELEGATION_SCHEMA = "iam.knowledge-delegation-introspection.v1"
DELEGATION_OPERATIONS = ("query", "record:read", "source:read", "document:read")
_DELEGATION_KEYS = {
    "schema_version",
    "active",
    "issuer",
    "audience",
    "operation",
    "identity",
    "delegation",
    "evaluated_at",
}
_DELEGATION_SOURCE_KEYS = {
    "issuing_client_id",
    "source_audience",
    "source_session_id",
    "operation",
    "expires_at",
}


def validate_delegation_inactive(payload: dict) -> str:
    """Validate the delegated inactive envelope (HTTP 200) and return its reason."""
    if not isinstance(payload, dict):
        raise RemoteProtocolError("delegation inactive: payload must be an object")
    _reject_unknown_keys(payload, _INACTIVE_KEYS, "delegation inactive")
    if payload["schema_version"] != DELEGATION_SCHEMA:
        raise RemoteProtocolError("delegation inactive: unexpected schema_version")
    if payload["active"] is not False:
        raise RemoteProtocolError("delegation inactive: active must be false")
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason:
        raise RemoteProtocolError("delegation inactive: reason must be a non-empty string")
    return reason


def validate_knowledge_delegation(
    payload: dict,
    *,
    expected_issuer: str,
    expected_operation: str,
    expected_audience: str = AUDIENCE,
) -> RemoteIdentity:
    """Strictly validate a delegated knowledge introspection reply.

    The nested ``identity`` uses the frozen ``iam.identity.v1`` human shape; the
    outer envelope additionally binds the single operation and the issuing
    Agent client.  A reply whose operation differs from the requested one is a
    protocol/authorization failure, never a usable identity.
    """
    if not isinstance(payload, dict):
        raise RemoteProtocolError("delegation identity: payload must be an object")
    _reject_unknown_keys(payload, _DELEGATION_KEYS, "delegation identity")
    where = "delegation identity"
    if payload["schema_version"] != DELEGATION_SCHEMA:
        raise RemoteProtocolError(f"{where}: unexpected schema_version")
    if payload["active"] is not True:
        raise RemoteProtocolError(f"{where}: active must be true here")
    if _require_str(payload, "issuer", where) != expected_issuer:
        raise RemoteProtocolError(f"{where}: issuer mismatch")
    if _require_str(payload, "audience", where) != expected_audience:
        raise RemoteProtocolError(f"{where}: audience mismatch")
    operation = _require_str(payload, "operation", where)
    if operation not in DELEGATION_OPERATIONS:
        raise RemoteProtocolError(f"{where}: unsupported operation")
    if expected_operation is None:
        raise Forbidden("delegated credential requires an operation", code="operation_required")
    if operation != expected_operation:
        raise Forbidden(
            "delegated operation does not match this endpoint", code="operation_mismatch"
        )
    if _parse_ts(_require_ts(payload, "evaluated_at", where)) is None:
        raise RemoteProtocolError(f"{where}: invalid evaluated_at")

    delegation = payload.get("delegation")
    if not isinstance(delegation, dict):
        raise RemoteProtocolError(f"{where}: delegation missing")
    _reject_unknown_keys(delegation, _DELEGATION_SOURCE_KEYS, "delegation source")
    _require_str(delegation, "issuing_client_id", "delegation source")
    if delegation["source_audience"] != "langgraph-runtime":
        raise RemoteProtocolError("delegation source: unexpected source_audience")
    if delegation["operation"] != operation:
        raise RemoteProtocolError("delegation source: operation mismatch")
    if not _is_uuid(delegation.get("source_session_id")):
        raise RemoteProtocolError("delegation source: invalid source_session_id")
    if _parse_ts(_require_ts(delegation, "expires_at", "delegation source")) is None:
        raise RemoteProtocolError("delegation source: invalid expires_at")

    identity_payload = payload.get("identity")
    if not isinstance(identity_payload, dict):
        raise RemoteProtocolError(f"{where}: identity missing")
    identity = validate_human_identity(
        identity_payload, expected_issuer=expected_issuer, expected_audience=expected_audience
    )
    if identity.session_id != delegation["source_session_id"]:
        raise RemoteProtocolError("delegation identity: session does not match source")
    # The IAM projection must contain only knowledge read codes for delegations.
    if any(not RESOURCE_READ_RE.match(code) for code in identity.permissions):
        raise RemoteProtocolError("delegation identity: non-knowledge permission leaked")
    if not identity.permissions:
        raise Forbidden("delegation grants no knowledge library", code="no_workspace")
    return replace(
        identity,
        delegation={
            "issuing_client_id": delegation["issuing_client_id"],
            "source_audience": delegation["source_audience"],
            "source_session_id": delegation["source_session_id"],
            "operation": operation,
            "expires_at": delegation["expires_at"],
        },
        delegation_operation=operation,
    )


def validate_verified(payload: dict) -> int:
    """Validate the ``active=true`` verified re-check envelope."""
    _reject_unknown_keys(payload, _INACTIVE_KEYS, "verified envelope")
    if payload["schema_version"] != MACHINE_SCHEMA:
        raise RemoteProtocolError("verified envelope: unexpected schema_version")
    if payload["active"] is not True:
        raise RemoteProtocolError("verified envelope: active must be true")
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason:
        raise RemoteProtocolError("verified envelope: reason must be a non-empty string")
    return 200


def validate_payload(
    payload: dict,
    *,
    expected_issuer: str,
    expected_audience: str = AUDIENCE,
    expected_operation: str | None = None,
) -> RemoteIdentity:
    """Dispatch to the human, machine, or delegation validator by schema."""
    if not isinstance(payload, dict):
        raise RemoteProtocolError("introspection reply must be a JSON object")
    schema = payload.get("schema_version")
    if schema == HUMAN_SCHEMA:
        return validate_human_identity(
            payload, expected_issuer=expected_issuer, expected_audience=expected_audience
        )
    if schema == DELEGATION_SCHEMA:
        if payload.get("active") is False:
            reason = validate_delegation_inactive(payload)
            raise IdentityRejected(f"delegation is not active ({reason})")
        return validate_knowledge_delegation(
            payload,
            expected_issuer=expected_issuer,
            expected_operation=expected_operation,
            expected_audience=expected_audience,
        )
    if schema == MACHINE_SCHEMA:
        if payload.get("active") is False:
            reason = validate_inactive(payload)
            raise IdentityRejected(f"subject is not active ({reason})")
        return validate_machine_identity(
            payload, expected_issuer=expected_issuer, expected_audience=expected_audience
        )
    raise RemoteProtocolError(f"unknown schema_version {schema!r}")


# ---------------------------------------------------------------------------
# explicit mapping and technical readiness
# ---------------------------------------------------------------------------


def parse_mapping(payload: dict) -> dict[str, dict[str, str]]:
    """Parse the explicit ``(tenant UUID, resource code) -> workspace`` map.

    Only literal tenant UUIDs are accepted as keys; ``all``/``default`` and
    anything that is not a UUID fail at load time so that a wildcard can never
    silently appear later.
    """
    if not isinstance(payload, dict):
        raise ValueError("mapping must be an object")
    tenants = payload.get("tenants")
    if not isinstance(tenants, dict) or not tenants:
        raise ValueError("mapping.tenants must be a non-empty object")
    out: dict[str, dict[str, str]] = {}
    for tenant_key, entries in tenants.items():
        if not _is_uuid(tenant_key):
            raise ValueError(f"mapping tenant key {tenant_key!r} is not a UUID")
        if tenant_key.lower() in ("all", "default"):
            raise ValueError("mapping must not use reserved tenant names")
        if not isinstance(entries, dict) or not entries:
            raise ValueError(f"mapping for tenant {tenant_key} must be a non-empty object")
        resolved: dict[str, str] = {}
        for resource, workspace in entries.items():
            if not isinstance(resource, str) or not re.fullmatch(
                r"knowledge:lib:[a-z][a-z0-9_-]{1,31}", resource
            ):
                raise ValueError(f"mapping resource {resource!r} is not a knowledge library")
            if resource in resolved:
                raise ValueError(f"mapping resource {resource!r} declared twice")
            if not isinstance(workspace, str) or not re.fullmatch(
                r"[a-z][a-z0-9_-]{1,31}", workspace
            ):
                raise ValueError(f"mapping workspace {workspace!r} is not a stable id")
            if workspace in ("default", "all"):
                raise ValueError(f"mapping workspace {workspace!r} is reserved")
            resolved[resource] = workspace
        out[tenant_key] = resolved
    return out


# ---------------------------------------------------------------------------
# provider
# ---------------------------------------------------------------------------


@dataclass
class RemoteConfig:
    iam_url: str
    issuer: str
    client_id: str
    client_secret: str
    mapping: dict[str, dict[str, str]]
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS
    audience: str = AUDIENCE
    sso_client_id: str | None = None
    sso_client_secret: str | None = None
    sso_callback: str | None = None

    @staticmethod
    def from_env(values: dict) -> "RemoteConfig":
        """Build the config from values, failing closed on anything missing."""

        def required(key: str) -> str:
            value = values.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"remote mode requires {key}")
            return value.strip()

        iam_url = required("ENV_RAG_IAM_URL")
        if not iam_url.startswith("http://") and not iam_url.startswith("https://"):
            raise ValueError("ENV_RAG_IAM_URL must be an http(s) URL")
        issuer = required("ENV_RAG_IAM_ISSUER")
        client_id = required("ENV_RAG_IAM_CLIENT_ID")
        client_secret = required("ENV_RAG_IAM_CLIENT_SECRET")
        mapping_path = required("ENV_RAG_IAM_MAPPING")
        mapping_file = Path(mapping_path)
        if not mapping_file.is_file():
            raise ValueError(f"ENV_RAG_IAM_MAPPING not found: {mapping_path}")
        mapping = parse_mapping(json.loads(mapping_file.read_text(encoding="utf-8")))
        deadline_raw = values.get("ENV_RAG_IAM_DEADLINE_SECONDS")
        deadline = DEFAULT_DEADLINE_SECONDS
        if deadline_raw not in (None, ""):
            try:
                deadline = float(deadline_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError("ENV_RAG_IAM_DEADLINE_SECONDS must be a number") from exc
            if not 0 < deadline <= 5:
                raise ValueError("ENV_RAG_IAM_DEADLINE_SECONDS must be within (0, 5]")
        sso_id = values.get("ENV_RAG_SSO_CLIENT_ID") or None
        sso_secret = values.get("ENV_RAG_SSO_CLIENT_SECRET") or None
        sso_callback = values.get("ENV_RAG_SSO_CALLBACK") or None
        return RemoteConfig(
            iam_url=iam_url.rstrip("/"),
            issuer=issuer,
            client_id=client_id,
            client_secret=client_secret,
            mapping=mapping,
            deadline_seconds=deadline,
            sso_client_id=sso_id.strip() if isinstance(sso_id, str) else None,
            sso_client_secret=sso_secret.strip() if isinstance(sso_secret, str) else None,
            sso_callback=sso_callback.strip() if isinstance(sso_callback, str) else None,
        )


class IamClient:
    """HTTP client for the IAM introspection endpoint.

    Mirrors the IAM's own intake semantics (``InternalClientAuthenticator``):
    an opaque ``Bearer`` credential, the live database check on every call, no
    positive authorization caching and no automatic retries beyond the
    bounded IAM request itself.
    """

    def __init__(self, config: RemoteConfig, *, transport=None, timeout: float | None = None):
        self.config = config
        self._timeout = timeout if timeout is not None else config.deadline_seconds
        self._client = httpx.AsyncClient(
            base_url=config.iam_url,
            timeout=httpx.Timeout(self._timeout, connect=min(self._timeout, 0.3)),
            transport=transport,
            headers={
                "Authorization": f"Bearer {config.client_secret}",
                "Content-Type": "application/json",
            },
        )
        self.calls = 0

    async def aclose(self) -> None:
        await self._client.aclose()

    async def introspect(
        self,
        subject_token: str,
        *,
        audience: str | None = None,
        operation: str | None = None,
    ) -> dict:
        """One introspection round-trip with a hard total deadline.

        ``operation`` is only sent for delegated tokens (``kdl_`` prefix); plain
        human tokens must keep the original request shape, otherwise the IAM
        rejects the request as an unsupported field combination.
        """
        if not isinstance(subject_token, str) or not subject_token.strip():
            raise IdentityRejected("credentials required")
        self.calls += 1
        body = {"subject_token": subject_token, "audience": audience or self.config.audience}
        if operation is not None and subject_token.startswith("kdl_"):
            body["operation"] = operation
        try:
            async with asyncio.timeout(self._timeout):
                response = await self._client.post(INTROSPECT_PATH, json=body)
        except TimeoutError as exc:
            raise RemoteDeadlineError("identity check timed out") from exc
        except httpx.HTTPError as exc:
            raise RemoteUnavailable("identity service unreachable") from exc
        if response.status_code == 401:
            # The consumer's own internal-client credential was refused: this is
            # a deployment fault, not the end user's fault → 503.
            raise RemoteUnavailable("consumer client authentication failed")
        if response.status_code == 403:
            raise RemoteUnavailable("consumer client is not authorized for this audience")
        if response.status_code == 409:
            raise ConflictError("context changed")
        if response.status_code != 200:
            raise RemoteProtocolError(f"identity service replied HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise RemoteProtocolError("identity service replied with invalid JSON") from exc
        if not isinstance(payload, dict):
            raise RemoteProtocolError("identity service replied with a non-object")
        return payload

    async def _human_call(
        self,
        method: str,
        path: str,
        *,
        subject_token: str | None = None,
        body: dict | None = None,
        expect=(200,),
        require_body: bool = True,
        extra_headers: dict | None = None,
    ):
        """One human-session round-trip (login / switch / tenants / logout)."""
        self.calls += 1
        headers = dict(extra_headers or {})
        if subject_token:
            headers["Authorization"] = f"Bearer {subject_token}"
        try:
            async with asyncio.timeout(self._timeout):
                response = await self._client.request(method, path, json=body, headers=headers)
        except TimeoutError as exc:
            raise RemoteDeadlineError("identity service timed out") from exc
        except httpx.HTTPError as exc:
            raise RemoteUnavailable("identity service unreachable") from exc
        if response.status_code in (401, 403) and path == "/v1/internal/sso/exchange":
            raise RemoteUnavailable("SSO client authentication failed")
        if response.status_code in (401, 403):
            raise IdentityRejected("identity rejected the credential")
        if response.status_code == 409:
            raise ConflictError("context changed")
        if response.status_code == 429:
            raise Forbidden("too many attempts", code="rate_limited")
        if response.status_code not in expect:
            raise RemoteProtocolError(
                f"identity service replied HTTP {response.status_code} for {path}"
            )
        if not require_body:
            return None
        try:
            payload = response.json()
        except ValueError as exc:
            raise RemoteProtocolError("identity service replied with invalid JSON") from exc
        return payload

    async def login_password(self, account: str, password: str, *, audience: str) -> dict:
        payload = await self._human_call(
            "POST",
            "/v1/auth/login",
            body={
                "account": account,
                "password": password,
                "realm": "workforce",
                "audience": audience,
            },
        )
        if not isinstance(payload, dict) or not payload.get("access_token"):
            raise RemoteProtocolError("login reply has no access token")
        return payload

    async def switch_tenant(
        self, subject_token: str, tenant_id: str, expected_ctx_version: object
    ) -> dict:
        if not isinstance(expected_ctx_version, int) or isinstance(expected_ctx_version, bool):
            raise Forbidden("expected_ctx_version is required", code="bad_context")
        payload = await self._human_call(
            "POST",
            "/v1/auth/switch-tenant",
            subject_token=subject_token,
            body={"tenant_id": tenant_id, "expected_ctx_version": expected_ctx_version},
        )
        return payload if isinstance(payload, dict) else {}

    async def list_tenants(self, subject_token: str) -> list:
        payload = await self._human_call("GET", "/v1/auth/tenants", subject_token=subject_token)
        return payload if isinstance(payload, list) else []

    async def logout(self, subject_token: str) -> None:
        await self._human_call(
            "POST", "/v1/auth/logout", subject_token=subject_token, require_body=False
        )

    async def sso_exchange(
        self, ticket: str, redirect_uri: str, state: str, *, audience: str
    ) -> dict:
        """Exchange an SSO ticket server-side (ticket/redirect_uri/state).

        The SSO client credential is a *separate* registration from the
        introspection client and is presented as its own Basic credential;
        the consumer never sends the browser's central-session cookie.
        """
        client_id = self.config.sso_client_id
        client_secret = self.config.sso_client_secret
        if not client_id or not client_secret:
            raise RemoteProtocolError("SSO client credential is not configured")
        import base64

        basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        payload = await self._human_call(
            "POST",
            "/v1/internal/sso/exchange",
            body={"ticket": ticket, "redirect_uri": redirect_uri, "state": state},
            extra_headers={"Authorization": f"Basic {basic}"},
        )
        if not isinstance(payload, dict):
            raise RemoteProtocolError("SSO exchange reply is not an object")
        return payload


class ConflictError(RemoteUnavailable):
    """The supplied context baseline no longer matches → 409."""

    status = 409
    code = "context_changed"


def _identity_to_context(
    identity: RemoteIdentity,
    workspaces: tuple[str, ...],
    *,
    registry_revision: str,
    directory_version: str,
    issued_at: float,
) -> AuthContext:
    return AuthContext(
        mode="remote",
        principal_type=identity.principal_type,
        principal_id=identity.principal_id,
        tenant_id=identity.tenant_id,
        tenant_code=identity.tenant_code,
        permissions=identity.permissions,
        context_version=identity.context_version,
        session_id=identity.session_id,
        credential_id=identity.credential_id,
        credential_revision=identity.credential_revision,
        workspaces=workspaces,
        policy_revision=registry_revision,
        directory_version=directory_version,
        issued_at=issued_at,
    )


def project_context_to_workspaces(
    ctx: AuthContext, workspaces: tuple[str, ...], *, issued_at: float | None = None
) -> AuthContext:
    """Narrow an authorized context to the workspaces actually used."""
    return replace(ctx, workspaces=workspaces, issued_at=issued_at or ctx.issued_at)


def can_reuse_context(ctx: AuthContext, identity: RemoteIdentity) -> bool:
    """Compare a fresh introspection with an existing context (no token read)."""
    if identity.principal_type != ctx.principal_type:
        return False
    if identity.principal_id != ctx.principal_id:
        return False
    if identity.tenant_id != ctx.tenant_id:
        return False
    if identity.context_version != ctx.context_version:
        return False
    if identity.session_id != ctx.session_id:
        return False
    if identity.credential_id != ctx.credential_id:
        return False
    if identity.credential_revision != ctx.credential_revision:
        return False
    return (
        identity.permissions == ctx.permissions
        and tuple(sorted((identity.revisions or {}).items())) == ctx.revisions
        and identity.service_account_revision == ctx.service_account_revision
        and identity.context_usable
        and not identity.needs_tenant_selection
    )
