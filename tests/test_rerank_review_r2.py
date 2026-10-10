"""Remaining R1/R2/R4 owning-entry cases, with explicit fake source rows."""

import hashlib
import json

import pytest
import test_rerank as base
import test_rerank_review_r1 as first

from env_rag_final import rerank as rr


@pytest.mark.parametrize("field", ["content_sha256", "doc_id"])
def test_source_verified_metadata_is_canonical(monkeypatch, tmp_path, field):
    _, fused, body, path = first._setup(monkeypatch, tmp_path)
    fused["usable"][0][field] = "incorrect-hash" if field == "content_sha256" else None
    path.write_text(json.dumps(body))

    async def transport(query, documents):
        return base._resp(base._ok_payload(1))

    try:
        report = first._invoke(tmp_path, path, transport)
    except Exception:
        return  # explicit refusal is allowed instead of canonical source repair
    result = report["results"][0]
    if result["status"] != "ok":
        return
    ordered = result["ordered"][0]
    assert ordered["doc_id"] == base.DOC_A
    assert ordered["content_sha256"] == hashlib.sha256(b"full body").hexdigest()


def test_replay_question_mismatch_rejected_before_service(monkeypatch, tmp_path):
    _, fused, body, path = first._setup(monkeypatch, tmp_path)
    fused["query"] = "different question with different source constraints"
    path.write_text(json.dumps(body))
    calls = []

    async def transport(query, documents):
        calls.append(query)
        return base._resp(base._ok_payload(1))

    try:
        first._invoke(tmp_path, path, transport)
    except Exception:
        pass
    assert calls == []


def test_block_link_not_fabricated_as_table_fragment(monkeypatch, tmp_path):
    _, _, _, path = first._setup(monkeypatch, tmp_path)

    class Conn:
        async def fetch(self, sql, *args):
            if "lightrag_doc_chunks" in sql:
                return [
                    {
                        "id": base.C1,
                        "workspace": "default",
                        "full_doc_id": base.DOC_A,
                        "content": "full body",
                        "file_path": "a.pdf",
                    }
                ]
            if "unit_chunk_links" in sql:
                rows = [
                    {
                        "unit_id": "block-original",
                        "doc_id": base.DOC_A,
                        "chunk_id": base.C1,
                        "unit_kind": "block",
                    },
                    {
                        "unit_id": "table-original",
                        "doc_id": base.DOC_A,
                        "chunk_id": base.C1,
                        "unit_kind": "table",
                    },
                ]
                if "unit_kind" in sql and "'table'" in sql:
                    return [r for r in rows if r["unit_kind"] == "table"]
                return rows
            return []

        async def close(self):
            pass

    async def connect(**kwargs):
        return Conn()

    async def call(values, query, documents, transport=None):
        return {"status": "success", "status_code": 200, "payload": base._ok_payload(1)}

    monkeypatch.setattr(rr.asyncpg, "connect", connect)
    monkeypatch.setattr(rr, "_call_rerank", call)
    result = first._invoke(tmp_path, path, None)["results"][0]
    table_ids = {
        p.get("table_id")
        for p in result["ordered"][0]["paths"]
        if (p.get("citation") or {}).get("kind") == "table_unit"
    }
    assert "block-original" not in table_ids
    assert "table-original" in table_ids


def test_secret_is_redacted_before_error_body_truncation(monkeypatch, tmp_path):
    values, _, _, path = first._setup(monkeypatch, tmp_path)
    key = "fixture-sensitive-prefix-" + "abcdef123456" * 5
    values["RERANK_BINDING_API_KEY"] = key

    async def transport(query, documents):
        return base._resp({}, status_code=401, text="x" * 290 + key)

    first._invoke(tmp_path, path, transport)
    terminal = (tmp_path / "rerank-runtime-latest.json").read_text()
    assert key[:10] not in terminal, "truncation must not expose an unredacted secret prefix"


def test_preflight_terminal_sanitizes_configured_secrets(monkeypatch, tmp_path):
    values, _, _, path = first._setup(monkeypatch, tmp_path)
    key = "fixture-sensitive-config-key"
    values["RERANK_BINDING_API_KEY"] = key

    def guard(values, workspace):
        raise rr.AdapterError("upstream config error includes " + key)

    monkeypatch.setattr(rr, "verify_config_guard", guard)

    async def transport(query, documents):
        raise AssertionError("preflight must reject before service")

    with pytest.raises(rr.AdapterError):
        first._invoke(tmp_path, path, transport)
    terminal = (tmp_path / "rerank-runtime-latest.json").read_text()
    assert key not in terminal, "all terminal stages, not just HTTP receipts, require sanitizing"
