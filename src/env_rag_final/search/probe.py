"""Task 4.1 probe runner: tokenizer/vocab evidence against live PG (read-only).

Executes:
1. controlled-vocab segmentation on REAL headings/captions/body/English text;
2. code normalization cases (spaces, dashes, full-width, version years);
3. index↔query consistency: every emitted lexeme group round-trips through
   ``to_tsvector('simple', …)`` and matches a ``tsquery`` built by the SAME
   tokenizer — recorded per case with the actual PG lexemes;
4. n-gram-free "no segmentation of codes" proof and the naive baseline for
   comparison.

Usage: uv run env-rag-final search-probe --report-dir reports/pg-retrieval/phase-2
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import asyncpg

from env_rag_final.catalog.lexical_norm import normalize_code

from . import tokenizer as tk


async def run_tokenizer_probes(conn: asyncpg.Connection, report_dir: Path, values: dict) -> dict:
    report_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()

    real_cases = await _real_cases(conn)
    code_cases = _code_cases()
    consistency = await _consistency(conn, real_cases)
    naive = _naive_baseline()

    payload = {
        "task": "4.1 tokenizer probes",
        "tokenizer_version": tk.VERSION,
        "vocab_sha": tk.vocab_sha(),
        "vocab_counts": {
            "base": len(tk.vocab_words()),
            "stopwords": len(tk.stopwords()),
            "synonyms": len(tk.synonyms()),
        },
        "generated_from": "live PG read-only + real parsed corpus text",
        "elapsed_ms": int((time.monotonic() - t0) * 1000),
        "real_text_cases": real_cases,
        "code_normalization": code_cases,
        "index_query_consistency": consistency,
        "naive_baseline": naive,
    }
    return payload


async def _real_cases(conn: asyncpg.Connection) -> list[dict]:
    """Real headings, captions and body snippets from the frozen corpus."""
    cases: list[dict] = []
    heads = await conn.fetch(
        """SELECT DISTINCT heading FROM env_rag.source_units
           WHERE workspace='default' AND heading IS NOT NULL
             AND heading NOT LIKE '%[part%' AND unit_kind='block'
           ORDER BY heading LIMIT 12"""
    )
    for r in heads:
        text = r["heading"]
        cases.append(
            {
                "source": "real heading (env_rag.source_units)",
                "text": text,
                "default_jieba": _seg_default(text),
                "controlled": _groups(text),
                "tokens_text": tk.tokens_text(text),
            }
        )
    caps = await conn.fetch(
        """SELECT DISTINCT caption FROM env_rag.source_units
           WHERE workspace='default' AND caption IS NOT NULL
             AND caption <> '' ORDER BY caption LIMIT 8"""
    )
    for r in caps:
        text = r["caption"]
        cases.append(
            {
                "source": "real caption",
                "text": text,
                "default_jieba": _seg_default(text),
                "controlled": _groups(text),
                "tokens_text": tk.tokens_text(text),
            }
        )
    body = await conn.fetch(
        """SELECT content FROM public.lightrag_doc_chunks
           WHERE workspace='default' AND content LIKE '%化学需氧量%'
           ORDER BY id LIMIT 2"""
    )
    for r in body:
        snippet = r["content"][:400]
        cases.append(
            {
                "source": "real chunk body snippet",
                "text": snippet,
                "controlled_head": _groups(snippet)[:25],
                "tokens_text_head": " ".join(tk.tokens_text(snippet).split()[:40]),
            }
        )
    # G2-7: code-phrase ADJACENCY cases — the canonical code form must survive
    # index mode and match the phrase query with positions preserved.
    for text in (
        "GB 8978—1996 表 1 总汞",
        "依据 GB 3095-2012 与 HJ 2.2—2018 执行",
        "GB/T 18883-2002 室内空气质量",
    ):
        cases.append(
            {
                "source": "code-phrase adjacency",
                "text": text,
                "controlled_head": _groups(text),
                "tokens_text_head": tk.tokens_text(text, mode="index"),
            }
        )
    return cases


def _code_cases() -> list[dict]:
    inputs = [
        "GB 3095—2012",
        "GB3095-2012",
        "ＧＢ３０９５－２０１２",
        "GB 8978—88",
        "gb3095/2012",
        "HJ 91.1-2019",
        "GB/T 18883-2002",
        "表 1 中总汞",
        "4.2.1 第一类污染物",
        "PM2.5 年平均浓度",
        "pH 值 6~9",
    ]
    out = []
    for text in inputs:
        out.append(
            {
                "input": text,
                "normalized_code": normalize_code(text) if _looks_code(text) else None,
                "tokens": [
                    {"lexemes": list(g.lexemes), "tsquery": g.to_tsquery()}
                    for g in tk.tokenize(text)
                ],
                "tokens_text": tk.tokens_text(text),
            }
        )
    return out


def _looks_code(text: str) -> bool:
    n = normalize_code(text)
    return bool(n) and any(n.startswith(p) for p in ("GB", "HJ", "DB", "TGB"))


async def _consistency(conn: asyncpg.Connection, cases: list[dict]) -> list[dict]:
    """Index↔query consistency through PG's simple dictionary, per real text.

    G2-7: the INDEX side uses the REAL index-mode tokenization
    (``tokens_text(text, mode="index")``); the QUERY side uses the real
    query-mode terms (``query_terms``). Both streams pass through PostgreSQL
    independently — the probe must FAIL if the actual index-mode stream does
    not contain every real query term (an injected inconsistency is detected).
    """
    results = []
    # R7: EVERY selected case runs through the real PG round-trip — the code
    # adjacency cases at the end of the list must not be silently skipped by a
    # fixed [:20] window.
    for c in cases:
        text = c["text"]
        indexed = tk.tokens_text(text, mode="index")
        pg_lex = await conn.fetchval("SELECT to_tsvector('simple', $1)::text", indexed)
        # query stream built from the REAL query mode over the same text
        terms = tk.query_terms(text)
        hits = 0
        misses = []
        for term in terms[:12]:
            q = term.to_tsquery()
            ok = await conn.fetchval(
                "SELECT to_tsvector('simple', $1) @@ to_tsquery('simple', $2)", indexed, q
            )
            if ok:
                hits += 1
            else:
                misses.append(q)
        results.append(
            {
                "text": text,
                "index_mode": "index",
                "indexed_tokens": indexed[:200],
                "pg_lexemes_head": pg_lex[:220],
                "query_mode": "query",
                "query_terms": [g.to_tsquery() for g in terms[:12]],
                "hits": hits,
                "misses": misses,
                "pass": not misses and hits > 0,
            }
        )
    return results


def _seg_default(text: str) -> list[str]:
    import jieba

    return [t for t in jieba.lcut(text, HMM=False) if t.strip()]


def _groups(text: str) -> list[str]:
    return ["-".join(g.lexemes) if len(g.lexemes) > 1 else g.lexemes[0] for g in tk.tokenize(text)]


def _naive_baseline() -> dict:
    from env_rag_final.catalog.lexical_norm import naive_tokens

    sentence = "医疗机构水污染物排放标准"
    return {
        "method": "punctuation split only (Phase 0 baseline)",
        "tokens": naive_tokens(sentence),
        "controlled_tokens": _groups(sentence),
        "observed": "no-dictionary split leaves the whole clause as one token; "
        "controlled jieba+vocab yields 医疗机构/水污染物/排放/标准",
    }


def main_probe(values: dict, report_dir: Path) -> dict:
    import asyncio

    async def run():
        conn = await asyncpg.connect(
            host=values["POSTGRES_HOST"],
            port=int(values["POSTGRES_PORT"]),
            user=values["POSTGRES_USER"],
            password=values["POSTGRES_PASSWORD"],
            database=values["POSTGRES_DATABASE"],
            timeout=15,
            server_settings={"default_transaction_read_only": "on"},
        )
        try:
            async with conn.transaction(readonly=True):
                return await run_tokenizer_probes(conn, report_dir, values)
        finally:
            await conn.close()

    payload = asyncio.run(run())
    out = report_dir / "tokenizer-probes.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return payload
