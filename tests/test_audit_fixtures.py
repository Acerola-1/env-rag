"""Offline fixture tests for the Phase-0 audit tools (handoff item 6).

Pure in-memory / tmp-path fixtures: no database, no real corpus, no network.
They verify the behaviors demanded by Gate 0 review:
- G0-1  fingerprint changes when content / chunking / refs / tables change
- G0-2  reports derive from collected records (dynamic conclusions) and a
        failed run records its stage without mixing successful outputs
- G0-3  unresolved targets are displaced and fails meets_minimum
"""

from __future__ import annotations

import json
from pathlib import Path

from env_rag_final.audit import snapshot

# --------------------------------------------------------------------------
# fixtures: minimal fake rows shaped like asyncpg Records
# --------------------------------------------------------------------------


class Row(dict):
    """dict with __getitem__ so snapshot helpers can read it like a Record."""

    def __getitem__(self, key):  # noqa: D105
        return super().__getitem__(key)


def make_doc(doc_id="doc-a", content="正文甲", chunk_options={"chunk_token_size": 1500}):
    return Row(
        id=doc_id,
        doc_name=f"{doc_id}.pdf",
        content=content,
        content_hash="h-" + doc_id,
        meta=None,
        sidecar_location=None,
        parse_format="lightrag",
        parse_engine="mineru",
        chunk_options=chunk_options,
    )


def make_chunk(
    doc_id="doc-a", idx=0, content="chunk 文本", sidecar='{"refs": [{"id": "b1", "type": "block"}]}'
):
    return Row(
        id=f"{doc_id}-chunk-{idx:03d}",
        full_doc_id=doc_id,
        chunk_order_index=idx,
        tokens=10,
        content=content,
        heading=None,
        sidecar=sidecar,
    )


def make_status(doc_id="doc-a", status="processed", chunks_count=1, error_msg=None):
    return Row(
        id=doc_id,
        file_path=f"{doc_id}.pdf",
        status=status,
        chunks_count=chunks_count,
        error_msg=error_msg,
    )


# --------------------------------------------------------------------------
# G0-1: fingerprint sensitivity
# --------------------------------------------------------------------------


def test_docs_fingerprint_changes_on_content_edit():
    base = snapshot.fingerprint_docs([make_doc()])
    edited = snapshot.fingerprint_docs([make_doc(content="正文乙")])
    assert base != edited


def test_docs_fingerprint_changes_on_chunk_param_change():
    base = snapshot.chunking_params([make_doc()])
    changed = snapshot.chunking_params([make_doc(chunk_options={"chunk_token_size": 2000})])
    assert base != changed


def test_chunks_fingerprint_changes_on_reorder():
    # fingerprint sorts by (doc, order): the ORDER VALUES are part of the payload,
    # so renumbering (0↔1) changes it; input list order alone must NOT matter.
    a = snapshot.fingerprint_chunks([make_chunk(idx=0), make_chunk(idx=1)])
    reordered_input = snapshot.fingerprint_chunks([make_chunk(idx=1), make_chunk(idx=0)][::-1])
    assert a == reordered_input  # input order irrelevant; sort_keys makes it canonical
    renumbered = snapshot.fingerprint_chunks([make_chunk(idx=1), make_chunk(idx=2)])
    assert a != renumbered  # renumbering (real re-chunk) changes it
    ambiguous = snapshot.fingerprint_chunks([make_chunk(idx=0), make_chunk(idx=0)])
    assert a != ambiguous  # duplicate order (ambiguity) changes it


def test_chunks_fingerprint_changes_on_content_edit():
    base = snapshot.fingerprint_chunks([make_chunk()])
    edited = snapshot.fingerprint_chunks([make_chunk(content="改动后的正文")])
    assert base != edited


def test_chunks_fingerprint_changes_on_ref_change():
    base = snapshot.fingerprint_chunks(
        [make_chunk(sidecar='{"refs": [{"id": "b1", "type": "block"}]}')]
    )
    changed = snapshot.fingerprint_chunks(
        [make_chunk(sidecar='{"refs": [{"id": "b2", "type": "block"}]}')]
    )
    assert base != changed


def test_composite_fingerprint_changes_on_any_component():
    def composite(
        chunks_hash="c1", docs_hash="d1", artifacts_hash="a1", status_hash="s1", params={"k": 1}
    ):
        return snapshot.source_snapshot_fingerprint(
            docs_hash, chunks_hash, status_hash, artifacts_hash, params
        )

    base = composite()
    assert base["value"] != composite(chunks_hash="c2")["value"]
    assert base["value"] != composite(docs_hash="d2")["value"]
    assert base["value"] != composite(artifacts_hash="a2")["value"]
    assert base["value"] != composite(status_hash="s2")["value"]
    assert base["value"] != composite(params={"k": 2})["value"]


