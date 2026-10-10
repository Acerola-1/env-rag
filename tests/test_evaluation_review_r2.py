"""6.1 revision review: production context/connection forms, fake I/O only."""

import asyncio
import json
from types import SimpleNamespace

import pytest
import test_answer as fx
from test_evaluation_review_r1 import capture, fake_path, run, stage
from test_evaluation_review_r1 import setup as _setup_fixture

from env_rag_final import answer as an
from env_rag_final import cli
from env_rag_final import evaluation as ev
from env_rag_final import local_adapter as la


@pytest.fixture
def setup(monkeypatch, tmp_path):
    return _setup_fixture.__wrapped__(monkeypatch, tmp_path)


def test_neo4j_async_context_budget_is_enforced(monkeypatch, setup):
    issued = []

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def run(self, *args, **kwargs):
            issued.append(1)
            return []

    class Driver:
        def session(self):
            return Session()

    async def runner(q, *args, **kwargs):
        driver = la._RecordingNeo4jDriver(Driver(), la.ServiceBoundary())
        async with driver.session() as session:
            await session.run("MATCH (n) RETURN n")
            await session.run("MATCH (n) RETURN n")
        return stage(q)

    monkeypatch.setattr(ev, "PATH_RUNNERS", {"local": runner})
    report = run(setup, budgets={"per_question": {"neo4j": 1}})
    assert len(issued) == 1, (issued, report)
    assert "budget_failure" in report["results"][0]


def test_answer_owned_connection_not_only_supplied_conn_is_budgeted(monkeypatch, setup):
    async def runner(q, *args, **kwargs):
        result = stage(q)
        result["fused_result"] = fx._fused(
            q["query_id"],
            q["question"],
            [fx._usable(fx.C1, fx.DOC_8978, fx.CHUNKS[fx.C1]["content"])],
        )
        result["usable"] = 1
        return result

    async def connect(**kwargs):
        return setup.conn

    monkeypatch.setattr(ev, "PATH_RUNNERS", {"local": runner})
    monkeypatch.setattr(ev, "_run_answer", an.run_answer)
    monkeypatch.setattr(an.asyncpg, "connect", connect)
    report = asyncio.run(
        ev.run_evaluation(
            setup.out,
            paths=["local"],
            gold_path=setup.gold,
            values=fx.VALUES,
            conn=None,
            budgets={"total_caps": {"pg": 0}},
        )
    )
    assert setup.conn.queries == [], report
    assert "budget_failure" in report["results"][0]


def test_reservation_is_not_an_issued_answer_request(monkeypatch, setup):
    fake_path(monkeypatch)
    q = fx._gold_q("syn-001", fx.Q_SYN, "synthesis")
    setup.gold.write_text(json.dumps({"questions": [q], "counter_examples": []}))

    async def no_model_answer(*args, **kwargs):
        return {
            "results": [
                {
                    "coverage_status": "partial",
                    "model": {"used": False, "status": "incomplete_conditions"},
                    "answer": {"items": []},
                }
            ],
            "model_calls_used": 0,
        }

    monkeypatch.setattr(ev, "_run_answer", no_model_answer)
    report = run(setup, user_allows_answer_model=True)
    assert report["results"][0]["answer"]["model_calls"] == 0
    assert report["budget_snapshot_end"]["issued_total"].get("answer_llm", 0) == 0


def test_post_adapter_refusal_also_preserves_terminal(monkeypatch, setup):
    fake_path(monkeypatch)
    n = 0

    async def identity(values):
        nonlocal n
        n += 1
        if n == 2:
            raise ev.AdapterError("post source guard refused")
        return capture()

    monkeypatch.setattr(an, "_capture_identity", identity)
    with pytest.raises(ev.AdapterError):
        run(setup)
    p = setup.out / "eval-runtime-latest.json"
    assert p.exists(), "AdapterError bypassed the post failure writer"
    terminal = json.loads(p.read_text())
    assert terminal["results"] and terminal.get("failure") and "finished_at" not in terminal


def test_cli_missing_phase4_anchor_never_dispatches_real_entry(monkeypatch, setup, tmp_path):
    monkeypatch.chdir(tmp_path)
    touched = []

    async def entry(*args, **kwargs):
        touched.append(kwargs)
        raise ev.AdapterError("entry was reached without frozen configuration")

    monkeypatch.setattr(ev, "run_evaluation", entry)
    args = SimpleNamespace(
        report_dir=setup.out,
        paths="local",
        budgets=None,
        dry_run=False,
        rounds=None,
        round=1,
        query_id="fact-001",
        allow_model=False,
    )
    with pytest.raises(SystemExit):
        cli._run_eval(args, fx.VALUES)
    assert touched == [], "missing anchor silently became expected_identity=None"


@pytest.mark.parametrize("bad_cap", [None, -1])
def test_invalid_cap_schema_refused_before_identity(monkeypatch, setup, bad_cap):
    fake_path(monkeypatch)
    with pytest.raises(ev.AdapterError):
        run(setup, budgets={"per_question": {"qdrant": bad_cap}})
    assert setup.calls["identity"] == 0


