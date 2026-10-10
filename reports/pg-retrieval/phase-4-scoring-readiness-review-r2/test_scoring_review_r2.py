"""Remaining scorer wiring checks. Offline fixtures/stored artifacts only."""

import copy
import importlib.util
import json
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SUBMIT = REPO / "reports/pg-retrieval/phase-4-scoring-readiness-r2"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def ctx(monkeypatch):
    a = load(
        Path(os.environ.get("ENV_RAG_SCORING_READINESS_SCRIPT", SUBMIT / "assess_two_rounds.py")),
        "scoring_review_r2_target",
    )
    h = load(
        REPO / "reports/pg-retrieval/phase-4-scoring-readiness/test_scoring_readiness.py",
        "scoring_review_r2_inputs",
    )
    monkeypatch.setattr(h, "assess", a)
    return a, h


def invoke(a, h, tmp, run, records=None, anchor=None):
    out = tmp / "adjudication-new.json"
    argv = [
        "--run-dir",
        str(run),
        "--round",
        "1",
        "--anchor",
        str(anchor or h.ANCHOR),
        "--out",
        str(out),
    ]
    if records:
        argv += ["--records", str(records)]
    a.main(argv)
    return json.loads(out.read_text())


def synthesis_run(h, tmp, coverage):
    run = h.build_run(
        tmp,
        legs=[("pg", "syn-002", h.ROUND1 / "legs/r1/pg/syn-002/answer/answer-runtime-latest.json")],
    )
    art = run / "legs/r1/pg/syn-002/answer/answer-runtime-latest.json"
    d = json.loads(art.read_text())
    d["results"][0]["coverage_status"] = coverage
    art.write_text(json.dumps(d))
    h.rewrite_manifest(run)
    return run, art


@pytest.mark.parametrize("record_mode", ["missing", "PENDING"])
def test_hard_partial_is_fail_without_manual_pass(ctx, tmp_path, record_mode):
    a, h = ctx
    run, _ = synthesis_run(h, tmp_path, "partial")
    records = None
    if record_mode == "PENDING":
        rec = h.record(
            run,
            1,
            "pg",
            "syn-002",
            "PENDING",
            "fixture: semantic reviewer has not decided",
            response="sha",
        )
        records = h.write_records(tmp_path, [rec])
    adj = invoke(a, h, tmp_path, run, records)
    row = next(x for x in adj["rows"] if x["qid"] == "syn-002" and x["path"] == "pg")
    assert row["final_status"] == "FAIL", (
        "known incomplete coverage is not an unresolved semantic gap"
    )


def test_unverified_synthesis_is_fail_without_records(ctx, tmp_path):
    a, h = ctx
    run, art = synthesis_run(h, tmp_path, "complete")
    d = json.loads(art.read_text())
    d["results"][0]["answer"]["items"][0]["citation"]["quote"] = "fabricated impossible quote"
    art.write_text(json.dumps(d))
    h.rewrite_manifest(run)
    adj = invoke(a, h, tmp_path, run)
    row = next(x for x in adj["rows"] if x["qid"] == "syn-002" and x["path"] == "pg")
    assert row["unverified_citations"]
    assert row["final_status"] == "FAIL"


def test_complete_supported_unaudited_synthesis_remains_pending(ctx, tmp_path):
    a, h = ctx
    run, _ = synthesis_run(h, tmp_path, "complete")
    row = next(
        x
        for x in invoke(a, h, tmp_path, run)["rows"]
        if x["qid"] == "syn-002" and x["path"] == "pg"
    )
    assert row["all_citations_verified"] is True
    assert row["final_status"] == "PENDING"


@pytest.mark.parametrize("kind", ["table_unit", "scope"])
def test_typed_target_identity_survives_actual_reader(ctx, tmp_path, kind):
    a, h = ctx
    run = h.build_run(tmp_path)
    q = next(q for q in h.GOLD["questions"] if q["query_id"] == "fact-001")
    ev = q["gold"]["target_evidence"][0]
    fusion = run / "legs/r1/pg/fact-001/fusion/fusion-runtime-latest.json"
    fusion.parent.mkdir(parents=True)
    target = {
        "target_type": kind,
        "workspace": "default",
        "doc_id": ev["doc_id"],
        "citation_verified": True,
    }
    if kind == "table_unit":
        target["unit_id"] = ev["unit_id"]
        target["table_id"] = ev["unit_id"]
    else:
        target["scope_id"] = "fixture-scope"
    fusion.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "query_id": "fact-001",
                        "workspace": "default",
                        "candidates": [],
                        "typed_targets": [target],
                        "pg": {"discovery_captured": True},
                    }
                ]
            }
        )
    )
    h.rewrite_manifest(run)
    mapping = copy.deepcopy(h.MAPPING_FIXTURE)
    mapping["entries"] = [
        {
            "workspace": "default",
            "doc_id": ev["doc_id"],
            "snapshot_id": "4919b3938ad93747",
            "unit_id": ev["unit_id"],
            "chunk_ids": ["fixture-target-chunk"],
            "content_sha256": "a" * 64,
            "scopes": [{"scope_id": "fixture-scope"}],
        }
    ]
    p = h._write_mapping(tmp_path, mapping)
    out = tmp_path / "adjudication-new.json"
    a.main(
        [
            "--run-dir",
            str(run),
            "--round",
            "1",
            "--anchor",
            str(h.ANCHOR),
            "--out",
            str(out),
            "--mapping",
            str(p),
        ]
    )
    row = json.loads(out.read_text())["recall"]["typed_evidence_recall"]["per_question"][
        "fact-001"
    ]["pg"]
    assert row["typed_evidence_recall"] == 1.0 and ev["unit_id"] in row["covered"]


