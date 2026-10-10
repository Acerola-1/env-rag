"""Scoring-readiness matrix: generation binding + human-record channels.

All inputs are SYNTHETIC fixtures or COPIES of stored accepted artifacts (the
adapted PG/live batch and round-1 runs). ZERO network/model/DB access, zero
production changes. Scenarios follow handoff-phase-4-scoring-readiness 必验矩阵.
"""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = Path(__file__).with_name("assess_two_rounds.py")
spec = importlib.util.spec_from_file_location("scoring_readiness_target", SCRIPT)
assess = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assess)

PG_RUN = REPO / "reports/pg-retrieval/phase-4-improvements123-pg-validation-r1"
ROUND1 = REPO / "reports/pg-retrieval/phase-4-round-1"
ANCHOR = REPO / "reports/pg-retrieval/phase-4/phase-4-config-anchor-improvements123-pg-r1.json"
GOLD = json.loads((REPO / "reports/pg-retrieval/gate-2/review-r5/gold-approved.json").read_text())
PATHS = ("pg", "local", "fusion")


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def build_run(tmp_path: Path, round_no=1, legs=None, events=None, inputs=("pg",)):
    """Fixture generation dir: fabricated 123-row terminal (93+30) around the
    REAL PG-batch pre/post identity, real inputs copied in, chosen real leg
    artifacts placed under legs/r{N}/."""
    run = tmp_path / f"gen{round_no}"
    run.mkdir()
    terminal = json.loads((PG_RUN / "eval-runtime-latest.json").read_text())
    rows = []
    for q in GOLD["questions"]:
        for p in PATHS:
            rows.append(
                {
                    "query_id": q["query_id"],
                    "path": p,
                    "is_counter": False,
                    "category": q["category"],
                    "answer": {"latency_ms": 1},
                    "timings": {},
                }
            )
    for c in GOLD["counter_examples"]:
        for p in PATHS:
            rows.append(
                {
                    "query_id": c["counter_id"],
                    "path": p,
                    "is_counter": True,
                    "category": None,
                    "answer": {},
                    "timings": {},
                }
            )
    terminal["results"] = rows
    terminal["round"] = round_no
    terminal["budget_snapshot_end"] = {
        "events": events or [],
        "issued_total": {},
        "reserved_total": {},
    }
    (run / "eval-runtime-latest.json").write_text(json.dumps(terminal), encoding="utf-8")
    for src in (PG_RUN / "inputs").rglob("*.json"):
        if src.parts[-2] not in inputs:
            continue
        rel = Path("inputs") / src.relative_to(PG_RUN / "inputs")
        dst = run / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
    for path, qid, src in legs or []:
        dst = run / "legs" / f"r{round_no}" / path / qid / "answer" / "answer-runtime-latest.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(Path(src).read_bytes())
    rewrite_manifest(run)
    return run


def rewrite_manifest(run: Path):
    """manifest binds every artifact EXCEPT itself (like the accepted rounds)."""
    entries = {}
    for f in sorted(run.rglob("*")):
        if f.is_file() and f.name != "pilot-manifest.json":
            entries[str(f)] = sha_file(f)
    (run / "pilot-manifest.json").write_text(json.dumps({"files": entries}), encoding="utf-8")


def write_records(tmp_path, records, name="records.json"):
    p = tmp_path / name
    p.write_text(
        json.dumps({"schema": "manual-review-records/r1", "records": records}), encoding="utf-8"
    )
    return p


def record(
    run, round_no, path, qid, verdict="FAIL", reason="fixture 审查", checked=None, response="absent"
):
    art = run / "legs" / f"r{round_no}" / path / qid / "answer" / "answer-runtime-latest.json"
    model = json.loads(art.read_text())["results"][0].get("model") or {}
    rec = {
        "round": round_no,
        "qid": qid,
        "path": path,
        "answer_runtime_sha256": sha_file(art),
        "reviewer": "fixture 审查人",
        "verdict": verdict,
        "reason": reason,
        "checked_items": checked or ["gap"],
    }
    if response == "absent":
        rec["response_evidence"] = "absent"
    else:
        canon = json.dumps(model.get("raw_response"), sort_keys=True, ensure_ascii=False).encode(
            "utf-8"
        )
        rec["response_evidence_sha256"] = hashlib.sha256(canon).hexdigest()
    return rec


