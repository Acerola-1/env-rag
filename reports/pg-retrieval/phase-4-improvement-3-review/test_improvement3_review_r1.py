"""Final publication-window acceptance over the real owning file-enum chain.

Only the supplied fake catalog changes; snapshot/public source identities stay
constant. The real publication guard, enumeration and row re-reader all run.
"""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tests"))
import test_phase4_improvement3_union_enumeration as tc  # noqa: E402


def catalog():
    return {
        "doc-std": copy.deepcopy(tc.CAT_005["doc-std"]),
        "doc-m1": copy.deepcopy(tc.CAT_005["doc-m1"]),
        "doc-noise": tc.doc("synth-unrelated.pdf", title="无关目录文件"),
    }


def test_stable_publication_window_keeps_full_verified_union(monkeypatch, tmp_path):
    report, out, stage, _conn = tc._run_leg(
        monkeypatch,
        tmp_path,
        tc.Q_WITH,
        catalog(),
        usable=[tc._usable("doc-std", tc.CAT_005["doc-std"]["doc_name"])],
    )
    assert out["coverage_status"] == "complete"
    assert {it["doc_id"] for it in out["answer"]["items"]} == {"doc-std", "doc-m1"}
    assert all(
        it["citation_verified"] and it["citation_reverified"] for it in out["answer"]["items"]
    )
    assert stage["members_total"] == stage["members_processed"] == 2
    assert report["model_calls_used"] == 0


@pytest.mark.parametrize("change", ["base-fields", "new-related-same-count"])
def test_same_snapshot_content_change_before_publication_refuses(monkeypatch, tmp_path, change):
    cat = catalog()
    original = tc.de.verify_publication_snapshot
    changed = []

    async def inject_then_real_guard(conn, workspace, snapshot_id, source_fp, *args, **kwargs):
        if not changed:
            if change == "base-fields":
                cat["doc-std"]["self_code_version"] = "2006"
                cat["doc-std"]["title"] = "当前登记已变为另一版本"
            else:
                cat["doc-noise"]["title"] = "GB 18466—2005 新增修改单"
            changed.append(True)
        # Same snapshot/count/public-source identity. No validator is mocked
        # to success: the real guard receives the changed fake metadata.
        return await original(conn, workspace, snapshot_id, source_fp, *args, **kwargs)

    monkeypatch.setattr(tc.de, "verify_publication_snapshot", inject_then_real_guard)
    report, out, _stage, _conn = tc._run_leg(
        monkeypatch,
        tmp_path,
        tc.Q_WITH,
        cat,
        usable=[tc._usable("doc-std", cat["doc-std"]["doc_name"])],
    )
    assert changed and len(cat) == 3
    assert report["model_calls_used"] == 0
    assert out["coverage_status"] != "complete", out
