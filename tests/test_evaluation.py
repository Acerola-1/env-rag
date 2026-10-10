"""6.1 acceptance through the evaluation owning entry — offline only.

No real model/embedding/rerank/DB request: fake path runners, fake identity
capture, fake transports and the fake read-only catalog from test_answer."""

import asyncio
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_answer as fx

from env_rag_final import evaluation as ev

EVAL_GOLD = {
    "version": "eval-fixture-gold",
    "questions": [
        {
            "query_id": "syn-001",
            "category": "synthesis",
            "question": fx.Q_SYN,
            "workspace": "default",
        },
        {
            "query_id": "fact-001",
            "category": "fact",
            "question": fx.Q_FACT,
            "workspace": "default",
        },
    ],
    "counter_examples": [
        {
            "counter_id": "neg-001",
            "type": "absent_version",
            "question": "GB 3095-1996 的二级标准年均限值是多少？",
            "expected_status": "missing",
            "review_status": "expectation_reviewed",
        },
        {
            "counter_id": "neg-008",
            "type": "constructed_budget",
            "question": "（构造）极小预算枚举 GB 18466-2005 全部 4.1 条款。",
            "expected_status": "partial",
            "review_status": "expectation_reviewed",
        },
    ],
}


@pytest.fixture
def eval_gold(tmp_path):
    p = tmp_path / "eval-gold.json"
    p.write_text(json.dumps(EVAL_GOLD, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.fixture
def expected_identity():
    return {
        "source_fingerprint": fx.FP,
        "catalog_run_snapshot": f"{fx.RUN}/{fx.SNAP}",
        "search_active": fx.SEARCH,
        "gold_sha256": fx.GOLD_SHA,
    }


def _fake_paths(usable_by_path):
    async def runner(q, values, conn, ledger, round_dir, local_adapter_factory=None):
        usable = list(usable_by_path.get(q["query_id"], []))
        fused = fx._fused(
            q["query_id"],
            q["question"],
            usable,
            status="ok" if usable else "missing",
        )
        return {
            "fused_result": fused,
            "rerank_report": None,
            "discovery_status": fused["status"],
            "usable": len(usable),
            "latency_ms": 1,
        }

    return {"pg": runner, "local": runner, "fusion": runner}


def _syn_usable():
    return [
        fx._usable(fx.CP12, fx.DOC_2012, fx.CHUNKS[fx.CP12]["content"]),
        fx._usable(fx.CP26, fx.DOC_2026, fx.CHUNKS[fx.CP26]["content"]),
    ]


def test_dry_run_matrix_246_rows_zero_backend(tmp_path):
    report = asyncio.run(
        ev.run_evaluation(
            tmp_path / "out",
            dry_run=True,
            rounds=[1, 2],
            paths=["pg", "local", "fusion"],
            gold_path=Path("reports/pg-retrieval/gate-2/review-r5/gold-approved.json"),
        )
    )
    assert report["mode"] == "dry_run"
    assert report["backend_fetches"] == 0
    assert report["total_executions"] == 246, "41 questions x 2 rounds x 3 paths"
    b = report["bounds"]
    assert b["path_executions"] == 246
    matrix = json.loads(Path(report["matrix_file"]).read_text())
    assert matrix["denominators"] == {
        "positive_executions": 186,
        "counter_executions": 60,
        "note": matrix["denominators"]["note"],
    }, "positive quality and counter behaviour stay SEPARATE denominators"
    assert all("expected_status" in r for r in matrix["rows"])


def test_dry_run_bounds_positives_36_answer_calls(tmp_path):
    report = asyncio.run(
        ev.run_evaluation(
            tmp_path / "out",
            dry_run=True,
            rounds=[1, 2],
            gold_path=Path("reports/pg-retrieval/gate-2/review-r5/gold-approved.json"),
        )
    )
    bounds = report["bounds"]
    # 6 synthesis positives x 2 rounds x 3 paths = 36 — the corrected budget
    assert bounds["answer_llm_calls_positives"] == 36
    assert bounds["local_or_fusion_legs"] == 164, "41x2 rounds x 2 legs with local"
    services = bounds["services"]
    assert services["llm"]["effective_bound"] == 164
    assert services["rerank"]["effective_bound"] == 82, "fusion path only: 41 x 2 rounds"
    assert services["pg"]["envelope_bound"] >= 123 * 24, "pg covers answer-leg SQL too"


def test_three_paths_same_generation_contract_and_ledger(
    monkeypatch, tmp_path, eval_gold, expected_identity
):
    conn, _ = fx._install(monkeypatch, tmp_path, [fx._gold_q("syn-001", fx.Q_SYN, "synthesis")])
    monkeypatch.setattr(ev, "PATH_RUNNERS", _fake_paths({"syn-001": _syn_usable()}))
    sink = []
    report = asyncio.run(
        ev.run_evaluation(
            tmp_path / "out",
            round_no=1,
            paths=["pg", "local", "fusion"],
            query_ids=["syn-001"],
            gold_path=eval_gold,
            values=fx.VALUES,
            conn=conn,
            transport=fx._model_transport(fx._GOOD_SYN, sink=sink),
            expected_identity=expected_identity,
            user_allows_answer_model=True,
        )
    )
    results = report["results"]
    assert len(results) == 3 and {r["path"] for r in results} == {"pg", "local", "fusion"}
    for r in results:
        # PG has ZERO-model discovery yet still produces a full ANSWER record
        assert r["answer"]["coverage_status"] == "complete", r
        assert r["answer"]["model_status"] == "ok"
        assert r["answer"]["model_calls"] == 1
        assert r["answer"]["items"] == 2
    # SAME downstream generation contract on all three paths
    assert len(sink) == 3
    systems = {json.dumps(p["messages"][0]["content"], ensure_ascii=False) for _, _, p in sink}
    assert len(systems) == 1, "one identical system prompt across paths"
    assert all(p["temperature"] == 0 for _, _, p in sink)
    # ledger: one reserved answer call per synthesis path execution
    snap = report["budget_snapshot_end"]
    assert snap["reserved_total"]["answer_llm"] == 3


def test_local_empty_discovery_never_filled(monkeypatch, tmp_path, eval_gold, expected_identity):
    conn, _ = fx._install(monkeypatch, tmp_path, [fx._gold_q("syn-001", fx.Q_SYN, "synthesis")])
    monkeypatch.setattr(ev, "PATH_RUNNERS", _fake_paths({"syn-001": []}))
    sink = []
    report = asyncio.run(
        ev.run_evaluation(
            tmp_path / "out",
            round_no=1,
            paths=["local"],
            query_ids=["syn-001"],
            gold_path=eval_gold,
            values=fx.VALUES,
            conn=conn,
            transport=fx._model_transport(fx._GOOD_SYN, sink=sink),
            expected_identity=expected_identity,
        )
    )
    r = report["results"][0]
    assert r["answer"]["coverage_status"] == "missing"
    assert r["answer"]["model_calls"] == 0 and sink == []
    # the synthesized input carries ONLY local candidates: none injected
    data = json.loads((tmp_path / "out" / "inputs" / "local" / "syn-001-fusion.json").read_text())
    assert data["results"][0]["usable"] == []
    assert data["results"][0]["status"] == "missing"
    assert data["results"][0]["pg"]["discovery_total"] == 0


def test_expected_status_recorded_but_never_routes(
    monkeypatch, tmp_path, eval_gold, expected_identity
):
    conn, _ = fx._install(
        monkeypatch,
        tmp_path,
        [fx._gold_q("neg-001", EVAL_GOLD["counter_examples"][0]["question"], "fact")],
    )
    monkeypatch.setattr(ev, "PATH_RUNNERS", _fake_paths({"neg-001": _syn_usable()}))
    report = asyncio.run(
        ev.run_evaluation(
            tmp_path / "out",
            round_no=1,
            paths=["pg"],
            query_ids=["neg-001"],
            gold_path=eval_gold,
            values=fx.VALUES,
            conn=conn,
            transport=fx._model_transport(fx._GOOD_SYN),
            expected_identity=expected_identity,
        )
    )
    r = report["results"][0]
    # gold says missing — the entry EXECUTED anyway and recorded actual routing
    assert r["expected_status"] == "missing"
    assert "answer" in r and "budget_failure" not in r and "failure" not in r
    assert r["discovery"]["status"] == "ok"


def test_single_batch_over_limit_zero_calls(tmp_path):
    ledger = ev.BudgetLedger(ev.BudgetSpec(), [1])
    ledger.override_question_envelope("qdrant", 1)
    calls = []

    async def main():
        ledger.begin_question("w/q")
        with ev.budgeted_local_boundary(ledger, "w"):
            boundary = ev.BudgetedServiceBoundary()

            async def embed(texts):
                calls.append(texts)
                return []

            with pytest.raises(ev.BudgetExhausted):
                await boundary.call("embedding", "openai_embed", embed, ["x" * 10] * 64)

    asyncio.run(main())
    assert calls == [], "over-limit batch NEVER issued"
    refusals = [e for e in ledger.events if e["kind"] == "budget_refusal"]
    assert len(refusals) == 1 and refusals[0]["issued"] == 0


def test_last_service_quota_exhausted_no_over_limit_call(tmp_path):
    ledger = ev.BudgetLedger(ev.BudgetSpec(), [1])
    ledger.override_question_envelope("qdrant", 1)
    calls = []

    async def main():
        ledger.begin_question("w/q")
        with ev.budgeted_local_boundary(ledger, "w"):
            boundary = ev.BudgetedServiceBoundary()

            async def ok_call():
                calls.append(1)
                return []

            await boundary.call("qdrant", "query_points", ok_call)
            with pytest.raises(ev.BudgetExhausted):
                await boundary.call("qdrant", "query_points", ok_call)

    asyncio.run(main())
    assert len(calls) == 1, "envelope exhausted: second call never issued"
    assert ledger.events[-1]["kind"] == "budget_refusal"


def test_neg008_constructed_budget_precondition(
    monkeypatch, tmp_path, eval_gold, expected_identity
):
    """E4: the constructed micro budget is REAL — it travels through the answer
    contract into the prose reader (max_members/max_chars) via the explicit
    seam, it is not a service-call count masquerading as an enumeration
    budget, and execution is attributed to an isolated fixture."""
    conn, _ = fx._install(
        monkeypatch,
        tmp_path,
        [fx._gold_q("neg-008", EVAL_GOLD["counter_examples"][1]["question"], "prose_enum")],
    )
    observed = []

    async def answer_stub(*args, **kwargs):
        observed.append(kwargs)
        return {
            "results": [{"coverage_status": "partial", "answer": {"items": []}}],
            "model_calls_used": 0,
        }

    async def local_runner(q, values, conn, ledger, round_dir, local_adapter_factory=None):
        fused = fx._fused(q["query_id"], q["question"], [], status="partial")
        return {
            "fused_result": fused,
            "rerank_report": None,
            "discovery_status": "partial",
            "usable": 0,
            "latency_ms": 1,
        }

    monkeypatch.setattr(ev, "PATH_RUNNERS", {"local": local_runner})
    monkeypatch.setattr(ev, "_run_answer", answer_stub)
    report = asyncio.run(
        ev.run_evaluation(
            tmp_path / "out",
            round_no=1,
            paths=["local"],
            query_ids=["neg-008"],
            gold_path=eval_gold,
            values=fx.VALUES,
            conn=conn,
            transport=fx._model_transport(fx._GOOD_SYN),
            expected_identity=expected_identity,
        )
    )
    r = report["results"][0]
    assert r["execution_attribution"] == "isolated_fixture"
    assert observed, "the answer contract ran for the counter"
    assert observed[0]["expand_budgets"] == {"neg-008": {"max_members": 1, "max_chars": 120}}, (
        "micro budget reaches the answer contract through the seam"
    )
    assert observed[0]["category_overrides"] == {"neg-008": "prose_enum"}
    # the envelope override must NOT leak into later questions
    assert report["budget_snapshot_end"]["caps"]["per_question"]["qdrant"] == 8


def test_failure_isolated_terminal_and_secrets_sanitized(
    monkeypatch, tmp_path, eval_gold, expected_identity
):
    conn, _ = fx._install(
        monkeypatch,
        tmp_path,
        [
            fx._gold_q("syn-001", fx.Q_SYN, "synthesis"),
            fx._gold_q("fact-001", fx.Q_FACT, "fact"),
        ],
    )

    async def boom_runner(q, values, conn, ledger, round_dir, local_adapter_factory=None):
        raise ValueError(f"broken leg for {q['query_id']}: {fx.VALUES['LLM_BINDING_API_KEY']}")

    async def ok_runner(q, values, conn, ledger, round_dir, local_adapter_factory=None):
        fused = fx._fused(q["query_id"], q["question"], [], status="missing")
        return {
            "fused_result": fused,
            "rerank_report": None,
            "discovery_status": "missing",
            "usable": 0,
            "latency_ms": 1,
        }

    paths = {"pg": boom_runner, "local": ok_runner, "fusion": ok_runner}
    monkeypatch.setattr(ev, "PATH_RUNNERS", paths)
    report = asyncio.run(
        ev.run_evaluation(
            tmp_path / "out",
            round_no=1,
            query_ids=["syn-001", "fact-001"],
            gold_path=eval_gold,
            values=fx.VALUES,
            conn=conn,
            transport=fx._model_transport(fx._GOOD_SYN),
            expected_identity=expected_identity,
        )
    )
    assert "identity_after" in report, "post identity still captured after failures"
    failed = [r for r in report["results"] if "failure" in r]
    assert {r["path"] for r in failed} == {"pg"}, "boom leg fails, others isolated"
    ok = [r for r in report["results"] if "failure" not in r]
    assert ok, "other paths/questions keep executing"
    runtime = (tmp_path / "out" / "eval-runtime-latest.json").read_text()
    assert fx.VALUES["LLM_BINDING_API_KEY"] not in runtime
    assert "<redacted>" in runtime


def test_completed_generation_refuses_reuse(monkeypatch, tmp_path, eval_gold, expected_identity):
    conn, _ = fx._install(monkeypatch, tmp_path, [])
    monkeypatch.setattr(ev, "PATH_RUNNERS", _fake_paths({}))
    first = asyncio.run(
        ev.run_evaluation(
            tmp_path / "out",
            round_no=1,
            paths=["pg"],
            query_ids=[],
            gold_path=eval_gold,
            values=fx.VALUES,
            conn=conn,
            expected_identity=expected_identity,
        )
    )
    assert first["results"] == []
    with pytest.raises(ev.AdapterError, match="new generation"):
        asyncio.run(
            ev.run_evaluation(
                tmp_path / "out",
                round_no=1,
                paths=["pg"],
                gold_path=eval_gold,
                values=fx.VALUES,
                conn=conn,
                expected_identity=expected_identity,
            )
        )


def test_config_drift_refused_before_any_question(monkeypatch, tmp_path, eval_gold):
    conn, counters = fx._install(monkeypatch, tmp_path, [])
    monkeypatch.setattr(ev, "PATH_RUNNERS", _fake_paths({}))
    bad = {
        "source_fingerprint": "drifted-fingerprint-value",
        "catalog_run_snapshot": f"{fx.RUN}/{fx.SNAP}",
        "search_active": fx.SEARCH,
        "gold_sha256": fx.GOLD_SHA,
    }
    with pytest.raises(ev.AdapterError, match="config drift"):
        asyncio.run(
            ev.run_evaluation(
                tmp_path / "out",
                round_no=1,
                paths=["pg"],
                gold_path=eval_gold,
                values=fx.VALUES,
                conn=conn,
                expected_identity=bad,
            )
        )
    assert counters["identity"] == 1, "pre capture only — no question executed after drift"


def test_budget_envelope_override_restored_between_questions(
    monkeypatch, tmp_path, eval_gold, expected_identity
):
    conn, _ = fx._install(
        monkeypatch,
        tmp_path,
        [
            fx._gold_q("neg-008", EVAL_GOLD["counter_examples"][1]["question"], "prose_enum"),
            fx._gold_q("fact-001", fx.Q_FACT, "fact"),
        ],
    )

    async def runner(q, values, conn, ledger, round_dir, local_adapter_factory=None):
        fused = fx._fused(q["query_id"], q["question"], [], status="missing")
        return {
            "fused_result": fused,
            "rerank_report": None,
            "discovery_status": "missing",
            "usable": 0,
            "latency_ms": 1,
        }

    monkeypatch.setattr(ev, "PATH_RUNNERS", {"local": runner})
    report = asyncio.run(
        ev.run_evaluation(
            tmp_path / "out",
            round_no=1,
            paths=["local"],
            gold_path=eval_gold,
            values=fx.VALUES,
            conn=conn,
            transport=fx._model_transport(fx._GOOD_SYN),
            expected_identity=expected_identity,
        )
    )
    assert len(report["results"]) == 4
    snap = report["budget_snapshot_end"]
    assert snap["caps"]["per_question"]["qdrant"] == ev.BudgetSpec().per_question["qdrant"], (
        "neg-008 override is per-question only"
    )


def test_frozen_execution_matrix_artifact_matches_gold():
    """The frozen dry-run artifact (committed under reports/) must agree with
    the gold file it was derived from."""
    matrix = json.loads(Path("reports/pg-retrieval/phase-4/execution-matrix.json").read_text())
    gold = json.loads(Path("reports/pg-retrieval/gate-2/review-r5/gold-approved.json").read_text())
    assert matrix["gold_sha256"] == (
        __import__("hashlib")
        .sha256(Path("reports/pg-retrieval/gate-2/review-r5/gold-approved.json").read_bytes())
        .hexdigest()
    )
    assert matrix["total_executions"] == 246
    assert len(matrix["rows"]) == 246
    assert matrix["denominators"]["positive_executions"] == 186
    assert matrix["denominators"]["counter_executions"] == 60
    ids = {r["query_id"] for r in matrix["rows"]}
    assert {q["query_id"] for q in gold["questions"]} <= ids
    assert {c["counter_id"] for c in gold["counter_examples"]} <= ids
    bounds = json.loads(Path("reports/pg-retrieval/phase-4/budget-upper-bounds.json").read_text())
    assert bounds["answer_llm_calls_positives"] == 36
    assert bounds["path_executions"] == 246


# ---------------------------------------------------------------------------
# E1-E6 necessary positives (per 6.1-fixes-r1 handoff): the guards must also
# let legitimate traffic through, and isolation/degradation are OBSERVED.
# ---------------------------------------------------------------------------


def test_local_rejects_foreign_workspace_and_unverified(
    monkeypatch, tmp_path, eval_gold, expected_identity
):
    # E1/E4 positive: cross-workspace and unverified candidates are refused
    # WITH EVIDENCE (never silently dropped, never filled from elsewhere).
    conn, _ = fx._install(monkeypatch, tmp_path, [fx._gold_q("fact-001", fx.Q_FACT, "fact")])
    from env_rag_final import local_adapter as la

    cand_foreign = la.Candidate(fx.C1, "other-ns", fx.DOC_8978, "gb8978.pdf", "head", 4, True)
    cand_unverified = la.Candidate(fx.C1, "default", fx.DOC_8978, "gb8978.pdf", "head", 4, False)

    class Adapter:
        async def fetch(self, *a, **kw):
            from types import SimpleNamespace

            return SimpleNamespace(
                candidates=[cand_foreign, cand_unverified],
                call_records=[],
                service_calls={},
                degraded=[],
                sorting_sources={},
            )

    report = asyncio.run(
        ev.run_evaluation(
            tmp_path / "out",
            paths=["local"],
            query_ids=["fact-001"],
            gold_path=eval_gold,
            values=fx.VALUES,
            conn=conn,
            local_adapter_factory=lambda *a: Adapter(),
            expected_identity=expected_identity,
        )
    )
    r = report["results"][0]
    assert r["discovery"]["usable"] == 0
    reasons = [ref["reason"] for ref in r["receipts"]["refused_candidates"]]
    assert any("cross-workspace" in x for x in reasons), reasons
    assert any("not source-verified" in x for x in reasons), reasons


def test_rerank_degradation_passes_through_fresh_report(
    monkeypatch, tmp_path, eval_gold, expected_identity
):
    # E1 positive: a degraded rerank stays visible in the fresh replayed
    # report — never upgraded to success by the evaluation layer.
    conn, _ = fx._install(monkeypatch, tmp_path, [fx._gold_q("fact-001", fx.Q_FACT, "fact")])

    async def fusion_stub(report_dir, queries, **kw):
        return {
            "results": [
                fx._fused(
                    queries[0],
                    fx.Q_FACT,
                    [fx._usable(fx.C1, fx.DOC_8978, fx.CHUNKS[fx.C1]["content"])],
                )
            ]
        }

    async def rerank_stub(*a, **kw):
        return {
            "results": [
                {
                    "query_id": "fact-001",
                    "status": "degraded",
                    "ordered": [],
                    "degraded": ["http_408 fixture"],
                    "call": {"status": "failure", "error": "http_408"},
                }
            ]
        }

    seen = []

    async def answer_stub(*args, **kwargs):
        seen.append(kwargs)
        return {
            "results": [{"coverage_status": "partial", "answer": {"items": []}}],
            "model_calls_used": 0,
        }

    monkeypatch.setattr(ev, "_run_fusion", fusion_stub)
    monkeypatch.setattr(ev, "_run_rerank", rerank_stub)
    monkeypatch.setattr(ev, "_run_answer", answer_stub)
    report = asyncio.run(
        ev.run_evaluation(
            tmp_path / "out",
            paths=["fusion"],
            query_ids=["fact-001"],
            gold_path=eval_gold,
            values=fx.VALUES,
            conn=conn,
            expected_identity=expected_identity,
        )
    )
    r = report["results"][0]
    assert r["timings"].get("rerank_ms") is not None
    replay = json.loads(seen[0]["rerank_report_path"].read_text())
    assert replay["results"][0]["status"] == "degraded"
    assert replay["results"][0]["degraded"], "degradation stays visible end-to-end"
    assert report["budget_snapshot_end"]["reserved_total"]["rerank"] == 1


def test_quotas_just_sufficient_still_issue(monkeypatch, tmp_path, eval_gold, expected_identity):
    # E2 companion positive: envelopes at EXACTLY the legitimate count issue
    # every call — budgeting must not become false starvation.
    from env_rag_final import local_adapter as la

    conn, _ = fx._install(monkeypatch, tmp_path, [fx._gold_q("fact-001", fx.Q_FACT, "fact")])
    issued = []

    async def runner(q, values, conn, ledger, round_dir, local_adapter_factory=None):
        async def ok_call():
            issued.append(1)
            return []

        boundary = la.ServiceBoundary()
        await boundary.call("qdrant", "query_points", ok_call)
        await boundary.call("qdrant", "query_points", ok_call)
        return {
            "fused_result": fx._fused(q["query_id"], q["question"], [], status="missing"),
            "rerank_report": None,
            "discovery_status": "missing",
            "usable": 0,
            "latency_ms": 1,
            "receipts": {},
        }

    monkeypatch.setattr(ev, "PATH_RUNNERS", {"local": runner})
    report = asyncio.run(
        ev.run_evaluation(
            tmp_path / "out",
            paths=["local"],
            query_ids=["fact-001"],
            gold_path=eval_gold,
            values=fx.VALUES,
            conn=conn,
            budgets={"per_question": {"qdrant": 2}},
            expected_identity=expected_identity,
        )
    )
    assert len(issued) == 2
    assert "budget_failure" not in report["results"][0]
    assert report["budget_snapshot_end"]["issued_total"]["qdrant"] == 2


def test_dry_run_subset_is_consistent_with_full_matrix(tmp_path):
    # E6: selection re-compiles the SAME matrix semantics; nothing is hidden
    # by shrinking denominators of the FULL run.
    full = asyncio.run(
        ev.run_evaluation(
            tmp_path / "full",
            dry_run=True,
            rounds=[1, 2],
            gold_path=Path("reports/pg-retrieval/gate-2/review-r5/gold-approved.json"),
        )
    )
    subset = asyncio.run(
        ev.run_evaluation(
            tmp_path / "subset",
            dry_run=True,
            rounds=[1, 2],
            query_ids=["fact-002", "syn-004"],
            gold_path=Path("reports/pg-retrieval/gate-2/review-r5/gold-approved.json"),
        )
    )
    assert full["total_executions"] == 246
    assert subset["total_executions"] == 2 * 3 * 2
    full_rows = {
        (r["round"], r["path"], r["query_id"]): r
        for r in json.loads(Path(full["matrix_file"]).read_text())["rows"]
    }
    for r in json.loads(Path(subset["matrix_file"]).read_text())["rows"]:
        assert full_rows[(r["round"], r["path"], r["query_id"])]["category"] == r["category"]


# ---------------------------------------------------------------------------
# rev-2 own cases (R1–R4): production connection/context shapes, receipts
# vs reservations, schema and anchor completeness, actual-resource
# attribution, verbatim provenance — offline, fake I/O only.
# ---------------------------------------------------------------------------


def _answer_stub(*_args, **_kwargs):
    return {
        "results": [{"coverage_status": "missing", "answer": {"items": []}}],
        "model_calls_used": 0,
    }


def _stage(q):
    return {
        "fused_result": fx._fused(q["query_id"], q["question"], [], status="missing"),
        "rerank_report": None,
        "discovery_status": "missing",
        "usable": 0,
        "latency_ms": 1,
        "receipts": {},
    }


def test_neo4j_both_production_shapes_gated_exactly_once(
    monkeypatch, tmp_path, eval_gold, expected_identity
):
    # R1 positive: direct driver.session().run AND async-with entered session
    # each pass ONE gate + ONE issued mark at a just-sufficient cap — no
    # double-billing, no false starvation, native receipts preserved.
    from env_rag_final import local_adapter as la

    conn, _ = fx._install(monkeypatch, tmp_path, [fx._gold_q("fact-001", fx.Q_FACT, "fact")])
    issued = []

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def run(self, *_a, **_kw):
            issued.append(1)
            return []

    class Driver:
        def session(self, *_a, **_kw):
            return Session()

    async def runner(q, values, conn, ledger, round_dir, local_adapter_factory=None):
        boundary = la.ServiceBoundary()
        driver = la._RecordingNeo4jDriver(Driver(), boundary)
        await driver.session().run("MATCH (a) RETURN 1")
        async with driver.session() as entered:
            await entered.run("MATCH (b) RETURN 1")
        stage = _stage(q)
        stage["receipts"] = {
            "call_records": [dict(vars(r)) for r in boundary.records],
            "service_calls": boundary.counts(),
            "degraded": [],
            "sorting_sources": {},
        }
        return stage

    monkeypatch.setattr(ev, "PATH_RUNNERS", {"local": runner})
    monkeypatch.setattr(ev, "_run_answer", _answer_stub)
    report = asyncio.run(
        ev.run_evaluation(
            tmp_path / "out",
            paths=["local"],
            query_ids=["fact-001"],
            gold_path=eval_gold,
            values=fx.VALUES,
            conn=conn,
            budgets={"per_question": {"neo4j": 2}},
            expected_identity=expected_identity,
        )
    )
    r = report["results"][0]
    assert len(issued) == 2 and "budget_failure" not in r
    snap = report["budget_snapshot_end"]
    assert snap["reserved_total"]["neo4j"] == 2, "one reservation per executed run"
    assert snap["issued_total"]["neo4j"] == 2, "one issued mark per executed run"
    assert len(r["receipts"]["call_records"]) == 2, "native recording receipts untouched"


def _install_self_conn(monkeypatch):
    """Fake PG seam for the CLI production form: nothing passes conn, code
    self-connects via asyncpg.connect; record every statement that arrives."""
    import asyncpg

    queries: list = []

    class SelfConn:
        async def fetch(self, sql, *_a):
            queries.append(sql)
            return []

        async def fetchrow(self, sql, *_a):
            queries.append(sql)
            return None

        async def fetchval(self, sql, *_a):
            queries.append(sql)
            return None

        async def close(self):
            queries.append("CLOSE")

    async def connect(**_kwargs):
        return SelfConn()

    monkeypatch.setattr(asyncpg, "connect", connect)
    return queries


def test_cli_shape_self_made_connection_billed_and_capped(
    monkeypatch, tmp_path, eval_gold, expected_identity
):  # noqa: E501
    # R1: the CLI form (conn=None) must still budget SELF-MADE connections.
    # installed AFTER fx._install so this fake connect is what the leg seam wraps
    fx._install(monkeypatch, tmp_path, [fx._gold_q("fact-001", fx.Q_FACT, "fact")])
    queries = _install_self_conn(monkeypatch)

    async def runner(q, values, conn, ledger, round_dir, local_adapter_factory=None):
        assert conn is None, "CLI form: nothing injects a connection"
        return _stage(q)

    async def answer_like(*args, **kwargs):
        assert "conn" not in kwargs, "the entry opens its own connection (production)"
        import asyncpg

        own = await asyncpg.connect()
        try:
            for i in range(3):
                await own.fetch(f"SELECT {i}")
        finally:
            await own.close()
        return {
            "results": [{"coverage_status": "missing", "answer": {"items": []}}],
            "model_calls_used": 0,
        }

    monkeypatch.setattr(ev, "PATH_RUNNERS", {"local": runner})
    monkeypatch.setattr(ev, "_run_answer", answer_like)
    report = asyncio.run(
        ev.run_evaluation(
            tmp_path / "ok",
            paths=["local"],
            query_ids=["fact-001"],
            gold_path=eval_gold,
            values=fx.VALUES,
            conn=None,
            budgets={"per_question": {"pg": 3}},
            expected_identity=expected_identity,
        )
    )
    assert "budget_failure" not in report["results"][0], report
    assert queries == ["SELECT 0", "SELECT 1", "SELECT 2", "CLOSE"], queries
    assert report["budget_snapshot_end"]["issued_total"]["pg"] == 3

    # just over the cap: the statement beyond it is NEVER forwarded
    queries.clear()
    report2 = asyncio.run(
        ev.run_evaluation(
            tmp_path / "cap",
            paths=["local"],
            query_ids=["fact-001"],
            gold_path=eval_gold,
            values=fx.VALUES,
            conn=None,
            budgets={"per_question": {"pg": 2}},
            expected_identity=expected_identity,
        )
    )
    r2 = report2["results"][0]
    assert "budget_failure" in r2, r2
    assert queries == ["SELECT 0", "SELECT 1", "CLOSE"], queries
    assert report2["budget_snapshot_end"]["issued_total"]["pg"] == 2
    assert r2["budget_failure"]["calls_issued"] == 0, "the refused statement issued zero"


def test_answer_stage_swallowed_refusal_is_never_clean(
    monkeypatch, tmp_path, eval_gold, expected_identity
):
    # R2: a refusal swallowed INSIDE the answer entry (library catches it) is
    # caught by the post-answer ledger delta — marked, never unlabelled.
    conn, _ = fx._install(monkeypatch, tmp_path, [fx._gold_q("fact-001", fx.Q_FACT, "fact")])

    async def runner(q, values, conn, ledger, round_dir, local_adapter_factory=None):
        return _stage(q)

    async def swallowing_answer(*args, **kwargs):
        try:
            await kwargs["conn"].fetch("SELECT inside-entry")
        except ev.BudgetExhausted:
            pass  # mimics the release VECTOR helper catching everything
        return {
            "results": [{"coverage_status": "complete", "answer": {"items": []}}],
            "model_calls_used": 0,
        }

    monkeypatch.setattr(ev, "PATH_RUNNERS", {"local": runner})
    monkeypatch.setattr(ev, "_run_answer", swallowing_answer)
    report = asyncio.run(
        ev.run_evaluation(
            tmp_path / "out",
            paths=["local"],
            query_ids=["fact-001"],
            gold_path=eval_gold,
            values=fx.VALUES,
            conn=conn,
            budgets={"per_question": {"pg": 0}},
            expected_identity=expected_identity,
        )
    )
    r = report["results"][0]
    assert "budget_failure" in r and r["budget_failure"]["stage"] == "answer", r
    assert r["budget_failure"]["calls_issued"] == 0
    assert report["budget_snapshot_end"]["issued_total"].get("pg", 0) == 0


def test_executed_failed_answer_call_stays_issued(
    monkeypatch, tmp_path, eval_gold, expected_identity
):
    # R2 bill side: a model call that REALLY ran and then failed must not be
    # rewritten to zero — issuance comes from the entry's runtime receipt
    # even on the exception path.
    conn, _ = fx._install(monkeypatch, tmp_path, [fx._gold_q("syn-001", fx.Q_SYN, "synthesis")])

    async def runner(q, values, conn, ledger, round_dir, local_adapter_factory=None):
        return _stage(q)

    async def failing_answer(report_dir_arg, _ids, **_kwargs):
        runtime = Path(report_dir_arg) / "answer-runtime-latest.json"
        runtime.parent.mkdir(parents=True, exist_ok=True)
        runtime.write_text(json.dumps({"model_calls_used": 1, "results": []}), encoding="utf-8")
        raise ev.AdapterError("model HTTP request ran and failed")

    monkeypatch.setattr(ev, "PATH_RUNNERS", {"local": runner})
    monkeypatch.setattr(ev, "_run_answer", failing_answer)
    report = asyncio.run(
        ev.run_evaluation(
            tmp_path / "out",
            paths=["local"],
            query_ids=["syn-001"],
            gold_path=eval_gold,
            values=fx.VALUES,
            conn=conn,
            expected_identity=expected_identity,
            user_allows_answer_model=True,
        )
    )
    r = report["results"][0]
    assert "failure" in r and "budget_failure" not in r
    snap = report["budget_snapshot_end"]
    assert snap["reserved_total"]["answer_llm"] == 1
    assert snap["issued_total"]["answer_llm"] == 1, "executed-then-failed stays billed"


def test_budget_spec_schema_rejects_before_any_use():
    # R3: caps are schema-checked at parse time — None unbinds, negatives fail
    # late, bools/floats/unknown services must all be refused up front.
    for bad in (None, -1, True, 1.5, "2"):
        with pytest.raises(ev.AdapterError):
            ev.BudgetSpec.from_dict({"per_question": {"qdrant": bad}})
    with pytest.raises(ev.AdapterError):
        ev.BudgetSpec.from_dict({"per_question": {"weaviate": 4}})
    with pytest.raises(ev.AdapterError):
        ev.BudgetSpec.from_dict({"nonsense_section": {}})
    with pytest.raises(ev.AdapterError):
        ev.BudgetSpec.from_dict({"max_texts_per_embed_call": 0})
    ok = ev.BudgetSpec.from_dict({"per_question": {"qdrant": 0}, "total_caps": {"pg": 0}})
    assert ok.per_question["qdrant"] == 0, "0 legally forbids issuing — valid config"
    assert ok.total_caps["pg"] == 0


def _anchor_values(anchor: dict) -> dict:
    # the ACTUAL required model inputs of the frozen config, keyword included
    # (S2: local/fusion term extraction is pinned by this identity too)
    mc = anchor["model_config"]
    return {
        "QUERY_LLM_MODEL": mc["answer_query_llm"]["value"],
        "LLM_BINDING_HOST": "http://127.0.0.1:8787/v1",
        "KEYWORD_LLM_MODEL": mc["keyword_llm"]["value"],
        "LLM_MODEL": mc["keyword_llm"]["value"],
        "EMBEDDING_MODEL": mc["embedding"]["value"],
        "EMBEDDING_DIM": str(mc["embedding"]["dim"]),
        "EMBEDDING_BINDING_HOST": "https://api.siliconflow.cn/v1",
        "RERANK_MODEL": mc["rerank"]["value"],
        "RERANK_BINDING_HOST": "https://api.siliconflow.cn/v1/rerank",
    }


def _regenerated_anchor(tmp_path: Path) -> Path:
    """A hypothetical NEW code-anchor generation built ONLY in tmp_path (the
    real phase-4 anchor stays untouched): source SHAs aligned to the current
    authorized-seam bytes, everything else copied from the frozen anchor."""
    anchor = json.loads(ev.CONFIG_ANCHOR.read_text(encoding="utf-8"))
    src = Path("src/env_rag_final")
    for fname in list(anchor["code_anchors"]):
        if fname.endswith(".py"):
            anchor["code_anchors"][fname] = hashlib.sha256((src / fname).read_bytes()).hexdigest()
    p = tmp_path / "anchor-gen2.json"
    p.write_text(json.dumps(anchor, ensure_ascii=False), encoding="utf-8")
    return p


def test_validate_phase4_anchor_full_config_and_drifts(tmp_path):
    # R3: the complete frozen anchor — zero backend, no per-run override.
    anchor = json.loads(ev.CONFIG_ANCHOR.read_text(encoding="utf-8"))
    values = _anchor_values(anchor)

    # 1) every NON-answer component still matches its anchor byte-for-byte;
    #    the approved answer.py seam change is REPORTED as drift, never
    #    silently papered over (the new Phase 4 generation is established by
    #    the main agent AFTER 6.1 acceptance — not by editing the old ledger).
    with pytest.raises(ev.AdapterError) as drift:
        ev.validate_phase4_anchor(values=values)
    msg = str(drift.value)
    assert "answer.py" in msg, msg
    for other in ("rerank.py", "fusion.py", "local_adapter.py", "compat_runtime.py"):
        assert other not in msg, f"{other} unexpectedly drifted: {msg}"

    # 2) a CONSISTENT generation (simulating the post-approval re-freeze on a
    #    temp copy — the real anchor stays untouched) validates completely.
    p = _regenerated_anchor(tmp_path)
    expected = ev.validate_phase4_anchor(anchor_path=p, values=values)
    fi = json.loads(p.read_text(encoding="utf-8"))["frozen_identity"]
    assert expected == {
        "source_fingerprint": fi["source_fingerprint"],
        "catalog_run_snapshot": fi["catalog_run_snapshot"],
        "search_active": fi["search_active"],
        "gold_sha256": fi["gold_sha256"],
    }

    # 3) negatives: model swap, missing anchor, absent config keys.
    with pytest.raises(ev.AdapterError, match="QUERY_LLM_MODEL"):
        ev.validate_phase4_anchor(anchor_path=p, values=dict(values, QUERY_LLM_MODEL="other"))
    with pytest.raises(ev.AdapterError, match="refusing before any backend contact"):
        ev.validate_phase4_anchor(anchor_path=Path("nope/anchor.json"), values=values)
    with pytest.raises(ev.AdapterError):
        ev.validate_phase4_anchor(anchor_path=p, values={"POSTGRES_HOST": "x"})


def test_keyword_identity_pinned_and_fallback_resolves(tmp_path):
    # S2 positives/negative: exact keyword match validates; the production
    # fallback (KEYWORD_LLM_MODEL absent -> LLM_MODEL) also validates; drift
    # or total absence refuses — two evaluation rounds must extract terms
    # with the same model to stay comparable.
    p = _regenerated_anchor(tmp_path)
    anchor = json.loads(p.read_text(encoding="utf-8"))
    values = _anchor_values(anchor)
    ev.validate_phase4_anchor(anchor_path=p, values=values)

    fallback = {k: v for k, v in values.items() if k != "KEYWORD_LLM_MODEL"}
    ev.validate_phase4_anchor(anchor_path=p, values=fallback)

    with pytest.raises(ev.AdapterError, match="keyword"):
        ev.validate_phase4_anchor(
            anchor_path=p,
            values=dict(values, KEYWORD_LLM_MODEL="another-keyword-model"),
        )
    bare = {k: v for k, v in values.items() if k not in ("KEYWORD_LLM_MODEL", "LLM_MODEL")}
    with pytest.raises(ev.AdapterError, match="keyword LLM identity absent"):
        ev.validate_phase4_anchor(anchor_path=p, values=bare)


def test_empty_anchor_sections_are_completeness_violations(tmp_path):
    # S2: an empty code_anchors/frozen_budgets/model_config/frozen_identity
    # section is NOT an optional skip — completeness is verified first.
    intact = json.loads(_regenerated_anchor(tmp_path).read_text(encoding="utf-8"))
    values = _anchor_values(intact)
    for section in ("code_anchors", "frozen_budgets", "model_config", "frozen_identity"):
        anchor = copy.deepcopy(intact)
        anchor[section] = {}
        bad = tmp_path / f"anchor-empty-{section}.json"
        bad.write_text(json.dumps(anchor, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(ev.AdapterError, match=section):
            ev.validate_phase4_anchor(anchor_path=bad, values=values)


def test_rerank_issuance_reconciled_from_call_receipt(
    monkeypatch, tmp_path, eval_gold, expected_identity
):
    # S1: entering the rerank entry is NOT the receipt. A result without any
    # call key → explicit unknown, unbilled; an exception AFTER a published
    # in-flight HTTP record → billed from THIS question's runtime; a guard
    # terminal without calls → zero. Reserved stays the pre-request gate.
    conn, _ = fx._install(monkeypatch, tmp_path, [fx._gold_q("fact-001", fx.Q_FACT, "fact")])

    async def fusion_stub(*a, **kw):
        return {
            "results": [
                fx._fused(
                    "fact-001",
                    fx.Q_FACT,
                    [fx._usable(fx.C1, fx.DOC_8978, fx.CHUNKS[fx.C1]["content"])],
                )
            ]
        }

    async def answer_stub(*a, **kw):
        return {
            "results": [{"coverage_status": "missing", "answer": {"items": []}}],
            "model_calls_used": 0,
        }

    async def no_call_rerank(*a, **kw):
        return {
            "results": [{"query_id": "fact-001", "status": "ok", "ordered": [], "degraded": []}]
        }

    monkeypatch.setattr(ev, "_run_fusion", fusion_stub)
    monkeypatch.setattr(ev, "_run_rerank", no_call_rerank)
    monkeypatch.setattr(ev, "_run_answer", answer_stub)
    report = asyncio.run(
        ev.run_evaluation(
            tmp_path / "unknown",
            paths=["fusion"],
            query_ids=["fact-001"],
            gold_path=eval_gold,
            values=fx.VALUES,
            conn=conn,
            expected_identity=expected_identity,
        )
    )
    r = report["results"][0]
    assert r["rerank_issuance"] == "unknown-no-receipt", r
    snap = report["budget_snapshot_end"]
    assert snap["reserved_total"]["rerank"] == 1
    assert snap["issued_total"].get("rerank", 0) == 0

    async def raising_rerank(report_dir, query_ids, **kw):
        p = Path(report_dir) / "rerank-runtime-latest.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {
                    "failure": {"stage": "rerank", "detail": "timeout"},
                    "failure_service_records": {
                        "query_id": "fact-001",
                        "call_records": [{"service": "rerank", "status": "failure"}],
                    },
                }
            ),
            encoding="utf-8",
        )
        raise ev.AdapterError("rerank run failed after the HTTP attempt")

    monkeypatch.setattr(ev, "_run_rerank", raising_rerank)
    report2 = asyncio.run(
        ev.run_evaluation(
            tmp_path / "executed",
            paths=["fusion"],
            query_ids=["fact-001"],
            gold_path=eval_gold,
            values=fx.VALUES,
            conn=conn,
            expected_identity=expected_identity,
        )
    )
    snap2 = report2["budget_snapshot_end"]
    assert snap2["reserved_total"]["rerank"] == 1
    assert snap2["issued_total"]["rerank"] == 1, "executed-then-failed stays billed"
    r2rec = report2["results"][0]
    assert "failure" in r2rec
    assert r2rec["rerank_issuance"] == "executed", r2rec
    terminal2 = json.loads((tmp_path / "executed" / "eval-runtime-latest.json").read_text())
    assert terminal2["results"][0]["rerank_issuance"] == "executed", "failed leg carries the state"

    async def guard_rerank(report_dir, query_ids, **kw):
        p = Path(report_dir) / "rerank-runtime-latest.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps({"failure": {"stage": "pre-flight", "detail": "source guard refused"}}),
            encoding="utf-8",
        )
        raise ev.AdapterError("refused before HTTP")

    monkeypatch.setattr(ev, "_run_rerank", guard_rerank)
    report3 = asyncio.run(
        ev.run_evaluation(
            tmp_path / "prehttp",
            paths=["fusion"],
            query_ids=["fact-001"],
            gold_path=eval_gold,
            values=fx.VALUES,
            conn=conn,
            expected_identity=expected_identity,
        )
    )
    assert report3["budget_snapshot_end"]["issued_total"].get("rerank", 0) == 0
    assert report3["results"][0]["rerank_issuance"] == "before-http-zero"

    # FOREIGN in-flight receipt: another question's call never counts here,
    # and the mere existence of a mid-run failure is NOT proof THIS question
    # stopped before HTTP — explicitly unknown, unbilled.
    async def foreign_rerank(report_dir, query_ids, **kw):
        p = Path(report_dir) / "rerank-runtime-latest.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {
                    "failure": {"stage": "rerank", "detail": "different question"},
                    "failure_service_records": {
                        "query_id": "another-question",
                        "call_records": [{"service": "rerank", "status": "failure"}],
                    },
                }
            ),
            encoding="utf-8",
        )
        raise ev.AdapterError("no usable receipt for THIS question")

    monkeypatch.setattr(ev, "_run_rerank", foreign_rerank)
    report4 = asyncio.run(
        ev.run_evaluation(
            tmp_path / "foreign",
            paths=["fusion"],
            query_ids=["fact-001"],
            gold_path=eval_gold,
            values=fx.VALUES,
            conn=conn,
            expected_identity=expected_identity,
        )
    )
    assert report4["budget_snapshot_end"]["issued_total"].get("rerank", 0) == 0, "no borrowed calls"
    assert report4["results"][0]["rerank_issuance"] == "unknown-no-receipt"