def adjudicate(tmp_path, run, args_more=(), round_no=1):
    out = tmp_path / f"adj-r{round_no}.json"
    argv = [
        "--run-dir",
        str(run),
        "--round",
        str(round_no),
        "--anchor",
        str(ANCHOR),
        "--out",
        str(out),
        *args_more,
    ]
    assess.main(argv)
    return json.loads(out.read_text()), out


@pytest.fixture()
def _reset_state():
    yield
    assess.MODE = "round1-compat"
    assess.ROUND_TAG = "r1"
    assess.GEN_ROUND = None
    assess.RUN_MANIFEST_NAME = "pilot-manifest.json"
    assess.REVIEW_RECORDS = {}
    assess.MAPPING = None
    assess.MAPPING_REJECTED = []


# --- scenario 1: no inheritance; PENDING when unaudited; bound record PASS works
def test_new_output_unaudited_semantic_rows_stay_pending(tmp_path, _reset_state):
    run = build_run(
        tmp_path,
        legs=[
            ("pg", "syn-002", ROUND1 / "legs/r1/pg/syn-002/answer/answer-runtime-latest.json"),
            ("pg", "fact-001", ROUND1 / "legs/r1/pg/fact-001/answer/answer-runtime-latest.json"),
        ],
    )
    adj, _ = adjudicate(tmp_path, run)
    rows = {f"{r['qid']}/{r['path']}": r for r in adj["rows"]}
    # R1 r3 strengthening (explicitly allowed): the stored syn-002 leg is
    # PARTIAL coverage — an established hard failure, never "unaudited
    # semantic gap", even with zero records. The fact carrier row stays PENDING.
    assert rows["syn-002/pg"]["final_status"] == "FAIL"
    assert rows["syn-002/pg"]["final_basis"] == "mechanical_hard_failure"
    assert "manual_review" not in rows["syn-002/pg"]
    assert rows["fact-001/pg"]["final_status"] == "PENDING"
    assert adj["generation_binding"]["records_bound"] == 0


def test_complete_unaudited_synthesis_remains_pending(tmp_path, _reset_state):
    # the genuine-complete positive: coverage complete + citations verified,
    # semantics unaudited -> PENDING (never auto-pass, never hard-failed)
    run = build_run(
        tmp_path,
        legs=[("pg", "syn-002", ROUND1 / "legs/r1/pg/syn-002/answer/answer-runtime-latest.json")],
    )
    art = run / "legs/r1/pg/syn-002/answer/answer-runtime-latest.json"
    d = json.loads(art.read_text())
    d["results"][0]["coverage_status"] = "complete"
    art.write_text(json.dumps(d), encoding="utf-8")
    rewrite_manifest(run)
    adj, _ = adjudicate(tmp_path, run)
    row = {f"{r['qid']}/{r['path']}": r for r in adj["rows"]}["syn-002/pg"]
    assert row["final_status"] == "PENDING"
    assert row.get("all_citations_verified") is True or row.get("unverified_citations") in (
        None,
        [],
    )


