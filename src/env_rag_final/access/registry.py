"""Workspace / principal / grant registry.

The registry is the single source of truth for which knowledge libraries
exist, how each maps onto the shared PostgreSQL / Qdrant / Neo4j namespaces
and which LightRAG instance serves it, and which enterprise+role may read
which library.  Adding a library is a registry edit plus ingestion — no
retrieval code changes.

The file lives in an ignored local directory; only a template without
credentials is committed.  Validation is strict: unknown workspace ids,
duplicate ids, conflicting effective namespaces and missing required fields
all fail loudly at load time.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

REGISTRY_FORMAT = "workspace-access/registry-r1"
_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")

# Reserved physical namespaces owned by pre-existing data.  A new workspace
# must never be pointed at them.
RESERVED_PG = {"default", ""}
RESERVED_VECTOR = {"_", ""}
RESERVED_GRAPH = {"base", ""}


class RegistryError(ValueError):
    """Raised for any invalid registry configuration."""


@dataclass(frozen=True)
class Workspace:
    id: str
    name: str
    pg_workspace: str
    vector_workspace: str
    graph_workspace: str
    status: str = "active"
    parsed_root: str | None = None
    document_scope: tuple[str, ...] | None = None
    instance_url: str | None = None
    instance_key_ref: str | None = None
    code_identity: str | None = None
    embedding_model: str | None = None
    embedding_dim: int | None = None
    corpus_manifest: str | None = None
    notes: str | None = None

    def as_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass(frozen=True)
class Principal:
    user_id: str
    enterprise: str
    display: str
    roles: tuple[str, ...]
    password_hash: str | None = None
    bearer_sha256: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "enterprise": self.enterprise,
            "display": self.display,
            "roles": list(self.roles),
        }


def hash_password(password: str, salt: str) -> str:
    """PBKDF2-SHA256, deterministic for a given salt (stored as ``salt$hash``)."""
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or "$" not in stored:
        return False
    salt, _ = stored.split("$", 1)
    return _consteq(hash_password(password, salt), stored)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _consteq(a: str, b: str) -> bool:
    import hmac

    return hmac.compare_digest(a, b)


@dataclass
class Registry:
    revision: str
    workspaces: dict[str, Workspace] = field(default_factory=dict)
    principals: dict[str, Principal] = field(default_factory=dict)
    grants: dict[str, tuple[str, ...]] = field(default_factory=dict)
    source_path: str | None = None

    # ---- grants -------------------------------------------------------
    @staticmethod
    def grant_key(enterprise: str, role: str) -> str:
        return f"{enterprise}\x1f{role}"

    def grant_workspaces(self, enterprise: str, role: str) -> tuple[str, ...]:
        return self.grants.get(self.grant_key(enterprise, role), ())

    def allowed_workspaces(self, principal: Principal) -> tuple[str, ...]:
        seen: list[str] = []
        for role in principal.roles:
            for ws in self.grant_workspaces(principal.enterprise, role):
                if ws not in seen:
                    seen.append(ws)
        return tuple(seen)

    # ---- lookup -------------------------------------------------------
    def workspace(self, ws_id: str) -> Workspace | None:
        return self.workspaces.get(ws_id)

    def principal(self, user_id: str) -> Principal | None:
        return self.principals.get(user_id)

    def principal_by_token(self, token: str) -> Principal | None:
        digest = hash_token(token)
        for p in self.principals.values():
            if digest in p.bearer_sha256:
                return p
        return None

    def principal_by_login(self, user_id: str, password: str) -> Principal | None:
        p = self.principals.get(user_id)
        if p and verify_password(password, p.password_hash):
            return p
        return None

    def active_workspaces(self) -> tuple[str, ...]:
        return tuple(sorted(w for w, e in self.workspaces.items() if e.status == "active"))

    def as_dict(self, *, redact: bool = True) -> dict:
        return {
            "format": REGISTRY_FORMAT,
            "revision": self.revision,
            "workspaces": {k: v.as_dict() for k, v in sorted(self.workspaces.items())},
            "principals": {k: p.as_dict() for k, p in sorted(self.principals.items())},
            "grants": {k.replace("\x1f", ":"): list(v) for k, v in sorted(self.grants.items())},
        }


def _require(payload: dict, key: str, where: str):
    if key not in payload or payload[key] in (None, ""):
        raise RegistryError(f"{where}: missing required field {key!r}")
    return payload[key]


def load_registry(path: Path | str) -> Registry:
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RegistryError(f"registry not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RegistryError(f"registry {path} is not valid JSON: {exc}") from exc

    fmt = payload.get("format")
    if fmt != REGISTRY_FORMAT:
        raise RegistryError(f"unsupported registry format {fmt!r}; expected {REGISTRY_FORMAT!r}")
    revision = _require(payload, "revision", "registry")

    workspaces: dict[str, Workspace] = {}
    for ws_id, raw in (payload.get("workspaces") or {}).items():
        if not _ID_RE.match(ws_id):
            raise RegistryError(f"workspace id {ws_id!r} is not a valid stable id")
        if ws_id in workspaces:
            raise RegistryError(f"duplicate workspace id {ws_id!r}")
        where = f"workspace {ws_id!r}"
        ws = Workspace(
            id=ws_id,
            name=_require(raw, "name", where),
            pg_workspace=_require(raw, "pg_workspace", where),
            vector_workspace=_require(raw, "vector_workspace", where),
            graph_workspace=_require(raw, "graph_workspace", where),
            status=raw.get("status", "active"),
            parsed_root=raw.get("parsed_root"),
            document_scope=(tuple(raw["document_scope"]) if raw.get("document_scope") else None),
            instance_url=raw.get("instance_url"),
            instance_key_ref=raw.get("instance_key_ref"),
            code_identity=raw.get("code_identity"),
            embedding_model=raw.get("embedding_model"),
            embedding_dim=raw.get("embedding_dim"),
            corpus_manifest=raw.get("corpus_manifest"),
            notes=raw.get("notes"),
        )
        if ws.status not in ("active", "building", "draft", "retired"):
            raise RegistryError(f"{where}: invalid status {ws.status!r}")
        if ws.embedding_dim is not None and int(ws.embedding_dim) <= 0:
            raise RegistryError(f"{where}: embedding_dim must be positive")
        if ws_id != "default":
            if ws.pg_workspace in RESERVED_PG:
                raise RegistryError(
                    f"{where}: pg_workspace {ws.pg_workspace!r} is reserved for existing data"
                )
            if ws.vector_workspace in RESERVED_VECTOR:
                raise RegistryError(
                    f"{where}: vector_workspace {ws.vector_workspace!r} is reserved"
                )
            if ws.graph_workspace in RESERVED_GRAPH:
                raise RegistryError(f"{where}: graph_workspace {ws.graph_workspace!r} is reserved")
        workspaces[ws_id] = ws

    # Effective namespaces must not collide across workspaces.
    for key in ("pg_workspace", "vector_workspace", "graph_workspace"):
        seen: dict[str, str] = {}
        for ws_id, ws in workspaces.items():
            value = getattr(ws, key)
            if value in seen and seen[value] != ws_id:
                raise RegistryError(f"{key} {value!r} used by both {seen[value]!r} and {ws_id!r}")
            seen[value] = ws_id

    principals: dict[str, Principal] = {}
    for user_id, raw in (payload.get("principals") or {}).items():
        where = f"principal {user_id!r}"
        enterprise = _require(raw, "enterprise", where)
        roles = tuple(_require(raw, "roles", where))
        for role in roles:
            if f"{enterprise}:{role}" not in (payload.get("grants") or {}):
                raise RegistryError(
                    f"{where}: role {role!r} has no grant in enterprise {enterprise!r}"
                )
        principals[user_id] = Principal(
            user_id=user_id,
            enterprise=enterprise,
            display=raw.get("display") or user_id,
            roles=roles,
            password_hash=raw.get("password_hash"),
            bearer_sha256=tuple(raw.get("bearer_sha256") or ()),
        )

    grants: dict[str, tuple[str, ...]] = {}
    for key, ws_ids in (payload.get("grants") or {}).items():
        if ":" not in key:
            raise RegistryError(f"grant key {key!r} must be '<enterprise>:<role>'")
        ent, role = key.split(":", 1)
        resolved = []
        for ws_id in ws_ids:
            if ws_id not in workspaces:
                raise RegistryError(f"grant {key!r} references unknown workspace {ws_id!r}")
            if ws_id == "default":
                raise RegistryError(
                    f"grant {key!r} must not include the pre-existing 'default' workspace"
                )
            resolved.append(ws_id)
        grants[Registry.grant_key(ent, role)] = tuple(resolved)

    return Registry(
        revision=revision,
        workspaces=workspaces,
        principals=principals,
        grants=grants,
        source_path=str(path),
    )


def save_registry(registry: Registry, path: Path | str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": REGISTRY_FORMAT,
        "revision": registry.revision,
        "workspaces": {k: v.as_dict() for k, v in registry.workspaces.items()},
        "principals": {k: p.as_dict() for k, p in registry.principals.items()},
        "grants": {k.replace("\x1f", ":"): list(v) for k, v in registry.grants.items()},
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def resolve_cli_workspace(workspace: str, registry_path: Path | str | None = None) -> str:
    """Validate a CLI ``--workspace`` value against the registry.

    ``default`` stays valid so the historical regression contracts keep
    working unchanged.  Any other value must be a registered, active
    workspace: the default-only restriction is *replaced* by registry
    validation, never removed.
    """
    if workspace == "default":
        return workspace
    if not _ID_RE.match(workspace or ""):
        raise RegistryError(f"invalid workspace id {workspace!r}")
    path = Path(registry_path) if registry_path else default_registry_path()
    if not path.is_file():
        raise RegistryError(f"workspace {workspace!r} requested but no registry exists at {path}")
    registry = load_registry(path)
    entry = registry.workspace(workspace) or next(
        (w for w in registry.workspaces.values() if w.pg_workspace == workspace), None
    )
    if entry is None:
        raise RegistryError(f"workspace {workspace!r} is not registered")
    if entry.status != "active":
        raise RegistryError(f"workspace {workspace!r} is not active (status={entry.status})")
    return entry.pg_workspace


def default_registry_path() -> Path:
    import os

    override = os.environ.get("ENV_RAG_WORKSPACE_REGISTRY")
    if override:
        return Path(override)
    from env_rag_final.paths import PROJECT_ROOT

    return PROJECT_ROOT / ".local/workspace-access/registry.json"
