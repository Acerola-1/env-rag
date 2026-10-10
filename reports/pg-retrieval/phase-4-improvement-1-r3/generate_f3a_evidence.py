"""F3-a evidence generator — OFFLINE ONLY, zero network/DB/model.

Runs the four attribution-through-caption scenarios through the OWNING answer
entry (run_answer over explicit fake read-only catalog + constructed blocks,
same harness as the frozen r2 matrix) and one bounded non-crossing negative,
plus the function-level boundary decisions, and records the published
terminal reports under owning-entry/<case>/ plus a summary.

Evidence labels: [构造读取注入 + 离线answer入口回放] for every case here; the
fixture texts mirror the frozen review-r2 matrix shapes. None of this is a
live database read or cold generation.

Regenerate:  .venv/bin/python reports/pg-retrieval/phase-4-improvement-1-r3/generate_f3a_evidence.py
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import test_phase4_improvement1r2_owning_replay as own  # noqa: E402

from env_rag_final.enumerate_.prose_enum import (  # noqa: E402
    UnitText,
    extract_clauses_regex,
    structural_boundaries,
)

OUT = Path(__file__).resolve().parent / "owning-entry"


class MP:
    def __init__(self):
        self._ps = []

    def setattr(self, target, name, value=None, raising=True):
        p = patch.object(target, name, value)
        p.start()
        self._ps.append(p)

    def setitem(self, mapping, key, value):
        p = patch.dict(mapping, {key: value}, clear=False)
        p.start()
        self._ps.append(p)

    def undo(self):
        while self._ps:
            self._ps.pop().stop()


def _attr_text(caption: str) -> str:
    return (
        "## 4 章规定\n4.1 本条限值见下表：\n" + caption + "\n"
        '<table id="tb-o"><tr><td>总汞</td><td>0.05</td></tr></table>\n'
        "本条补充要求：每日监测一次。\n4.2 下一条独立要求。"
    )


_INDEPENDENT_TEXT = (
    "## 4 章规定\n4.1 本条要求已独立成句。\n表 1\n"
    '<table id="tb-o"><tr><td>总汞</td><td>0.05</td></tr></table>\n'
    "4.2 下一条独立要求。"
)

_NONCROSS_TEXT = (
    "## 4 章规定\n4.1 本条限值见下表：\n表 1\n"
    '<table id="tb-a"><tr><td>总汞</td><td>0.05</td></tr></table>\n'
    "本条补充要求：每日监测一次。\n"
    "4.2 另一条已独立成句。\n表 9\n"
    '<table id="tb-b"><tr><td>乙</td></tr></table>\n4.3 再下一条要求。'
)


def _run_case(name: str, text: str, checks) -> dict:
    mp = MP()
    td = Path(tempfile.mkdtemp())
    try:
        conn, question, fp, rp = own._own_fixture(td, mp, {"own-u1": text})
        report = own._own_run(mp, td, conn, question, fp, rp)
    finally:
        mp.undo()
    out = report["results"][0]
    cdir = OUT / name
    cdir.mkdir(parents=True, exist_ok=True)
    shutil.copy(td / "run" / "answer-runtime-latest.json", cdir / "answer-runtime-latest.json")
    byc = {it.get("clause"): it for it in out["answer"]["items"]}
    rec = {
        "case": name,
        "evidence_label": "构造读取注入 + 离线answer入口回放（run_answer owning 入口）",
        "coverage_status": out["coverage_status"],
        "status": out["status"],
        "model_calls_used": report["model_calls_used"],
        "reverification_problems": out["reverification"]["problems"],
        "clause_4_1_text": (byc.get("4.1") or {}).get("text"),
        "clause_4_1_citation_reverified": (byc.get("4.1") or {}).get("citation_reverified"),
        "clause_4_2_text": (byc.get("4.2") or {}).get("text"),
        "checks": checks(out),
    }
    assert all(v == "PASS" for v in rec["checks"].values()), rec
    return rec


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    records = [
        _run_case(
            "plain-caption-attributed-kept",
            _attr_text("表 1"),
            lambda out: {
                "complete": "PASS" if out["coverage_status"] == "complete" else "FAIL",
                "table_values_and_continuation_kept": "PASS"
                if all(
                    s in next(i["text"] for i in out["answer"]["items"] if i.get("clause") == "4.1")
                    for s in ("总汞", "0.05", "每日监测一次")
                )
                else "FAIL",
                "citation_reverified": "PASS"
                if next(i for i in out["answer"]["items"] if i.get("clause") == "4.1").get(
                    "citation_reverified"
                )
                is True
                else "FAIL",
                "zero_problems": "PASS" if out["reverification"]["problems"] == [] else "FAIL",
            },
        ),
        _run_case(
            "markdown-caption-attributed-kept",
            _attr_text("## 表 1 限值"),
            lambda out: {
                "complete": "PASS" if out["coverage_status"] == "complete" else "FAIL",
                "table_values_and_continuation_kept": "PASS"
                if all(
                    s in next(i["text"] for i in out["answer"]["items"] if i.get("clause") == "4.1")
                    for s in ("总汞", "0.05", "每日监测一次")
                )
                else "FAIL",
                "zero_problems": "PASS" if out["reverification"]["problems"] == [] else "FAIL",
            },
        ),
        _run_case(
            "independent-captioned-table-stays-out",
            _INDEPENDENT_TEXT,
            lambda out: {
                "complete": "PASS" if out["coverage_status"] == "complete" else "FAIL",
                "clause_4_1_short_sentence": "PASS"
                if next(i["text"] for i in out["answer"]["items"] if i.get("clause") == "4.1")
                == "4.1 本条要求已独立成句。"
                else "FAIL",
                "citation_reverified": "PASS"
                if next(i for i in out["answer"]["items"] if i.get("clause") == "4.1").get(
                    "citation_reverified"
                )
                is True
                else "FAIL",
            },
        ),
        _run_case(
            "attribution-does-not-cross-next-clause",
            _NONCROSS_TEXT,
            lambda out: {
                "complete": "PASS" if out["coverage_status"] == "complete" else "FAIL",
                "4_1_keeps_own_attributed_table": "PASS"
                if "总汞"
                in next(i["text"] for i in out["answer"]["items"] if i.get("clause") == "4.1")
                else "FAIL",
                "4_2_stops_at_its_own_caption": "PASS"
                if next(i["text"] for i in out["answer"]["items"] if i.get("clause") == "4.2")
                == "4.2 另一条已独立成句。"
                else "FAIL",
                "later_table_in_no_clause": "PASS"
                if all("乙" not in i["text"] for i in out["answer"]["items"])
                else "FAIL",
            },
        ),
    ]

    # function-level boundary decisions (chain snapshot of the fixed rule)
    chain = {}
    for label, text in (
        ("plain-caption-kept", _attr_text("表 1")),
        ("markdown-caption-kept", _attr_text("## 表 1 限值")),
        ("independent", _INDEPENDENT_TEXT),
        ("non-crossing", _NONCROSS_TEXT),
    ):
        u = UnitText("u", text, [], {"blockid": "u"}, 0, len(text), False, "parsed_block")
        cuts, notes = structural_boundaries([u], text)
        chain[label] = {
            "cuts": cuts,
            "note_positions": [n["pos"] for n in notes],
            "extracted": {
                it["clause"]: it["text"] for it in extract_clauses_regex(text, hard_ends=cuts)
            },
        }

    summary = {
        "cases": records,
        "function_level_boundary_decisions": chain,
        "note": (
            "attribution is looked up through the table object's own title "
            "lines (bounded walk: stops at the first prose line), so a caption "
            "cannot reset a proven attribution and attribution never crosses "
            "into the next independent clause"
        ),
    }
    (OUT.parent / "f3a-evidence.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"wrote f3a-evidence.json ({len(records)} owning cases, all checks PASS)")


if __name__ == "__main__":
    main()