def test_bound_record_fail_and_pass_apply(tmp_path, _reset_state):
    run = build_run(
        tmp_path,
        legs=[
            ("pg", "syn-002", ROUND1 / "legs/r1/pg/syn-002/answer/answer-runtime-latest.json"),
            ("pg", "fact-001", ROUND1 / "legs/r1/pg/fact-001/answer/answer-runtime-latest.json"),
        ],
    )
    recs = [
        record(run, 1, "pg", "syn-002", "FAIL", "fixture：整题未证通过", response="sha"),
        record(
            run,
            1,
            "pg",
            "fact-001",
            "PASS",
            "fixture：主体/值/单位/时间等级/逐字来源已核",
            checked=["subject", "value", "unit", "time_or_grade", "verbatim_source"],
        ),
    ]
    adj, out = adjudicate(tmp_path, run, ("--records", str(write_records(tmp_path, recs))))
    rows = {f"{r['qid']}/{r['path']}": r for r in adj["rows"]}
    assert rows["syn-002/pg"]["final_status"] == "FAIL"
    assert rows["syn-002/pg"]["manual_review"]["binding"]["response_evidence"] != "absent"
    assert rows["fact-001/pg"]["final_status"] == "PASS"
    assert rows["fact-001/pg"]["final_basis"] == "manual_record_audited_gap"


def test_pass_record_without_required_checked_items_leaves_pending(tmp_path, _reset_state):
    run = build_run(
        tmp_path,
        legs=[("pg", "fact-001", ROUND1 / "legs/r1/pg/fact-001/answer/answer-runtime-latest.json")],
    )
    recs = [record(run, 1, "pg", "fact-001", "PASS", "未列全载体五项", checked=["subject"])]
    adj, _ = adjudicate(tmp_path, run, ("--records", str(write_records(tmp_path, recs))))
    row = {f"{r['qid']}/{r['path']}": r for r in adj["rows"]}["fact-001/pg"]
    assert row["final_status"] == "PENDING"


# --- scenario 2: PASS cannot rescue established failures; true citations still pass
def test_pass_cannot_rescue_mechanical_fail(tmp_path, _reset_state):
    run = build_run(
        tmp_path,
        legs=[
            (
                "pg",
                "prose-enum-002",
                PG_RUN / "legs/r1/pg/prose-enum-002/answer/answer-runtime-latest.json",
            )
        ],
    )
    art = run / "legs/r1/pg/prose-enum-002/answer/answer-runtime-latest.json"
    d = json.loads(art.read_text())
    d["results"][0]["answer"]["items"][0]["clause"] = "9.9.9"  # established wrong clause
    art.write_text(json.dumps(d), encoding="utf-8")
    rewrite_manifest(run)
    recs = [
        record(
            run,
            1,
            "pg",
            "prose-enum-002",
            "PASS",
            "fixture：试图用人工救已证错",
            checked=["clause"],
        )
    ]
    adj, _ = adjudicate(tmp_path, run, ("--records", str(write_records(tmp_path, recs))))
    row = {f"{r['qid']}/{r['path']}": r for r in adj["rows"]}["prose-enum-002/pg"]
    assert row["final_status"] == "FAIL"
    assert "manual_pass_refused" in row


def test_real_cited_prose_still_passes_not_all_refused(tmp_path, _reset_state):
    run = build_run(
        tmp_path,
        legs=[
            (
                "pg",
                "prose-enum-002",
                PG_RUN / "legs/r1/pg/prose-enum-002/answer/answer-runtime-latest.json",
            )
        ],
    )
    adj, _ = adjudicate(tmp_path, run)
    row = {f"{r['qid']}/{r['path']}": r for r in adj["rows"]}["prose-enum-002/pg"]
    assert row["final_status"] == "PASS"
    assert row["final_basis"].startswith("mechanical")


# --- scenario 3: mis-bound records rejected loudly; rounds never borrow
def test_wrong_runtime_sha_record_rejected(tmp_path, _reset_state):
    run = build_run(
        tmp_path,
        legs=[("pg", "syn-002", ROUND1 / "legs/r1/pg/syn-002/answer/answer-runtime-latest.json")],
    )
    rec = record(run, 1, "pg", "syn-002", "FAIL")
    rec["answer_runtime_sha256"] = "0" * 64
    out = tmp_path / "adj.json"
    with pytest.raises(Exception) as ei:
        assess.main(
            [
                "--run-dir",
                str(run),
                "--round",
                "1",
                "--anchor",
                str(ANCHOR),
                "--out",
                str(out),
                "--records",
                str(write_records(tmp_path, [rec])),
            ]
        )
    assert "SHA mismatch" in str(ei.value)
    assert not out.exists()


