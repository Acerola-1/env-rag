"""Owning transport/service tests; synthetic evidence is not live acceptance."""

import asyncio
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from env_rag_final.web import native, service
from env_rag_final.web.budget import CAPS, BudgetExhausted, Ledger, check_embedding_batch
from env_rag_final.web.server import create_app, resolve_source


def ledger(tmp_path):
    return Ledger(tmp_path / "budget.json")


def chunk(doc="doc-a", cid="c1", sources=None):
    return {
        "workspace": "default",
        "doc_id": doc,
        "chunk_id": cid,
        "content": "原文限值35",
        "content_sha256": native.sha("原文限值35"),
        "verified": True,
        "reference_id": "1",
        "sources": sources or ["local"],
    }


def test_ledger_restart_and_refusal(tmp_path):
    accounting = ledger(tmp_path)
    for i in range(CAPS["retrieval"]):
        accounting.reserve(["retrieval"], str(i), "local")
        accounting.issued(["retrieval"], str(i), "local")
    restored = ledger(tmp_path)
    with pytest.raises(BudgetExhausted):
        restored.reserve(["retrieval"], "extra", "mix")
    got = restored.snapshot()
    assert got["issued"]["retrieval"] == 40
    assert got["events"][-1]["status"] == "refused"
    assert got["events"][-1]["issued"] == 0


def test_ledger_atomic_extra_cap_and_ownership(tmp_path):
    accounting = ledger(tmp_path)
    for i in range(20):
        accounting.reserve(["extra_answer"], str(i), "x")
    with pytest.raises(BudgetExhausted):
        accounting.reserve(["answer", "extra_answer"], "last", "x")
    assert accounting.snapshot()["reserved"].get("answer", 0) == 0
    accounting.reserve(["answer"], "correct", "x")
    with pytest.raises(RuntimeError):
        accounting.issued(["answer"], "wrong", "x")
    assert accounting.snapshot()["issued"].get("answer", 0) == 0


@pytest.mark.parametrize("texts", [["x"] * 33, ["x" * 32001], [], [None]])
def test_embedding_batch_bound_before_io(texts):
    with pytest.raises((ValueError, BudgetExhausted)):
        check_embedding_batch(texts)


def test_merge_identity_and_paths():
    a, b = chunk(), chunk(sources=["pg"])
    merged = service.merge_chunks([a], [b, chunk("doc-b", "c2", ["pg"])])
    assert len(merged) == 2
    assert merged[0]["sources"] == ["local", "pg"]
    with pytest.raises(ValueError):
        service.merge_chunks([a], [chunk("doc-b")])
    bad = dict(a, workspace="other")
    with pytest.raises(ValueError):
        service.merge_chunks([bad])


def fake_service(tmp_path, monkeypatch):
    monkeypatch.setattr(
        service, "read_environment", lambda p: {"LLM_BINDING_API_KEY": "fixture-secret-123"}
    )
    s = service.ComparisonService(tmp_path, budget_path=tmp_path / "budget.json")
    ident = {
        "public_counts": {"lightrag_doc_full": 221},
        "catalog_active": {"run_id": "r", "snapshot_id": "s"},
        "search_active": "i",
        "source_fingerprint": "f",
        "gold_sha": "g",
        "env_sha": "e",
    }

    async def identity():
        return dict(ident)

    s.identity = identity
    calls = []

    async def retrieve(q, mode, rid, **kw):
        calls.append(mode)
        return {
            "chunks": [chunk(sources=[mode])],
            "entities": [{"entity_name": "河流"}],
            "relations": [],
            "native_prompt": "原生提示\n\n---User Query---\n\n" + q,
            "receipts": [],
            "mode": mode,
        }

    s.native.retrieve = retrieve

    async def pg(q, rid, opts, k):
        return {
            "chunks": [chunk(sources=["pg"])],
            "enumeration": None,
            "discovery": {"status": "ok"},
            "typed_targets": [],
        }

    s.pg = pg
    return s, calls