def test_artifacts_fingerprint_changes_on_table_byte_change(tmp_path: Path):
    doc_dir = tmp_path / "x.pdf.parsed"
    doc_dir.mkdir()
    (doc_dir / "x.blocks.jsonl").write_text('{"type":"meta"}\n', encoding="utf-8")
    (doc_dir / "x.tables.json").write_text('{"tables": {}}', encoding="utf-8")
    base = snapshot.fingerprint_artifacts(tmp_path)
    (doc_dir / "x.tables.json").write_text(
        '{"tables": {"tb-1": {"caption": "表1"}}}', encoding="utf-8"
    )
    changed = snapshot.fingerprint_artifacts(tmp_path)
    assert base != changed


def test_artifacts_fingerprint_stable_on_unchanged_dir(tmp_path: Path):
    doc_dir = tmp_path / "x.pdf.parsed"
    doc_dir.mkdir()
    (doc_dir / "x.blocks.jsonl").write_text('{"type":"meta"}\n', encoding="utf-8")
    assert snapshot.fingerprint_artifacts(tmp_path) == snapshot.fingerprint_artifacts(tmp_path)


def test_audit_code_fingerprint_changes_with_source(tmp_path: Path):
    (tmp_path / "collect.py").write_text("x = 1\n", encoding="utf-8")
    a = snapshot.audit_code_fingerprint(tmp_path)
    (tmp_path / "collect.py").write_text("x = 2\n", encoding="utf-8")
    b = snapshot.audit_code_fingerprint(tmp_path)
    assert a != b


# --------------------------------------------------------------------------
# G0-2: duplicate-claim evidence keeps the verified scope
# --------------------------------------------------------------------------


def test_duplicate_pair_claim_is_scoped_to_normalized_text(tmp_path: Path):
    from env_rag_final.audit import collect

    def parsed_dir(name: str, body: str) -> Path:
        d = tmp_path / f"{name}.pdf.parsed"
        d.mkdir()
        # Two blocks whose merged text differs only by file-derived id prefix
        (d / f"{name}.pdf.blocks.jsonl").write_text(
            json.dumps({"type": "meta", "doc_id": "doc-x"})
            + "\n"
            + json.dumps({"type": "content", "blockid": "b1", "content": body})
            + "\n",
            encoding="utf-8",
        )
        return d

    d58 = parsed_dir(
        "water-58_ca-resolution", "见 <table id='tb-aaaa0000000000000000000000000000-0001'>"
    )
    d44 = parsed_dir(
        "water-44_ca-amend", "见 <table id='tb-bbbb0000000000000000000000000000-0001'>"
    )

    evidence = collect._duplicate_pair_evidence([d58, d44])
    assert evidence is not None
    assert evidence["raw_merged_text_equal"] is False
    assert evidence["normalized_merged_text_equal"] is True
    assert "规范化" in evidence["verified_claim"]
    assert "PDF 字节未比较" in evidence["verified_claim"]


def test_duplicate_pair_flags_investigation_when_normalized_differs(tmp_path: Path):
    from env_rag_final.audit import collect

    def parsed_dir(name: str, body: str) -> Path:
        d = tmp_path / f"{name}.pdf.parsed"
        d.mkdir()
        (d / f"{name}.pdf.blocks.jsonl").write_text(
            json.dumps({"type": "meta", "doc_id": "doc-x"})
            + "\n"
            + json.dumps({"type": "content", "blockid": "b1", "content": body})
            + "\n",
            encoding="utf-8",
        )
        return d

    d58 = parsed_dir("water-58_ca-resolution", "内容甲")
    d44 = parsed_dir("water-44_ca-amend", "内容乙")
    evidence = collect._duplicate_pair_evidence([d58, d44])
    assert evidence["normalized_merged_text_equal"] is False
    assert "重新调查" in evidence["verified_claim"]


