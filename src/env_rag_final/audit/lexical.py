"""Normalized standard-code handling used by the search probes.

Task 1.7 requires demonstrating Unicode / whitespace / hyphen normalization;
these helpers are the audit's reference implementation (versioned by the
run-manifest code version) and the seed for the Phase-2 production module.
"""

from __future__ import annotations

import re

_WS = re.compile(r"\s+")
_CODE_TOKEN = re.compile(r"(GB|HJ|DB\d{0,2}|T\s*GB)", re.IGNORECASE)


def normalize_text_basic(text: str) -> str:
    """Full-width alphanumerics -> ASCII, collapse whitespace, strip outer space."""
    table = str.maketrans({chr(c): chr(c - 0xFEE0) for c in range(0xFF01, 0xFF5F)})
    return _WS.sub(" ", text.translate(table)).strip()


def normalize_code(text: str) -> str:
    """Normalize a standard code reference for exact matching.

    "GB 3095—2012" / "GB 3095-2012" / "ＧＢ３０９５-2012" / "GB3095-2012"
    all reduce to "GB3095-2012". Em/en dashes become hyphens.
    """
    t = normalize_text_basic(text).upper().replace("—", "-").replace("–", "-")
    t = t.replace("－", "-")  # full-width hyphen-minus
    t = _WS.sub("", t.replace("/", ""))
    return t


def extract_codes(text: str) -> list[str]:
    """Extract standard-code-like tokens from free text, normalized."""
    out = []
    t = normalize_text_basic(text).upper().replace("—", "-").replace("–", "-")
    for match in re.finditer(r"(GB[/\s]*T?[/\s]*\d+(?:\.\d+)?|HJ\s*\d+(?:\.\d+)?)-(\d{4})", t):
        code = match.group(1).replace(" ", "").replace("/", "")
        out.append(f"{code}-{match.group(2)}")
    return out


def naive_tokens(text: str) -> list[str]:
    """A deliberately naive lexical split showing why whole-sentence matching fails.

    Splits on punctuation/whitespace only (no dictionary segmentation); long
    Chinese spans stay as single tokens, which PG 'simple' cannot match
    substring-wise. Recorded in search-probes.json as the baseline failure.
    """
    parts = re.split(r"[，。、；：？！,.;:?!()\s（《》）\"']+", text)
    return [p for p in (p.strip() for p in parts) if p]


def is_uninstalled(name: str) -> bool:
    try:
        __import__(name)
        return False
    except ImportError:
        return True