def test_same_record_generation_and_duplicate_submission(tmp_path, monkeypatch):
    s, calls = fake_service(tmp_path, monkeypatch)
    completions = []

    async def complete(messages, rid, **kw):
        completions.append((messages, rid))
        return "原文限值35 [1]", {"status": "success"}

    s.native.completion = complete

    async def run():
        got = await s.execute("说明限值", ["local", "pg+local"], submission_id="a")
        assert len(calls) == 1
        assert got["results"][1]["retrieval_reused"]
        assert got["results"][1]["chunks"][0]["sources"] == ["pg", "local"]
        rid = got["results"][0]["record_id"]
        generated = await s.generate_record(rid)
        assert generated["answer"] == "原文限值35 [1]"
        assert completions[0][0][0]["content"] == "原生提示"
        assert len(calls) == 1
        await s.generate_record(rid)
        assert len(completions) == 1
        repeat = await s.execute("说明限值", ["local", "pg+local"], submission_id="a")
        assert repeat["results"][0]["record_id"] == rid
        assert len(calls) == 1

    asyncio.run(run())


def test_missing_version_skips_native(tmp_path, monkeypatch):
    s, calls = fake_service(tmp_path, monkeypatch)

    async def missing(*args):
        return {"chunks": [], "enumeration": None, "discovery": {"status": "missing"}}

    s.pg = missing
    got = asyncio.run(s.execute("GB3095-1996 是什么", ["pg+mix"], generate=True))
    assert got["results"][0]["status"] == "missing"
    assert got["results"][0]["generation_status"] == "skipped"
    assert calls == []


def test_empty_discovery_not_promoted(tmp_path, monkeypatch):
    s, _ = fake_service(tmp_path, monkeypatch)

    async def empty(*args, **kwargs):
        return {"chunks": [], "entities": [], "relations": [], "native_prompt": None}

    s.native.retrieve = empty
    got = asyncio.run(s.execute("说明污水", ["local"], generate=True))
    assert got["results"][0]["chunks"] == []
    assert got["results"][0]["generation_status"] == "no_context"
    assert got["results"][0]["enumeration"] is None


def test_model_failure_preserves_complete_enumeration(tmp_path, monkeypatch):
    s, _ = fake_service(tmp_path, monkeypatch)

    async def pg(*args):
        return {
            "chunks": [chunk(sources=["pg"])],
            "discovery": {},
            "enumeration": {"coverage_status": "complete", "answer": {"items": [{"text": "35"}]}},
        }

    async def fail(*args, **kwargs):
        raise TimeoutError("fixture-secret-123")

    s.pg, s.native.completion = pg, fail
    got = asyncio.run(s.execute("列出条款", ["pg"], generate=True))
    r = got["results"][0]
    assert r["status"] == "complete"
    assert r["generation_status"] == "model_failure"
    assert r["enumeration"]["answer"]["items"] == [{"text": "35"}]
    assert "fixture-secret-123" not in json.dumps(got)


@pytest.mark.parametrize("mode", native.MODES)
def test_native_dispatch_no_init_or_second_query(tmp_path, monkeypatch, mode):
    path = Path(inspect.getfile(native.operate))
    monkeypatch.setattr(native, "NATIVE_ROOT", path.parents[1])
    monkeypatch.setattr(
        native.la, "verify_config_guard", lambda *a: {"vector": "_", "graph": "base"}
    )
    monkeypatch.setattr(native.shared_storage, "initialize_share_data", lambda **kw: None)
    monkeypatch.setattr(native.la, "_pipeline_global_config", lambda *a: {})
    closed = []

    def storage(namespace, *args):
        return SimpleNamespace(_client=SimpleNamespace(close=lambda: closed.append(namespace)))

    monkeypatch.setattr(native.la, "bind_qdrant_readonly", storage)
    monkeypatch.setattr(native.la, "bind_neo4j_readonly", lambda *a: storage("graph"))

    class Text:
        def __init__(self, *args):
            pass

        async def get_by_ids(self, ids):
            return [{"workspace": "default", "content": "原文限值35", "full_doc_id": "doc-a"}]

    monkeypatch.setattr(native, "NativeTextChunks", Text)
    calls = []

    async def kg(*args, **kw):
        param = args[5]
        calls.append(("kg", param.mode))
        assert param.only_need_prompt and not param.enable_rerank
        assert kw["hashing_kv"] is None
        return SimpleNamespace(content="prompt", raw_data={"data": {"chunks": [chunk()]}})

    async def naive(*args, **kw):
        calls.append(("naive", args[2].mode))
        assert kw["hashing_kv"] is None
        return SimpleNamespace(content="prompt", raw_data={"data": {"chunks": [chunk()]}})

    monkeypatch.setattr(native.operate, "kg_query", kg)
    monkeypatch.setattr(native.operate, "naive_query", naive)
    backend = native.NativeBackend({}, ledger(tmp_path))
    got = asyncio.run(backend.retrieve("问题", mode, "r"))
    assert calls == [("naive" if mode == "naive" else "kg", mode)]
    assert got["chunks"][0]["verified"]
    assert len(closed) == (1 if mode == "naive" else 4)


