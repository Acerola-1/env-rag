"""Counterexamples from the independent review; offline contract tests only."""

from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_workspace_access import make_service

from env_rag_final.access.auth import NotAvailable, authorize
from env_rag_final.access.deployment import PINNED_IMAGE, instance_plan
from env_rag_final.access.gateway import KnowledgeService
from env_rag_final.access.snapshot import SNAPSHOT_FORMAT, compare


def fixture_service(tmp_path):
    service = make_service(tmp_path, None, backends=[])
    ctx = authorize(service.registry, service.registry.principal("air-reader"), "air")
    snap = asyncio.run(service.workspace_snapshots(ctx))
    retrieval = {
        "question": "问题",
        "status": "retrieved",
        "workspaces": ["air"],
        "workspace_snapshots": snap,
        "evidence": [{"workspace": "air", "chunk_id": "c", "content": "依据", "verified": True}],
    }
    return service, ctx, retrieval


def test_nonchunk_evidence_never_collapses():
    evidence = [
        {"workspace": "water", "kind": "document", "doc_id": d, "content": d} for d in ("d1", "d2")
    ]
    evidence += [
        {"workspace": "water", "kind": "table_row", "doc_id": "d1", "content": str(row)}
        for row in range(3)
    ]
    assert len(KnowledgeService.merge_evidence([{"items": evidence}])) == 5


def test_collects_plural_and_nested_scope_chunk_bindings():
    assert KnowledgeService.chunk_ids(
        {"chunk_ids": ["table1", "table2"], "trace": [{"citation": {"chunk_id": "clause"}}]}
    ) == {"table1", "table2", "clause"}


def test_source_change_and_legacy_records_refuse_before_model(tmp_path):
    svc, ctx, retrieval = fixture_service(tmp_path)
    retrieval["workspace_snapshots"]["air"]["source_fingerprint"] = "withdrawn"
    with pytest.raises(NotAvailable):
        asyncio.run(svc.generate(ctx, retrieval))
    retrieval.pop("workspace_snapshots")
    with pytest.raises(NotAvailable):
        asyncio.run(svc.generate(ctx, retrieval))
    assert "llm:answer" not in svc.backend_calls


@pytest.mark.parametrize("status", ["stale", "partial", "ambiguous", "missing", "service_failure"])
def test_incomplete_coverage_never_promoted_by_model(tmp_path, status):
    svc, ctx, retrieval = fixture_service(tmp_path)
    retrieval["status"] = status
    result = asyncio.run(svc.generate(ctx, retrieval))
    assert result["dispatches"] == 0
    assert result["coverage_status"] == status


def test_full_enumeration_exceeds_context_without_truncation_or_call(tmp_path):
    svc, ctx, retrieval = fixture_service(tmp_path)
    svc.values["MAX_TOTAL_TOKENS"] = "2000"
    retrieval["status"] = "complete"
    retrieval["evidence"][0]["content"] = "完整内容" * 2000
    result = asyncio.run(svc.generate(ctx, retrieval))
    assert result["status"] == "context_limit"
    assert result["dispatches"] == 0
    assert "llm:answer" not in svc.backend_calls


def test_whole_body_and_invalid_citation_and_after_call_guard(tmp_path):
    svc, ctx, retrieval = fixture_service(tmp_path)
    content = "全文" * 2500 + "尾部必须保留"
    retrieval["evidence"][0]["content"] = content
    sent = []

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            sent.append(kwargs["json"]["messages"][0]["content"])

            class Response:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {
                        "model": "fixture",
                        "choices": [{"message": {"content": "结论[0][999]"}}],
                    }

            return Response()

    svc._client_factory = Client
    result = asyncio.run(svc.generate(ctx, retrieval))
    assert content in sent[0]
    assert result["status"] == "unverified" and result["invalid_citations"] == [999]
    assert result["citations"][0]["semantic_support"] == "unreviewed"

    async def withdrawn(ctx):
        return {"air": {"state": "stale"}}

    original = svc.validate_retrieval

    async def validate_then_change(ctx, value):
        await original(ctx, value)
        svc.workspace_snapshots = withdrawn

    svc.validate_retrieval = validate_then_change
    with pytest.raises(NotAvailable):
        asyncio.run(svc.generate(ctx, retrieval))


def test_arbitrary_registered_name_and_mapping_need_no_port_code(tmp_path):
    svc, _, _ = fixture_service(tmp_path)
    reg = svc.registry
    reg.workspaces["estuary"] = replace(
        reg.workspaces["air"],
        id="estuary",
        pg_workspace="estuary_pg",
        vector_workspace="estuary_vec",
        graph_workspace="estuary_graph",
        instance_url="http://127.0.0.1:9637",
    )
    plan = instance_plan(reg, "estuary")
    assert plan["port"] == 9637 and plan["pg_workspace"] == "estuary_pg"
    assert plan["image"] == PINNED_IMAGE
    with pytest.raises(ValueError):
        instance_plan(reg, "estuary", image="repo:latest")


def protected_snapshot():
    return {
        "format": SNAPSHOT_FORMAT,
        "files": {},
        "pg": {
            "complete_content_scan": True,
            "tables": {"t": {"counts": {"default": 1}, "content_digest": {"default": "original"}}},
            "env_rag": {},
        },
        "qdrant": {
            "collections": {
                "vectors": {
                    "complete_content_scan": True,
                    "by_workspace": {"_": {"count": 1, "content_digest": "vector"}},
                }
            }
        },
        "neo4j": {
            "labels": {
                "base": {
                    "complete_content_scan": True,
                    "node_content_digest": "node",
                    "relationship_content_digest": "edge",
                }
            }
        },
    }


