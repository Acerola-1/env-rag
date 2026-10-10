"""5.2 independent acceptance at owning paths; all I/O and models are fake."""

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from env_rag_final import local_adapter as la

_spec = importlib.util.spec_from_file_location(
    "local_adapter_submission_fixtures", Path(__file__).with_name("test_local_adapter.py")
)
fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixture)


def setup_fetch(monkeypatch, rows=None, selected=None):
    rows = [dict(fixture.ROW_A)] if rows is None else rows
    selected = [r["id"] for r in rows] if selected is None else selected
    fixture._stub_pipeline(monkeypatch, selected)
    instances = []

    class Storage:
        def __init__(self, **kwargs):
            self.final_namespace = "lightrag_vdb_entities_qwen_qwen3_embedding_4b_2560d"
            self.workspace = "base"
            self.closed = False
            instances.append(self)

        async def initialize(self):
            pass

        async def finalize(self):
            self.closed = True

    monkeypatch.setattr(la, "QdrantVectorDBStorage", Storage)
    monkeypatch.setattr(la, "Neo4JStorage", Storage)

    async def read(self, ids):
        return [r for r in rows if r["id"] in ids]

    monkeypatch.setattr(la.LocalCandidateAdapter, "_read_chunks", read)
    return instances


def test_fetch_existing_qdrant_collection_must_not_submit_index_write(monkeypatch):
    import lightrag.kg.qdrant_impl as qmodule

    mutations = []
    setup_fetch(monkeypatch)

    class Client:
        def __init__(self, **kwargs):
            pass

        def collection_exists(self, name):
            return True

        def create_payload_index(self, **kwargs):
            mutations.append("create_payload_index")

        def count(self, **kwargs):
            return SimpleNamespace(count=5709)

        def close(self):
            pass

    monkeypatch.setattr(qmodule, "QdrantClient", Client)
    monkeypatch.setattr(qmodule, "_find_legacy_collection", lambda *args: None)
    monkeypatch.setattr(la, "QdrantVectorDBStorage", qmodule.QdrantVectorDBStorage)
    asyncio.run(la.LocalCandidateAdapter(fixture.VALUES).fetch("fixture"))
    assert mutations == [], "Existing indexes must be inspected, not ensured by a write API"


def assemble(monkeypatch, edges, vector=None, embedding=None):
    from lightrag import utils

    if vector is not None:

        async def pick(**kwargs):
            return vector

        monkeypatch.setattr(utils, "pick_by_vector_similarity", pick)
    entities = [{"entity_name": "A", "source_id": "main"}]
    return asyncio.run(
        la._assemble_candidates(
            entities,
            edges,
            "fixture",
            la._SimpleQueryParam(),
            embedding,
            SimpleNamespace(),
            SimpleNamespace(),
            {"qdrant_queries": 0},
            SimpleNamespace(),
        )
    )


def test_native_edge_pairs_do_not_overwrite_one_another(monkeypatch):
    edges = [
        {"src_tgt": ("A", "B"), "source_id": "edge-first"},
        {"src_tgt": ("C", "D"), "source_id": "edge-second"},
    ]
    selected, _tracking, _notes = assemble(monkeypatch, edges, vector=["main"])
    assert {"edge-first", "edge-second"}.issubset(selected)


def test_edge_provenance_names_actual_native_endpoints(monkeypatch):
    _, tracking, _ = assemble(
        monkeypatch, [{"src_tgt": ("A", "B"), "source_id": "edge-first"}], vector=["main"]
    )
    assert "edge:|" not in tracking["edge-first"]
    assert any("A" in path and "B" in path for path in tracking["edge-first"])


def test_vector_helper_swallowed_embedding_failure_is_visible(monkeypatch):
    async def failed_embedding(*args, **kwargs):
        raise TimeoutError("query embedding service timed out")

    _selected, _tracking, notes = assemble(monkeypatch, [], embedding=failed_embedding)
    assert notes, "Release VECTOR helper returns a truncation fallback after this failure"


def test_fetch_closes_owned_semantic_clients(monkeypatch):
    instances = setup_fetch(monkeypatch)
    asyncio.run(la.LocalCandidateAdapter(fixture.VALUES).fetch("fixture"))
    assert instances and all(s.closed for s in instances)


def test_changed_embedding_model_cannot_use_old_model_collection_label(monkeypatch):
    setup_fetch(monkeypatch)
    values = dict(fixture.VALUES, EMBEDDING_MODEL="Another/Embedding-2560")
    with pytest.raises(la.AdapterError):
        asyncio.run(la.LocalCandidateAdapter(values).fetch("fixture"))


def test_unmapped_pg_workspace_cannot_reuse_default_semantic_namespace(monkeypatch):
    setup_fetch(monkeypatch, rows=[dict(fixture.ROW_A, workspace="other")])
    with pytest.raises(la.AdapterError):
        asyncio.run(la.LocalCandidateAdapter(fixture.VALUES, workspace="other").fetch("fixture"))


def test_empty_pg_read_has_no_claimed_sql_query(monkeypatch):
    setup_fetch(monkeypatch, rows=[], selected=[])
    result = asyncio.run(la.LocalCandidateAdapter(fixture.VALUES).fetch("fixture"))
    assert result.service_calls["pg_readonly_queries"] == 0


def test_run_frozen_rejects_wrong_gold_sha_before_any_fetch(monkeypatch, tmp_path):
    calls = []

    class Adapter:
        def __init__(self, values, workspace):
            pass

        async def fetch(self, query, query_id=None):
            calls.append(query_id)
            return la.LocalCandidateResult(
                query, "local", "default", query_id, "start", "end", {}, [], [], [], {}, [], []
            )

    monkeypatch.setattr(la, "LocalCandidateAdapter", Adapter)
    monkeypatch.setitem(la.FROZEN, "gold_sha", "0" * 64)
    with pytest.raises(la.AdapterError):
        asyncio.run(la.run_frozen(tmp_path, ["fact-001"]))
    assert calls == []


def test_missing_pg_candidate_remains_rejected(monkeypatch):
    setup_fetch(monkeypatch, rows=[], selected=[fixture.ROW_A["id"]])
    result = asyncio.run(la.LocalCandidateAdapter(fixture.VALUES).fetch("fixture"))
    assert result.candidates[0].verified is False
    assert result.candidates[0].verify_error == "missing-in-production-pg"
    assert result.degraded
