"""Recheck L3/L4/L5 at real owning entries; no network or model calls."""

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from env_rag_final import local_adapter as la
from env_rag_final.compat_runtime import _identity_mismatch

spec = importlib.util.spec_from_file_location(
    "r2_submission_fixture", Path(__file__).with_name("test_local_adapter.py")
)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def install_fetch(monkeypatch, with_entity=False, vector_error=False):
    """Use actual release Qdrant read methods with a native-client double."""
    import lightrag.kg.qdrant_impl as qmodule

    clients = []

    class Client:
        def __init__(self, **kwargs):
            self.closed = False
            self.reads = []
            clients.append(self)

        def collection_exists(self, name):
            return True

        def get_collection(self, name):
            return SimpleNamespace(
                config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=2560))),
                payload_schema={"workspace_id": "keyword"},
            )

        def query_points(self, **kwargs):
            self.reads.append("query_points")
            return SimpleNamespace(points=[])

        def retrieve(self, **kwargs):
            self.reads.append("retrieve")
            if vector_error:
                raise TimeoutError("vector service failed")
            return []

        def close(self):
            self.closed = True

    monkeypatch.setattr(qmodule, "QdrantClient", Client)

    class Graph:
        workspace = "base"

        async def finalize(self):
            pass

    monkeypatch.setattr(la, "bind_neo4j_readonly", lambda *a: Graph())

    def embedding(values, boundary):
        async def raw(texts, **kwargs):
            return np.ones((len(texts), 2560))

        async def wrapped(texts, **kwargs):
            return await boundary.call("embedding", "openai_embed", raw, texts)

        return la.EmbeddingFunc(
            embedding_dim=2560, max_token_size=8192, func=wrapped, model_name=la.EMBEDDING_MODEL
        )

    monkeypatch.setattr(la, "build_real_embedding_func", embedding)

    async def keywords(*args):
        return [], ["fixture"]

    async def nodes(query, graph, vdb, param):
        if not with_entity:
            return [], []
        await vdb.query(query, top_k=10)
        return [{"entity_name": "A", "source_id": fixture.ROW_A["id"]}], []

    async def rows(self, ids):
        return [dict(fixture.ROW_A) if cid == fixture.ROW_A["id"] else None for cid in ids]

    monkeypatch.setattr(la, "release_get_keywords_from_query", keywords)
    monkeypatch.setattr(la, "_get_node_data", nodes)
    monkeypatch.setattr(la.ReadOnlyPGTextChunks, "_fetch", rows)
    return clients


def test_reused_adapter_records_are_per_request(monkeypatch):
    install_fetch(monkeypatch)

    async def run():
        adapter = la.LocalCandidateAdapter(fixture.VALUES)
        first = await adapter.fetch("first")
        second = await adapter.fetch("second")
        assert second.service_calls["by_service"] == first.service_calls["by_service"]
        assert len(second.call_records) == len(first.call_records)

    asyncio.run(run())


def test_actual_qdrant_reads_have_service_receipts(monkeypatch):
    clients = install_fetch(monkeypatch, with_entity=True)
    result = asyncio.run(la.LocalCandidateAdapter(fixture.VALUES).fetch("fixture"))
    assert any(c.reads for c in clients), "Actual release read APIs were executed"
    assert any(r["service"] == "qdrant" for r in result.call_records)


def test_missing_vectors_do_not_claim_vector_similarity(monkeypatch):
    install_fetch(monkeypatch, with_entity=True)
    result = asyncio.run(la.LocalCandidateAdapter(fixture.VALUES).fetch("fixture"))
    assert result.candidates and all(c.verified for c in result.candidates)
    assert result.sorting_sources["chunk_pick"] != "vector-similarity"


def test_swallowed_qdrant_timeout_has_failure_receipt(monkeypatch):
    install_fetch(monkeypatch, with_entity=True, vector_error=True)
    result = asyncio.run(la.LocalCandidateAdapter(fixture.VALUES).fetch("fixture"))
    assert any(r["service"] == "qdrant" and r["status"] == "failure" for r in result.call_records)


def install_run(monkeypatch, env_drift=False, fetch_failure=False):
    count = 0

    async def capture(values):
        nonlocal count
        count += 1
        identity = {
            "public_counts": dict(la.FROZEN["public_counts"]),
            "catalog_active": {
                "run_id": la.FROZEN["catalog_run_id"],
                "snapshot_id": la.FROZEN["catalog_snapshot_id"],
            },
            "source_fingerprint": la.FROZEN["source_fingerprint"],
            "search_active": la.FROZEN["search_active"],
            "gold_sha": la.FROZEN["gold_sha"],
            "env_sha": "after" if env_drift and count > 1 else "before",
        }
        problems = _identity_mismatch(identity)
        return {"identity": identity, "problems": problems, "matches_frozen": not problems}

    class Adapter:
        def __init__(self, *a, **kw):
            pass

        async def fetch(self, *a, **kw):
            if fetch_failure:
                raise TimeoutError("fixture keyword failure")
            return None

    monkeypatch.setattr(la, "_capture_production_identity", capture)
    monkeypatch.setattr(la, "LocalCandidateAdapter", Adapter)
    monkeypatch.setattr(la, "_result_to_json", lambda result, q: {"query_id": q["query_id"]})


def test_env_drift_is_rejected_by_frozen_entry(monkeypatch, tmp_path):
    install_run(monkeypatch, env_drift=True)
    with pytest.raises(la.AdapterError):
        asyncio.run(la.run_frozen(tmp_path, ["fact-001"]))


def test_fetch_failure_persists_post_guard_terminal(monkeypatch, tmp_path):
    import json

    install_run(monkeypatch, fetch_failure=True)
    with pytest.raises(la.AdapterError):
        asyncio.run(la.run_frozen(tmp_path, ["fact-001"]))
    report = json.loads((tmp_path / "local-runtime-latest.json").read_text())
    assert report["failure"]["stage"] == "fetch"
    assert "identity_after" in report, "Post-guard ran but the terminal report must persist it"


def test_construct_failure_closes_client_acquired_inside_binding(monkeypatch):
    import lightrag.kg.qdrant_impl as qmodule

    clients = install_fetch(monkeypatch)

    def broken_constructor(self, **kwargs):
        raise RuntimeError("storage constructor failed after client acquisition")

    monkeypatch.setattr(qmodule.QdrantVectorDBStorage, "__init__", broken_constructor)
    with pytest.raises(RuntimeError):
        asyncio.run(la.LocalCandidateAdapter(fixture.VALUES).fetch("fixture"))
    assert clients and all(c.closed for c in clients)


def test_successful_binding_closes_all_actual_clients(monkeypatch):
    clients = install_fetch(monkeypatch)
    asyncio.run(la.LocalCandidateAdapter(fixture.VALUES).fetch("fixture"))
    assert len(clients) == 2 and all(c.closed for c in clients)
