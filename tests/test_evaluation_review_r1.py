"""Independent 6.1 acceptance: actual adapters/wrappers, fake I/O only."""

import asyncio
import json
from types import SimpleNamespace

import pytest
import test_answer as fx

from env_rag_final import answer as an
from env_rag_final import evaluation as ev
from env_rag_final import local_adapter as la
from env_rag_final import rerank as rr


@pytest.fixture
def setup(monkeypatch, tmp_path):
    q = fx._gold_q("fact-001", fx.Q_FACT, "fact")
    conn, calls = fx._install(monkeypatch, tmp_path, [q])
    gold = tmp_path / "eval.json"
    gold.write_text(json.dumps({"questions": [q], "counter_examples": []}))
    observed = []

    async def answer_stub(*args, **kwargs):
        observed.append(kwargs)
        return {
            "results": [{"coverage_status": "missing", "answer": {"items": []}}],
            "model_calls_used": 0,
        }

    monkeypatch.setattr(ev, "_run_answer", answer_stub)
    return SimpleNamespace(
        conn=conn, calls=calls, gold=gold, out=tmp_path / "out", q=q, answers=observed
    )


def run(s, **kw):
    return asyncio.run(
        ev.run_evaluation(
            s.out, paths=["local"], gold_path=s.gold, values=fx.VALUES, conn=s.conn, **kw
        )
    )


def stage(q):
    return {
        "fused_result": fx._fused(q["query_id"], q["question"], [], status="missing"),
        "rerank_report": None,
        "discovery_status": "missing",
        "usable": 0,
        "latency_ms": 0,
    }


def fake_path(monkeypatch):
    async def runner(q, *a, **kw):
        return stage(q)

    monkeypatch.setattr(ev, "PATH_RUNNERS", {"local": runner})


def test_real_candidate_object_is_read_back_not_dict_crash(monkeypatch, setup):
    candidate = la.Candidate(
        fx.C1,
        "default",
        fx.DOC_8978,
        "gb8978.pdf",
        fx.CHUNKS[fx.C1]["content"][:80],
        len(fx.CHUNKS[fx.C1]["content"]),
        True,
    )

    class Adapter:
        async def fetch(self, *a, **kw):
            return SimpleNamespace(
                candidates=[candidate], call_records=[], degraded=[], sorting_sources={}
            )

    report = run(setup, local_adapter_factory=lambda *a: Adapter())
    record = report["results"][0]
    assert "failure" not in record, record
    assert record["discovery"]["usable"] == 1
    data = json.loads((setup.out / "inputs/local/fact-001-fusion.json").read_text())
    assert data["results"][0]["usable"][0]["content"] == fx.CHUNKS[fx.C1]["content"]


def test_fusion_really_reranks_and_passes_fresh_report(monkeypatch, setup):
    seen = []

    async def fusion_stub(*a, **kw):
        fused = fx._fused(
            setup.q["query_id"],
            setup.q["question"],
            [fx._usable(fx.C1, fx.DOC_8978, fx.CHUNKS[fx.C1]["content"])],
        )
        return {"results": [fused]}

    async def rerank_stub(*a, **kw):
        seen.append(kw)
        return {
            "results": [
                {
                    "query_id": "fact-001",
                    "status": "ok",
                    "ordered": [],
                    "degraded": [],
                    "call": {"status": "success"},
                }
            ]
        }

    monkeypatch.setattr(ev, "_run_fusion", fusion_stub)
    monkeypatch.setattr(rr, "run_rerank", rerank_stub)
    monkeypatch.setattr(ev, "_run_rerank", rerank_stub, raising=False)
    report = asyncio.run(
        ev.run_evaluation(
            setup.out, paths=["fusion"], gold_path=setup.gold, values=fx.VALUES, conn=setup.conn
        )
    )
    assert len(seen) == 1, report
    replay = json.loads(setup.answers[0]["rerank_report_path"].read_text())
    assert replay["results"][0]["status"] == "ok"
    assert report["budget_snapshot_end"]["reserved_total"]["rerank"] == 1


@pytest.mark.parametrize("service", ["qdrant", "neo4j"])
def test_native_recording_wrappers_cannot_bypass_budget(monkeypatch, setup, service):
    issued = []

    class Client:
        def query_points(self, *a, **kw):
            issued.append(1)
            return []

    class Session:
        async def run(self, *a, **kw):
            issued.append(1)
            return []

    class Driver:
        def session(self, *a, **kw):
            return Session()

    async def runner(q, *a, **kw):
        boundary = la.ServiceBoundary()
        if service == "qdrant":
            client = la._RecordingQdrantClient(Client(), boundary, "chunks")
            client.query_points()
            client.query_points()
        else:
            driver = la._RecordingNeo4jDriver(Driver(), boundary)
            await driver.session().run("MATCH (n) RETURN n")
            await driver.session().run("MATCH (n) RETURN n")
        return stage(q)

    monkeypatch.setattr(ev, "PATH_RUNNERS", {"local": runner})
    report = run(setup, budgets={"per_question": {service: 1}})
    assert len(issued) == 1, (issued, report)
    assert "budget_failure" in report["results"][0]


