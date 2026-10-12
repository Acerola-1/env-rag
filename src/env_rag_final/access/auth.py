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
    principal: Principal
    enterprise: str
    policy_revision: str
    workspaces: tuple[str, ...]
    issued_at: float

    @property
    def user_id(self) -> str:
        return self.principal.user_id

    def cache_key(self, *parts: object) -> tuple:
        """Identity prefix every cache/record key must carry."""
        return (
            self.principal.user_id,
            self.enterprise,
            self.policy_revision,
            self.workspaces,
            *parts,
        )

    def allows(self, ws_id: str) -> bool:
        return ws_id in self.workspaces

    def as_dict(self) -> dict:
        return {
            "user_id": self.principal.user_id,
            "display": self.principal.display,
            "enterprise": self.enterprise,
            "roles": list(self.principal.roles),
            "policy_revision": self.policy_revision,
            "workspaces": list(self.workspaces),
        }


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
        principal=principal,
        enterprise=principal.enterprise,
        policy_revision=registry.revision,
        workspaces=workspaces,
        issued_at=time.time(),
    )
