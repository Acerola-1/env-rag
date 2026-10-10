"""N1: returned Qdrant points are not necessarily usable chunk vectors."""

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from env_rag_final import local_adapter as la

spec = importlib.util.spec_from_file_location(
    "r4_r2_fixtures", Path(__file__).with_name("test_local_adapter_review_r2.py")
)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


@pytest.mark.parametrize(
    "has_vector,correct_identity", [(False, True), (True, False), (True, True)]
)
def test_vector_coverage_requires_vectors_not_just_returned_points(
    monkeypatch, has_vector, correct_identity
):
    import lightrag.kg.qdrant_impl as qmodule

    fixture.install_fetch(monkeypatch, with_entity=True)
    client_class = qmodule.QdrantClient

    class Client(client_class):
        def query_points(self, **kwargs):
            self.reads.append("query_points")
            return SimpleNamespace(
                points=[SimpleNamespace(id="entity", payload={"entity_name": "A"}, score=0.8)]
            )

        def retrieve(self, **kwargs):
            self.reads.append("retrieve")
            # Exactly the requested IDs are returned, but missing vectors
            # are discarded by the actual release get_vectors_by_ids().
            return [
                SimpleNamespace(
                    id=rid,
                    payload={} if correct_identity else {qmodule.ID_FIELD: "unrelated-chunk"},
                    vector=[1.0] * 2560 if has_vector else None,
                )
                for rid in kwargs["ids"]
            ]

    monkeypatch.setattr(qmodule, "QdrantClient", Client)
    result = asyncio.run(la.LocalCandidateAdapter(fixture.fixture.VALUES).fetch("fixture"))
    assert result.candidates and all(c.verified for c in result.candidates)
    supported = has_vector and correct_identity
    assert result.sorting_sources["chunk_pick_vectors"]["vector_backed"] is supported
    if supported:
        assert result.sorting_sources["chunk_pick"] == "vector-similarity"
    else:
        assert result.sorting_sources["chunk_pick"] == "weight-fallback"
        assert result.degraded
