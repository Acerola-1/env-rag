"""F3 incremental acceptance: a caption cannot reset proven table attribution.

These drive the real owning answer entry over explicit fixture blocks and a
fake read-only catalog. No service, historical input or frozen test is changed.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tests"))
import test_phase4_improvement1r2_owning_replay as own  # noqa: E402


@pytest.mark.parametrize("caption", ["表 1", "## 表 1 限值"])
def test_caption_cannot_reset_attributed_embedded_table(monkeypatch, tmp_path, caption):
    text = (
        "## 4 章规定\n4.1 本条限值见下表：\n"
        f"{caption}\n"
        '<table id="tb-o"><tr><td>总汞</td><td>0.05</td></tr></table>\n'
        "本条补充要求：每日监测一次。\n4.2 下一条独立要求。"
    )
    conn, question, fp, rp = own._own_fixture(tmp_path, monkeypatch, {"own-u1": text})
    report = own._own_run(monkeypatch, tmp_path, conn, question, fp, rp)
    out = report["results"][0]
    items = out["answer"]["items"]
    if out["coverage_status"] == "complete":
        clause = next(it for it in items if it.get("clause") == "4.1")
        assert "总汞" in clause["text"] and "0.05" in clause["text"]
        assert "每日监测一次" in clause["text"]
        assert clause.get("citation_reverified") is True
    else:
        assert out["coverage_status"] in {"partial", "ambiguous"}
        selected = [e for e in out["expansions"] if e.get("selected")]
        assert any(e.get("warnings") or e.get("boundary_ambiguities") for e in selected)
    assert report["model_calls_used"] == 0


def test_independent_captioned_table_stays_outside_clause(monkeypatch, tmp_path):
    text = (
        "## 4 章规定\n4.1 本条要求已独立成句。\n表 1\n"
        '<table id="tb-o"><tr><td>总汞</td><td>0.05</td></tr></table>\n'
        "4.2 下一条独立要求。"
    )
    conn, question, fp, rp = own._own_fixture(tmp_path, monkeypatch, {"own-u1": text})
    report = own._own_run(monkeypatch, tmp_path, conn, question, fp, rp)
    out = report["results"][0]
    assert out["coverage_status"] == "complete"
    clause = next(it for it in out["answer"]["items"] if it.get("clause") == "4.1")
    assert clause["text"] == "4.1 本条要求已独立成句。"
    assert clause.get("citation_reverified") is True
    assert report["model_calls_used"] == 0
