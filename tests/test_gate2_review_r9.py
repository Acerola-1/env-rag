"""Malformed JSON offsets must be safely refused along the model/bind/verify path."""

import asyncio
import json

import httpx

from env_rag_final.enumerate_.prose_enum import (
    UnitText,
    bind_citations,
    extract_items_with_model,
    verify_citations,
)


def test_model_json_invalid_segment_offsets_are_refused_without_type_error(monkeypatch):
    text = "引用原文完整存在，限值99。"
    unit = UnitText("u", text, ["c"], {}, 0, len(text), False, "parsed_block")
    response_items = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": json.dumps(response_items)}}]}

    class LocalFixtureClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, *a, **kw):
            return Response()

    monkeypatch.setattr(httpx, "AsyncClient", LocalFixtureClient)
    failures = []
    for invalid in ("invalid", None):
        response_items[:] = [
            {
                "text": text,
                "citation": {
                    "quote": text,
                    "unit_segments": [{"unit_id": "u", "rel_start": invalid, "rel_end": len(text)}],
                },
            }
        ]
        items, _logs, error = asyncio.run(
            extract_items_with_model(
                text,
                "逐字抽取",
                {
                    "LLM_BINDING_HOST": "http://fixture.invalid",
                    "LLM_MODEL": "fixture",
                    "LLM_BINDING_API_KEY": "fixture",
                },
            )
        )
        if error:
            assert error.startswith("model_failure:")
            continue  # Upstream rejection is also safe.
        bound = bind_citations(items, "default", "d", "s", [unit])
        try:
            result = verify_citations(bound, text, [unit])
        except (TypeError, ValueError) as exc:
            failures.append((type(invalid).__name__, type(exc).__name__))
        else:
            if result[0]["citation_verified"] is not False:
                failures.append((type(invalid).__name__, "incorrectly_verified"))
    assert not failures, f"Malformed JSON offsets were not safely refused: {failures}"
