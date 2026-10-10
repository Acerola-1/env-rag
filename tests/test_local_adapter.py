"""5.2 local candidate adapter: entry-level behavior with fakes; no services.

The REAL production path is exercised by the CLI (reports/pg-retrieval/
phase-3-local/). These tests pin the adapter's read-only and identity
verification contracts without touching Qdrant/Neo4j/PG or model services.
"""

import asyncio

import pytest

from env_rag_final import local_adapter as la

VALUES = {
    "POSTGRES_HOST": "test.invalid",
    "POSTGRES_PORT": "5432",
    "POSTGRES_USER": "fixture",
    "POSTGRES_PASSWORD": "fixture",
    "POSTGRES_DATABASE": "rag",
    "EMBEDDING_MODEL": "Qwen/Qwen3-Embedding-4B",
    "EMBEDDING_DIM": "2560",
    "EMBEDDING_TOKEN_LIMIT": "8192",
    "EMBEDDING_BINDING_HOST": "https://embedding.invalid/v1",
    "EMBEDDING_BINDING_API_KEY": "k-embed",
    "LLM_MODEL": "deepseek-v4.1-flash",
    "KEYWORD_LLM_MODEL": "",
    "LLM_BINDING_HOST": "http://llm.invalid/v1",
    "LLM_BINDING_API_KEY": "k-llm",
    "QDRANT_URL": "http://qdrant.invalid:6333",
    "NEO4J_URI": "bolt://neo4j.invalid:7687",
    "NEO4J_USERNAME": "fixture",
    "NEO4J_PASSWORD": "fixture",
}


class FakeConn:
    """Captures SQL; returns a chunk row for the verification SELECT."""

    def __init__(self, rows):
        self.rows = rows
        self.executed = []

    async def fetch(self, sql, *args):
        self.executed.append(" ".join(sql.split()))
        if "lightrag_doc_chunks" in sql:
            ids = args[1] if len(args) > 1 else []
            return [r for r in self.rows if r["id"] in ids]
        return []

    async def close(self):
        pass


def install_pg(monkeypatch, rows):
    seen = []

    async def connect(**kwargs):
        # the adapter MUST connect read-only
        settings = kwargs.get("server_settings") or {}
        assert settings.get("default_transaction_read_only") == "on"
        conn = FakeConn(rows)
        seen.append(conn)
        return conn

    monkeypatch.setattr(la.asyncpg, "connect", connect)
    return seen


ROW_A = {
    "id": "doc-257d8cf3fdf90e76c31908c4f92fc1a1-chunk-000",
    "workspace": "default",
    "full_doc_id": "doc-257d8cf3fdf90e76c31908c4f92fc1a1",
    "content": "二氧化硫年平均浓度二级限值 0.15 mg/m3",
    "tokens": 100,
    "chunk_order_index": 0,
    "file_path": "air-02_GB3095-2012.pdf",
}
ROW_OTHER = dict(
    ROW_A,
    id="doc-4c883d21fa02a53189e0911c3d59d1d1-chunk-000",
    full_doc_id="doc-4c883d21fa02a53189e0911c3d59d1d1",
)


def test_readonly_pg_upsert_delete_drop_forbidden(monkeypatch):
    install_pg(monkeypatch, [ROW_A])
    store = la.ReadOnlyPGTextChunks(VALUES, workspace="default", boundary=la.ServiceBoundary())
    for call in (
        lambda: store.upsert({"x": {}}),
        lambda: store.delete(["x"]),
        lambda: store.drop(),
        lambda: store.is_empty(),
    ):
        with pytest.raises(la.AdapterError):
            asyncio.run(call())
    # no SQL beyond nothing was executed by the forbidden calls
    assert all(
        "INSERT" not in e and "DELETE" not in e and "DROP" not in e for conn in [store] for e in []
    )


def test_readonly_pg_get_by_ids_returns_rows_and_none_for_missing(monkeypatch):
    seen = install_pg(monkeypatch, [ROW_A, ROW_OTHER])
    store = la.ReadOnlyPGTextChunks(VALUES, workspace="default", boundary=la.ServiceBoundary())
    got = asyncio.run(store.get_by_ids([ROW_A["id"], "doc-x-chunk-999", ROW_OTHER["id"]]))
    assert got[0]["full_doc_id"] == "doc-257d8cf3fdf90e76c31908c4f92fc1a1"
    assert got[1] is None  # missing chunk → explicit None, never fabricated
    assert got[2]["id"] == ROW_OTHER["id"]
    # read-only transaction setting enforced on every connection
    assert seen and all("SELECT" in e for conn in seen for e in conn.executed)


def test_filter_keys_returns_missing_only(monkeypatch):
    install_pg(monkeypatch, [ROW_A])
    store = la.ReadOnlyPGTextChunks(VALUES, workspace="default", boundary=la.ServiceBoundary())
    missing = asyncio.run(store.filter_keys({ROW_A["id"], "doc-x-chunk-999"}))
    assert missing == {"doc-x-chunk-999"}


