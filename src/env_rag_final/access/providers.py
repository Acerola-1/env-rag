"""Authorization providers: ``local`` (registry) and ``remote`` (IAM).

The provider is chosen once at process start from ``ENV_RAG_AUTH_MODE`` and is
never re-chosen at request time.  A remote provider never consults registry
principals or grants for authorization, and never falls back to local on an
IAM failure; a local provider never issues an IAM request.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field, replace

from env_rag_final.access.auth import (
    ALL,
    AuthContext,
    Forbidden,
    NotAvailable,
    Unauthenticated,
    authenticate,
    authorize,
)
from env_rag_final.access.registry import Principal, Registry
from env_rag_final.access.remote import (
    IamClient,
    IdentityRejected,
    RemoteConfig,
    RemoteIdentity,
    RemoteProtocolError,
    RemoteUnavailable,
    can_reuse_context,
    validate_payload,
)


class AuthProviderError(Exception):
    """Configuration or wiring failure for the provider."""


@dataclass
class LocalProvider:
    """Registry-backed provider preserving the original local behaviour."""

    registry: Registry
    mode: str = "local"

    def principal_for_request(
        self, *, session_user: str | None = None, bearer_token: str | None = None
    ) -> Principal:
        return authenticate(self.registry, session_user=session_user, bearer_token=bearer_token)

    def authorize_request(self, principal: Principal, requested: object) -> AuthContext:
        return authorize(self.registry, principal, requested)

    def context_for_human_token(self, *args, **kwargs) -> AuthContext:  # pragma: no cover
        raise AuthProviderError("local mode has no IAM sessions")

    def as_public_dict(self) -> dict:
        return {"mode": "local", "registry_revision": self.registry.revision}


@dataclass
class RemoteProvider:
    """IAM-backed provider.

    ``authorize_token`` resolves one subject credential into a context limited
    to the explicit mapping intersection ``allowed ∩ mapped ∩ ready``.  A
    request that explicitly names an unknown or unmapped library is rejected as
    a whole — nothing is trimmed silently and no library name/count leaks.

    Human sessions keep the raw IAM subject token **only** in this in-memory
    store; the browser holds an application handle (cookie) and a CSRF token.
    Machines never get a session: their Bearer credential is re-checked on
    every request.
    """

    config: RemoteConfig
    registry: Registry
    iam: IamClient
    mode: str = "remote"
    directory_version: str = field(default="")
    session_ttl_seconds: int = 12 * 3600
    _sessions: dict = field(default_factory=dict, repr=False)

    # ---- session store ----------------------------------------------
    def session_for(self, session_id: str | None) -> dict | None:
        if not session_id:
            return None
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if time.time() - session["created_at"] > self.session_ttl_seconds:
            self._sessions.pop(session_id, None)
            return None
        return session

    def _new_session(self, identity: RemoteIdentity, subject_token: str, csrf: str) -> dict:
        import secrets as _secrets

        session = {
            "session_id": _secrets.token_urlsafe(32),
            "subject_token": subject_token,
            "csrf": csrf,
            "principal_id": identity.principal_id,
            "tenant": identity.tenant_id,
            "tenant_code": identity.tenant_code,
            "context_version": identity.context_version,
            "tenant_epoch": _secrets.token_urlsafe(16),
            "credentials_digest": hashlib.sha256(subject_token.encode()).hexdigest(),
            "tenants": [],
            "created_at": time.time(),
        }
        self._sessions[session["session_id"]] = session
        return session

    async def login_human(self, account: str, password: str) -> dict:
        """Exchange a password for an application session (server-side only)."""
        if not account or not password:
            raise Unauthenticated("credentials required")
        payload = await self.iam.login_password(account, password, audience=self.config.audience)
        return await self._materialise_session(payload)

    async def sso_exchange(self, ticket: str, redirect_uri: str, state: str) -> dict:
        payload = await self.iam.sso_exchange(
            ticket, redirect_uri, state, audience=self.config.audience
        )
        return await self._materialise_session(payload)

    # ---- SSO façade (contract §SSO) ---------------------------------
    def sso_authorize_url(self, *, client_id: str, redirect_uri: str, state: str) -> str:
        """Build the IAM authorize URL for a browser redirect (303 + ticket)."""
        from urllib.parse import quote, urlencode

        if not client_id or not redirect_uri or not state:
            raise AuthProviderError("SSO requires client_id, redirect_uri and state")
        query = urlencode(
            {"client_id": client_id, "redirect_uri": redirect_uri, "state": state},
            quote_via=quote,
        )
        return f"{self.config.iam_url}/v1/sso/authorize?{query}"

    async def sso_login(self, ticket: str, redirect_uri: str, state: str) -> dict:
        """Server-side exchange; the resulting token never reaches the page."""
        return await self.sso_exchange(ticket, redirect_uri, state)

    async def _materialise_session(self, login_payload: dict) -> dict:
        token = login_payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise RemoteProtocolError("IAM login reply has no access token")
        identity = await self.introspect(token)
        if identity.principal_type != "human":
            raise IdentityRejected("human login produced a non-human identity")
        session = self._new_session(identity, token, secrets.token_urlsafe(32))
        session["display"] = (login_payload.get("identity") or {}).get("user", {}).get(
            "display_name"
        ) or identity.principal_id
        session["tenants"] = await self._list_tenants(token)
        session["workspaces"] = self._workspace_views(identity)
        return self.session_view(session)

    async def _list_tenants(self, subject_token: str) -> list[dict]:
        try:
            payload = await self.iam.list_tenants(subject_token)
        except (RemoteUnavailable, RemoteProtocolError):
            return []
        return payload if isinstance(payload, list) else []

    def _workspace_views(self, identity: RemoteIdentity) -> list[dict]:
        out = []
        for ws_id in self.allowed_workspaces(identity):
            ws = self.registry.workspace(ws_id)
            if ws is not None:
                out.append(
                    {
                        "id": ws.id,
                        "name": ws.name,
                        "status": ws.status,
                        "instance_url": ws.instance_url,
                    }
                )
        return out

    def session_view(self, session: dict) -> dict:
        return {
            "session_id": session["session_id"],
            "principal_id": session["principal_id"],
            "display": session.get("display") or session["principal_id"],
            "csrf": session["csrf"],
            "tenant": session["tenant"],
            "tenant_code": session["tenant_code"],
            "tenant_epoch": session["tenant_epoch"],
            "context_version": session["context_version"],
            "tenants": session["tenants"],
            "workspaces": session.get("workspaces", []),
        }

    async def switch_tenant(
        self, session_id: str, tenant_id: str, expected_ctx_version: object
    ) -> dict:
        """Switch the IAM session context via CAS; everything else re-derives."""
        session = self.session_for(session_id)
        if session is None:
            raise Unauthenticated("credentials required")
        payload = await self.iam.switch_tenant(
            session["subject_token"], tenant_id, expected_ctx_version
        )
        # IAM ≥ V13 rotates the token on a context switch; persist the new one.
        new_token = payload.get("access_token")
        if isinstance(new_token, str) and new_token.strip():
            session["subject_token"] = new_token.strip()
            session["credentials_digest"] = hashlib.sha256(
                session["subject_token"].encode()
            ).hexdigest()
        identity = await self.introspect(session["subject_token"])
        if identity.principal_type != "human":
            raise IdentityRejected("tenant switch produced a non-human identity")
        if identity.tenant_id != tenant_id:
            raise NotAvailable("context changed; re-open the selection")
        session["tenant"] = identity.tenant_id
        session["tenant_code"] = identity.tenant_code
        session["context_version"] = identity.context_version
        session["tenant_epoch"] = secrets.token_urlsafe(16)
        session["csrf"] = secrets.token_urlsafe(32)
        session["workspaces"] = self._workspace_views(identity)
        return self.session_view(session)

    async def logout(self, session_id: str | None) -> None:
        session = self.session_for(session_id) if session_id else None
        if session is not None:
            try:
                await self.iam.logout(session["subject_token"])
            except (RemoteUnavailable, RemoteProtocolError, IdentityRejected):
                # A logout must not fail on an IAM hiccup; dropping the local
                # session already removes every path to the credential.
                pass
        if session_id:
            self._sessions.pop(session_id, None)

    # ---- helpers -----------------------------------------------------
    def mapped_workspaces(self, identity: RemoteIdentity) -> dict[str, str]:
        """Knowledge grants of a subject that also exist in the tenant map."""
        tenant_map = self.config.mapping.get(identity.tenant_id or "", {})
        grants = identity.workspace_grants()
        return {resource: tenant_map[resource] for resource in grants if resource in tenant_map}

    def ready_workspaces(self) -> set[str]:
        return {
            ws_id
            for ws_id, ws in self.registry.workspaces.items()
            if ws.status == "active" and ws_id != "default"
        }

    def allowed_workspaces(self, identity: RemoteIdentity) -> tuple[str, ...]:
        mapped = self.mapped_workspaces(identity)
        ready = self.ready_workspaces()
        seen: list[str] = []
        for workspace in mapped.values():
            if workspace in ready and workspace not in seen:
                seen.append(workspace)
        return tuple(sorted(seen))

    def resolve_selection(self, identity: RemoteIdentity, requested: object) -> tuple[str, ...]:
        """Server-side selection: the client only expresses intent."""
        allowed = self.allowed_workspaces(identity)
        if requested is None:
            raise Forbidden("workspace selection is required", code="workspace_required")
        if isinstance(requested, str) and requested == ALL:
            if not allowed:
                raise Forbidden(
                    "no knowledge library is granted to this principal",
                    code="no_workspace",
                )
            return allowed
        if not isinstance(requested, (str, list, tuple)):
            raise Forbidden("invalid selection", code="bad_selection")
        candidates = [requested] if isinstance(requested, str) else list(requested)
        if not candidates:
            raise Forbidden("empty workspace selection", code="no_workspace")
        if ALL in candidates:
            raise Forbidden("'all' cannot be combined with explicit ids", code="bad_selection")
        known = set(self.registry.workspaces)
        effective: list[str] = []
        for ws_id in candidates:
            if not isinstance(ws_id, str) or ws_id not in known:
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

    # ---- request entry points ---------------------------------------
    async def authorize_token(
        self, subject_token: str, requested: object, *, operation: str | None = None
    ) -> AuthContext:
        identity = await self.introspect(subject_token, operation=operation)
        if identity.principal_type == "human":
            if identity.needs_tenant_selection or not identity.context_usable:
                raise Forbidden(
                    "select an enterprise before querying", code="tenant_selection_required"
                )
        if not identity.tenant_id:
            raise Forbidden("no enterprise context", code="tenant_selection_required")
        workspaces = self.resolve_selection(identity, requested)
        return self._context_for(identity, workspaces)

    async def introspect(
        self, subject_token: str, *, operation: str | None = None
    ) -> RemoteIdentity:
        if operation is None:
            payload = await self.iam.introspect(subject_token, audience=self.config.audience)
        else:
            payload = await self.iam.introspect(
                subject_token, audience=self.config.audience, operation=operation
            )
        # Only a well-formed inactive response is a subject 401. Malformed
        # successful upstream responses are protocol/deployment failures (503).
        from env_rag_final.access.remote import (
            DELEGATION_SCHEMA,
            validate_delegation_inactive,
            validate_inactive,
        )

        if isinstance(payload, dict) and payload.get("active") is False:
            try:
                if payload.get("schema_version") == DELEGATION_SCHEMA:
                    reason = validate_delegation_inactive(payload)
                    if reason == "operation_mismatch":
                        # The token is valid but was issued for another endpoint.
                        # This is a caller error, not an expired identity.
                        raise Forbidden(
                            "delegated operation does not match this endpoint",
                            code="operation_mismatch",
                        )
                else:
                    validate_inactive(payload)
            except Forbidden:
                raise
            except (IdentityRejected, RemoteProtocolError) as exc:
                raise RemoteProtocolError("malformed inactive identity") from exc
            raise IdentityRejected("subject is not active")
        try:
            return validate_payload(
                payload,
                expected_issuer=self.config.issuer,
                expected_audience=self.config.audience,
                expected_operation=operation,
            )
        except (IdentityRejected, TypeError, ValueError, OverflowError) as exc:
            raise RemoteProtocolError("malformed active identity") from exc

    def _context_for(self, identity: RemoteIdentity, workspaces: tuple[str, ...]) -> AuthContext:
        if not identity.tenant_id:
            raise Forbidden("no enterprise context", code="tenant_selection_required")
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
            revisions=tuple(sorted((identity.revisions or {}).items())),
            service_account_revision=identity.service_account_revision,
            delegation_operation=identity.delegation_operation,
            issuing_client_id=(identity.delegation or {}).get("issuing_client_id"),
            workspaces=workspaces,
            policy_revision=self.registry.revision,
            directory_version=self.mapping_revision(),
            issued_at=time.time(),
        )

    def mapping_revision(self) -> str:
        """Technical mapping changes invalidate derived contexts and records."""
        return hashlib.sha256(
            json.dumps([self.registry.revision, self.config.mapping], sort_keys=True).encode()
        ).hexdigest()

    async def recheck_token(self, subject_token: str, ctx: AuthContext) -> AuthContext:
        """Live re-check of the same subject credential.

        Raises ``NotAvailable`` when the permissions, tenant, revisions or
        principal changed — the stale context must not authorise new work.
        """
        identity = await self.introspect(subject_token, operation=ctx.delegation_operation)
        if ctx.directory_version != self.mapping_revision() or not can_reuse_context(ctx, identity):
            raise NotAvailable("not available")
        current_allowed = set(self.allowed_workspaces(identity))
        if not set(ctx.workspaces) <= current_allowed:
            raise NotAvailable("not available")
        return replace(
            ctx,
            permissions=identity.permissions,
            policy_revision=self.registry.revision,
            issued_at=time.time(),
        )

    async def aclose(self) -> None:
        await self.iam.aclose()

    def as_public_dict(self) -> dict:
        return {
            "mode": "remote",
            "issuer": self.config.issuer,
            "iam_url": self.config.iam_url,
            "tenants_mapped": len(self.config.mapping),
            "observed_tenant": self._locked_tenant,
        }

    @property
    def _locked_tenant(self) -> str | None:
        """A machine principal has exactly one tenant; humans may switch."""
        return None


def build_provider(mode: str, **kwargs):
    """Startup factory that fails closed on unknown modes."""
    if mode == "local":
        return LocalProvider(**kwargs)
    if mode == "remote":
        return RemoteProvider(**kwargs)
    raise AuthProviderError(f"unknown ENV_RAG_AUTH_MODE {mode!r}; expected local or remote")
