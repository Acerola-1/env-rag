"""C1/C2 provenance must survive the actual 5.3 input shape and publication."""

import json

import test_rerank as base
import test_rerank_review_r1 as first

from env_rag_final import rerank as rr


def test_real_fusion_shape_uses_verified_active_snapshot_for_enrichment(monkeypatch, tmp_path):
    _, fused, body, path = first._setup(monkeypatch, tmp_path)
    # Actual 5.3 reports keep the catalog snapshot under `pg`; they do not
    # have this top-level field used by the earlier fixture.
    fused.pop("catalog_snapshot_id", None)
    fused["pg"] = {"catalog_snapshot_id": "s"}
    path.write_text(json.dumps(body))
    catalog_reads = []

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
                catalog_reads.append(args)
                return [
                    {
                        "unit_id": "actual-table-unit",
                        "doc_id": base.DOC_A,
                        "chunk_id": base.C1,
                        "unit_kind": "table",
                    }
                ]
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
    assert catalog_reads, "the real input shape must not silently skip catalog enrichment"
    assert all(args[1] == "s" for args in catalog_reads), "use the verified active snapshot"
    assert any(p.get("table_id") == "actual-table-unit" for p in result["ordered"][0]["paths"])


def test_canonical_repair_evidence_is_published_not_only_kept_in_local_dict(monkeypatch, tmp_path):
    _, fused, body, path = first._setup(monkeypatch, tmp_path)
    fused["usable"][0]["content_sha256"] = "incorrect-original-hash"
    fused["usable"][0]["doc_id"] = None
    path.write_text(json.dumps(body))

    async def transport(query, documents):
        return base._resp(base._ok_payload(1))

    first._invoke(tmp_path, path, transport)
    terminal = json.loads((tmp_path / "rerank-runtime-latest.json").read_text())

    def records(value):
        if isinstance(value, dict):
            yield value
            for v in value.values():
                yield from records(v)
        elif isinstance(value, list):
            for v in value:
                yield from records(v)

    repairs = [
        r
        for r in records(terminal)
        if r.get("replayed_content_sha256") == "incorrect-original-hash"
    ]
    assert repairs, "repair originals and basis must exist in the persisted terminal"
    assert any(r.get("canonicalization_basis") and "replayed_doc_id" in r for r in repairs)
