"""Search text preparation (task 4.2): strip markup, keep searchable content.

Rules (observed from the real corpus):
- ``<table>`` blocks → cell texts joined by row/space (tags removed), so table
  content is searchable but no markup leaks into tsvector input.
- ``<sup>``/``<sub>`` keep their text ("mg/m<sup>3</sup>" → "mg/m3").
- ``<drawing …/>`` (figures) keep the caption text only — the caption is the
  searchable description; the image path is dropped entirely.
- ``<equation …>$$ …$$</equation>`` (LaTeX) is replaced by a placeholder (the
  raw TeX is not searchable text); surrounding prose is kept.
- inline math ``$…$`` is dropped for the same reason.
- markdown heading markers ('#') are removed but the heading text is kept.

The cleaning is deterministic and versioned by ``CLEAN_VERSION`` which is part
of the search build identity.
"""

from __future__ import annotations

import html as html_mod
import re

CLEAN_VERSION = "phase-2-v1"

_EQUATION_RE = re.compile(r"<equation\b[^>]*>.*?</equation>", re.S | re.I)
_DRAWING_RE = re.compile(r"<drawing\b([^>]*?)/?>", re.I)
_CAPTION_ATTR_RE = re.compile(r"""caption\s*=\s*["']([^"']*)["']""")
_TABLE_TAG_RE = re.compile(r"</?(?:table|tr|td|th|tbody|thead)\b[^>]*>", re.I)
_OTHER_TAG_RE = re.compile(r"<(?!/?(?:sup|sub)\b)[^>]{0,400}?>", re.I)
_SUP_SUB_RE = re.compile(r"</?su[bp]\b[^>]*>", re.I)
_INLINE_MATH_RE = re.compile(r"\$\$.*?\$\$|\$[^$\n]{1,120}\$", re.S)
_MD_HEAD_RE = re.compile(r"(?m)^\s*#{1,6}\s*")


def clean_markup(text: str) -> str:
    """Markup-free searchable text (order matters; deterministic)."""
    t = text or ""

    def _keep_caption(m: re.Match) -> str:
        cap = _caption_of(m.group(1) or "")
        return f" {cap} "

    # figures: keep captions, drop the rest of the tag
    t = _DRAWING_RE.sub(_keep_caption, t)
    t = _EQUATION_RE.sub(" ", t)
    t = _INLINE_MATH_RE.sub(" ", t)
    t = _TABLE_TAG_RE.sub(" ", t)  # cell boundaries → spaces
    t = _SUP_SUB_RE.sub("", t)  # keep inner text
    t = _OTHER_TAG_RE.sub(" ", t)
    t = html_mod.unescape(t)
    t = _MD_HEAD_RE.sub("", t)
    return re.sub(r"[ \t\u3000]+", " ", t)


def _caption_of(attrs: str) -> str:
    m = _CAPTION_ATTR_RE.search(attrs or "")
    return html_mod.unescape(m.group(1)) if m else ""


def heading_text(heading_raw) -> str:
    """chunks.heading is a JSON string: {"heading": "...", "parent_headings": [...]}."""
    import json

    if not heading_raw:
        return ""
    try:
        obj = json.loads(heading_raw)
    except (TypeError, ValueError):
        return str(heading_raw)
    parts = []
    if isinstance(obj, dict):
        parts = [obj.get("heading") or ""] + list(obj.get("parent_headings") or [])
    return " ".join(p for p in parts if p)
