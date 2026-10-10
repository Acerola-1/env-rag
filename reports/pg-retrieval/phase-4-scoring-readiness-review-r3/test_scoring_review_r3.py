"""One remaining strict binding lifetime at the owning entry; offline only."""

import importlib.util
import json
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SUBMIT = REPO / "reports/pg-retrieval/phase-4-scoring-readiness-r3"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def ctx(monkeypatch):
    a = load(
        Path(os.environ.get("ENV_RAG_SCORING_READINESS_SCRIPT", SUBMIT / "assess_two_rounds.py")),
        "scoring_r3_target",
    )
    h = load(
        REPO / "reports/pg-retrieval/phase-4-scoring-readiness/test_scoring_readiness.py",
        "scoring_r3_inputs",
    )
    monkeypatch.setattr(h, "assess", a)
    return a, h


def discovery_run(h, tmp, kind, omitted=None):
    run = h.build_run(tmp)
    row = {"query_id": "fact-001", "workspace": "default", "status": "ok"}
    if kind == "fusion":
        p = run / "legs/r1/pg/fact-001/fusion/fusion-runtime-latest.json"
        row.update(candidates=[], typed_targets=[], pg={"discovery_captured": True})
    else:
        p = run / "inputs/local/fact-001-fusion.json"
        row.update(usable=[])
    if omitted:
        del row[omitted]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"results": [row]}))
    h.rewrite_manifest(run)
    return run


def invoke(a, h, tmp, run):
    out = tmp / "new-adjudication.json"
    a.main(["--run-dir", str(run), "--round", "1", "--anchor", str(h.ANCHOR), "--out", str(out)])
    return json.loads(out.read_text())


@pytest.mark.parametrize(("kind", "omitted"), [("fusion", "query_id"), ("local", "workspace")])
def test_strict_binding_covers_post_answer_discovery_reads(ctx, tmp_path, kind, omitted):
    a, h = ctx
    run = discovery_run(h, tmp_path, kind, omitted)
    with pytest.raises(a.InputIntegrityError):
        invoke(a, h, tmp_path, run)
    assert not (tmp_path / "new-adjudication.json").exists()
    assert (tmp_path / "input-rejection.json").exists()
    assert a._STRICT_BIND is False, "strict scope must restore after failure"


def test_valid_empty_discovery_keeps_zero_and_restores_binding(ctx, tmp_path):
    a, h = ctx
    run = discovery_run(h, tmp_path, "fusion")
    adj = invoke(a, h, tmp_path, run)
    assert len(adj["rows"]) == 123
    assert adj["recall"]["per_question"]["fact-001"]["pg"]["explicit_zero"] is True
    assert a._STRICT_BIND is False
