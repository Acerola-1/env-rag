"""M1–M3 owning failure paths; native release methods, fake transports only."""

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from env_rag_final import local_adapter as la

spec = importlib.util.spec_from_file_location(
    "r3_previous_fixtures", Path(__file__).with_name("test_local_adapter_review_r2.py")
)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class AsyncDriver:
    def __init__(self, failure=False):
        self.closed = False
        self.failure = failure

    def session(self, **kwargs):
        driver = self

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def run(self, *args, **kwargs):
                await asyncio.sleep(0)
                if driver.failure:
                    raise TimeoutError("async graph read failed")
                return SimpleNamespace()

        return Session()

    async def close(self):
        await asyncio.sleep(0)
        self.closed = True


def test_native_neo4j_async_failure_is_a_failure_receipt(monkeypatch):
    from neo4j import AsyncGraphDatabase

    driver = AsyncDriver(failure=True)
    monkeypatch.setattr(AsyncGraphDatabase, "driver", lambda *a, **k: driver)
    boundary = la.ServiceBoundary()
    graph = la.bind_neo4j_readonly("base", None, fixture.fixture.VALUES, boundary)

    async def run():
        try:
            with pytest.raises(TimeoutError):
                await graph.get_nodes_batch(["A"])
        finally:
            await graph._driver.close()

    asyncio.run(run())
    assert any(r.service == "neo4j" and r.status == "failure" for r in boundary.records)
    assert not any(r.service == "neo4j" and r.status == "success" for r in boundary.records)


def test_entity_search_hits_do_not_prove_chunk_vectors_exist(monkeypatch):
    import lightrag.kg.qdrant_impl as qmodule

    fixture.install_fetch(monkeypatch, with_entity=True)
    original_client = qmodule.QdrantClient

    class Client(original_client):
        def query_points(self, **kwargs):
            self.reads.append("query_points")
            return SimpleNamespace(
                points=[SimpleNamespace(id="entity-id", payload={"entity_name": "A"}, score=0.8)]
            )

    monkeypatch.setattr(qmodule, "QdrantClient", Client)
    result = asyncio.run(la.LocalCandidateAdapter(fixture.fixture.VALUES).fetch("fixture"))
    assert result.candidates and all(c.verified for c in result.candidates)
    assert result.sorting_sources["chunk_pick"] == "weight-fallback"
    assert result.degraded


def test_failed_model_receipt_survives_frozen_terminal(monkeypatch, tmp_path):
    adapter_class = la.LocalCandidateAdapter
    fixture.install_run(monkeypatch)
    monkeypatch.setattr(la, "LocalCandidateAdapter", adapter_class)
    fixture.install_fetch(monkeypatch)

    async def failed_complete(*args, **kwargs):
        raise TimeoutError("keyword service failed")

    monkeypatch.setattr("lightrag.llm.openai.openai_complete_if_cache", failed_complete)

    async def keywords(query, param, config, cache):
        await config["role_llm_funcs"]["keyword"]("fixture")

    monkeypatch.setattr(la, "release_get_keywords_from_query", keywords)
    with pytest.raises(la.AdapterError):
        asyncio.run(la.run_frozen(tmp_path, ["fact-001"]))
    report = json.loads((tmp_path / "local-runtime-latest.json").read_text())

    def contains_receipt(value):
        if isinstance(value, dict):
            return (value.get("service") == "llm" and value.get("status") == "failure") or any(
                contains_receipt(v) for v in value.values()
            )
        if isinstance(value, list):
            return any(contains_receipt(v) for v in value)
        return False

    assert "identity_after" in report
    assert contains_receipt(report), (
        "The failing adapter recorded the call; terminal must retain it"
    )


def test_native_close_failure_never_calls_flush_finalizer(monkeypatch):
    import lightrag.kg.qdrant_impl as qmodule

    fixture.install_fetch(monkeypatch)
    original_client = qmodule.QdrantClient
    finalize_calls = []

    class Client(original_client):
        def close(self):
            raise OSError("close transport failed")

    async def forbidden_finalize(self):
        finalize_calls.append(self)

    monkeypatch.setattr(qmodule, "QdrantClient", Client)
    monkeypatch.setattr(qmodule.QdrantVectorDBStorage, "finalize", forbidden_finalize)
    result = asyncio.run(la.LocalCandidateAdapter(fixture.fixture.VALUES).fetch("fixture"))
    assert result.degraded, "Close failure must remain visible"
    assert not finalize_calls, "Native finalize can flush; it is forbidden even when close fails"


def test_partial_native_graph_binding_is_closed_before_fetch_returns(monkeypatch):
    import lightrag.kg.neo4j_impl as nmodule
    from neo4j import AsyncGraphDatabase

    bind = la.bind_neo4j_readonly
    fixture.install_fetch(monkeypatch)
    monkeypatch.setattr(la, "bind_neo4j_readonly", bind)
    driver = AsyncDriver()
    acquisitions = []

    def acquire_driver(*args, **kwargs):
        acquisitions.append(driver)
        return driver

    monkeypatch.setattr(AsyncGraphDatabase, "driver", acquire_driver)

    def failed_storage(self, **kwargs):
        raise RuntimeError("graph storage constructor failed")

    monkeypatch.setattr(nmodule.Neo4JStorage, "__init__", failed_storage)

    async def run():
        with pytest.raises(RuntimeError):
            await la.LocalCandidateAdapter(fixture.fixture.VALUES).fetch("fixture")
        assert not acquisitions or driver.closed, (
            "Acquired graph driver must be awaited closed before terminal return"
        )

    asyncio.run(run())


def test_async_graph_success_receipt_is_retained():
    boundary = la.ServiceBoundary()
    driver = la._RecordingNeo4jDriver(AsyncDriver(), boundary)

    async def run():
        async with driver.session() as session:
            await session.run("RETURN 1")
        await driver.close()

    asyncio.run(run())
    assert boundary.counts()["neo4j"] == {"attempt": 1, "success": 1, "failure": 0}