def test_transport_requires_csrf_and_rejects_wrong_origin(tmp_path):
    from aiohttp.test_utils import TestClient, TestServer

    s = SimpleNamespace(ledger=ledger(tmp_path))

    async def run():
        client = TestClient(TestServer(create_app(s)), headers={"Host": "127.0.0.1"})
        try:
            await client.start_server()
            resp = await client.post("/api/query", json={})
            assert resp.status == 403
            cfg = await (await client.get("/api/config")).json()
            resp = await client.post(
                "/api/query",
                json={},
                headers={"X-RAG-Token": cfg["token"], "Origin": "http://outside.example"},
            )
            assert resp.status == 403
        finally:
            await client.close()

    asyncio.run(run())


def test_source_whitelist_and_record_binding(tmp_path, monkeypatch):
    import env_rag_final.web.server as server

    root = tmp_path / "LightRAG"
    inputs = root / "inputs"
    inputs.mkdir(parents=True)
    good = inputs / "source.pdf"
    good.write_text("pdf fixture")
    outside = tmp_path / "secret.pdf"
    outside.write_text("private")
    (inputs / "secret.pdf").symlink_to(outside)
    monkeypatch.setattr(server, "NATIVE_ROOT", root)
    rec = {"chunks": [dict(chunk(), file_path="source.pdf")]}
    assert resolve_source(rec, 0, "pdf") == good
    assert resolve_source(rec, 9, "pdf") is None
    rec["chunks"][0]["file_path"] = "secret.pdf"
    assert resolve_source(rec, 0, "pdf") is None
    assert resolve_source(rec, 0, "other") is None


def test_bypass_and_general_question_not_enumeration():
    assert "bypass" in service.STRATEGIES
    assert "pg+bypass" not in service.STRATEGIES
    assert not service.enumeration_intent("两表是同一张表吗？", {})
    assert not service.enumeration_intent("水质评价主要怎么做？", {})
    assert service.enumeration_intent("列出表1所有项目", {})


def test_sensitive_values_sanitized_recursively():
    v = {"LLM_API_KEY": "longsecret-value", "PASSWORD": "shortsecret"}
    got = service.sanitize({"x": [{"error": "longsecret-value"}], "s": "shortsecret"}, v)
    assert got == {"x": [{"error": "<redacted>"}], "s": "<redacted>"}


def test_identity_wrapper_rejection_and_actual_drift():
    actual = {
        "public_counts": {"lightrag_doc_full": 221},
        "catalog_active": {"run_id": "r", "snapshot_id": "s"},
        "source_fingerprint": "f",
        "search_active": "i",
        "gold_sha": "g",
        "env_sha": "e",
    }
    wrapped = {"identity": actual, "matches_frozen": True, "problems": []}
    assert service.canonical_identity(wrapped) == actual
    for change in ({"matches_frozen": False}, {"problems": ["drift"]}):
        with pytest.raises(ValueError):
            service.canonical_identity({**wrapped, **change})
    assert service._identity_drift(actual, {**actual, "env_sha": "changed"})
    assert service._identity_drift(actual, {**actual, "public_counts": {"lightrag_doc_full": 222}})


