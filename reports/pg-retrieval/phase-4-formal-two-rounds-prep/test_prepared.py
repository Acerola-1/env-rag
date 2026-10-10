"""Bounded offline verification of the preparation wrapper, not production tests."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
common = importlib.import_module("prepared_common")


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_unauthorized_round_never_reaches_config_or_backend(monkeypatch):
    mod = load("run_round")
    monkeypatch.setattr(mod, "validate_bundle", lambda: pytest.fail("not authorized"))
    with pytest.raises(SystemExit):
        mod.main(["--round", "1"])


def test_unauthorized_mapping_never_connects(monkeypatch):
    mod = load("collect_mapping")
    monkeypatch.setattr(mod, "validate_bundle", lambda: pytest.fail("not authorized"))
    with pytest.raises(SystemExit):
        mod.main([])


def test_two_independent_caps_sum_to_global_caps():
    whole = json.loads((HERE / "two-round-budget.json").read_text())
    for service, maximum in whole["total_caps"].items():
        first = json.loads((HERE / "round-1-budget.json").read_text())["total_caps"][service]
        second = json.loads((HERE / "round-2-budget.json").read_text())["total_caps"][service]
        assert first + second == maximum
    assert common.round_path(1) != common.round_path(2)
    with pytest.raises(ValueError):
        common.round_path(3)


def rows_and_targets():
    targets = [{"workspace": "default", "doc_id": "d", "unit_id": "u"}]
    rows = [
        {
            "workspace": "default",
            "doc_id": "d",
            "unit_id": "u",
            "snapshot_id": "s",
            "unit_kind": "block",
            "content_length": 4,
            "requires_span": False,
            "chunk_ids": '["c"]',
            "scopes": "[]",
        }
    ]
    return rows, targets


def test_mapping_content_positive_and_wrong_length_refused():
    mod = load("collect_mapping")
    rows, targets = rows_and_targets()
    assert mod.build_entries(rows, targets, "default", "s", lambda _: "正文原文")[0][
        "chunk_ids"
    ] == ["c"]
    with pytest.raises(RuntimeError):
        mod.build_entries(rows, targets, "default", "s", lambda _: "错")


def test_partial_and_duplicate_mapping_refused():
    mod = load("collect_mapping")
    rows, targets = rows_and_targets()
    with pytest.raises(RuntimeError):
        mod.build_entries([], targets, "default", "s", lambda _: "正文原文")
    with pytest.raises(RuntimeError):
        mod.build_entries(rows * 2, targets, "default", "s", lambda _: "正文原文")


def test_readonly_mapping_query_contract():
    mod = load("collect_mapping")
    assert "env_rag.unit_chunk_links" in mod.SQL
    assert "env_rag.source_units" in mod.SQL
    assert "public.lightrag_doc_full" in mod.SQL
    assert "jsonb_to_recordset($3::jsonb)" in mod.SQL
    assert not any(
        word in mod.SQL.upper().split() for word in ("INSERT", "UPDATE", "DELETE", "CREATE", "DROP")
    )


def test_source_manifest_tamper_refused(tmp_path):
    source = tmp_path / "artifact.json"
    source.write_text("{}")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"files": {str(source): common.digest(source)}}))
    common.verify_artifact_manifest(manifest)
    with pytest.raises(RuntimeError):
        common.verify_artifact_manifest(manifest, [tmp_path / "unregistered.json"])
    source.write_text('{"changed": true}')
    with pytest.raises(RuntimeError):
        common.verify_artifact_manifest(manifest)


def test_mapping_connection_failure_still_post_captures(monkeypatch, tmp_path):
    mod = load("collect_mapping")
    values = {
        "POSTGRES_HOST": "fixture",
        "POSTGRES_PORT": "1",
        "POSTGRES_USER": "fixture",
        "POSTGRES_PASSWORD": "fixture",
        "POSTGRES_DATABASE": "fixture",
    }
    anchor = {"frozen_identity": {"catalog_run_snapshot": "run/s"}}
    monkeypatch.setattr(mod, "validate_bundle", lambda: (anchor, values, {}))
    calls = []

    async def capture(_):
        calls.append("guard")
        return {"matches_frozen": True, "identity": {"public_counts": {}, "env_sha": "fixture"}}

    async def connect(**_):
        calls.append("connect-failure")
        raise ConnectionRefusedError("fixture")

    monkeypatch.setattr(mod.ev, "_capture_identity", capture)
    monkeypatch.setattr(mod.asyncpg, "connect", connect)
    destination = tmp_path / "mapping"
    with pytest.raises(RuntimeError):
        asyncio.run(mod.collect(destination))
    assert calls == ["guard", "connect-failure", "guard"]
    assert not (destination / "mapping.json").exists()
    assert (
        json.loads((destination / "capture-failure.json").read_text())["identity_after"] is not None
    )


def test_actual_failure_shape_stops_second_round():
    root = HERE.parents[2]
    terminal = json.loads(
        (root / "reports/pg-retrieval/phase-4-round-1/eval-runtime-latest.json").read_text()
    )
    caps = json.loads((HERE / "round-1-budget.json").read_text())["total_caps"]
    common.check_terminal(terminal, caps)
    terminal["results"][0]["failure"] = {"stage": "fixture", "error": "fixture"}
    with pytest.raises(RuntimeError):
        common.check_terminal(terminal, caps)
