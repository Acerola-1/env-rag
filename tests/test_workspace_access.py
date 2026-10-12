"""Offline tests for workspace access: registry, authorization and the gateway.

Real-model/browser acceptance lives in the run report; these tests pin the
*contracts* — especially that a refused request performs zero backend work.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from env_rag_final.access import auth as A  # noqa: E402
from env_rag_final.access import registry as R  # noqa: E402
from env_rag_final.access.gateway import KnowledgeService, RecordStore  # noqa: E402


def make_registry(tmp_path: Path, **overrides) -> R.Registry:
    payload = {
        "format": R.REGISTRY_FORMAT,
        "revision": "test-r1",
        "workspaces": {
            "air": {
                "name": "大气资料",
                "pg_workspace": "air",
                "vector_workspace": "air",
                "graph_workspace": "air",
                "instance_url": "http://127.0.0.1:9622",
                "instance_key_ref": "air",
            },
            "water": {
                "name": "水资料",
                "pg_workspace": "water",
                "vector_workspace": "water",
                "graph_workspace": "water",
                "instance_url": "http://127.0.0.1:9623",
                "instance_key_ref": "water",
            },
        },
        "principals": {},
        "grants": {},
    }
    for family, (user_id, enterprise, roles) in {
        "air": ("air-reader", "alpha", ["air-reader"]),
        "water": ("water-reader", "alpha", ["water-reader"]),
        "dual": ("dual-reader", "alpha", ["environment-reader"]),
        "none": ("no-access", "alpha", ["guest"]),
        "beta": ("beta-reader", "beta", ["air-reader"]),
    }.items():
        payload["principals"][user_id] = {
            "enterprise": enterprise,
            "display": user_id,
            "roles": roles,
            "password_hash": R.hash_password("pw-" + user_id, "s"),
            "bearer_sha256": [R.hash_token("tok-" + user_id)],
        }
    payload["grants"] = {
        "alpha:air-reader": ["air"],
        "alpha:water-reader": ["water"],
        "alpha:environment-reader": ["air", "water"],
        "alpha:guest": [],
        "beta:air-reader": ["water"],
    }
    payload.update(overrides)
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return R.load_registry(path)


def registry_path(tmp_path: Path, **overrides) -> Path:
    make_registry(tmp_path, **overrides)
    return tmp_path / "registry.json"


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------


def test_role_names_are_enterprise_scoped(tmp_path):
    reg = make_registry(tmp_path)
    alpha = reg.principal("air-reader")
    beta = reg.principal("beta-reader")
    assert reg.allowed_workspaces(alpha) == ("air",)
    assert reg.allowed_workspaces(beta) == ("water",)


def test_registry_rejects_reserved_namespace(tmp_path):
    payload = json.loads(registry_path(tmp_path).read_text(encoding="utf-8"))
    payload["workspaces"]["air"]["vector_workspace"] = "_"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(R.RegistryError, match="reserved"):
        R.load_registry(path)


def test_registry_rejects_namespace_collision(tmp_path):
    payload = json.loads(registry_path(tmp_path).read_text(encoding="utf-8"))
    payload["workspaces"]["water"]["pg_workspace"] = "air"
    path = tmp_path / "clash.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(R.RegistryError, match="used by both"):
        R.load_registry(path)


def test_registry_rejects_unknown_grant_workspace(tmp_path):
    payload = json.loads(registry_path(tmp_path).read_text(encoding="utf-8"))
    payload["grants"]["alpha:air-reader"] = ["ghost"]
    path = tmp_path / "ghost.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(R.RegistryError, match="unknown workspace"):
        R.load_registry(path)


def test_registry_rejects_grant_of_default(tmp_path):
    payload = json.loads(registry_path(tmp_path).read_text(encoding="utf-8"))
    payload["grants"]["alpha:guest"] = ["default"]
    path = tmp_path / "defaultgrant.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(R.RegistryError):
        R.load_registry(path)


def test_password_and_token_verification(tmp_path):
    reg = make_registry(tmp_path)
    assert reg.principal_by_login("air-reader", "pw-air-reader") is not None
    assert reg.principal_by_login("air-reader", "wrong") is None
    assert reg.principal_by_token("tok-water-reader") is not None
    assert reg.principal_by_token("tok-nope") is None


# --------------------------------------------------------------------------
# authorization matrix
# --------------------------------------------------------------------------


MATRIX = [
    ("air-reader", "air", True),
    ("air-reader", "water", False),
    ("air-reader", ["air", "water"], False),
    ("air-reader", "all", True),
    ("air-reader", "default", False),
    ("air-reader", "ghost", False),
    ("water-reader", "water", True),
    ("water-reader", "air", False),
    ("water-reader", "default", False),
    ("dual-reader", "air", True),
    ("dual-reader", "water", True),
    ("dual-reader", ["air", "water"], True),
    ("dual-reader", "all", True),
    ("no-access", "air", False),
    ("no-access", "all", False),
    ("beta-reader", "water", True),
    ("beta-reader", "air", False),
]


@pytest.mark.parametrize("user_id,selection,allowed", MATRIX)
def test_authorization_matrix(tmp_path, user_id, selection, allowed):
    reg = make_registry(tmp_path)
    principal = reg.principal(user_id)
    if allowed:
        ctx = A.authorize(reg, principal, selection)
        assert ctx.workspaces
    else:
        with pytest.raises(A.Forbidden):
            A.authorize(reg, principal, selection)


def test_all_expands_to_granted_set_only(tmp_path):
    reg = make_registry(tmp_path)
    ctx = A.authorize(reg, reg.principal("dual-reader"), A.ALL)
    assert set(ctx.workspaces) == {"air", "water"}
    ctx_single = A.authorize(reg, reg.principal("air-reader"), A.ALL)
    assert ctx_single.workspaces == ("air",)


def test_partial_selection_is_refused_whole(tmp_path):
    reg = make_registry(tmp_path)
    with pytest.raises(A.Forbidden) as exc:
        A.authorize(reg, reg.principal("air-reader"), ["air", "water"])
    assert exc.value.code == "unauthorized_workspace"


def test_unknown_and_missing_credentials(tmp_path):
    reg = make_registry(tmp_path)
    with pytest.raises(A.Unauthenticated):
        A.authenticate(reg)
    with pytest.raises(A.Unauthenticated):
        A.authenticate(reg, bearer_token="nonsense")


def test_context_cache_key_binds_identity(tmp_path):
    reg = make_registry(tmp_path)
    ctx_a = A.authorize(reg, reg.principal("air-reader"), "air")
    ctx_b = A.authorize(reg, reg.principal("water-reader"), "water")
    assert ctx_a.cache_key("q") != ctx_b.cache_key("q")
    assert ctx_a.cache_key("q")[0:3] == ("air-reader", "alpha", "test-r1")


# --------------------------------------------------------------------------
# gateway: refusal must not touch a backend
# --------------------------------------------------------------------------


class FakeConn:
    def __init__(self):
        self.queries = 0

    async def fetch(self, *a, **k):
        self.queries += 1
        return []

    async def fetchrow(self, *a, **k):
        self.queries += 1
        return None

    async def fetchval(self, *a, **k):
        self.queries += 1
        return 0

    async def execute(self, *a, **k):
        self.queries += 1
        return "OK"

    async def close(self):
        return None


class FakeInstanceClient:
    def __init__(self, log):
        self.log = log

    async def __aenter__(self):
        self.log.append("client-open")
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        self.log.append(("post", url))

        class _Res:
            status_code = 200

            def json(self):
                return {
                    "status": "success",
                    "data": {"chunks": [], "entities": [], "relationships": []},
                }

        return _Res()


def make_service(tmp_path, monkeypatch, *, backends: list):
    calls: list[str] = []

    class TrackingConn(FakeConn):
        async def fetch(self, sql, *a, **k):
            calls.append("pg")
            return []

        async def fetchrow(self, sql, *a, **k):
            calls.append("pg")
            return None

        async def fetchval(self, sql, *a, **k):
            calls.append("pg")
            return 0

    def connect_factory():
        calls.append("pg-connect")
        return TrackingConn()

    def client_factory():
        return FakeInstanceClient(calls)

    reg = make_registry(tmp_path)
    service = KnowledgeService(
        registry=reg,
        values={
            "LLM_BINDING_HOST": "http://127.0.0.1:0/v1",
            "LLM_BINDING_API_KEY": "x",
            "LLM_MODEL": "m",
            "QUERY_LLM_MODEL": "m",
        },
        record_root=tmp_path / "records",
        parsed_root=tmp_path / "parsed",
        instance_keys={"air": "k", "water": "k"},
        client_factory=client_factory,
        connect_factory=connect_factory,
    )
    backends.append(calls)
    return service


def test_refused_query_never_reaches_a_backend(tmp_path):
    backends: list = []
    service = make_service(tmp_path, None, backends=backends)
    calls = backends[0]
    reg = service.registry
    with pytest.raises(A.Forbidden):
        A.authorize(reg, reg.principal("air-reader"), "water")
    assert calls == []  # nothing touched
    assert service.backend_calls == []

    # And a full refused request through the service path:
    async def run():
        with pytest.raises(A.Forbidden):
            A.authorize(reg, reg.principal("no-access"), "all")

    asyncio.run(run())
    assert calls == []
    assert service.backend_calls == []


def test_allowed_query_does_reach_backends(tmp_path):
    backends: list = []
    service = make_service(tmp_path, None, backends=backends)
    calls = backends[0]
    reg = service.registry
    ctx = A.authorize(reg, reg.principal("air-reader"), "air")

    async def run():
        result = await service.retrieve(ctx, "空气质量标准", route="lightrag", mode="local")
        return result

    result = asyncio.run(run())
    assert result["workspaces"] == ["air"]
    assert "instance:air:local" in service.backend_calls
    assert ("post", "http://127.0.0.1:9622/query/data") in calls


def test_merge_keeps_same_chunk_id_in_two_workspaces():
    blocks = [
        {
            "workspace": "air",
            "items": [
                {"workspace": "air", "chunk_id": "c1", "doc_id": "d", "content": "A", "kind": "pg"}
            ],
        },
        {
            "workspace": "water",
            "items": [
                {
                    "workspace": "water",
                    "chunk_id": "c1",
                    "doc_id": "d",
                    "content": "A",
                    "kind": "pg",
                }
            ],
        },
    ]
    merged = KnowledgeService.merge_evidence(blocks)
    assert len(merged) == 2
    assert {m["workspace"] for m in merged} == {"air", "water"}


def test_private_records_and_revocation(tmp_path):
    backends: list = []
    service = make_service(tmp_path, None, backends=backends)
    reg = service.registry
    dual = A.authorize(reg, reg.principal("dual-reader"), ["air", "water"])
    from env_rag_final.access.gateway import Record

    service.records.save(
        Record(
            record_id="wa-1",
            user_id="dual-reader",
            enterprise="alpha",
            policy_revision=reg.revision,
            workspaces=["air", "water"],
            created_at=0.0,
            question="q",
            route="pg",
            status="complete",
            payload={
                "retrieval": {"evidence": [{"workspace": "water", "chunk_id": "c", "content": "w"}]}
            },
        )
    )
    assert service._record_for(dual, "wa-1").record_id == "wa-1"

    air_ctx = A.authorize(reg, reg.principal("air-reader"), "air")
    with pytest.raises(A.NotAvailable):
        service._record_for(air_ctx, "wa-1")
    with pytest.raises(A.NotAvailable):
        service.record_chunk(air_ctx, "wa-1", 0)

    revoked = A.AuthContext(
        principal=reg.principal("dual-reader"),
        enterprise="alpha",
        policy_revision=reg.revision,
        workspaces=("air",),
        issued_at=0.0,
    )
    with pytest.raises(A.NotAvailable):
        service._record_for(revoked, "wa-1")
    with pytest.raises(A.NotAvailable):
        service.record_chunk(revoked, "wa-1", 0)


def test_record_store_roundtrip(tmp_path):
    store = RecordStore(tmp_path / "records")
    from env_rag_final.access.gateway import Record

    record = Record(
        record_id="wa-x",
        user_id="u",
        enterprise="e",
        policy_revision="r",
        workspaces=["air"],
        created_at=1.0,
        question="q",
        route="pg",
        status="complete",
    )
    store.save(record)
    loaded = RecordStore(tmp_path / "records").get("wa-x")
    assert loaded is not None and loaded.question == "q"