def test_actual_local_provenance_is_not_discarded(monkeypatch, setup):
    candidate = la.Candidate(
        fx.C1,
        "default",
        fx.DOC_8978,
        "gb8978.pdf",
        "head",
        len(fx.CHUNKS[fx.C1]["content"]),
        True,
        reached_via=["entity:provenance-marker", "edge:source-marker|target-marker"],
        similarity_order=7,
        source_type="entity+relation",
    )

    class Adapter:
        async def fetch(self, *args, **kwargs):
            return SimpleNamespace(
                candidates=[candidate],
                call_records=[],
                service_calls={},
                degraded=[],
                sorting_sources={"chunk_pick": "weight-fallback"},
            )

    run(setup, local_adapter_factory=lambda *args: Adapter())
    published = "\n".join(p.read_text() for p in setup.out.rglob("*.json"))
    assert (
        "entity:provenance-marker" in published and "edge:source-marker|target-marker" in published
    )
    assert "weight-fallback" in published and "similarity_order" in published


def test_release_swallowed_quota_refusal_cannot_become_clean_complete(monkeypatch, setup):
    issued = []

    class Client:
        def retrieve(self, *args, **kwargs):
            issued.append(1)
            return []

    async def runner(q, *args, **kwargs):
        client = la._RecordingQdrantClient(Client(), la.ServiceBoundary(), "chunks")
        client.retrieve(ids=["a"])
        # The release vector helper catches Exception and falls back to WEIGHT.
        try:
            client.retrieve(ids=["b"])
        except Exception:
            pass
        result = stage(q)
        result["fused_result"] = fx._fused(
            q["query_id"],
            q["question"],
            [fx._usable(fx.C1, fx.DOC_8978, fx.CHUNKS[fx.C1]["content"])],
        )
        result["discovery_status"] = "ok"
        result["usable"] = 1
        return result

    monkeypatch.setattr(ev, "PATH_RUNNERS", {"local": runner})
    monkeypatch.setattr(ev, "_run_answer", an.run_answer)
    report = run(setup, budgets={"per_question": {"qdrant": 1, "pg": 1000}})
    record = report["results"][0]
    assert issued == [1]
    assert (
        "budget_failure" in record or record.get("answer", {}).get("coverage_status") == "partial"
    ), record


def test_neg008_reaches_reader_budget_not_an_unrelated_sql_quota(monkeypatch, setup):
    from env_rag_final.enumerate_ import prose_enum

    question = fx.Q_PROSE
    counter = {
        "counter_id": "neg-008",
        "question": question,
        "type": "budget_exhaustion",
        "expected_status": "partial",
    }
    setup.gold.write_text(json.dumps({"questions": [], "counter_examples": [counter]}))
    an.GOLD_PATH.write_text(json.dumps({"questions": [], "counter_examples": [counter]}))
    observed = []
    original = prose_enum.read_prose_scope

    async def read(*args, **kwargs):
        observed.append(kwargs)
        return await original(*args, **kwargs)

    async def runner(q, *args, **kwargs):
        result = stage(q)
        result["fused_result"] = fx._fused(
            q["query_id"],
            question,
            [fx._usable("chunk-18466-001", fx.DOC_18466, "3 术语和定义 3.1 医疗机构污水")],
        )
        result["usable"] = 1
        result["discovery_status"] = "ok"
        return result

    monkeypatch.setattr(prose_enum, "read_prose_scope", read)
    monkeypatch.setattr(ev, "PATH_RUNNERS", {"local": runner})
    monkeypatch.setattr(ev, "_run_answer", an.run_answer)
    report = run(setup)
    assert observed, report
    assert observed[0]["max_members"] == 1 and observed[0]["max_chars"] == 120
    assert report["results"][0].get("answer", {}).get("coverage_status") == "partial"


def test_actual_answer_request_is_still_counted_positive(monkeypatch, setup):
    fake_path(monkeypatch)
    q = fx._gold_q("syn-001", fx.Q_SYN, "synthesis")
    setup.gold.write_text(json.dumps({"questions": [q], "counter_examples": []}))

    async def answer(*args, **kwargs):
        return {
            "results": [
                {
                    "coverage_status": "complete",
                    "model": {"used": True, "status": "ok", "call": {"status": "success"}},
                    "answer": {"items": [{"kind": "synthesis_claim"}]},
                }
            ],
            "model_calls_used": 1,
        }

    monkeypatch.setattr(ev, "_run_answer", answer)
    report = run(setup, user_allows_answer_model=True)
    assert report["results"][0]["answer"]["model_calls"] == 1
    assert report["budget_snapshot_end"]["issued_total"]["answer_llm"] == 1


def test_cli_dry_run_remains_zero_touch_without_anchor(monkeypatch, setup, tmp_path):
    monkeypatch.chdir(tmp_path)
    observed = []

    async def entry(*args, **kwargs):
        observed.append(kwargs)
        return {
            "mode": "dry_run",
            "total_executions": 1,
            "bounds": {},
            "matrix_file": "fixture.json",
        }

    monkeypatch.setattr(ev, "run_evaluation", entry)
    args = SimpleNamespace(
        report_dir=setup.out,
        paths="local",
        budgets=None,
        dry_run=True,
        rounds=1,
        round=1,
        query_id="fact-001",
        allow_model=False,
    )
    cli._run_eval(args, fx.VALUES)
    assert len(observed) == 1 and observed[0]["dry_run"] is True
    assert observed[0]["expected_identity"] is None