def test_wrong_workspace_typed_target_never_hits(ctx, tmp_path):
    a, h = ctx
    run = h.build_run(tmp_path)
    q = next(q for q in h.GOLD["questions"] if q["query_id"] == "fact-001")
    ev = q["gold"]["target_evidence"][0]
    p = run / "legs/r1/pg/fact-001/fusion/fusion-runtime-latest.json"
    p.parent.mkdir(parents=True)
    p.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "query_id": "fact-001",
                        "workspace": "default",
                        "candidates": [],
                        "typed_targets": [
                            {
                                "target_type": "table_unit",
                                "workspace": "other",
                                "doc_id": ev["doc_id"],
                                "unit_id": ev["unit_id"],
                                "citation_verified": True,
                            }
                        ],
                        "pg": {"discovery_captured": True},
                    }
                ]
            }
        )
    )
    h.rewrite_manifest(run)
    a.configure_generation(run, 1, h.ANCHOR, "pilot-manifest.json")
    mapping = copy.deepcopy(h.MAPPING_FIXTURE)
    mapping["entries"] = [
        {
            "workspace": "default",
            "doc_id": ev["doc_id"],
            "snapshot_id": "4919b3938ad93747",
            "unit_id": ev["unit_id"],
            "chunk_ids": ["fixture-chunk"],
            "content_sha256": "a" * 64,
        }
    ]
    a.load_mapping_manifest(h._write_mapping(tmp_path, mapping))
    row = a.typed_evidence_recall({"questions": [q]})["per_question"]["fact-001"]["pg"]
    assert row["typed_evidence_recall"] == 0.0 and not row["covered"]


def test_each_refusal_gets_new_diagnostic(ctx, tmp_path):
    a, h = ctx
    run, art = synthesis_run(h, tmp_path, "complete")
    original = art.read_bytes()
    art.write_text("{broken answer JSON")
    h.rewrite_manifest(run)
    with pytest.raises(a.InputIntegrityError):
        invoke(a, h, tmp_path, run)
    first = tmp_path / "input-rejection.json"
    original_diag = first.read_bytes()
    art.write_bytes(original)
    h.rewrite_manifest(run)
    rec = h.record(run, 1, "pg", "syn-002", response="sha")
    rec["answer_runtime_sha256"] = "0" * 64
    with pytest.raises(a.InputIntegrityError):
        invoke(a, h, tmp_path, run, h.write_records(tmp_path, [rec]))
    assert first.read_bytes() == original_diag
    diagnostics = list(tmp_path.glob("input-rejection*.json"))
    assert len(diagnostics) == 2, "each failing invocation needs its own current diagnostic"
    assert not (tmp_path / "adjudication-new.json").exists()


def test_required_answer_identity_cannot_be_omitted(ctx, tmp_path):
    a, h = ctx
    run = h.build_run(
        tmp_path,
        legs=[
            (
                "pg",
                "prose-enum-002",
                h.PG_RUN / "legs/r1/pg/prose-enum-002/answer/answer-runtime-latest.json",
            )
        ],
    )
    art = run / "legs/r1/pg/prose-enum-002/answer/answer-runtime-latest.json"
    d = json.loads(art.read_text())
    del d["results"][0]["query_id"]
    art.write_text(json.dumps(d))
    h.rewrite_manifest(run)
    with pytest.raises(a.InputIntegrityError):
        invoke(a, h, tmp_path, run)
    assert (tmp_path / "input-rejection.json").exists()


def test_required_frozen_counts_cannot_be_omitted(ctx, tmp_path):
    a, h = ctx
    run = h.build_run(tmp_path)
    d = json.loads(h.ANCHOR.read_text())
    del d["frozen_identity"]["eight_table_counts"]
    anchor = tmp_path / "incomplete-approved-anchor.json"
    anchor.write_text(json.dumps(d))
    with pytest.raises(a.InputIntegrityError):
        invoke(a, h, tmp_path, run, anchor=anchor)
    assert (tmp_path / "input-rejection.json").exists()