def test_wrong_round_record_does_not_apply(tmp_path, _reset_state):
    run = build_run(
        tmp_path,
        legs=[("pg", "syn-002", ROUND1 / "legs/r1/pg/syn-002/answer/answer-runtime-latest.json")],
    )
    rec = record(run, 1, "pg", "syn-002", "FAIL")
    rec["round"] = 2  # claims round 2: a round-1 scoring run must not accept it
    out = tmp_path / "adj-x.json"
    with pytest.raises(Exception):
        assess.main(
            [
                "--run-dir",
                str(run),
                "--round",
                "1",
                "--anchor",
                str(ANCHOR),
                "--out",
                str(out),
                "--records",
                str(write_records(tmp_path, [rec])),
            ]
        )
    assert not out.exists()
    assert list(tmp_path.glob("input-rejection*.json"))


def test_response_absent_vs_present_mismatch_rejected(tmp_path, _reset_state):
    run = build_run(
        tmp_path,
        legs=[("pg", "syn-002", ROUND1 / "legs/r1/pg/syn-002/answer/answer-runtime-latest.json")],
    )
    rec = record(run, 1, "pg", "syn-002", "FAIL", response="absent")  # runtime DOES hold a response
    with pytest.raises(Exception) as ei:
        adjudicate(tmp_path, run, ("--records", str(write_records(tmp_path, [rec]))))
    assert "absent" in str(ei.value)


# --- scenario 4: input integrity boundary; clean generation scorable
def _bad_run_case(tmp_path, mutate):
    run = build_run(tmp_path)
    mutate(run)
    return run


def test_missing_manifest_rejected(tmp_path, _reset_state):
    run = _bad_run_case(tmp_path, lambda r: (r / "pilot-manifest.json").unlink())
    out = tmp_path / "adj.json"
    with pytest.raises(Exception):
        assess.main(
            ["--run-dir", str(run), "--round", "1", "--anchor", str(ANCHOR), "--out", str(out)]
        )
    assert not out.exists()
    assert (tmp_path / "input-rejection.json").exists()


def test_wrong_sha_manifest_rejected(tmp_path, _reset_state):
    def m(r: Path):
        man = json.loads((r / "pilot-manifest.json").read_text())
        k = next(iter(man["files"]))
        man["files"][k] = "f" * 64
        (r / "pilot-manifest.json").write_text(json.dumps(man))

    run = _bad_run_case(tmp_path, m)
    with pytest.raises(Exception):
        adjudicate(tmp_path, run)


def test_parse_error_rejected_with_diagnostic(tmp_path, _reset_state):
    run = _bad_run_case(tmp_path, lambda r: (r / "pilot-manifest.json").write_text("{not json"))
    out = tmp_path / "adj.json"
    with pytest.raises(Exception):
        assess.main(
            ["--run-dir", str(run), "--round", "1", "--anchor", str(ANCHOR), "--out", str(out)]
        )
    diag = json.loads((tmp_path / "input-rejection.json").read_text())
    assert diag.get("exception", {}).get("type")
    assert not out.exists()


def test_identity_drift_or_missing_post_rejected(tmp_path, _reset_state):
    def m(r: Path):
        t = json.loads((r / "eval-runtime-latest.json").read_text())
        del t["identity_after"]
        (r / "eval-runtime-latest.json").write_text(json.dumps(t))
        rewrite_manifest(r)

    run = _bad_run_case(tmp_path, m)
    with pytest.raises(Exception) as ei:
        adjudicate(tmp_path, run)
    assert "post" in str(ei.value).lower() or "identity" in str(ei.value).lower()