def test_embedding_keyword_batch_cannot_bypass_single_call_cap(monkeypatch, setup):
    issued = []

    async def embed(*, texts):
        issued.append(texts)
        return []

    async def runner(q, *a, **kw):
        await la.ServiceBoundary().call("embedding", "openai_embed", embed, texts=["x"] * 33)
        return stage(q)

    monkeypatch.setattr(ev, "PATH_RUNNERS", {"local": runner})
    report = run(setup)
    assert issued == [], report
    assert "budget_failure" in report["results"][0]


def test_local_actual_receipts_survive_evaluation(monkeypatch, setup):
    class Adapter:
        async def fetch(self, *a, **kw):
            return SimpleNamespace(
                candidates=[],
                call_records=[
                    {
                        "service": "llm",
                        "operation": "receipt-marker",
                        "status": "failure",
                        "error": "TimeoutError",
                        "latency_ms": 7,
                    }
                ],
                service_calls={"llm": {"attempt": 1, "failure": 1}},
                degraded=["keyword failure"],
                sorting_sources={},
            )

    report = run(setup, local_adapter_factory=lambda *a: Adapter())
    files = [report] + [json.loads(p.read_text()) for p in setup.out.rglob("*.json")]
    assert any("receipt-marker" in json.dumps(d) for d in files), report


def capture(env="env-1", frozen=True):
    return {
        "identity": {
            "public_counts": fx._identity()["counts"],
            "source_fingerprint": fx.FP,
            "catalog_active": {"run_id": fx.RUN, "snapshot_id": fx.SNAP},
            "search_active": fx.SEARCH,
            "gold_sha": fx.GOLD_SHA,
            "env_sha": env,
        },
        "matches_frozen": frozen,
        "problems": [] if frozen else ["counts changed"],
    }


def test_pre_guard_false_refuses_even_matching_primary_keys(monkeypatch, setup):
    fake_path(monkeypatch)

    async def identity(v):
        return capture(frozen=False)

    monkeypatch.setattr(an, "_capture_identity", identity)
    with pytest.raises(ev.AdapterError):
        run(setup)
    assert setup.answers == []
    assert (setup.out / "eval-runtime-latest.json").exists()


def test_pre_env_only_configuration_drift_refuses(monkeypatch, setup):
    fake_path(monkeypatch)
    expected = {
        "source_fingerprint": fx.FP,
        "catalog_run_snapshot": f"{fx.RUN}/{fx.SNAP}",
        "search_active": fx.SEARCH,
        "gold_sha256": fx.GOLD_SHA,
        "env_sha": "expected-config",
    }
    with pytest.raises(ev.AdapterError):
        run(setup, expected_identity=expected)
    assert setup.answers == []


def test_post_env_only_drift_rejects_and_keeps_terminal(monkeypatch, setup):
    fake_path(monkeypatch)
    n = 0

    async def identity(v):
        nonlocal n
        n += 1
        return capture(env="env-1" if n == 1 else "env-2")

    monkeypatch.setattr(an, "_capture_identity", identity)
    with pytest.raises(ev.AdapterError):
        run(setup)
    terminal = json.loads((setup.out / "eval-runtime-latest.json").read_text())
    assert terminal.get("failure") and "finished_at" not in terminal
    assert terminal["results"]


def test_post_capture_error_still_writes_terminal(monkeypatch, setup):
    fake_path(monkeypatch)
    n = 0

    async def identity(v):
        nonlocal n
        n += 1
        if n == 2:
            raise OSError("post capture failed")
        return capture()

    monkeypatch.setattr(an, "_capture_identity", identity)
    with pytest.raises((ev.AdapterError, OSError)):
        run(setup)
    path = setup.out / "eval-runtime-latest.json"
    assert path.exists(), "post capture error lost all completed evaluation records"
    terminal = json.loads(path.read_text())
    assert (
        terminal["results"]
        and terminal.get("identity_after_error")
        and "finished_at" not in terminal
    )


def test_each_discovery_gets_its_own_runtime_generation(monkeypatch, setup):
    q2 = fx._gold_q("fact-002", fx.Q_FACT, "fact")
    setup.gold.write_text(json.dumps({"questions": [setup.q, q2], "counter_examples": []}))
    dirs = []

    async def fusion_stub(report_dir, queries, **kw):
        dirs.append(report_dir)
        return {"results": [fx._fused(queries[0], fx.Q_FACT, [], status="missing")]}

    monkeypatch.setattr(ev, "_run_fusion", fusion_stub)
    asyncio.run(
        ev.run_evaluation(
            setup.out, paths=["pg"], gold_path=setup.gold, values=fx.VALUES, conn=setup.conn
        )
    )
    assert len(set(dirs)) == 2, "two question runtimes overwrite the same path generation"


