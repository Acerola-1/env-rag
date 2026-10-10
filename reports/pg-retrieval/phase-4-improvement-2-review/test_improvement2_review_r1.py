"""Offline owning-entry acceptance of target provenance, not just code matching."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tests"))
import test_phase4_improvement2_target_confirmation as tc  # noqa: E402


def test_canonical_target_with_noise_remains_complete(monkeypatch, tmp_path):
    report, _ = tc._synth_leg(
        tmp_path,
        monkeypatch,
        "GB 9001-2020 的 4 章规定了哪些要求？",
        {tc._G: tc._goal_doc(), tc._X: tc._foreign_doc()},
    )
    out = report["results"][0]
    assert out["coverage_status"] == "complete"
    assert tc._pub_docs(out) == {tc._G}


@pytest.mark.parametrize("claim", ["discovery-label", "membership-string"])
def test_candidate_attribution_marker_without_bound_evidence_refuses(monkeypatch, tmp_path, claim):
    original = tc._usable

    def mark(*args, **kwargs):
        row = original(*args, **kwargs)
        if row["doc_id"] == tc._X:
            row["paths"][0]["discovery"] = (
                "doc_attribution" if claim == "discovery-label" else "entity"
            )
            if claim == "membership-string":
                row["paths"][0]["membership_basis"] = "this is supposedly a related document"
        return row

    monkeypatch.setattr(tc, "_usable", mark)
    report, _ = tc._synth_leg(
        tmp_path,
        monkeypatch,
        "GB 9001-2020 的 4 章规定了哪些要求？含修改单和相关文件。",
        {
            tc._G: tc._goal_doc(),
            tc._X: tc._foreign_doc(self_code=None, self_code_version=None),
        },
    )
    out = report["results"][0]
    assert tc._X not in tc._audit_of(out)["allowed"]
    assert tc._pub_docs(out) == {tc._G}


def test_verified_typed_attribution_absent_from_chunks_keeps_full_read(monkeypatch, tmp_path):
    """Same 5.3 target/allowed_set_basis shape, with a valid catalog citation.

    The unknown-self-code target is already confirmed by upstream evidence;
    missing a usable chunk must not remove it from the full scope read.
    """
    typed = {
        "target_type": "doc",
        "workspace": "default",
        "doc_id": tc._M,
        "doc_name": "synth-GB9001-含2020修改单.pdf",
        "self_code": None,
        "self_code_version": None,
        "discovery": "doc_attribution",
        "membership_basis": "doc name/title carries the requested code (self_code=None)",
        "citation": {
            "kind": "catalog_row",
            "workspace": "default",
            "snapshot_id": tc.IDENT["catalog_active"]["snapshot_id"],
            "doc_id": tc._M,
        },
        "citation_verified": True,
    }
    original = tc.ev._synthesized_fused_result

    def upstream(q, usable, path_label):
        row = original(q, [u for u in usable if u["doc_id"] != tc._M], path_label)
        row["path_provenance"] = {"path": "fusion", "discovery_only": False}
        row["targets_resolved"] = [{"code": "GB9001", "version": "2020", "docs": [tc._G]}]
        row["allowed_set_basis"] = {
            "resolved_code_targets": [[tc._G]],
            "verified_attributions": [
                {
                    k: typed[k]
                    for k in ("doc_id", "self_code", "self_code_version", "membership_basis")
                }
            ],
        }
        return row

    monkeypatch.setattr(tc.ev, "_synthesized_fused_result", upstream)
    report, _ = tc._synth_leg(
        tmp_path,
        monkeypatch,
        "GB 9001-2020 的 4 章规定了哪些要求？含修改单和相关文件。",
        {
            tc._G: tc._goal_doc(),
            tc._M: tc._goal_doc(
                self_code=None,
                self_code_version=None,
                file_path=typed["doc_name"],
            ),
        },
        typed_promotion=[typed],
    )
    out = report["results"][0]
    assert set(tc._audit_of(out)["allowed"]) == {tc._G, tc._M}
    assert tc._pub_docs(out) == {tc._G, tc._M}
    assert out["coverage_status"] == "complete"


@pytest.mark.parametrize("target_shape", ["typed-discovery", "resolved-discovery"])
def test_codeless_discovery_cannot_promote_itself_to_confirmed_scope(
    monkeypatch, tmp_path, target_shape
):
    original = tc.ev._synthesized_fused_result

    def discovery(q, usable, path_label):
        row = original(q, usable, path_label)
        doc = {"target_type": "doc", "workspace": "default", "doc_id": tc._X, "discovery": "local"}
        if target_shape == "typed-discovery":
            row["typed_targets"] = [doc]
        else:
            row["targets_resolved"] = [{"docs": [tc._X], "discovery": "local"}]
        return row

    monkeypatch.setattr(tc.ev, "_synthesized_fused_result", discovery)
    report, _ = tc._synth_leg(
        tmp_path,
        monkeypatch,
        "第 4 章规定了哪些要求？逐项列出。",
        {tc._X: tc._foreign_doc()},
    )
    out = report["results"][0]
    assert out["coverage_status"] in {"partial", "ambiguous"}
    assert not ((out.get("answer") or {}).get("items") or [])
    assert not ((out.get("scope_selection") or {}).get("selected_docs") or [])