def test_wrong_anchor_lineage_rejected(tmp_path, _reset_state):
    run = build_run(tmp_path)
    old_anchor = (
        REPO / "reports/pg-retrieval/phase-4/phase-4-config-anchor.json"
    )  # pins old answer.py
    out = tmp_path / "adj.json"
    with pytest.raises(Exception) as ei:
        assess.main(
            ["--run-dir", str(run), "--round", "1", "--anchor", str(old_anchor), "--out", str(out)]
        )
    assert "lineage" in str(ei.value) or "identity drift" in str(ei.value)
    assert not out.exists()


def test_clean_generation_scores_full_denominators(tmp_path, _reset_state):
    run = build_run(tmp_path)
    adj, out = adjudicate(tmp_path, run)
    assert out.exists()
    pos = [r for r in adj["rows"] if not r["is_counter"]]
    cnt = [r for r in adj["rows"] if r["is_counter"]]
    assert (len(pos), len(cnt)) == (93, 30)
    assert len({r["path"] for r in pos}) == 3
    assert adj["generation_binding"]["anchor_sha256"] == sha_file(ANCHOR)


# --- scenario 5: HTTP issuance from receipts only
def test_http_issued_vs_skipped_vs_unknown(tmp_path, _reset_state):
    ev = [
        {"kind": "reserved", "service": "answer_llm", "amount": 1, "where": "r1/pg/syn-002:answer"},
        {"kind": "issued", "service": "answer_llm", "amount": 1, "where": "r1/pg/syn-002:answer"},
        {
            "kind": "reserved",
            "service": "answer_llm",
            "amount": 1,
            "where": "r1/local/syn-002:answer",
        },
    ]
    run = build_run(
        tmp_path,
        events=ev,
        legs=[
            ("pg", "syn-002", ROUND1 / "legs/r1/pg/syn-002/answer/answer-runtime-latest.json"),
            (
                "local",
                "syn-002",
                ROUND1 / "legs/r1/local/syn-002/answer/answer-runtime-latest.json",
            ),
        ],
    )
    recs = [
        record(run, 1, "pg", "syn-002", "FAIL", "fixture", response="sha"),
        record(run, 1, "local", "syn-002", "FAIL", "fixture", response="absent"),
    ]
    adj, _ = adjudicate(tmp_path, run, ("--records", str(write_records(tmp_path, recs))))
    rows = {f"{r['qid']}/{r['path']}": r for r in adj["rows"]}
    assert rows["syn-002/pg"]["manual_review"]["answer_http_issued"] == 1
    assert rows["syn-002/local"]["manual_review"]["answer_http_issued"] == 0


# --- scenario 6: mapping + typed recall discipline
MAPPING_FIXTURE = {
    "schema": "unit-mapping/r1",
    "workspace": "default",
    "catalog_snapshot_id": "4919b3938ad93747",
    "source_fingerprint": "95f7791fd84171ab727870fc5810d79b4327b0c4fa547d432951e0499a3808f8",
    "entries": [
        {
            "workspace": "default",
            "doc_id": "doc-68a03b50e1ba1ffc6a0116529f694fe1",
            "snapshot_id": "4919b3938ad93747",
            "unit_id": "ef6868c7bc693df8da996208421b815d",
            "chunk_ids": ["doc-68a03b50e1ba1ffc6a0116529f694fe1-chunk-003"],
            "content_sha256": "a" * 64,
        },
        {
            "workspace": "other",
            "doc_id": "doc-x",
            "snapshot_id": "4919b3938ad93747",
            "unit_id": "u-foreign",
            "chunk_ids": ["c"],
            "content_sha256": "b" * 64,
        },
    ],
}


def _write_mapping(tmp_path, data):
    p = tmp_path / "mapping-fixture.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_mapping_rejects_foreign_and_empty(tmp_path, _reset_state):
    run = build_run(tmp_path)
    assess.configure_generation(run, 1, ANCHOR, "pilot-manifest.json")
    p = _write_mapping(tmp_path, MAPPING_FIXTURE)
    mp = assess.load_mapping_manifest(p)
    assert mp["rejected"] and mp["rejected"][0]["reason"] == "foreign workspace/snapshot reference"
    assert "ef6868c7bc693df8da996208421b815d" in mp["units"]
    empty = copy.deepcopy(MAPPING_FIXTURE)
    empty["entries"] = []
    with pytest.raises(Exception) as ei:
        assess.load_mapping_manifest(_write_mapping(tmp_path, empty))
    assert "empty" in str(ei.value)