def test_dry_run_uses_selected_query_set(setup):
    p = ev.GOLD_PATH
    report = asyncio.run(
        ev.run_evaluation(
            setup.out, dry_run=True, rounds=[1], paths=["pg"], query_ids=["fact-001"], gold_path=p
        )
    )
    assert report["total_executions"] == 1


def test_unknown_query_rejected_before_backend(monkeypatch, setup):
    fake_path(monkeypatch)
    with pytest.raises(ev.AdapterError):
        run(setup, query_ids=["not-a-frozen-question"])
    assert setup.calls["identity"] == 0


def test_direct_async_boundary_legitimate_cap_still_works(monkeypatch, setup):
    issued = []

    async def runner(q, *a, **kw):
        async def embed(texts):
            issued.append(texts)
            return []

        await la.ServiceBoundary().call("embedding", "openai_embed", embed, ["one"])
        return stage(q)

    monkeypatch.setattr(ev, "PATH_RUNNERS", {"local": runner})
    report = run(setup, budgets={"per_question": {"embedding": 1}})
    assert issued == [["one"]] and "failure" not in report["results"][0]
    assert report["budget_snapshot_end"]["reserved_total"]["embedding"] == 1


def test_explicit_absent_nonfusion_replay_is_preserved(monkeypatch, setup):
    fake_path(monkeypatch)
    report = run(setup)
    assert "failure" not in report["results"][0]
    replay = json.loads(setup.answers[0]["rerank_report_path"].read_text())
    assert replay["status"] == "absent"


def test_pg_queries_in_accepted_answer_are_also_budgeted(monkeypatch, setup):
    fake_path(monkeypatch)

    async def reading_answer(*a, **kw):
        await kw["conn"].fetch("SELECT fixture_read")
        return {"results": [{"coverage_status": "missing"}], "model_calls_used": 0}

    monkeypatch.setattr(ev, "_run_answer", reading_answer)
    report = run(setup, budgets={"total_caps": {"pg": 0}})
    assert setup.conn.queries == [], report
    assert "budget_failure" in report["results"][0]


@pytest.mark.parametrize("field", ["catalog_active", "gold_sha"])
def test_post_other_identity_changes_are_rejected(monkeypatch, setup, field):
    fake_path(monkeypatch)
    n = 0

    async def identity(v):
        nonlocal n
        n += 1
        result = capture()
        if n == 2:
            result["identity"][field] = (
                {"run_id": "new-run", "snapshot_id": fx.SNAP}
                if field == "catalog_active"
                else "new-gold-sha"
            )
        return result

    monkeypatch.setattr(an, "_capture_identity", identity)
    with pytest.raises(ev.AdapterError):
        run(setup)
    terminal = json.loads((setup.out / "eval-runtime-latest.json").read_text())
    assert terminal.get("failure") and "finished_at" not in terminal


def test_exception_redacted_before_truncation(monkeypatch, setup):
    key = "independent-review-synthetic-credential-0123456789"
    values = dict(fx.VALUES, LLM_BINDING_API_KEY=key)

    async def runner(q, *a, **kw):
        raise ValueError("x" * 190 + key)

    monkeypatch.setattr(ev, "PATH_RUNNERS", {"local": runner})
    report = asyncio.run(
        ev.run_evaluation(
            setup.out,
            paths=["local"],
            gold_path=setup.gold,
            values=values,
            conn=setup.conn,
        )
    )
    terminal = (setup.out / "eval-runtime-latest.json").read_text()
    assert key[:10] not in terminal, "configured secret prefix survived truncation"
    assert "<redacted>" in terminal and report["results"][0].get("failure")


def test_counter_category_reaches_same_real_answer_contract(monkeypatch, setup):
    question = "GB 8978-1996 表 1 共有几项？"
    counter = {
        "counter_id": "neg-004",
        "question": question,
        "type": "fragmented_table_merge",
        "expected_status": "complete",
    }
    setup.gold.write_text(json.dumps({"questions": [], "counter_examples": [counter]}))
    an.GOLD_PATH.write_text(json.dumps({"questions": [], "counter_examples": [counter]}))
    monkeypatch.setattr(ev, "_run_answer", an.run_answer)

    async def runner(q, *a, **kw):
        data = stage(q)
        usable = [fx._usable(cid, fx.DOC_8978, fx.CHUNKS[cid]["content"]) for cid in [fx.C1, fx.C2]]
        data["fused_result"] = fx._fused(q["query_id"], question, usable)
        data["discovery_status"] = "ok"
        data["usable"] = 2
        return data

    monkeypatch.setattr(ev, "PATH_RUNNERS", {"local": runner})
    report = run(setup)
    record = report["results"][0]
    assert "failure" not in record, record
    assert record["category"] == "table_enum"
    assert record["answer"]["items"] == 13, record
