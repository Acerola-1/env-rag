"""R2 owning-entry evidence generator — OFFLINE ONLY, zero network/DB/model.

Runs the six owning-entry (run_answer) replay scenarios from
tests/test_phase4_improvement1r2_owning_replay.py exactly as the test suite
does (same assertions, same fake read-only connection/storage and stored
identity material) and copies each published terminal report into
owning-replay/<case>/answer-runtime-latest.json, then writes a summary.

Evidence labels per handoff: the first case is [原始产物读取 + 离线answer入口
回放] (stored round-1 request trace + stored 5.3/5.4 replay reports + the
ORIGINAL parsed sidecars); the rest are [构造读取注入 / 构造篡改注入 +
离线answer入口回放]. None of them are live database reads or cold generation.

Regenerate:  .venv/bin/python reports/pg-retrieval/phase-4-improvement-1-r2/generate_owning_evidence.py
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

OUT = Path(__file__).resolve().parent / "owning-replay"


class MP:
    """Minimal monkeypatch shim (setattr/setitem with undo)."""

    def __init__(self):
        self._patchers = []

    def setattr(self, target, name, value=None, raising=True):
        p = patch.object(target, name, value)
        p.start()
        self._patchers.append(p)

    def setitem(self, mapping, key, value):
        p = patch.dict(mapping, {key: value}, clear=False)
        p.start()
        self._patchers.append(p)

    def undo(self):
        while self._patchers:
            self._patchers.pop().stop()


CASES = [
    (
        "stored-trace-prose-enum-003-real-sidecars",
        own.test_owning_realdata_prose003_pass_through,
        "原始产物读取 + 离线answer入口回放（stored round-1 请求 trace + 已存 5.3/5.4 重放报告 + 原始 sidecars）",
    ),
    (
        "legit-cross-unit-complete",
        own.test_owning_legitimate_cross_unit_publishes_complete,
        "构造读取注入 + 离线answer入口回放（协议换行真实间隙的跨单元合法条款）",
    ),
    (
        "fabricated-separator-refused-partial",
        own.test_owning_fabricated_separator_publishes_partial,
        "构造篡改注入 + 离线answer入口回放（真实展开后的条目被伪 separator 重拼）",
    ),
    (
        "malformed-numeric-span-refused-partial",
        own.test_owning_malformed_numeric_span_cannot_downgrade,
        "构造篡改注入 + 离线answer入口回放（真实展开后的条目坐标字段置 null）",
    ),
    (
        "attributed-embedded-table-kept-complete",
        own.test_owning_attributed_embedded_table_stays_and_publishes_complete,
        "构造读取注入 + 离线answer入口回放（冒号宣告且指认 表 对象的内嵌表条款）",
    ),
    (
        "ambiguous-boundary-partial-recorded",
        own.test_owning_ambiguous_boundary_publishes_partial_with_record,
        "构造读取注入 + 离线answer入口回放（冒号宣告未指认对象 → 显式 partial + 记录）",
    ),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    evidence = []
    for name, fn, label in CASES:
        mp = MP()
        td = Path(tempfile.mkdtemp())
        try:
            fn(mp, td)  # assertions run for real; a failure aborts the script
        finally:
            mp.undo()
        src = td / "run" / "answer-runtime-latest.json"
        assert src.exists(), src
        cdir = OUT / name
        cdir.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, cdir / "answer-runtime-latest.json")
        rep = json.loads(src.read_text(encoding="utf-8"))
        out = rep["results"][0]
        prose = [e for e in out["expansions"] if e.get("kind") == "prose" and e.get("selected")]
        evidence.append(
            {
                "case": name,
                "evidence_label": label,
                "published_terminal": f"owning-replay/{name}/answer-runtime-latest.json",
                "identity_before_matches_frozen": rep["identity_before"]["matches_frozen"],
                "identity_after_matches_frozen": (rep.get("identity_after") or {}).get("matches_frozen"),
                "model_calls_used": rep["model_calls_used"],
                "coverage_status": out["coverage_status"],
                "status": out["status"],
                "reverification_problems": out["reverification"]["problems"],
                "items_count": (prose[0]["items_count"] if prose else 0),
                "boundary_ambiguities": (prose[0].get("boundary_ambiguities") if prose else None),
                "flags": out["flags"],
            }
        )
    summary = OUT / "owning-replay-evidence.json"
    summary.write_text(json.dumps(evidence, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {summary} ({len(evidence)} cases, all assertions green)")


if __name__ == "__main__":
    main()