# --------------------------------------------------------------------------
# G0-3: unresolved targets displaced, whitelist check requires chunks
# --------------------------------------------------------------------------


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def test_sample_set_displaces_targets_without_chunks(monkeypatch):
    from env_rag_final.audit import samples

    monkeypatch.setattr(samples.identity, "blocks_lines_for", lambda *a: ['{"type":"meta"}'])

    class FakeConn:
        """Minimal asyncpg stub: every doc resolves, but one has 0 chunks."""

        def __init__(self):
            self.zero_chunk_docs = set()

        async def fetchrow(self, sql, ws, doc_name):
            chunks = 0 if doc_name in self.zero_chunk_docs else 5
            return {
                "doc_id": "doc-" + doc_name[:10],
                "doc_name": doc_name,
                "workspace": ws,
                "chunks": chunks,
                "sidecar_location": None,
            }

        async def fetch(self, sql, *args):
            first = args[1] if len(args) > 1 else (args[0] if args else "")
            if "doc_status" in sql:
                return []
            if "中国移动源" in first:
                names = [
                    f"air-{i}_生态环境部_中国移动源环境管理年报_20{i}.pdf" for i in range(15, 20)
                ]
            elif "年中国水资源公报" in first:
                names = [f"water-{i}_水利部_20{i}年中国水资源公报_20{i}.pdf" for i in range(25, 30)]
            elif "修改单" in first:
                names = [f"air-{i}_xx修改单.pdf" for i in (7, 8)]
            elif "GB3095" in first:
                names = [
                    "air-02_环境空气质量标准_GB3095-2012.pdf",
                    "air-03_环境空气质量标准_GB3095-2026.pdf",
                ]
            elif "恶臭" in first:
                names = ["air-06_生态环境部_恶臭污染物排放标准_GB14554-93.pdf"]
            elif "HJ" in first:
                names = ["air-27_HJ1328-2023.pdf"]
            else:
                names = []
            return [
                {
                    "doc_id": "doc-" + n[:10],
                    "doc_name": n,
                    "workspace": "default",
                    "chunks": 0 if n in self.zero_chunk_docs else 5,
                }
                for n in names
            ]

        async def fetchval(self, sql, *a):
            return 100

    conn = FakeConn()
    # Give air-06 (GB14554) zero chunks → all its questions must be displaced.
    conn.zero_chunk_docs.add("air-06_生态环境部_恶臭污染物排放标准_GB14554-93.pdf")

    result = _run(samples.build_sample_set(conn))
    assert result["coverage_check"]["displaced_unresolved_targets"], (
        "0-chunk targets must be displaced"
    )
    assert result["coverage_check"]["meets_minimum"] is False
    kept = [q for v in result["questions"].values() for q in v]
    assert all(t["chunks_in_db"] > 0 for q in kept for t in q["target_docs"]), (
        "no kept question may reference a 0-chunk target"
    )
    # every target carries a real doc_id, never an ellipsis placeholder
    assert all("…" not in t["doc_name"] for q in kept for t in q["target_docs"])
    # gold stays unreviewed
    assert all(q["gold_review_status"] == "unreviewed" for q in kept)


def test_sample_set_displaces_missing_parsed_artifacts(monkeypatch):
    from env_rag_final.audit import samples

    monkeypatch.setattr(samples.identity, "blocks_lines_for", lambda *a: None)

    class FakeConn:
        async def fetchrow(self, sql, ws, doc_name):
            return {
                "doc_id": "doc-fixture",
                "doc_name": doc_name,
                "workspace": ws,
                "chunks": 5,
                "sidecar_location": None,
            }

        async def fetch(self, sql, *args):
            if "doc_status" in sql:
                return []
            return [
                {
                    "doc_id": "doc-fixture",
                    "doc_name": "fixture.pdf",
                    "workspace": "default",
                    "chunks": 5,
                }
            ]

        async def fetchval(self, *args):
            return 1

    result = _run(samples.build_sample_set(FakeConn()))
    assert result["coverage_check"]["meets_minimum"] is False
    assert all(not questions for questions in result["questions"].values())


def test_publish_fresh_directory_and_retains_old_generation(tmp_path):
    from env_rag_final.audit.pg import _commit

    output = tmp_path / "output"
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "audit.md").write_text("first")
    _commit(stage, output)
    first = output.resolve()
    assert output.is_symlink()
    assert (output / "audit.md").read_text() == "first"
    stage.mkdir()
    (stage / "audit.md").write_text("second")
    _commit(stage, output)
    assert (output / "audit.md").read_text() == "second"
    assert (first / "audit.md").read_text() == "first"


