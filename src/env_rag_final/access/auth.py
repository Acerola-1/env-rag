"""Authentication and authorization for the Knowledge API.

Nothing reaches retrieval, a model or a file until :func:`authorize` returns
an immutable :class:`AuthContext`.  The client only ever expresses *intent*
(``workspace`` / ``workspaces`` / ``all``); the allowed set is always computed
from the server-owned registry, and an intent that contains any unknown or
ungranted workspace is rejected as a whole — never silently trimmed, never
fell back to ``default``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from env_rag_final.access.registry import Principal, Registry

ALL = "all"

_UNSET = object()
_DEFAULTS = {
    "mode": "local",
    "principal_type": "local",
    "principal_id": "",
    "tenant_id": "",
    "tenant_code": "",
    "permissions": frozenset(),
    "context_version": None,
    "session_id": None,
    "credential_id": None,
    "credential_revision": None,
    "workspaces": (),
    "issued_at": 0.0,
    "policy_revision": "",
    "directory_version": "",
    "revisions": (),
    "service_account_revision": None,
}

# HTTP status mapping contract:
#   401 unauthenticated / bad credentials
#   403 authenticated but not permitted (or a forbidden selection)
#   404 object id that is unknown or not reachable for this principal
STATUS_UNAUTHENTICATED = 401
STATUS_FORBIDDEN = 403
STATUS_NOT_FOUND = 404


class AccessError(Exception):
    """Base class carrying the HTTP status the gateway must return."""

    status = STATUS_FORBIDDEN
    code = "access_error"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        if code:
            self.code = code


class Unauthenticated(AccessError):
    status = STATUS_UNAUTHENTICATED
    code = "unauthenticated"


class Forbidden(AccessError):
    status = STATUS_FORBIDDEN
    code = "forbidden"


class NotAvailable(AccessError):
    """Object ids that do not exist or are not reachable by this principal.

    Used so that a cross-workspace probe cannot distinguish "exists but you
    cannot see it" from "does not exist".
    """

    status = STATUS_NOT_FOUND
    code = "not_available"


@dataclass(frozen=True)
class AuthContext:
    """Immutable, serialisable, non-secret authorization context.

    ``mode`` tells whether the deployment is local (registry principals and
    grants) or remote (IAM introspection).  The two modes share the same shape
    so that every downstream boundary (cache, records, sources, generation)
    applies one rule, but the identity fields differ in meaning:

    * ``mode="local"`` — ``principal_type`` is always ``"local"``,
      ``tenant_id`` is the registry enterprise, ``permissions`` is empty and
      ``context_version`` is ``None``.  Nothing changes for existing
      deployments.
    * ``mode="remote"`` — ``principal_type`` is ``"human"`` or
      ``"service_account"``, ``principal_id`` ``tenant_id`` come from the IAM
      reply, ``permissions`` holds the exact permission codes and
      ``context_version``/``revisions`` mirror the IAM authority snapshot.

    The raw IAM subject token is deliberately *not* part of this dataclass: it
    must never reach a record, a log or an export.
    """

    mode: str
    principal_type: str
    principal_id: str
    tenant_id: str
    tenant_code: str
    permissions: frozenset[str]
    context_version: int | None
    session_id: str | None
    credential_id: str | None
    credential_revision: int | None
    workspaces: tuple[str, ...]
    issued_at: float
    policy_revision: str = ""
    directory_version: str = ""
    revisions: tuple[tuple[str, int], ...] = ()
    service_account_revision: int | None = None

    def __init__(self, **kwargs):
        """Accept both the mode-aware fields and the legacy local shorthand.

        ``AuthContext(principal=..., enterprise=..., policy_revision=...,
        workspaces=..., issued_at=...)`` from existing local callers is
        translated into the explicit local form so that one context type
        serves both deployments without weakening either.
        """
        sentinel = _UNSET
        principal = kwargs.pop("principal", sentinel)
        enterprise = kwargs.pop("enterprise", sentinel)
        if enterprise is not sentinel and "tenant_id" not in kwargs:
            kwargs["tenant_id"] = enterprise
            kwargs.setdefault("tenant_code", enterprise or "")
        if principal is not sentinel:
            kwargs.setdefault("principal_type", "local")
            kwargs.setdefault("principal_id", principal.user_id)
            kwargs.setdefault("tenant_id", principal.enterprise)
            kwargs.setdefault("tenant_code", principal.enterprise)
            kwargs["permissions"] = frozenset(kwargs.get("permissions") or ())
            kwargs.setdefault("context_version", None)
            kwargs.setdefault("session_id", None)
            kwargs.setdefault("credential_id", None)
            kwargs.setdefault("credential_revision", None)
        fields = (
            "mode",
            "principal_type",
            "principal_id",
            "tenant_id",
            "tenant_code",
            "permissions",
            "context_version",
            "session_id",
            "credential_id",
            "credential_revision",
            "workspaces",
            "issued_at",
            "policy_revision",
            "directory_version",
            "revisions",
            "service_account_revision",
        )
        unknown = set(kwargs) - set(fields)
        if unknown:
            raise TypeError(f"AuthContext got unexpected fields {sorted(unknown)}")
        for name in fields:
            object.__setattr__(self, name, kwargs[name] if name in kwargs else _DEFAULTS[name])

    @property
    def principal(self) -> Principal:
        """Back-compat shim: the local registry principal when available."""
        raise AttributeError("principal is not carried by AuthContext; use principal_id")

    @property
    def user_id(self) -> str:
        return self.principal_id

    @property
    def enterprise(self) -> str:
        return self.tenant_id

    def cache_key(self, *parts: object) -> tuple:
        """Identity prefix every cache/record key must carry."""
        return (
            self.principal_id,
            self.tenant_id,
            self.policy_revision,
            self.mode,
            self.principal_type,
            self.directory_version,
            self.workspaces,
            tuple(sorted(self.permissions)),
            self.context_version,
            self.session_id,
            self.credential_id,
            self.credential_revision,
            self.revisions,
            self.service_account_revision,
            *parts,
        )

    def auth_binding(self) -> dict:
        """Exact, non-secret scope persisted with remote records."""
        result = self.identity_dict()
        result.pop("issued_at")
        result.pop("workspaces")
        return result

    def allows(self, ws_id: str) -> bool:
        return ws_id in self.workspaces

    def identity_dict(self) -> dict:
        """Non-secret identity projection (safe for records and JSON)."""
        return {
            "mode": self.mode,
            "principal_type": self.principal_type,
            "principal_id": self.principal_id,
            "tenant_id": self.tenant_id,
            "tenant_code": self.tenant_code,
            "permissions": sorted(self.permissions),
            "context_version": self.context_version,
            "session_id": self.session_id,
            "credential_id": self.credential_id,
            "credential_revision": self.credential_revision,
            "policy_revision": self.policy_revision,
            "directory_version": self.directory_version,
            "workspaces": list(self.workspaces),
            "issued_at": self.issued_at,
            "revisions": dict(self.revisions),
            "service_account_revision": self.service_account_revision,
        }

    def as_dict(self) -> dict:
        return self.identity_dict()


def resolve_selection(
    registry: Registry,
    allowed: tuple[str, ...],
    requested: object,
) -> tuple[str, ...]:
    """Turn a client selection intent into the effective workspace tuple.

    ``requested`` is one of: ``"all"``, a single workspace id, or an iterable
    of ids.  Unknown ids, ids outside the granted set, and empty selections are
    all errors — the whole request is refused.
    """
    if requested is None:
        raise Forbidden("workspace selection is required", code="workspace_required")

    if isinstance(requested, str):
        if requested == ALL:
            if not allowed:
                raise Forbidden(
                    "no knowledge library is granted to this principal",
                    code="no_workspace",
                )
            return tuple(allowed)
        candidates = [requested]
    else:
        candidates = list(requested)

    if not candidates:
        raise Forbidden("empty workspace selection", code="no_workspace")

    if ALL in candidates:
        if len(candidates) > 1:
            raise Forbidden("'all' cannot be combined with explicit ids", code="bad_selection")
        if not allowed:
            raise Forbidden(
                "no knowledge library is granted to this principal", code="no_workspace"
            )
        return tuple(allowed)

    known = set(registry.workspaces)
    effective: list[str] = []
    for ws_id in candidates:
        if not isinstance(ws_id, str) or ws_id not in known:
            # Do not reveal whether an unknown id exists elsewhere.
            raise Forbidden(f"unknown knowledge library {ws_id!r}", code="unknown_workspace")
        if ws_id not in allowed:
            raise Forbidden(
                f"not authorized for knowledge library {ws_id!r}",
                code="unauthorized_workspace",
            )
        if ws_id not in effective:
            effective.append(ws_id)
    if not effective:
        raise Forbidden("empty workspace selection", code="no_workspace")
    return tuple(effective)


def authenticate(
    registry: Registry,
    *,
    bearer_token: str | None = None,
    session_user: str | None = None,
) -> Principal:
    if session_user:
        principal = registry.principal(session_user)
        if principal is None:
            raise Unauthenticated("session principal no longer exists")
        return principal
    if bearer_token:
        principal = registry.principal_by_token(bearer_token)
        if principal is None:
            raise Unauthenticated("invalid credentials")
        return principal
    raise Unauthenticated("credentials required")


def authorize(
    registry: Registry,
    principal: Principal,
    requested: object,
) -> AuthContext:
    allowed = registry.allowed_workspaces(principal)
    workspaces = resolve_selection(registry, allowed, requested)
    return AuthContext(
        mode="local",
        principal_type="local",
        principal_id=principal.user_id,
        tenant_id=principal.enterprise,
        tenant_code=principal.enterprise,
        permissions=frozenset(),
        context_version=None,
        session_id=None,
        credential_id=None,
        credential_revision=None,
        workspaces=workspaces,
        policy_revision=registry.revision,
        directory_version=registry.revision,
        issued_at=time.time(),
    )
