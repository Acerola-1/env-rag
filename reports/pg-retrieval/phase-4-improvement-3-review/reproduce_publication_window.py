"""Offline owning-entry publication-window receipts; only fake metadata changes."""

import importlib.util
import json
import tempfile
from pathlib import Path

from pytest import MonkeyPatch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "window_matrix", HERE / "test_improvement3_review_r1.py"
)
matrix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(matrix)
tc = matrix.tc


def main():
    receipts = []
    for change in ("stable", "base-fields", "new-related-same-count"):
        cat = matrix.catalog()
        before = json.loads(json.dumps(cat))
        original = tc.de.verify_publication_snapshot
        changed = []

        async def inject(conn, workspace, snapshot_id, source_fp, *args, **kwargs):
            if not changed and change != "stable":
                if change == "base-fields":
                    cat["doc-std"]["self_code_version"] = "2006"
                    cat["doc-std"]["title"] = "当前登记已变为另一版本"
                else:
                    cat["doc-noise"]["title"] = "GB 18466—2005 新增修改单"
                changed.append(True)
            return await original(conn, workspace, snapshot_id, source_fp, *args, **kwargs)

        with MonkeyPatch.context() as mp, tempfile.TemporaryDirectory() as tmp:
            mp.setattr(tc.de, "verify_publication_snapshot", inject)
            report, out, stage, _conn = tc._run_leg(
                mp,
                Path(tmp),
                tc.Q_WITH,
                cat,
                usable=[tc._usable("doc-std", cat["doc-std"]["doc_name"])],
            )
            (HERE / f"window-{change}-runtime.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n"
            )
            receipts.append(
                {
                    "case": change,
                    "evidence_class": "offline owning entry / constructed catalog",
                    "before": before,
                    "after": cat,
                    "metadata_count_before": len(before),
                    "metadata_count_after": len(cat),
                    "injection_executed": bool(changed),
                    "coverage": out["coverage_status"],
                    "publication_guard": stage.get("publication_guard"),
                    "members_total": stage.get("members_total"),
                    "items": out["answer"]["items"],
                    "model_calls_used": report["model_calls_used"],
                    "expected": "complete" if change == "stable" else "non-complete",
                }
            )
    (HERE / "publication-window-observations.json").write_text(
        json.dumps(receipts, ensure_ascii=False, indent=2) + "\n"
    )
    for row in receipts:
        print(row["case"], row["coverage"], row["publication_guard"], row["model_calls_used"])


if __name__ == "__main__":
    main()