def test_post_generation_guard_preserves_receipt(tmp_path, monkeypatch):
    s, _ = fake_service(tmp_path, monkeypatch)

    async def run():
        got = await s.execute("说明限值", ["local"])
        rid = got["results"][0]["record_id"]
        original = s.identity
        calls = 0

        async def identity():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError("post drift")
            return await original()

        s.identity = identity

        async def complete(*args, **kwargs):
            return "原文限值35 [1]", {"status": "success"}

        s.native.completion = complete
        result = await s.generate_record(rid)
        assert result["status"] == "stale"
        assert result["answer_call"]["status"] == "success"
        assert result["generation_identity_error"]
        assert list(tmp_path.glob(rid + "-generation-*.json"))

    asyncio.run(run())


def test_general_footnotes_and_whole_context_budget():
    assert not service.enumeration_intent("表1脚注 a、b 分别适用于哪些蔬菜？", {})
    assert service.enumeration_intent("列出表1全部脚注", {})
    rec = {
        "chunks": [chunk(), dict(chunk(cid="c2"), content="x" * 50000)],
        "entities": [{"entity_name": "河流"}],
        "relations": [],
    }
    text = service.bounded_context(rec)
    data = json.loads(text)
    assert len(data["chunks"]) == 1
    assert data["chunks"][0]["content"] == "原文限值35"
    assert rec["generation_exclusions"] == [
        {"kind": "chunks", "index": 1, "reason": "whole_evidence_context_budget"}
    ]
    assert rec["used_evidence"][0]["chunk_id"] == "c1"


def test_uniform_generation_reuses_source_not_native_answer(tmp_path, monkeypatch):
    s, calls = fake_service(tmp_path, monkeypatch)
    completions = []

    async def complete(messages, *args, **kwargs):
        completions.append(messages)
        return "原文限值35 [1]", {"status": "success"}

    s.native.completion = complete

    async def run():
        original = (await s.execute("说明限值", ["local"], generate=True))["results"][0]
        exp = await s.generate_record(original["record_id"], profile="uniform_evidence")
        assert len(calls) == 1 and len(completions) == 2
        assert completions[1][0]["content"].startswith(service.ANSWER_INSTRUCTION)
        assert "原文限值35 [1]" not in completions[1][0]["content"]
        assert exp["experiment_retrieval_record_id"] == original["record_id"]
        assert exp["record_id"] != original["record_id"]
        assert exp["chunks"][0]["native_reference_id"] == "1"
        await s.generate_record(original["record_id"], profile="uniform_evidence")
        assert len(completions) == 2

    asyncio.run(run())


def test_display_redaction_is_not_raw_source_hash():
    source = chunk()
    got = service.sanitize(source, {"POSTGRES_PASSWORD": "35"})
    assert got["content"] == "原文限值<redacted>"
    assert got["content_redacted"] is True
    assert got["content_sha256"] == source["content_sha256"]
    assert got["display_content_sha256"] == native.sha(got["content"])


def test_redacted_record_requires_source_reread(tmp_path, monkeypatch):
    s, _ = fake_service(tmp_path, monkeypatch)
    source = chunk()
    display = dict(source, content="原文限值<redacted>", content_redacted=True)

    class Connection:
        closed = False

        async def fetch(self, *args):
            assert args[1] == "default"
            return [{"id": "c1", "full_doc_id": "doc-a", "content": source["content"]}]

        async def close(self):
            self.closed = True

    conn = Connection()

    async def connect():
        return conn

    s.connect = connect
    rec = {"chunks": [display]}
    asyncio.run(s.hydrate_chunks(rec))
    assert rec["chunks"][0]["content"] == source["content"] and conn.closed
    assert "content_redacted" not in rec["chunks"][0]


def test_cited_table_value_requires_same_row():
    from env_rag_final.web.support import table_summary_problems

    items = [{"cells": ["1", "总汞", "0.05"]}, {"cells": ["2", "总镉", "0.1"]}]
    assert not table_summary_problems("|1|总汞|0.05 [1]|", items)
    assert table_summary_problems("|1|总汞|0.1 [1]|", items)
    assert table_summary_problems("|1|总汞|999 [1]|", items)
    assert table_summary_problems("|1|总汞|-0.05 [1]|", items)
    assert table_summary_problems("|1|停车场|0.05 [1]|", items)


