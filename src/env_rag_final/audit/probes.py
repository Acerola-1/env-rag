"""Search probes executed against the live PG (read-only) — task 1.7.

Every probe records observed facts only. No tokenizer is installed at this
phase, so candidate segmentation schemes are listed as *pending*, never "passed".
"""

from __future__ import annotations

import asyncpg

from . import lexical

SAMPLE_SENTENCE = "医疗机构水污染物排放标准 GB 18466-2005 表1 总氮"
WHOLE_CLAUSE = "医疗机构水污染物排放标准"


async def build_search_probes(conn: asyncpg.Connection) -> dict:
    # Probe 1: default-config whole-sentence failure (observed).
    ts_debug = [
        {"alias": r["alias"], "token": r["token"]}
        for r in await conn.fetch(
            "SELECT alias, token FROM ts_debug('simple', $1)", SAMPLE_SENTENCE
        )
    ]
    match = await conn.fetchrow(
        """SELECT
             to_tsvector('simple', $1) @@ to_tsquery('simple', $2) AS substr_match,
             to_tsvector('simple', $1) @@ plainto_tsquery('simple', $1) AS self_match""",
        WHOLE_CLAUSE,
        "医疗机构",
    )
    default_cfg = await conn.fetchval("SHOW default_text_search_config")
    custom_cfgs = await conn.fetch(
        """SELECT c.cfgname FROM pg_ts_config c
           JOIN pg_namespace n ON n.oid=c.cfgnamespace
           WHERE n.nspname NOT IN ('pg_catalog','information_schema')"""
    )

    # Probe 2: code normalization (offline, deterministic).
    code_cases = [
        {"input": "GB 3095—2012", "expected": "GB3095-2012"},
        {"input": "ＧＢ３０９５－２０１２", "expected": "GB3095-2012"},
        {"input": "gb3095-2012", "expected": "GB3095-2012"},
        {"input": "HJ 91.1-2019", "expected": "HJ91.1-2019"},
        {"input": "GB/T 18883-2002", "expected": "GBT18883-2002"},
    ]
    code_results = [
        {
            "input": c["input"],
            "normalized": lexical.normalize_code(c["input"]),
            "expected": c["expected"],
            "pass": lexical.normalize_code(c["input"]) == c["expected"],
        }
        for c in code_cases
    ]
    extracted = lexical.extract_codes(
        "依据 GB 8978—1996 表 4 与 HJ 91.1-2019，参照 GB/T 18883-2002 执行"
    )

    # Probe 3: naive tokenization baseline (offline; documents the failure mode
    # that motivates a real segmenter).
    naive = lexical.naive_tokens("医疗机构的水污染物排放执行什么标准？表1里总氮的排放限值是多少？")

    # Probe 4: title/body query examples drawn from the audited corpus.
    corpus_examples = [
        {
            "query": "环境空气污染物基本项目浓度限值",
            "expected_doc": "air-02_生态环境部_环境空气质量标准_GB3095-2012.pdf",
            "evidence": "GB 3095-2012 表1 caption（tables.json）",
            "segmentation_pending": ["环境空气", "污染物", "基本项目", "浓度限值"],
        },
        {
            "query": "医疗机构污水排放的接管限值",
            "expected_doc": "water-09_生态环境部_医疗机构水污染物排放标准_GB18466-2005.pdf",
            "evidence": "GB 18466-2005 表2 预处理标准（chunks 内联表）",
            "segmentation_pending": ["医疗机构", "污水", "排放", "接管限值"],
        },
        {
            "query": "第一类污染物最高允许排放浓度",
            "expected_doc": "water-11_生态环境部_污水综合排放标准_GB8978-1996.pdf",
            "evidence": "GB 8978-1996 表 1 caption",
            "segmentation_pending": ["第一类", "污染物", "最高允许排放浓度"],
        },
    ]

    return {
        "generated_at_note": "由只读审计生成；只记录已执行探针的结果",
        "probe_1_default_pg_chinese_failure": {
            "status": "executed",
            "input": SAMPLE_SENTENCE,
            "ts_debug_simple": ts_debug,
            "observed": "整句中文（含标点前长串）在 simple/english 配置下并成单个 lexeme；"
            "to_tsvector('simple','医疗机构水污染物排放标准') @@ to_tsquery('simple','医疗机构') = "
            f"{match['substr_match']}，逐字自身匹配 = {match['self_match']}。",
            "default_text_search_config": default_cfg,
            "custom_configs_present": [r["cfgname"] for r in custom_cfgs],
            "conclusion": "数据库默认中文处理失配 → design.md 决策 4（应用侧分词 + simple）前提成立（已观察）。",
        },
        "probe_2_code_normalization": {
            "status": "executed",
            "implementation": "env_rag_final.audit.lexical.normalize_code（版本随 run-manifest code_version）",
            "cases": code_results,
            "extract_from_text_example": {
                "text": "依据 GB 8978—1996 表 4 与 HJ 91.1-2019，参照 GB/T 18883-2002 执行",
                "extracted": extracted,
                "note": "提取的是**引用编号**；文档自身编号另从封面/正文提取，两者不得混用（specs 元数据要求）",
            },
        },
        "probe_3_naive_segmentation_baseline": {
            "status": "executed",
            "implementation": "标点切分（无词典）",
            "question": "医疗机构的水污染物排放执行什么标准？表1里总氮的排放限值是多少？",
            "tokens": naive,
            "observed": "无词典切分会把「医疗机构的水污染物排放执行什么标准」整段留作一个 token，"
            "验证了不做词库级分词时 AND 组合必然漏召回；该基线用于 Phase 2 对照。",
        },
        "probe_4_corpus_query_examples": {
            "status": "listed_pending_validation",
            "note": "词项拆分是**拟采用**的应用分词示意；jieba 未安装、tsvector 未构建，"
            "在 Phase 2（tasks 4.1/4.2）执行前后均不得标记为通过。",
            "examples": corpus_examples,
        },
        "tokenizer_candidates": [
            {"name": "jieba", "status": "未安装（待 Phase 2 uv 探针锁定）", "pass": None},
            {"name": "受控环保词表叠加", "status": "待词表起草", "pass": None},
        ],
    }