@pytest.mark.parametrize("family", ["pg", "qdrant", "neo4j"])
def test_same_counts_and_ids_cannot_hide_protected_content_change(family):
    before = protected_snapshot()
    after = copy.deepcopy(before)
    if family == "pg":
        after[family]["tables"]["t"]["content_digest"]["default"] = "modified"
    elif family == "qdrant":
        after[family]["collections"]["vectors"]["by_workspace"]["_"]["content_digest"] = "modified"
    else:
        after[family]["labels"]["base"]["relationship_content_digest"] = "modified"
    assert not compare(before, after, protected_workspaces=["default"])["ok"]


def test_legacy_snapshot_cannot_claim_full_proof():
    snap = protected_snapshot()
    snap["format"] = "workspace-access/protected-snapshot-r1"
    assert not compare(snap, copy.deepcopy(snap), protected_workspaces=["default"])["ok"]


def test_pdf_requires_authorized_document_and_frozen_hash(tmp_path, monkeypatch):
    svc, ctx, _ = fixture_service(tmp_path)
    body = b"%PDF-real-bytes"
    import hashlib

    root = tmp_path / "datasets"
    root.mkdir()
    svc.parsed_root.mkdir()
    (svc.parsed_root / "original.pdf").write_bytes(body)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": "corpus/parsed/original.pdf",
                        "sha256": hashlib.sha256(body).hexdigest(),
                    }
                ]
            }
        )
    )
    monkeypatch.setattr("env_rag_final.paths.DATASET_ROOT", root)

    async def doc(ctx, ws, doc_id):
        assert ws == "air" and doc_id == "authorized"
        return {"doc_name": "original.pdf", "content": "whole document"}

    svc.document_row = doc
    item = {"workspace": "air", "doc_id": "authorized", "path": "../../ignored"}
    assert asyncio.run(svc.document_source(ctx, item, "pdf")) == body
    assert asyncio.run(svc.document_source(ctx, item, "document-text")) == b"whole document"
    (svc.parsed_root / "original.pdf").write_bytes(b"modified")
    with pytest.raises(NotAvailable):
        asyncio.run(svc.document_source(ctx, item, "pdf"))
    item["workspace"] = "water"
    # The document row is never accepted as authority over workspace scope.
    with pytest.raises(NotAvailable):
        asyncio.run(svc.document_source(ctx, item, "pdf"))


def test_wrong_instance_workspace_is_refused_before_query(tmp_path):
    svc, ctx, _ = fixture_service(tmp_path)
    svc.instance_urls = {"air": "http://127.0.0.1:9623"}  # fixture reports water's actual identity
    with pytest.raises(NotAvailable, match="identity mismatch"):
        asyncio.run(svc.instance_evidence(ctx, "air", "x", mode="naive", top_k=1))
    assert not svc.backend_calls


def test_enumeration_hydrates_only_confirmed_scope_not_discovery(tmp_path, monkeypatch):
    svc, ctx, _ = fixture_service(tmp_path)

    async def answer(*args, **kwargs):
        return {
            "coverage_status": "complete",
            "discovery": {"chunk_id": "unconfirmed"},
            "answer": {
                "items": [
                    {
                        "kind": "table_row",
                        "doc_id": "doc",
                        "cells": ["all rows"],
                        "citation_verified": True,
                        "citation_reverified": True,
                        "citation": {"chunk_ids": ["confirmed"]},
                    }
                ]
            },
        }

    captured = []

    async def hydrate(ctx, ws, ids):
        captured.extend(ids)
        return []

    monkeypatch.setattr("env_rag_final.ask.ask_question", answer)
    svc.hydrate_chunks = hydrate
    result = asyncio.run(svc.pg_evidence(ctx, "air", "列出表1全部行", top_k=1, expand=True))
    assert captured == ["confirmed"] and len(result["items"]) == 1
    assert result["status"] == "complete"


def test_multiworkspace_context_cannot_be_consumed_by_first_library(tmp_path):
    svc, _, retrieval = fixture_service(tmp_path)
    ctx = authorize(svc.registry, svc.registry.principal("dual-reader"), "all")
    retrieval["workspaces"] = ["air", "water"]
    retrieval["workspace_snapshots"] = asyncio.run(svc.workspace_snapshots(ctx))
    svc.values["MAX_TOTAL_TOKENS"] = "3000"
    retrieval["evidence"] = [
        {
            "workspace": ws,
            "chunk_id": f"{ws}-{n}",
            "content": "甲乙丙丁戊己庚辛" * 12,
            "verified": True,
        }
        for ws in ["air", "water"]
        for n in range(20)
    ]

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            class Response:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {"choices": [{"message": {"content": "甲[0]乙[20]"}}]}

            return Response()

    svc._client_factory = Client
    result = asyncio.run(svc.generate(ctx, retrieval))
    assert result["included_workspaces"] == ["air", "water"]
    assert result["status"] == "success" and result["coverage_status"] == "partial"


def test_mismatched_ingestion_target_is_refused_before_manifest_read(tmp_path, monkeypatch):
    from env_rag_final.ingest.runner import IngestConfig, IngestError, run_ingest

    svc, _, _ = fixture_service(tmp_path)
    payload = json.loads(Path(svc.registry.source_path).read_text())
    payload["workspaces"]["air"]["pg_workspace"] = "air_physical"
    Path(svc.registry.source_path).write_text(json.dumps(payload))
    monkeypatch.setenv("ENV_RAG_WORKSPACE_REGISTRY", svc.registry.source_path)
    cfg = IngestConfig(
        workspace="air",
        values={},
        parsed_root=tmp_path,
        manifest_path=tmp_path / "missing.jsonl",
        ledger_path=tmp_path / "ledger",
    )
    with pytest.raises(IngestError, match="mismatched target"):
        asyncio.run(run_ingest(cfg))
    assert not cfg.ledger_path.exists()