def test_publish_failure_restores_existing_directory(monkeypatch, tmp_path):
    import os

    import pytest

    from env_rag_final.audit.pg import _commit

    output = tmp_path / "output"
    output.mkdir()
    (output / "audit.md").write_text("old")
    (output / "run-manifest.json").write_text("old-manifest")
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "audit.md").write_text("new")
    (stage / "run-manifest.json").write_text("new-manifest")
    replace = os.replace

    def fail_pointer(source, destination):
        if ".pointer-" in Path(source).name:
            raise OSError("fixture publish failure")
        return replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_pointer)
    with pytest.raises(OSError):
        _commit(stage, output)
    assert (output / "audit.md").read_text() == "old"
    assert (output / "run-manifest.json").read_text() == "old-manifest"
    assert (stage / "audit.md").read_text() == "new"


def test_audit_failure_keeps_stage_and_diagnostic(monkeypatch, tmp_path):
    import pytest

    from env_rag_final.audit import collect, pg

    observed = {}

    class Transaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class Connection:
        def transaction(self, **kwargs):
            observed.update(kwargs)
            return Transaction()

        async def execute(self, sql):
            pass

        async def close(self):
            pass

    async def connect(**kwargs):
        return Connection()

    async def failed_collect(conn, staging):
        (staging / "run-manifest.json").write_text(
            json.dumps(
                {
                    "run_id": "fixture",
                    "status": "failed_at:inventory.jsonl",
                }
            )
        )
        raise ValueError("secret must not appear")

    monkeypatch.setattr(pg.asyncpg, "connect", connect)
    monkeypatch.setattr(collect, "collect_everything", failed_collect)
    output = tmp_path / "output"
    with pytest.raises(pg.AuditError) as error:
        _run(pg._audit({}, output))
    assert "inventory.jsonl" in str(error.value)
    assert "secret" not in str(error.value)
    assert observed == {"readonly": True, "isolation": "repeatable_read"}
    manifests = list((tmp_path / ".output.failures").glob("*/run-manifest.json"))
    assert len(manifests) == 1
    assert json.loads(manifests[0].read_text())["status"] == "failed_at:inventory.jsonl"
    assert not output.exists()


def test_changed_local_artifacts_fail_before_success_manifest(monkeypatch, tmp_path):
    import pytest

    from env_rag_final.audit import collect

    class Connection:
        async def fetch(self, *args):
            return []

    async def empty(*args):
        return {}

    async def inventory(*args):
        return [], {"stats": {}, "hash_verify": {}}

    async def mapping(*args):
        return []

    async def samples(*args):
        return {"questions": {}}

    hashes = iter(["before", "after"])
    monkeypatch.setattr(collect.snapshot, "fingerprint_artifacts", lambda *a: next(hashes))
    monkeypatch.setattr(collect, "_schema_json", empty)
    monkeypatch.setattr(collect, "_inventory", inventory)
    monkeypatch.setattr(collect, "_mapping_samples", mapping)
    monkeypatch.setattr(collect, "build_search_probes", empty)
    monkeypatch.setattr(collect, "build_sample_set", samples)
    monkeypatch.setattr(collect, "build_compatibility_md", lambda *a: "# fixture")
    with pytest.raises(RuntimeError):
        _run(collect.collect_everything(Connection(), tmp_path))
    manifest = json.loads((tmp_path / "run-manifest.json").read_text())
    assert manifest["status"] == "failed_at:artifact_snapshot_end"
    assert not (tmp_path / "audit.md").exists()


# --------------------------------------------------------------------------
# G0-2: failed runs record the stage; manifest covers every deliverable
# --------------------------------------------------------------------------


def test_manifest_marks_failed_stage_and_run_id():
    from env_rag_final.audit.collect import _manifest

    steps = [
        {"step": "schema.json", "status": "ok"},
        {"step": "inventory.jsonl", "status": "error", "error_type": "ValueError"},
    ]
    m = _manifest("deadbeef00112233", {"algorithm": "x", "value": "y", "components": {}}, steps, {})
    assert m["run_id"] == "deadbeef00112233"
    assert m["status"] == "failed_at:inventory.jsonl"
    assert set(m["deliverables_expected"]) >= {
        "audit.md",
        "run-manifest.json",
        "compatibility.md",
    }


def test_manifest_success_lists_all_steps():
    from env_rag_final.audit.collect import _manifest

    steps = [
        {"step": s, "status": "ok"}
        for s in (
            "collect_rows",
            "schema.json",
            "inventory.jsonl",
            "mapping-samples.jsonl",
            "search-probes.json",
            "sample-set.json",
            "compatibility.md",
            "audit.md",
        )
    ]
    m = _manifest("a" * 16, {"algorithm": "x", "value": "y", "components": {}}, steps, {})
    assert m["status"] == "ok"
    assert {s["step"] for s in m["steps"]} >= set(m["deliverables_expected"]) - {
        "run-manifest.json"
    }
