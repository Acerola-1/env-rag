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


def column_errors(sql):
    """Offline comparison to recorded public schema + accepted catalog DDL.

    This checks the qualified column references in THIS bounded SQL; it is not
    a PostgreSQL parser or a claim about the currently live database.
    """
    import re

    from env_rag_final.catalog.schema import _migration_ddl

    root = HERE.parents[2]
    recorded = json.loads((root / "reports/pg-retrieval/phase-0/schema.json").read_text())
    columns = {
        "d": {c["column_name"] for c in recorded["tables"]["lightrag_doc_full"]["columns"]},
        "r": {"doc_id", "unit_id"},
    }
    aliases = {"source_units": "u", "unit_chunk_links": "l", "scope_units": "su", "scopes": "s"}
    for _, ddl in _migration_ddl("env_rag"):
        for table, alias in aliases.items():
            match = re.search(
                r"CREATE TABLE IF NOT EXISTS env_rag\." + table + r"\s*\((.*?)\n\s*\)", ddl, re.S
            )
            if match:
                columns[alias] = set(
                    re.findall(r"^\s*(\w+)\s+(?:TEXT|INTEGER|BOOLEAN|JSONB)\b", match[1], re.M)
                )
    assert set(columns) == {"d", "r", "u", "l", "su", "s"}
    return [
        (alias, col)
        for alias, col in re.findall(r"\b(d|r|u|l|su|s)\.(\w+)\b", sql)
        if col not in columns[alias]
    ]


def test_all_qualified_columns_match_recorded_schema_and_catalog_ddl():
    mod = load("collect_mapping")
    assert column_errors(mod.SQL) == []
    assert "d.doc_name" in mod.SQL
    assert ("d", "file_path") in column_errors(mod.SQL.replace("d.doc_name", "d.file_path"))


@pytest.mark.parametrize(
    "valid,bad",
    [
        ("u.content_length", "u.missing_length"),
        ("l.chunk_order", "l.chunk_order_index"),
        ("s.confirm_status", "s.requires_span"),
    ],
)
def test_other_table_column_mismatches_are_also_detected(valid, bad):
    mod = load("collect_mapping")
    assert column_errors(mod.SQL.replace(valid, bad))


def test_doc_name_resolves_all_27_frozen_units_from_existing_artifacts():
    """Real local artifact reads only; no DB links or live lengths are invented."""
    mod = load("collect_mapping")
    root = HERE.parents[2]
    inventory = [
        json.loads(line)
        for line in (root / "reports/pg-retrieval/phase-0/inventory.jsonl").read_text().splitlines()
    ]
    names = {x["doc_id"]: x["doc_name"] for x in inventory if x.get("kind") == "db_doc"}
    targets = json.loads((HERE / "mapping-targets.json").read_text())["targets"]
    assert len(targets) == 27
    reader = mod.read_text_cached()
    for target in targets:
        kind = "table" if target["unit_id"].startswith("tb-") else "block"
        row = dict(target, unit_kind=kind, doc_name=names[target["doc_id"]])
        text = reader(row)
        assert isinstance(text, str) and text
        assert reader(row) == text
        with pytest.raises(KeyError):
            reader({k: v for k, v in row.items() if k != "doc_name"})
