"""Independent offline owning-entry checks; no services or production edits."""

import copy
import importlib.util
import json
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SUBMIT = REPO / "reports/pg-retrieval/phase-4-scoring-readiness"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ctx(monkeypatch):
    target = Path(
        os.environ.get("ENV_RAG_SCORING_READINESS_SCRIPT", SUBMIT / "assess_two_rounds.py")
    )
    a = load(target, "review_scorer")
    h = load(SUBMIT / "test_scoring_readiness.py", "review_input_helpers")
    monkeypatch.setattr(h, "assess", a)
    return a, h


def invoke(a, h, tmp, run, *, records=None, anchor=None):
    out = tmp / "new-adjudication.json"
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


def expect_rejection(a, h, tmp, run, **kwargs):
    with pytest.raises((a.InputIntegrityError, SystemExit)):
        invoke(a, h, tmp, run, **kwargs)
    assert not (tmp / "new-adjudication.json").exists()
    assert (tmp / "input-rejection.json").exists(), "refusal must publish a diagnostic"


def prose_run(h, tmp):
    return h.build_run(
        tmp,
        legs=[
            (
                "pg",
                "prose-enum-002",
                h.PG_RUN / "legs/r1/pg/prose-enum-002/answer/answer-runtime-latest.json",
            )
        ],
    )


@pytest.mark.parametrize("omitted", ["terminal", "answer"])
def test_manifest_must_cover_consumed_artifacts(ctx, tmp_path, omitted):
    a, h = ctx
    run = prose_run(h, tmp_path)
    p = run / "pilot-manifest.json"
    data = json.loads(p.read_text())
    tail = "eval-runtime-latest.json" if omitted == "terminal" else "answer-runtime-latest.json"
    data["files"] = {k: v for k, v in data["files"].items() if not k.endswith(tail)}
    p.write_text(json.dumps(data))
    expect_rejection(a, h, tmp_path, run)


@pytest.mark.parametrize("field", ["env_sha", "counts"])
def test_post_identity_every_frozen_field(ctx, tmp_path, field):
    a, h = ctx
    run = h.build_run(tmp_path)
    p = run / "eval-runtime-latest.json"
    d = json.loads(p.read_text())
    if field == "env_sha":
        d["identity_after"][field] = "0" * 64
    else:
        d["identity_after"][field]["lightrag_doc_full"] += 1
    p.write_text(json.dumps(d))
    h.rewrite_manifest(run)
    expect_rejection(a, h, tmp_path, run)


def test_denominator_requires_unique_gold_matrix(ctx, tmp_path):
    a, h = ctx
    run = h.build_run(tmp_path)
    p = run / "eval-runtime-latest.json"
    d = json.loads(p.read_text())
    d["results"][1] = copy.deepcopy(d["results"][0])  # still 93+30, missing one key
    p.write_text(json.dumps(d))
    h.rewrite_manifest(run)
    expect_rejection(a, h, tmp_path, run)


def test_required_lineage_cannot_be_deleted(ctx, tmp_path):
    a, h = ctx
    run = h.build_run(tmp_path)
    d = json.loads(h.ANCHOR.read_text())
    d["code_anchors"] = {
        k: v for k, v in d["code_anchors"].items() if k in ("answer.py", "fusion.py")
    }
    d["evaluation_code_anchors"] = {}
    p = tmp_path / "incomplete-anchor.json"
    p.write_text(json.dumps(d))
    expect_rejection(a, h, tmp_path, run, anchor=p)


def test_answer_file_must_bind_this_question(ctx, tmp_path):
    a, h = ctx
    run = prose_run(h, tmp_path)
    p = run / "legs/r1/pg/prose-enum-002/answer/answer-runtime-latest.json"
    d = json.loads(p.read_text())
    d["results"][0]["query_id"] = "prose-enum-001"
    p.write_text(json.dumps(d))
    h.rewrite_manifest(run)
    expect_rejection(a, h, tmp_path, run)


@pytest.mark.parametrize("mutation", ["partial", "invalid-citation"])
def test_manual_pass_cannot_rescue_synthesis_contract_failure(ctx, tmp_path, mutation):
    a, h = ctx
    run = h.build_run(
        tmp_path,
        legs=[("pg", "syn-002", h.ROUND1 / "legs/r1/pg/syn-002/answer/answer-runtime-latest.json")],
    )
    p = run / "legs/r1/pg/syn-002/answer/answer-runtime-latest.json"
    d = json.loads(p.read_text())
    r = d["results"][0]
    assert r["answer"]["items"]
    if mutation == "partial":
        r["coverage_status"] = "partial"
    else:
        r["coverage_status"] = "complete"
        r["answer"]["items"][0]["citation"]["quote"] = "fabricated impossible quote"
    p.write_text(json.dumps(d))
    h.rewrite_manifest(run)
    rec = h.record(
        run,
        1,
        "pg",
        "syn-002",
        "PASS",
        "fixture cannot override source failure",
        checked=["semantic_answer"],
        response="sha",
    )
    adj = invoke(a, h, tmp_path, run, records=h.write_records(tmp_path, [rec]))
    row = next(x for x in adj["rows"] if x["qid"] == "syn-002" and x["path"] == "pg")
    assert row["final_status"] == "FAIL", row