def test_attribution_follows_actual_resources_not_labels():
    # evidence limit from the review: a constructed micro budget on a
    # production read-only leg is NOT an isolated fixture; the label follows
    # what the leg actually ran on.
    neg8 = {
        "kind": "enum_member_budget",
        "execution_attribution": "production_readonly_with_constructed_budget",
        "attribution_note": "constructed micro budget reaches the real prose reader...",
    }
    q8 = {"is_counter": True, "category": "prose_enum", "workspace": "default"}
    real = ev._ORIGINAL_PATH_RUNNERS["local"]
    attribution, note = ev._leg_attribution(q8, neg8, real, "local", None)
    assert attribution == "production_readonly_with_constructed_budget" and note
    assert ev._leg_attribution(q8, neg8, real, "local", lambda *a: None)[0] == "isolated_fixture"
    swapped, n = ev._leg_attribution(q8, neg8, lambda *a: None, "local", None)
    assert swapped == "isolated_fixture" and "test seam" in n
    qpos = {"is_counter": False, "category": "fact", "workspace": "default"}
    assert ev._leg_attribution(qpos, {}, real, "local", None)[0] == "real_entry"


def test_local_provenance_reaches_the_inputs_artifact(
    monkeypatch, tmp_path, eval_gold, expected_identity
):
    # R4 own case: the FULL actual provenance lands in the published input
    # and receipts — verbatim, with no fabricated vector score.
    from env_rag_final import local_adapter as la

    conn, _ = fx._install(monkeypatch, tmp_path, [fx._gold_q("fact-001", fx.Q_FACT, "fact")])
    candidate = la.Candidate(
        fx.C1,
        "default",
        fx.DOC_8978,
        "gb8978.pdf",
        "head",
        len(fx.CHUNKS[fx.C1]["content"]),
        True,
        reached_via=["entity:via-x", "edge:a|b"],
        similarity_order=3,
        source_type="entity+relation",
    )

    class Adapter:
        async def fetch(self, *a, **kw):
            return SimpleNamespace(
                candidates=[candidate],
                call_records=[],
                service_calls={},
                degraded=[],
                sorting_sources={"chunk_pick": "weight-fallback"},
            )

    monkeypatch.setattr(ev, "_run_answer", _answer_stub)
    report = asyncio.run(
        ev.run_evaluation(
            tmp_path / "out",
            paths=["local"],
            query_ids=["fact-001"],
            gold_path=eval_gold,
            values=fx.VALUES,
            conn=conn,
            local_adapter_factory=lambda *a: Adapter(),
            expected_identity=expected_identity,
        )
    )
    r = report["results"][0]
    assert r["receipts"]["sorting_sources"] == {"chunk_pick": "weight-fallback"}
    data = json.loads((tmp_path / "out" / "inputs" / "local" / "fact-001-fusion.json").read_text())
    entry = data["results"][0]["usable"][0]["paths"][0]
    assert entry["discovery"] == "entity+relation", entry
    assert entry["reached_via"] == ["entity:via-x", "edge:a|b"]
    assert entry["similarity_order"] == 3
    assert entry["score"] is None, "no fabricated vector score"
