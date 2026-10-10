"""5.5 relationship and coverage acceptance through the real owning entry."""

import asyncio
import copy
import json

import pytest
import test_answer as fx

from env_rag_final import answer as an


def _run_syn(tmp_path, conn, fp, rp, payload):
    return asyncio.run(
        an.run_answer(
            tmp_path / "out",
            ["q-syn"],
            fused_report_path=fp,
            rerank_report_path=rp,
            values=fx.VALUES,
            conn=conn,
            transport=fx._model_transport(payload),
            allow_model=True,
        )
    )["results"][0]


def _table_replay(tmp_path, question):
    return fx._write_replay(
        tmp_path,
        [
            fx._fused(
                "q-syn",
                question,
                [
                    fx._usable(fx.CP12, fx.DOC_2012, fx.CHUNKS[fx.CP12]["content"]),
                    fx._usable(fx.CP26, fx.DOC_2026, fx.CHUNKS[fx.CP26]["content"]),
                ],
            )
        ],
        [],
    )


def test_requested_second_level_not_filled_by_first_level(monkeypatch, tmp_path):
    conn, _ = fx._install(monkeypatch, tmp_path, [fx._gold_q("q-syn", fx.Q_SYN, "synthesis")])
    fp, rp = _table_replay(tmp_path, fx.Q_SYN)
    payload = copy.deepcopy(fx._GOOD_SYN)
    for item, value in zip(payload["items"], ["15", "10"], strict=True):
        year = item["edition"].split("-")[-1]
        item["claim"] = f"{year}版PM2.5年平均一级限值为{value}μg/m³"
    result = _run_syn(tmp_path, conn, fp, rp, payload)
    assert result["answer"]["items"], "retain correct but off-topic first-level evidence"
    assert result["coverage_status"] != "complete", result["answer"]


def test_absent_exact_pollutant_not_filled_by_prefix_match(monkeypatch, tmp_path):
    question = "对比 GB 3095-2012 与 GB 3095-2026 表1中PM1的年平均二级限值。"
    conn, _ = fx._install(monkeypatch, tmp_path, [fx._gold_q("q-syn", question, "synthesis")])
    fp, rp = _table_replay(tmp_path, question)
    payload = {
        "items": [
            {
                "edition": f"gb3095-{year}",
                "claim": f"{year}版PM10年平均二级限值为70μg/m³",
                "quote": "PM10 | 年平均 | 50 | 70",
            }
            for year in ["2012", "2026"]
        ]
    }
    result = _run_syn(tmp_path, conn, fp, rp, payload)
    assert result["coverage_status"] != "complete", result["answer"]


def test_multiple_requested_subjects_can_be_answered_in_separate_items(monkeypatch, tmp_path):
    question = "对比 GB 3095-2012 与 GB 3095-2026 表1中PM2.5与PM10的年平均二级限值。"
    conn, _ = fx._install(monkeypatch, tmp_path, [fx._gold_q("q-syn", question, "synthesis")])
    fp, rp = _table_replay(tmp_path, question)
    payload = copy.deepcopy(fx._GOOD_SYN)
    payload["items"] += [
        {
            "edition": f"gb3095-{year}",
            "claim": f"{year}版PM10年平均二级限值为70μg/m³",
            "quote": "PM10 | 年平均 | 50 | 70",
        }
        for year in ["2012", "2026"]
    ]
    result = _run_syn(tmp_path, conn, fp, rp, payload)
    assert len(result["answer"]["items"]) == 4
    assert all(i["citation_verified"] for i in result["answer"]["items"])
    assert result["coverage_status"] == "complete", result["model"]


@pytest.mark.parametrize("swap", [False, True], ids=["prose-associated", "prose-swapped"])
def test_prose_values_bound_to_their_subjects(monkeypatch, tmp_path, swap):
    question = "对比 GB 3095-2012 与 GB 3095-2026 第3章的总汞、总镉限值。"
    conn, _ = fx._install(monkeypatch, tmp_path, [fx._gold_q("q-syn", question, "synthesis")])
    quote = "3.1 污染物限值 总汞限值为0.05 mg/L，总镉限值为0.1 mg/L。"
    for doc_id, year in [(fx.DOC_2012, "2012"), (fx.DOC_2026, "2026")]:
        unit_id, scope_id = f"block-{year}", f"{doc_id}:scope:3"
        body = "3 污染物限值\n" + quote + "\n"
        conn.cat["scopes"][(doc_id, "3")] = [
            {
                "scope_id": scope_id,
                "scope_kind": "chapter",
                "title": "污染物限值",
                "number": "3",
                "confirm_status": "confirmed",
            }
        ]
        conn.cat["scope_units"][scope_id] = [unit_id]
        conn.cat["units"][(doc_id, unit_id)] = {
            "unit_id": unit_id,
            "unit_kind": "block",
            "heading": "3",
            "requires_span": False,
            "content_length": len(body),
            "locator": json.dumps({"blockid": unit_id}),
        }
        conn.cat["links"][(doc_id, unit_id)] = []
        path = tmp_path / f"gb3095-{year}.pdf.parsed" / "x.blocks.jsonl"
        path.write_text(
            '{"meta":true}\n'
            + json.dumps({"type": "content", "blockid": unit_id, "content": body})
            + "\n"
        )
    fp, rp = _table_replay(tmp_path, question)
    claim = "总汞限值为0.1 mg/L，总镉限值为0.05 mg/L。" if swap else quote
    payload = {
        "items": [
            {"edition": f"gb3095-{year}", "claim": claim, "quote": quote}
            for year in ["2012", "2026"]
        ]
    }
    result = _run_syn(tmp_path, conn, fp, rp, payload)
    assert result["reverification"]["items_checked"] == 2
    assert result["reverification"]["problems"] == []
    if swap:
        assert result["coverage_status"] != "complete", result["answer"]
        assert result["answer"].get("model_failure")
    else:
        assert result["coverage_status"] == "complete", result


def test_named_table_title_does_not_spread_other_subjects_dimensionless_note(monkeypatch, tmp_path):
    # No unit for mercury anywhere in this fixture; the only unit judgment
    # explicitly names pH. The title separately lists both subjects.
    conn, _ = fx._install(monkeypatch, tmp_path, [fx._gold_q("q-fact", fx.Q_FACT, "fact")])
    caption = "表 1 总汞及pH限值（pH为无量纲）"
    conn.cat["table_units"][fx.DOC_8978][0]["caption"] = caption
    chunks = copy.deepcopy(fx.CHUNKS)
    chunks[fx.C1]["content"] = "总汞 0.05"
    monkeypatch.setattr(fx, "CHUNKS", chunks)
    path = tmp_path / "gb8978.pdf.parsed" / "x.tables.json"
    tables = json.loads(path.read_text())
    tables["tables"][fx.FRAG1] = {
        "caption": caption,
        "content": "<table><tr><th>序号</th><th>污染物</th><th>最高允许排放浓度</th></tr>"
        "<tr><td>1</td><td>总汞</td><td>0.05</td></tr></table>",
    }
    path.write_text(json.dumps(tables, ensure_ascii=False))
    fp, rp = fx._write_replay(
        tmp_path,
        [fx._fused("q-fact", fx.Q_FACT, [fx._usable(fx.C1, fx.DOC_8978, "总汞 0.05")])],
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
    item = result["answer"]["items"][0]
    assert item["unit_status"] != "dimensionless", item
    assert result["coverage_status"] != "complete"
