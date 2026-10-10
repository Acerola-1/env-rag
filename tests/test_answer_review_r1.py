"""Independent 5.5 acceptance through run_answer; no real service calls."""

import asyncio
import copy
import json

import pytest
import test_answer as fx

from env_rag_final import answer as an


@pytest.mark.parametrize(
    "claim",
    [
        "2012版停车场年平均二级限值为35μg/m³",
        "2012版PM2.5年平均二级限值为15μg/m³",
        "2012版PM2.5年平均二级限值为35吨",
        "2012版PM2.5年平均二级限值为3μg/m³",
    ],
    ids=["wrong-subject", "wrong-column", "wrong-unit", "numeric-substring"],
)
def test_unsupported_model_claim_cannot_complete(monkeypatch, tmp_path, claim):
    conn, _ = fx._install(monkeypatch, tmp_path, [fx._gold_q("q-syn", fx.Q_SYN, "synthesis")])
    fp, rp = fx._syn_replay(tmp_path)
    payload = copy.deepcopy(fx._GOOD_SYN)
    payload["items"][0]["claim"] = claim
    sink = []
    report = asyncio.run(
        an.run_answer(
            tmp_path / "out",
            ["q-syn"],
            fused_report_path=fp,
            rerank_report_path=rp,
            values=fx.VALUES,
            conn=conn,
            allow_model=True,
            transport=fx._model_transport(payload, sink=sink),
        )
    )
    assert len(sink) == 1
    result = report["results"][0]
    assert result["coverage_status"] != "complete", result["answer"]
    assert result["answer"].get("model_failure"), result["answer"]


def test_comparison_requires_claims_for_both_requested_editions(monkeypatch, tmp_path):
    conn, _ = fx._install(monkeypatch, tmp_path, [fx._gold_q("q-syn", fx.Q_SYN, "synthesis")])
    fp, rp = fx._syn_replay(tmp_path)
    payload = copy.deepcopy(fx._GOOD_SYN)
    payload["items"] = payload["items"][:1]
    report = asyncio.run(
        an.run_answer(
            tmp_path / "out",
            ["q-syn"],
            fused_report_path=fp,
            rerank_report_path=rp,
            values=fx.VALUES,
            conn=conn,
            allow_model=True,
            transport=fx._model_transport(payload),
        )
    )
    result = report["results"][0]
    assert result["coverage_status"] != "complete", result["answer"]


def test_concentration_without_verified_unit_is_not_complete(monkeypatch, tmp_path):
    # Mirror the real fact-002 three-column grid: the unit is absent in the
    # parsed table, so it must be recovered from verified context or be unknown.
    header = "<tr><th>序号</th><th>污染物</th><th>最高允许排放浓度</th></tr>"
    for attr, rows in [("_TBL1_8978_F1", fx._ROWS1), ("_TBL1_8978_F2", fx._ROWS2)]:
        html = "<table>" + header
        html += "".join(
            "<tr>" + "".join(f"<td>{cell}</td>" for cell in row[:3]) + "</tr>" for row in rows
        )
        monkeypatch.setattr(fx, attr, html + "</table>")
    chunks = copy.deepcopy(fx.CHUNKS)
    chunks[fx.C1]["content"] = "表 1 第一类污染物 总汞 0.05"
    monkeypatch.setattr(fx, "CHUNKS", chunks)
    conn, _ = fx._install(monkeypatch, tmp_path, [fx._gold_q("q-fact", fx.Q_FACT, "fact")])
    fp, rp = fx._write_replay(
        tmp_path,
        [
            fx._fused(
                "q-fact",
                fx.Q_FACT,
                [fx._usable(fx.C1, fx.DOC_8978, fx.CHUNKS[fx.C1]["content"])],
            )
        ],
        [],
    )
    report = asyncio.run(
        an.run_answer(
            tmp_path / "out",
            ["q-fact"],
            fused_report_path=fp,
            rerank_report_path=rp,
            values=fx.VALUES,
            conn=conn,
            allow_model=False,
        )
    )
    result = report["results"][0]
    assert result["answer"]["items"], "keep the verified numeric evidence"
    assert result["coverage_status"] != "complete", result["answer"]


def _table_replay(tmp_path):
    return fx._write_replay(
        tmp_path,
        [
            fx._fused(
                "q-table",
                fx.Q_TABLE,
                [fx._usable(fx.C1, fx.DOC_8978, fx.CHUNKS[fx.C1]["content"])],
            )
        ],
        [],
    )


@pytest.mark.parametrize("fault", ["drift", "capture-error"])
def test_post_guard_failure_rejects_owning_entry(monkeypatch, tmp_path, fault):
    conn, _ = fx._install(monkeypatch, tmp_path, [fx._gold_q("q-table", fx.Q_TABLE, "table_enum")])
    fp, rp = _table_replay(tmp_path)
    capture = an._capture_identity
    calls = 0

    async def fail_after(values):
        nonlocal calls
        calls += 1
        if calls == 2 and fault == "capture-error":
            raise OSError("injected post guard unavailable")
        identity = await capture(values)
        if calls == 2:
            identity["identity"]["source_fingerprint"] = "changed-after-read"
        return identity

    monkeypatch.setattr(an, "_capture_identity", fail_after)
    caught = None
    try:
        asyncio.run(
            an.run_answer(
                tmp_path / "out",
                ["q-table"],
                fused_report_path=fp,
                rerank_report_path=rp,
                values=fx.VALUES,
                conn=conn,
                allow_model=False,
            )
        )
    except an.AdapterError as exc:
        caught = exc
    terminal = json.loads((tmp_path / "out" / "answer-runtime-latest.json").read_text())
    assert terminal["failure"]["stage"].startswith("identity-after")
    assert "finished_at" not in terminal
    assert calls == 2
    assert caught is not None, "failed post guard returned normally with complete answers"


def test_connection_acquire_failure_has_post_guard_and_terminal(monkeypatch, tmp_path):
    _, calls = fx._install(monkeypatch, tmp_path, [fx._gold_q("q-table", fx.Q_TABLE, "table_enum")])
    fp, rp = _table_replay(tmp_path)

    async def failed_connect(**kwargs):
        raise TimeoutError("injected PG connection failure")

    monkeypatch.setattr(an.asyncpg, "connect", failed_connect)
    with pytest.raises((an.AdapterError, TimeoutError)):
        asyncio.run(
            an.run_answer(
                tmp_path / "out",
                ["q-table"],
                fused_report_path=fp,
                rerank_report_path=rp,
                values=fx.VALUES,
                allow_model=False,
            )
        )
    terminal = tmp_path / "out" / "answer-runtime-latest.json"
    assert terminal.exists(), "PG acquisition failed outside terminal-writing boundary"
    data = json.loads(terminal.read_text())
    assert data.get("failure")
    assert data.get("identity_after") or data.get("identity_after_error")
    assert calls["identity"] == 2