def test_misbound_round_records_refused_with_diagnostic(ctx, tmp_path):
    a, h = ctx
    run = h.build_run(
        tmp_path,
        legs=[("pg", "syn-002", h.ROUND1 / "legs/r1/pg/syn-002/answer/answer-runtime-latest.json")],
    )
    rec = h.record(run, 1, "pg", "syn-002", response="sha")
    rec["round"] = 2
    expect_rejection(a, h, tmp_path, run, records=h.write_records(tmp_path, [rec]))


def test_record_sha_failure_has_diagnostic(ctx, tmp_path):
    a, h = ctx
    run = h.build_run(
        tmp_path,
        legs=[("pg", "syn-002", h.ROUND1 / "legs/r1/pg/syn-002/answer/answer-runtime-latest.json")],
    )
    rec = h.record(run, 1, "pg", "syn-002", response="sha")
    rec["answer_runtime_sha256"] = "0" * 64
    expect_rejection(a, h, tmp_path, run, records=h.write_records(tmp_path, [rec]))


def test_answer_parse_failure_has_diagnostic(ctx, tmp_path):
    a, h = ctx
    run = prose_run(h, tmp_path)
    p = run / "legs/r1/pg/prose-enum-002/answer/answer-runtime-latest.json"
    p.write_text("{invalid json")
    h.rewrite_manifest(run)
    expect_rejection(a, h, tmp_path, run)


def typed_setup(a, h, tmp, targets, mapping_entries, chunks):
    run = h.build_run(tmp)
    p = run / "legs/r1/pg/probe/fusion/fusion-runtime-latest.json"
    p.parent.mkdir(parents=True)
    p.write_text(
        json.dumps(
            {
                "results": [
                    {"candidates": chunks, "typed_targets": [], "pg": {"discovery_captured": True}}
                ]
            }
        )
    )
    a.configure_generation(run, 1, h.ANCHOR, "pilot-manifest.json")
    mapping = copy.deepcopy(h.MAPPING_FIXTURE)
    mapping["entries"] = mapping_entries
    a.load_mapping_manifest(h._write_mapping(tmp, mapping))
    gold = {"questions": [{"query_id": "probe", "gold": {"target_evidence": targets}}]}
    return a.typed_evidence_recall(gold)["per_question"]["probe"]["pg"]


def ent(doc="d", uid="u", chunks=None):
    return {
        "workspace": "default",
        "doc_id": doc,
        "snapshot_id": "4919b3938ad93747",
        "unit_id": uid,
        "chunk_ids": chunks or ["c-target"],
        "content_sha256": "a" * 64,
    }


def target(doc="d", uid="u"):
    return {"workspace": "default", "doc_id": doc, "unit_id": uid}


def test_wrong_chunk_same_document_cannot_hit_unit(ctx, tmp_path):
    a, h = ctx
    row = typed_setup(
        a,
        h,
        tmp_path,
        [target()],
        [ent()],
        [{"workspace": "default", "doc_id": "d", "chunk_id": "c-other"}],
    )
    assert row["typed_evidence_recall"] in (None, 0.0) and not row["covered"]


def test_unmapped_units_do_not_shrink_metric_denominator(ctx, tmp_path):
    a, h = ctx
    row = typed_setup(
        a,
        h,
        tmp_path,
        [target(), target(uid="u-missing")],
        [ent()],
        [{"workspace": "default", "doc_id": "d", "chunk_id": "c-target"}],
    )
    assert row["pending_unmapped"] == ["u-missing"]
    assert row["typed_evidence_recall"] is None, (
        "unresolved unit cannot become a perfect published metric"
    )


def test_mapping_uses_document_and_workspace_composite_key(ctx, tmp_path):
    a, h = ctx
    row = typed_setup(
        a,
        h,
        tmp_path,
        [target("d1")],
        [ent("d1"), ent("d2", chunks=["c2"])],
        [{"workspace": "default", "doc_id": "d2", "chunk_id": "c2"}],
    )
    assert row["typed_evidence_recall"] in (None, 0.0) and not row["covered"]


def test_known_chunk_unit_positive_still_hit(ctx, tmp_path):
    a, h = ctx
    row = typed_setup(
        a,
        h,
        tmp_path,
        [target()],
        [ent()],
        [{"workspace": "default", "doc_id": "d", "chunk_id": "c-target"}],
    )
    assert row["typed_evidence_recall"] == 1.0 and row["covered"]


def test_clean_identity_and_source_still_scores_true_prose(ctx, tmp_path):
    a, h = ctx
    adj = invoke(a, h, tmp_path, prose_run(h, tmp_path))
    row = next(x for x in adj["rows"] if x["qid"] == "prose-enum-002" and x["path"] == "pg")
    assert row["final_status"] == "PASS"
    assert len(adj["rows"]) == 123
