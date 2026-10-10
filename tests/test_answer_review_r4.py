"""5.5 remaining coverage/local-unit boundaries; fake services only."""

import json

import pytest
import test_answer as fx


@pytest.mark.parametrize("full", [False, True], ids=["missing-cadmium", "both-subjects"])
def test_prose_slot_requires_answered_subject_not_only_read_paragraph(monkeypatch, tmp_path, full):
    conn, fp, rp = fx._syn_env(monkeypatch, tmp_path, fx._Q_HG_CD)
    fx._load_limits_chapter(conn, tmp_path)
    claim = fx._LIMITS_QUOTE if full else "总汞限值为0.05 mg/L。"
    payload = {
        "items": [
            {"edition": f"gb3095-{year}", "claim": claim, "quote": claim}
            for year in ["2012", "2026"]
        ]
    }
    # In the missing case, strip sentence punctuation that is not present
    # directly after the mercury clause in the actual source paragraph.
    if not full:
        for item in payload["items"]:
            item["quote"] = "总汞限值为0.05 mg/L"
    result = fx._run_syn(tmp_path, conn, fp, rp, payload)
    assert result["reverification"]["problems"] == []
    assert len(result["answer"]["items"]) == 2
    assert all(i["citation_verified"] for i in result["answer"]["items"])
    if full:
        assert result["coverage_status"] == "complete", result
    else:
        assert result["coverage_status"] != "complete", result["answer"]
        assert any("总镉" in s for s in result["answer"]["missing_answer_editions"])


@pytest.mark.parametrize("combined", [False, True], ids=["separate-brackets", "combined-bracket"])
def test_multiple_local_unit_assertions_inside_brackets_do_not_cross_subjects(
    monkeypatch, tmp_path, combined
):
    conn, _ = fx._install(monkeypatch, tmp_path, [fx._gold_q("q-fact", fx.Q_FACT, "fact")])
    note = "（总汞单位为mg/L；pH为无量纲）" if combined else "（总汞单位为mg/L）（pH为无量纲）"
    caption = "表 1 总汞及pH限值" + note
    conn.cat["table_units"][fx.DOC_8978][0]["caption"] = caption
    path = tmp_path / "gb8978.pdf.parsed" / "x.tables.json"
    tables = json.loads(path.read_text())
    tables["tables"][fx.FRAG1] = {
        "caption": caption,
        "content": "<table><tr><th>序号</th><th>污染物</th><th>最高允许排放浓度</th></tr>"
        "<tr><td>1</td><td>总汞</td><td>0.05</td></tr></table>",
    }
    tables["tables"][fx.FRAG2]["content"] = (
        "<table><tr><th>序号</th><th>污染物</th><th>最高允许排放浓度</th></tr>"
        "<tr><td>2</td><td>pH</td><td>7</td></tr></table>"
    )
    path.write_text(json.dumps(tables, ensure_ascii=False))
    fp, rp = fx._write_replay(
        tmp_path,
        [
            fx._fused(
                "q-fact", fx.Q_FACT, [fx._usable(fx.C1, fx.DOC_8978, fx.CHUNKS[fx.C1]["content"])]
            )
        ],
        [],
    )
    report = fx._run(
        fx.an.run_answer(
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
    assert item["citation_reverified"] is True
    assert item["unit"] == "mg/L", item
    assert item["unit_status"] == "source_context"
    assert result["coverage_status"] == "complete", result
