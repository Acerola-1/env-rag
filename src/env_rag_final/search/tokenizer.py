"""Versioned application-side tokenizer (task 4.1).

Design (design.md decision 4):
- jieba (pinned by uv.lock, 0.42.1) with a CONTROLLED environmental vocabulary
  and HMM disabled (dictionary-only, deterministic). Index and query MUST use
  this same module and the same version.
- Standard codes are NOT segmented: "GB 3095—2012" / "ＧＢ３０９５－２０１２" /
  "gb3095/2012" all canonicalize to the ASCII *phrase* gb3095-2012 (base
  lexeme + "-year" lexeme, adjacent in PG's simple parser), so a code's own
  lexeme sequence must appear adjacently in the indexed text.
- Bare codes ("GB 3095", "GB/T 18883") become ONE lexeme (gbt18883 style).
- Clause numbers ("4.2.1"), latin+digit compounds ("pm2.5", "pm10") and table
  numbers ("表 1" → "表1") are protected from segmentation the same way.
- ``VERSION`` + vocab file SHA participate in the search index build identity:
  changing the algorithm or vocabulary produces a NEW build (old index is
  pruned by the atomic publish), never a silent reuse.

PG side is always ``to_tsvector('simple', <tokens_text>)``; the tokens_text is
whitespace-joined. Query side builds a tsquery from the SAME token groups.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

VERSION = "phase-2-v3-jieba-0.42.1-cfs-index"

_VOCAB_DIR = Path(__file__).parent / "vocab"

_TOKEN_OK = re.compile(r"^[\u4e00-\u9fff0-9a-z][\u4e00-\u9fff0-9a-z._+\-/%]*$")

_SUPERSCRIPT = str.maketrans({"²": "2", "³": "3", "¹": "1", "⁰": "0", "µ": "u", "μ": "u"})
_FULLWIDTH = str.maketrans({chr(c): chr(c - 0xFEE0) for c in range(0xFF01, 0xFF5F)})

# standard codes WITH a year:  GB 3095—2012 / GB/T 18883-2002 / GB8978—88
_CODE_YEAR_RE = re.compile(
    r"(?:GB|HJ|DB\d{0,2})\s*/?\s*T?\s*\d+(?:\.\d+)?\s*[-—–－/]\s*\d{2,4}",
    re.IGNORECASE,
)
# bare codes:  GB 3095 / GB/T 18883 / HJ 91.1
_CODE_BARE_RE = re.compile(
    r"(?:GB|HJ|DB\d{0,2})\s*/?\s*T?\s*\d+(?:\.\d+)?",
    re.IGNORECASE,
)
_LATIN_NUM_RE = re.compile(r"[A-Za-z]{1,6}\d+(?:\.\d+)?")
# clause numbers mid-text; pure decimals ("0.05") excluded
_CLAUSE_RE = re.compile(r"(?<![\w.])(?!0(?:\.|$))\d+(?:\.\d+){1,3}(?![\d])")
_TABLE_RE = re.compile(r"(续\s*表|表)\s*([A-Z]?\d+(?:\.\d+)?)")
_CODE_BASE_RE = re.compile(
    r"(?P<base>[A-Za-z][A-Za-z/ ]*?\d+(?:\.\d+)?)\s*[-/]\s*(?P<year>\d{2,4})$"
)


def normalize_text(text: str) -> str:
    """Full-width → ASCII, dash variants → '-', superscripts → digits, collapse ws."""
    t = text.translate(_FULLWIDTH).translate(_SUPERSCRIPT)
    t = t.replace("—", "-").replace("–", "-").replace("－", "-")
    t = t.replace("#", " ")
    return re.sub(r"\s+", " ", t).strip()


def canon_code_year(span: str) -> tuple[str, str] | None:
    """('gb3095', '-2012') / ('gbt18883', '-2002') — canonical code+year pair."""
    t = normalize_text(span)
    m = _CODE_BASE_RE.match(t)
    if not m:
        return None
    base = re.sub(r"[\s/]", "", m.group("base")).lower()
    return base, "-" + m.group("year")


def canon_code_bare(span: str) -> str | None:
    """'gb3095' / 'gbt18883' — canonical single-lexeme code."""
    t = normalize_text(span)
    base = re.sub(r"[\s/]", "", t).lower()
    return base or None


@dataclass(frozen=True)
class QueryToken:
    """One query term group: 1 lexeme (plain) or several adjacent ones (phrase)."""

    lexemes: tuple[str, ...]

    def render(self) -> str:
        """The indexed-text form: adjacent lexemes are joined without a space."""
        return "".join(self.lexemes)

    def to_tsquery(self) -> str:
        """The indexed-text form may tokenize as the ADJACENT phrase (gb3095
        <-> -2012) or as a SINGLE lexeme (hj2.2-2018, where PG's parser keeps
        the dotted-number join intact) — the query matches BOTH shapes."""
        if len(self.lexemes) == 1:
            return "'" + self.lexemes[0].replace("'", "''") + "'"
        phrase = " <-> ".join("'" + lx.replace("'", "''") + "'" for lx in self.lexemes)
        joined = "".join(self.lexemes).replace("'", "''")
        return f"({phrase} | '{joined}')"


def _spans(text: str) -> list[tuple[int, int, QueryToken]]:
    """Protected spans in order; each carries its canonical QueryToken."""
    out: list[tuple[int, int, QueryToken]] = []
    taken: list[tuple[int, int]] = []

    def free(s: int, e: int) -> bool:
        return not any(s < e0 and s0 < e for s0, e0 in taken)

    for m in _CODE_YEAR_RE.finditer(text):
        pair = canon_code_year(m.group(0))
        if pair:
            out.append((m.start(), m.end(), QueryToken(pair)))
            taken.append((m.start(), m.end()))
    for m in _CODE_BARE_RE.finditer(text):
        if not free(m.start(), m.end()):
            continue
        base = canon_code_bare(m.group(0))
        if base:
            out.append((m.start(), m.end(), QueryToken((base,))))
            taken.append((m.start(), m.end()))
    for m in _LATIN_NUM_RE.finditer(text):
        if not free(m.start(), m.end()):
            continue
        out.append((m.start(), m.end(), QueryToken((m.group(0).lower(),))))
        taken.append((m.start(), m.end()))
    for m in _CLAUSE_RE.finditer(text):
        if not free(m.start(), m.end()):
            continue
        out.append((m.start(), m.end(), QueryToken((m.group(0),))))
        taken.append((m.start(), m.end()))
    for m in _TABLE_RE.finditer(text):
        if not free(m.start(), m.end()):
            continue
        num = m.group(2)
        token = f"续表{num}" if m.group(1).startswith("续") else f"表{num}"
        out.append((m.start(), m.end(), QueryToken((token,))))
        taken.append((m.start(), m.end()))
    return sorted(out, key=lambda x: x[0])


_jieba = None


def _seg():
    global _jieba
    if _jieba is None:
        import jieba

        jieba.initialize()
        for word in vocab_words():
            jieba.add_word(word, freq=1_000_000)
        _jieba = jieba
    return _jieba


def vocab_words() -> list[str]:
    return _read_vocab("base.txt")


def stopwords() -> set[str]:
    return set(_read_vocab("stopwords.txt"))


def synonyms() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in _read_vocab("synonyms.txt"):
        if "=" not in line:
            continue
        canon, alts = line.split("=", 1)
        out[canon] = [a for a in alts.split("|") if a]
    return out


def _read_vocab(name: str) -> list[str]:
    path = _VOCAB_DIR / name
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def vocab_sha() -> str:
    """SHA over the three vocab files (canonical order) — part of build identity."""
    h = hashlib.sha256()
    for name in ("base.txt", "stopwords.txt", "synonyms.txt"):
        h.update(name.encode())
        h.update(b"\0")
        h.update((_VOCAB_DIR / name).read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _segment_plain(text: str, mode: str = "query") -> list[str]:
    """jieba on a span with no protected tokens; normalized, filtered tokens.

    ``query`` mode emits maximal words (jieba.lcut): one query term per word.
    ``index`` mode emits the SEARCH superset (jieba.cut_for_search): maximal
    words AND their dictionary sub-words, so every query-side maximal word is
    present in the index whenever its containing phrase is. That asymmetry is
    one-directional by construction (index ⊇ query vocabulary).
    """
    jieba = _seg()
    pieces = (
        jieba.cut_for_search(text, HMM=False) if mode == "index" else jieba.lcut(text, HMM=False)
    )
    tokens: list[str] = []
    for raw in pieces:
        tok = raw.strip().lower()
        if not tok or not _TOKEN_OK.match(tok):
            continue
        tokens.append(tok)
    return tokens


def tokenize(text: str, mode: str = "query") -> list[QueryToken]:
    """The single tokenization contract for BOTH index and query side.

    ``mode="index"`` emits the search superset (see ``_segment_plain``);
    ``mode="query"`` emits maximal terms. Both share protected-span handling.
    """
    t = normalize_text(text)
    groups: list[QueryToken] = []
    pos = 0
    for start, end, group in _spans(t):
        if start > pos:
            groups.extend(QueryToken((x,)) for x in _segment_plain(t[pos:start], mode))
        groups.append(group)
        pos = end
    if pos < len(t):
        groups.extend(QueryToken((x,)) for x in _segment_plain(t[pos:], mode))
    return groups


def tokens_text(text: str, mode: str = "query") -> str:
    """Whitespace-joined token groups — the exact string indexed via simple."""
    return " ".join(g.render() for g in tokenize(text, mode))


def query_terms(query: str, drop_stopwords: bool = True) -> list[QueryToken]:
    """Query-side terms: tokenize + drop question/stop words (single-lexeme only)."""
    sw = stopwords() if drop_stopwords else set()
    out = []
    for g in tokenize(query):
        if len(g.lexemes) == 1 and g.lexemes[0] in sw:
            continue
        out.append(g)
    return out


def and_tsquery(terms: list[QueryToken]) -> str:
    return " & ".join(t.to_tsquery() for t in terms)


def or_tsquery(terms: list[QueryToken]) -> str:
    return " | ".join(t.to_tsquery() for t in terms)