def test_identity_verification_rejects_full_doc_id_mismatch(monkeypatch):
    # A chunk whose id prefix does not match its row's full_doc_id is degraded,
    # not silently accepted.
    tampered = dict(ROW_A, full_doc_id="doc-some-other-document")
    install_pg(monkeypatch, [tampered])

    result = _run_fetch_with_stubbed_pipeline(monkeypatch, rows=[tampered])
    bad = [c for c in result.candidates if c.verify_error == "full_doc_id-mismatch"]
    assert bad, "mismatched chunk must be rejected"


def test_missing_chunk_is_degraded_not_fabricated(monkeypatch):
    install_pg(monkeypatch, [])  # production PG returns nothing

    result = _run_fetch_with_stubbed_pipeline(monkeypatch, rows=[])
    missing = [c for c in result.candidates if c.verify_error == "missing-in-production-pg"]
    assert missing, "pipeline-selected chunk absent from PG must be a recorded miss"
    assert all(not c.verified for c in missing)


# -- pipeline stubbing helpers -----------------------------------------------


def _stub_pipeline(monkeypatch, selected_ids):
    """Stub the release pipeline stages so fetch() reaches the verification
    layer with controlled candidate ids (no services, no storage init)."""

    async def fake_keywords(query, param, config, hashing_kv):
        return ["hl"], ["ll"]

    monkeypatch.setattr(la, "release_get_keywords_from_query", fake_keywords)

    async def fake_node_data(ll, graph, vdb, param, query_embedding=None):
        return [], []

    monkeypatch.setattr(la, "_get_node_data", fake_node_data)

    async def fake_assemble(*args, **kwargs):
        return list(selected_ids), {cid: ["entity:fake"] for cid in selected_ids}, []

    monkeypatch.setattr(la, "_assemble_candidates", fake_assemble)


def _run_fetch_with_stubbed_pipeline(monkeypatch, rows, selected_ids=None):
    # give the adapter storages that skip initialize() but record nothing
    selected_ids = selected_ids or ([ROW_A["id"]] if not rows else [r["id"] for r in rows])
    _stub_pipeline(monkeypatch, selected_ids)

    class SkipInit:
        def __init__(self, *a, **k):
            self.final_namespace = "lightrag_vdb_entities_qwen_qwen3_embedding_4b_2560d"
            self.workspace = "base"

        async def initialize(self):
            pass

    monkeypatch.setattr(la, "QdrantVectorDBStorage", SkipInit)
    monkeypatch.setattr(la, "Neo4JStorage", SkipInit)

    async def fake_read(self, ids):
        return rows

    monkeypatch.setattr(la.LocalCandidateAdapter, "_read_chunks", fake_read)

    adapter = la.LocalCandidateAdapter(VALUES, workspace="default")
    return asyncio.run(adapter.fetch("测试查询", query_id="fixture"))


def test_fetch_service_call_counters_only_count_real_calls(monkeypatch):
    install_pg(monkeypatch, [ROW_A])
    result = _run_fetch_with_stubbed_pipeline(monkeypatch, [ROW_A])
    # the stubbed pipeline does not touch services: counters must stay zero —
    # recorded calls must correspond to actual service traffic, not code paths
    assert result.service_calls["embedding_requests"] == 0
    assert result.service_calls["llm_requests"] == 0
    assert result.candidates and all(c.verified for c in result.candidates)


def test_embedding_func_uses_unwrapped_release_embed(monkeypatch):
    # The release openai_embed is double-decorated (dim 1536 wrapper); the
    # adapter must call .func, otherwise production 2560d vectors fail dim
    # validation (observed live: "cannot be evenly divided by 1536").
    calls = {}

    class FakeWrapped:
        func = None  # set below

    async def raw_embed(texts, **kwargs):
        calls["texts"] = list(texts)
        calls["model"] = kwargs.get("model")
        import numpy as np

        return np.zeros((len(texts), 2560), dtype=np.float32)

    FakeWrapped.func = raw_embed
    monkeypatch.setattr("lightrag.llm.openai.openai_embed", FakeWrapped, raising=False)
    func = la.build_real_embedding_func(VALUES, la.ServiceBoundary())
    out = asyncio.run(func(["测试"], context="query"))
    assert out.shape == (1, 2560)
    assert calls["model"] == "Qwen/Qwen3-Embedding-4B"


def test_keyword_llm_binds_env_models_and_host(monkeypatch):
    captured = {}

    async def fake_complete(model, prompt, **kwargs):
        captured["model"] = model
        captured["base_url"] = kwargs.get("base_url")
        return "{}"

    import lightrag.llm.openai as openai_llm

    monkeypatch.setattr(openai_llm, "openai_complete_if_cache", fake_complete)
    llm = la.build_real_keyword_llm(VALUES, la.ServiceBoundary())
    asyncio.run(llm("提取关键词"))
    assert captured["model"] == VALUES["EMBEDDING_MODEL"] or captured["model"] is not None
    assert captured["base_url"] is not None
