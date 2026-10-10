"""Review the ordinary prose fallback with a blank line after its heading."""

import asyncio

from env_rag_final.enumerate_.contract import EnumResult
from env_rag_final.enumerate_.prose_enum import UnitText
from env_rag_final.search import expand


def test_plain_prose_fallback_blank_line_has_readable_declared_span(monkeypatch):
    import env_rag_final.enumerate_.prose_enum as prose

    source = "## 4.2 标准分级\n\n一类区适用一级浓度限值 10，二类区适用二级浓度限值 99"
    unit = UnitText("u", source, ["c"], {"blockid": "u"}, 0, len(source), False, "parsed_block")

    async def current(*a, **kw):
        return {"state": "current", "catalog_snapshot_id": "catalog"}

    async def read(*a, **kw):
        return [unit], EnumResult(
            "q",
            "prose",
            "default",
            "catalog",
            "source",
            members_total=1,
            members_processed=1,
            coverage_status="ambiguous",
            read_status="complete",
        )

    monkeypatch.setattr(expand, "check_search_stale", current)
    monkeypatch.setattr(prose, "read_prose_scope", read)
    result = asyncio.run(expand._expand_prose(None, "default", "d", "d:scope:4.2", None))
    assert len(result["items"]) == 1
    item = result["items"][0]
    citation = item["citation"]
    declared = source[citation["unit_rel_start"] : citation["unit_rel_end"]]
    # Returning partial/unverified would be a safe refusal. A complete,
    # verified result must support its WHOLE quote within the declared span.
    if result["coverage_status"] == "complete":
        assert item["citation_verified"] is True
        assert declared.strip().startswith(citation["quote"].strip())
    else:
        assert item["citation_verified"] is not True
        assert result["coverage_status"] == "partial"