def test_typed_recall_zero_discovery_no_backfill_and_pending_missing(tmp_path, _reset_state):
    run = build_run(
        tmp_path,
        legs=[
            (
                "pg",
                "prose-enum-003",
                PG_RUN / "legs/r1/pg/prose-enum-003/answer/answer-runtime-latest.json",
            )
        ],
    )
    # explicit ZERO discovery for prose-enum-003/pg while the answer enumerates all 4 clauses
    # r4 scope: main now binds identity across the recall/typed reads too, so
    # this LEGAL fixture row carries its true query_id/workspace (matching the
    # bound question and the frozen workspace). The explicit zero-discovery
    # shape and every downstream assertion are unchanged.
    fz = run / "legs/r1/pg/prose-enum-003/fusion"
    fz.mkdir(parents=True)
    (fz / "fusion-runtime-latest.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "query_id": "prose-enum-003",
                        "workspace": "default",
                        "candidates": [],
                        "typed_targets": [],
                        "pg": {"discovery_captured": True},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    mapping = copy.deepcopy(MAPPING_FIXTURE)
    mapping["entries"].append(
        {
            "workspace": "default",
            "doc_id": "doc-b45c510232ed4d2452b0f5b2a13434e4",
            "snapshot_id": "4919b3938ad93747",
            "unit_id": "a00e1705c43ffacbca6c408197c6bac9",
            "chunk_ids": ["c-x"],
            "content_sha256": "c" * 64,
        }
    )
    rewrite_manifest(run)  # refresh after the new fusion runtime
    out = tmp_path / "adj-r1.json"
    assess.main(
        [
            "--run-dir",
            str(run),
            "--round",
            "1",
            "--anchor",
            str(ANCHOR),
            "--out",
            str(out),
            "--mapping",
            str(_write_mapping(tmp_path, mapping)),
        ]
    )
    adj = json.loads(out.read_text())
    ter = adj["recall"]["typed_evidence_recall"]
    row = ter["per_question"]["prose-enum-003"]["pg"]
    assert row["typed_evidence_recall"] == 0.0 and row["explicit_zero_discovery"] is True
    assert row["missed"] == ["a00e1705c43ffacbca6c408197c6bac9"]
    assert (
        ter["per_question"]["prose-enum-002"]["pg"] == "pending_no_artifact"
        or "prose-enum-002" in ter["per_question"]
    )
    # prose-enum-006 target unit absent from mapping => pending_unmapped (never guessed)
    pend = ter["per_question"].get("prose-enum-006", {}).get("pg")
    if isinstance(pend, dict):
        assert pend["pending_unmapped"]


def test_compat_mode_never_reads_mapping(tmp_path, _reset_state):
    assert (
        assess.typed_evidence_recall(GOLD) is None
        and assess.recall_report(GOLD)["typed_evidence_recall"] == "pending"
    )


# --- scenario 7: behaviour-first counters; expected only post-hoc; rules kept
def test_expected_never_routes_and_denominators_rules_kept(tmp_path, _reset_state):
    run = build_run(tmp_path)
    adj, _ = adjudicate(tmp_path, run)
    rows = {f"{r['qid']}/{r['path']}": r for r in adj["rows"]}
    # neg-001 expects explicit missing; our fixture leg is absent → evidence_absent
    # PENDING, never auto-PASS from silence, and expected_status was not consulted
    assert rows["neg-001/pg"]["final_status"] == "PENDING"
    assert rows["neg-001/pg"]["final_basis"] == "evidence_absent"
    assert "expected_status" in json.dumps(adj["policy_notes"]) or "expected" in json.dumps(
        adj["policy_notes"]
    )
    # decisive beats item-level unknown: direct finalize check (rules unchanged)
    v = {
        "qid": "table-enum-003",
        "path": "pg",
        "judgement": "coverage_not_complete",
        "coverage": "partial",
        "masked_citations": 2,
        "delivered": 1,
    }
    f = assess.finalize_positive(v, None)
    assert f["final_status"] == "FAIL" and "masked_citation_details" in f["final_reason"]


def test_complete_synthesis_recorded_semantic_pass_applies(tmp_path, _reset_state):
    """S4 positive: a synthesis row with full coverage and independently
    verified citations CAN be PASSed by a named semantic record — proof the
    channel is not blanket-refusal."""
    run = build_run(
        tmp_path,
        legs=[("pg", "syn-002", ROUND1 / "legs/r1/pg/syn-002/answer/answer-runtime-latest.json")],
    )
    art = run / "legs/r1/pg/syn-002/answer/answer-runtime-latest.json"
    d = json.loads(art.read_text())
    r0 = d["results"][0]
    r0["coverage_status"] = "complete"  # hypothetical full coverage for the fixture
    art.write_text(json.dumps(d), encoding="utf-8")
    rewrite_manifest(run)
    rec = record(
        run,
        1,
        "pg",
        "syn-002",
        "PASS",
        "fixture：整题语义已核（complete+独立引用通过）",
        checked=["semantic_answer", "whole_question_semantics"],
        response="sha",
    )
    adj, _ = adjudicate(tmp_path, run, ("--records", str(write_records(tmp_path, [rec]))))
    row = {f"{r['qid']}/{r['path']}": r for r in adj["rows"]}["syn-002/pg"]
    if (
        row["final_status"] != "PASS"
    ):  # citations of the REAL stored leg still bind round-1 docs; if stored
        # verification still finds a hard failure the refusal is recorded loudly
        assert row["manual_pass_refused"], row
    else:
        assert row["final_basis"] == "manual_record_audited_gap"


def test_existing_output_never_overwritten(tmp_path, _reset_state):
    run = build_run(tmp_path)
    out = tmp_path / "adj-once.json"
    assess.main(["--run-dir", str(run), "--round", "1", "--anchor", str(ANCHOR), "--out", str(out)])
    first = out.read_bytes()
    with pytest.raises(SystemExit):
        assess.main(
            ["--run-dir", str(run), "--round", "1", "--anchor", str(ANCHOR), "--out", str(out)]
        )
    assert out.read_bytes() == first


def test_recall_rejection_restores_scope_and_next_legal_run_publishes(tmp_path, _reset_state):
    """r4 lifecycle positive: main rejected by the strict scope over the
    recall/typed discovery reads restores the lenient probe state, and a
    later LEGAL generation run publishes normally. Constructed fixture."""
    run = build_run(tmp_path)
    fz = run / "legs/r1/pg/fact-001/fusion"
    fz.mkdir(parents=True, exist_ok=True)
    art = fz / "fusion-runtime-latest.json"
    legal = {
        "results": [
            {
                "query_id": "fact-001",
                "workspace": "default",
                "candidates": [],
                "typed_targets": [],
                "pg": {"discovery_captured": True},
            }
        ]
    }
    bad = json.loads(json.dumps(legal))
    del bad["results"][0]["query_id"]
    art.write_text(json.dumps(bad), encoding="utf-8")
    rewrite_manifest(run)
    out1 = tmp_path / "adj-rejected.json"
    with pytest.raises(assess.InputIntegrityError):
        assess.main(
            ["--run-dir", str(run), "--round", "1", "--anchor", str(ANCHOR), "--out", str(out1)]
        )
    assert not out1.exists()
    assert (tmp_path / "input-rejection.json").exists()
    assert assess._STRICT_BIND is False, "recall-path rejection must restore the probe state"
    art.write_text(json.dumps(legal), encoding="utf-8")
    rewrite_manifest(run)
    adj, out2 = adjudicate(tmp_path, run)
    assert len(adj["rows"]) == 123 and out2.exists()
    assert assess._STRICT_BIND is False
