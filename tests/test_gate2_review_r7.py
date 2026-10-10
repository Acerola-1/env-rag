"""F1 acceptance: whole declared quotes, sliced-unit coordinates, legacy checks."""

from env_rag_final.enumerate_.prose_enum import UnitText, bind_citations, verify_citations


def test_declared_span_cannot_validate_only_first_sixty_characters():
    quote = "适用范围必须逐字核验" * 8 + "完整引用结尾的限值是99"
    unit = UnitText("u", quote, ["c"], {"blockid": "u"}, 0, len(quote), False, "parsed_block")
    item = {
        "text": quote,
        "citation_verified": True,
        "citation": {
            "kind": "char_span",
            "char_start": 0,
            "char_end": 60,
            "quote": quote,
        },
    }
    bound = bind_citations([item], "default", "d", "s", [unit])
    checked = verify_citations(bound, quote, [unit])
    assert checked[0]["citation_verified"] is False


def test_requires_span_raw_offsets_are_translated_to_sliced_unit_text():
    prefix = "无关的前置原文" * 10
    text = "7.5 只读取请求条款，限值99，保留完整原文引句。"
    unit = UnitText(
        "u",
        text,
        ["c"],
        {"blockid": "u"},
        0,
        len(text),
        True,
        "parsed_block",
        span_offset_in_unit=len(prefix),
    )
    item = {
        "text": text,
        "citation_verified": True,
        "citation": {
            "kind": "char_span",
            "char_start": 0,
            "char_end": len(text),
            "quote": text,
        },
    }
    bound = bind_citations([item], "default", "d", "s", [unit])
    citation = bound[0]["citation"]
    raw = prefix + text
    assert raw[citation["unit_rel_start"] : citation["unit_rel_end"]] == text
    checked = verify_citations(bound, text, [unit])
    assert checked[0]["citation_verified"] is True


def test_legacy_verify_without_units_still_rejects_quote_absent_from_text():
    item = {
        "text": "停车场",
        "citation_verified": True,
        "citation": {"quote": "停车场"},
    }
    checked = verify_citations([item], "门诊、病房")
    assert checked[0]["citation_verified"] is False
