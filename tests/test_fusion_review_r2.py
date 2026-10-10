"""Remaining F3 owning-entry boundaries; no real services or database writes."""

import asyncio
import json

import pytest
import test_fusion as base
import test_fusion_review_r1 as accepted

from env_rag_final import fusion as fu
from env_rag_final.local_adapter import AdapterError


def test_malformed_gold_has_zero_call_failure_terminal(monkeypatch, tmp_path):
    accepted._install_local(monkeypatch, tmp_path, base._pg_result())
    fu.GOLD_PATH.write_text("{malformed JSON")
    captures = []

    async def capture(values):
        captures.append(True)
        return base._identity()

    monkeypatch.setattr(fu, "_capture_identity", capture)
    with pytest.raises((AdapterError, json.JSONDecodeError)):
        asyncio.run(fu.run_fusion(tmp_path, ["q-merge"]))
    assert captures == [], "gold parse rejection must precede backend calls"
    path = tmp_path / "fusion-runtime-latest.json"
    assert path.exists(), "gold JSON parse failure requires a failure terminal"
    terminal = json.loads(path.read_text())
    assert "finished_at" not in terminal
    assert "gold" in json.dumps(terminal["failure"])
    assert terminal["failure_service_records"]["call_records"] == []


def test_second_query_pg_failure_does_not_borrow_first_local_receipts(monkeypatch, tmp_path):
    pg = base._pg_result()
    accepted._install_local(monkeypatch, tmp_path, pg)
    local_calls = []

    class Impl:
        async def fetch(self, question, query_id=None, **kwargs):
            local_calls.append(query_id)
            result = base._local_result()
            result.call_records = [
                {
                    "service": "llm",
                    "operation": "keyword_extraction",
                    "status": "success",
                    "query_id": query_id,
                }
            ]
            return result

    monkeypatch.setattr(fu, "LocalCandidateAdapter", lambda *args, **kwargs: Impl())
    calls = []

    async def discovery(conn, question, **kwargs):
        calls.append(question)
        if len(calls) == 2:
            raise TimeoutError("second query PG discovery timed out before local")
        return pg

    monkeypatch.setattr("env_rag_final.search.query.run_query", discovery)
    with pytest.raises(AdapterError):
        asyncio.run(fu.run_fusion(tmp_path, ["q-merge", "q-dual"]))
    assert local_calls == ["q-merge"]
    terminal = json.loads((tmp_path / "fusion-runtime-latest.json").read_text())
    assert len(terminal["results"]) == 1
    assert terminal["identity_after"]["matches_frozen"]
    assert "second query PG discovery" in terminal["failure"]["detail"]
    receipts = terminal["failure_service_records"]
    assert receipts["query_id"] == "q-dual", "failure ledger belongs to current query"
    assert receipts["call_records"] == [], "second query never reached local"
    assert terminal["results"][0]["local"]["receipts"]["call_records"], (
        "first query's successful receipts remain on its own result"
    )