def test_document_file_requires_verified_catalog_binding(tmp_path, monkeypatch):
    from env_rag_final.web.server import resolve_document

    s, _ = fake_service(tmp_path, monkeypatch)
    captured = []
    import env_rag_final.web.server as transport

    monkeypatch.setattr(
        transport,
        "resolve_file",
        lambda name, kind: captured.append((name, kind)) or Path("/fixture.pdf"),
    )
    cit = {"kind": "catalog_row", "workspace": "default", "snapshot_id": "s", "doc_id": "doc-a"}
    item = {
        "kind": "document",
        "doc_id": "doc-a",
        "doc_name": "a.pdf",
        "citation": cit,
        "citation_verified": True,
        "citation_reverified": True,
    }

    async def run():
        ident = await s.identity()
        rec = {"identity_before": ident, "enumeration": {"answer": {"items": [item]}}}
        assert resolve_document(rec, "doc-a", "pdf") == Path("/fixture.pdf")
        assert captured == [("a.pdf", "pdf")]
        cit["snapshot_id"] = "old"
        assert resolve_document(rec, "doc-a", "pdf") is None
        cit["snapshot_id"] = "s"
        item["citation_reverified"] = False
        assert resolve_document(rec, "doc-a", "pdf") is None
        assert resolve_document(rec, "foreign", "pdf") is None

    asyncio.run(run())


def test_model_and_token_limits_are_not_credentials():
    got = service.sanitize(
        {"model": "deepseek", "context": "限值6000，向量8192", "key": "actual-secret"},
        {
            "KEYWORD_LLM_MODEL": "deepseek",
            "MAX_ENTITY_TOKENS": "6000",
            "EMBEDDING_MAX_TOKEN_SIZE": "8192",
            "LLM_BINDING_API_KEY": "actual-secret",
        },
    )
    assert got["model"] == "deepseek" and got["context"] == "限值6000，向量8192"
    assert got["key"] == "<redacted>"


def test_interactive_accounting_separate_and_durable(tmp_path):
    from env_rag_final.web.budget import InteractiveLedger

    goal = Ledger(tmp_path / "goal.json")
    old_bytes = goal.path.read_bytes()
    manual = InteractiveLedger(tmp_path / "manual.json")
    for i in range(65):
        manual.reserve(["answer", "extra_answer"], str(i), "generation")
        manual.issued(["answer", "extra_answer"], str(i), "generation")
    restored = InteractiveLedger(manual.path).snapshot()
    assert restored["issued"]["extra_answer"] == 65
    assert restored["caps"]["answer"] is None
    assert goal.path.read_bytes() == old_bytes
    with pytest.raises(RuntimeError, match="reservation"):
        manual.issued(["answer"], "no-reservation", "generation")
    with pytest.raises(ValueError):
        Ledger(manual.path).snapshot()


def test_interactive_reopens_only_unissued_budget_refusal(tmp_path, monkeypatch):
    from env_rag_final.web.budget import InteractiveLedger

    s, _ = fake_service(tmp_path, monkeypatch)
    s.ledger = InteractiveLedger(tmp_path / "manual.json")
    calls = []

    async def complete(messages, rid, **kw):
        calls.append(rid)
        return "原文限值35 [1]", {"status": "success"}

    s.native.completion = complete

    async def run():
        got = await s.execute("说明限值", ["local"], submission_id="manual")
        rid = got["results"][0]["record_id"]
        s.records[rid].update(generation_status="budget_exhausted", answer_call=None)
        result = await s.generate_record(rid)
        assert result["answer"] == "原文限值35 [1]"
        assert result["generation_retry_basis"] == "previous_app_budget_refusal_no_request"
        await s.generate_record(rid)
        assert len(calls) == 1
        s.records[rid].update(generation_status="model_failure", answer_call={"status": "failure"})
        await s.generate_record(rid)
        assert len(calls) == 1

    asyncio.run(run())
