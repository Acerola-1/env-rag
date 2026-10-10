import asyncio
from types import SimpleNamespace

import pytest

from env_rag_final import ask
from env_rag_final import lightrag_enum_bridge as bridge


class FakeRAG:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.aquery_calls = []
        self.initialize_calls = 0

    async def aquery(self, query, **kwargs):
        self.aquery_calls.append((query, kwargs))
        if self.error is not None:
            raise self.error
        return self.result

    async def initialize_storages(self):
        self.initialize_calls += 1
        raise AssertionError("the bridge must not initialize LightRAG")


def test_disabled_path_forwards_kwargs_and_preserves_result_identity(monkeypatch):
    result = object()
    rag = FakeRAG(result=result)

    def fail_if_loaded(*args, **kwargs):
        raise AssertionError("enumeration module should not be loaded")

    monkeypatch.setattr(bridge, "import_module", fail_if_loaded)
    query_options = {"mode": "mix", "param": object()}

    actual = asyncio.run(bridge.aquery_with_enumeration(rag, "question", **query_options))

    assert actual is result
    assert rag.aquery_calls == [("question", query_options)]
    assert rag.initialize_calls == 0


def test_disabled_path_does_not_inspect_enumeration_arguments(monkeypatch):
    rag = FakeRAG(result="original")

    def fail_if_loaded(*args, **kwargs):
        raise AssertionError("enumeration module should not be loaded")

    monkeypatch.setattr(bridge, "import_module", fail_if_loaded)
    actual = asyncio.run(
        bridge.aquery_with_enumeration(
            rag,
            "question",
            enumeration=False,
            enum_options=object(),
            values=object(),
            conn=object(),
            top_k=7,
        )
    )

    assert actual == "original"
    assert rag.aquery_calls == [("question", {"top_k": 7})]


def test_disabled_path_propagates_the_original_exception_instance():
    error = RuntimeError("query failed")
    rag = FakeRAG(error=error)

    with pytest.raises(RuntimeError) as caught:
        asyncio.run(bridge.aquery_with_enumeration(rag, "question"))

    assert caught.value is error


def test_enabled_path_calls_only_enumeration_with_explicit_inputs(monkeypatch):
    rag = FakeRAG(result="must not be used")
    values = {"POSTGRES_HOST": "example.invalid"}
    conn = object()
    payload = {"coverage_status": "complete", "answer": {"items": []}}
    observed = {}

    async def fake_ask_question(request, received_values, *, conn=None):
        observed.update(request=request, values=received_values, conn=conn)
        return payload

    monkeypatch.setattr(ask, "ask_question", fake_ask_question)
    monkeypatch.setattr(
        bridge,
        "import_module",
        lambda name, package=None: SimpleNamespace(
            Question=ask.Question, ask_question=ask.ask_question
        ),
    )

    actual = asyncio.run(
        bridge.aquery_with_enumeration(
            rag,
            "列出表 2 中的指标",
            enumeration=True,
            enum_options={"kind": "table", "table_number": "2"},
            values=values,
            conn=conn,
            mode="mix",
        )
    )

    assert actual is payload
    assert observed["request"] == ask.Question("列出表 2 中的指标", kind="table", table_number="2")
    assert observed["values"] is values
    assert observed["conn"] is conn
    assert rag.aquery_calls == []
    assert rag.initialize_calls == 0


def test_enabled_path_requires_explicit_values_before_loading_enumerator(monkeypatch):
    rag = FakeRAG()

    def fail_if_loaded(*args, **kwargs):
        raise AssertionError("enumerator should not load without explicit values")

    monkeypatch.setattr(bridge, "import_module", fail_if_loaded)

    with pytest.raises(ValueError, match="values is required"):
        asyncio.run(bridge.aquery_with_enumeration(rag, "列出相关标准", enumeration=True))

    assert rag.aquery_calls == []
    assert rag.initialize_calls == 0
