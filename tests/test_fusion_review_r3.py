"""F3-a: structural and configuration failures use the promised terminal."""

import asyncio
import json

import pytest
import test_fusion as base
import test_fusion_review_r1 as accepted

from env_rag_final import fusion as fu


@pytest.mark.parametrize("bad_input", ["missing_questions", "null_questions", "invalid_dim"])
def test_preflight_failure_types_all_write_zero_call_terminal(monkeypatch, tmp_path, bad_input):
    accepted._install_local(monkeypatch, tmp_path, base._pg_result())
    if bad_input == "missing_questions":
        fu.GOLD_PATH.write_text(json.dumps({"counter_examples": []}))
        expected_error = KeyError
    elif bad_input == "null_questions":
        fu.GOLD_PATH.write_text(json.dumps({"questions": None}))
        expected_error = TypeError
    else:
        values = {**base.VALUES, "EMBEDDING_DIM": "not-an-integer"}
        monkeypatch.setattr(fu, "dotenv_values", lambda path: values)
        expected_error = ValueError

    captures = []

    async def capture(values):
        captures.append(True)
        return base._identity()

    monkeypatch.setattr(fu, "_capture_identity", capture)
    with pytest.raises(Exception) as error:
        asyncio.run(fu.run_fusion(tmp_path, ["q-merge"]))
    assert isinstance(error.value, expected_error) or isinstance(
        error.value.__cause__, expected_error
    )
    assert captures == []
    terminal_path = tmp_path / "fusion-runtime-latest.json"
    assert terminal_path.exists(), f"{expected_error.__name__} must write a preflight terminal"
    terminal = json.loads(terminal_path.read_text())
    assert "finished_at" not in terminal
    assert terminal["failure_service_records"]["call_records"] == []
    assert expected_error.__name__ in json.dumps(terminal["failure"]), (
        "original error type remains auditable"
    )
