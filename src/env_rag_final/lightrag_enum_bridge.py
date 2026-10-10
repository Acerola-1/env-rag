"""Explicit adapter between LightRAG's async query API and catalog enumeration.

The normal path delegates directly to ``rag.aquery``. Enumeration is an
explicit opt-in that uses :mod:`env_rag_final.ask` and its read-only catalog
path; it does not initialize or call the LightRAG instance.

Example::

    from lightrag import QueryParam

    # Keeps LightRAG's normal result type (usually str or an async iterator).
    answer = await aquery_with_enumeration(
        rag, question, param=QueryParam(mode="mix")
    )

    # Returns the enumeration result dictionary and uses only explicit values.
    listing = await aquery_with_enumeration(
        rag,
        question,
        enumeration=True,
        enum_options={"kind": "auto"},
        values=environment_values,
    )

This helper does not register an HTTP route or modify LightRAG. In normal
mode, the exact object returned by ``rag.aquery`` is passed back; exceptions
also propagate unchanged. In enumeration mode, the result is the dictionary
returned by ``ask_question``. The caller must provide database ``values``
explicitly; this module does not read global environment or project config.
"""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from importlib import import_module
from typing import Any, Protocol, TypeVar

_ResultT_co = TypeVar("_ResultT_co", covariant=True)


class _AsyncRAG(Protocol[_ResultT_co]):
    def aquery(self, query: str, **query_kwargs: Any) -> Awaitable[_ResultT_co]: ...


async def aquery_with_enumeration(
    rag: _AsyncRAG[_ResultT_co],
    query: str,
    *,
    enumeration: bool = False,
    enum_options: Mapping[str, Any] | None = None,
    values: dict[str, str] | None = None,
    conn: Any = None,
    **query_kwargs: Any,
) -> _ResultT_co | dict[str, Any]:
    """Run LightRAG's query or, when explicitly requested, catalog enumeration.

    ``query_kwargs`` are forwarded unchanged to ``rag.aquery`` only when
    ``enumeration`` is false. For enumeration, ``enum_options`` are keyword
    arguments for ``ask.Question``; LightRAG query options are not applied.
    The enabled result is the structured dictionary from ``ask_question``.
    """
    if not enumeration:
        return await rag.aquery(query, **query_kwargs)

    if values is None:
        raise ValueError("values is required when enumeration=True")

    ask = import_module(".ask", package=__package__)
    request = ask.Question(query, **dict(enum_options or {}))
    return await ask.ask_question(request, values, conn=conn)
