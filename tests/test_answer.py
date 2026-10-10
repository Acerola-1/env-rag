"""Task 5.5 entry-level acceptance matrix (handoff-phase-3-5.5 classes 1–6).

OFFLINE: every scenario drives the OWNING entry env_rag_final.answer.run_answer
with injected fake env_rag connections, tmp parsed-sidecar fixtures, FIXED
replay generations of the accepted 5.3/5.4 reports, and a fake answer-model
transport. No real database, no real HTTP, no real model.
"""

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import env_rag_final.answer as an
from env_rag_final.audit import identity as audit_identity

WS = "default"
SNAP = "snap-1"
RUN = "r1"
FP = "fp-1"
SEARCH = "srch-1"
GOLD_SHA = "gold-sha"

DOC_8978 = "doc-8978"
DOC_8978_OLD = "doc-8978-old"
DOC_18466 = "doc-18466"
DOC_2012 = "doc-2012"
DOC_2026 = "doc-2026"
FRAG1 = "tb-8978-0001"
FRAG2 = "tb-8978-0002"  # the low-ranked continuation fragment
C1 = "chunk-8978-001"
C2 = "chunk-8978-002"
CP12 = "chunk-3095-2012-001"
CP26 = "chunk-3095-2026-001"

DOCS = {
    DOC_8978: {
        "doc_name": "gb8978.pdf",
        "self_code": "GB8978",
        "self_code_version": "1996",
        "title": "污水综合排放标准",
        "doc_type": "standard",
    },
    DOC_8978_OLD: {
        "doc_name": "gb8978-1989.pdf",
        "self_code": "GB8978",
        "self_code_version": "1989",
        "title": "污水综合排放标准（旧版）",
        "doc_type": "standard",
    },
    DOC_18466: {
        "doc_name": "gb18466.pdf",
        "self_code": "GB18466",
        "self_code_version": "2005",
        "title": "医疗机构水污染物排放标准",
        "doc_type": "standard",
    },
    DOC_2012: {
        "doc_name": "gb3095-2012.pdf",
        "self_code": "GB3095",
        "self_code_version": "2012",
        "title": "环境空气质量标准",
        "doc_type": "standard",
    },
    DOC_2026: {
        "doc_name": "gb3095-2026.pdf",
        "self_code": "GB3095",
        "self_code_version": "2026",
        "title": "环境空气质量标准（2026）",
        "doc_type": "standard",
    },
}

_HDR = "<tr><th>序号</th><th>污染物项目</th><th>最高允许排放浓度</th><th>单位</th></tr>"
_ROWS1 = [
    ("1", "总汞", "0.05", "mg/L"),
    ("2", "总镉", "0.1", "mg/L"),
    ("3", "总铬", "1.5", "mg/L"),
    ("4", "六价铬", "0.5", "mg/L"),
    ("5", "总砷", "0.5", "mg/L"),
    ("6", "总铅", "1.0", "mg/L"),
    ("7", "总镍", "1.0", "mg/L"),
    ("8", "苯并芘", "0.00003", "mg/L"),
    ("9", "总银", "0.05", "mg/L"),
    ("10", "总α放射性", "1", "Bq/L"),
    ("11", "总β放射性", "10", "Bq/L"),
]
# the continuation fragment carries items 12–13 (its own header, never merged
# into the count) — exactly the "续表" pattern the rerank top-k cannot see
_ROWS2 = [("12", "pH值", "6~9", ""), ("13", "色度", "50", "倍")]

PROSE_3 = (
    "3 术语和定义\n"
    "3.1 医疗机构污水 医疗机构收治的传染病病人或疑似传染病病人产生的 "
    "含有病原体的排泄物、分泌物及与此相关的污水。\n"
    "3.2 医疗机构污泥 医疗机构污水处理产生的污泥。\n"
    "3.3 传染医疗机构 医疗机构内具有传染性的科室。\n"
    "3.4 污水处理设施 用于处理医疗机构污水的设施与设备。\n"
)

_TBL1_8978_F1 = (
    "<table>"
    + _HDR
    + "".join(f"<tr>{''.join(f'<td>{c}</td>' for c in r)}</tr>" for r in _ROWS1)
    + "</table>"
)
_TBL1_8978_F2 = (
    "<table>"
    + _HDR
    + "".join(f"<tr>{''.join(f'<td>{c}</td>' for c in r)}</tr>" for r in _ROWS2)
    + "</table>"
)

_HDR_AIR = "<tr><th>序号</th><th>污染物项目</th><th>平均时间</th><th>一级浓度限值</th><th>二级浓度限值</th><th>单位</th></tr>"


def _air_table(pm_value: str, level1: str) -> str:
    rows = [
        ("1", "PM2.5", "年平均", level1, pm_value, "μg/m³"),
        ("2", "PM10", "年平均", "50", "70", "μg/m³"),
        # the 24h row exists so an averaging-time POSITIVE can be verified via
        # the owning entry (answer-review r2 B1-3 companion)
        ("3", "PM2.5", "24小时平均", "80", "150", "μg/m³"),
    ]
    inner = "".join(f"<tr>{''.join(f'<td>{c}</td>' for c in r)}</tr>" for r in rows)
    return f"<table>{_HDR_AIR}{inner}</table>"


def _run(coro):
    return asyncio.run(coro)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# fake catalog/PG layer
# ---------------------------------------------------------------------------


class FakeEnvConn:
    """Routes the exact SQL shapes the FORMAL entries issue (env_rag side).
    Counts every statement so zero-contact promises are testable."""

    def __init__(self, cat: dict):
        self.cat = cat
        self.queries: list[tuple[str, tuple]] = []

    def _table_units(self, doc_id: str) -> list[dict]:
        return self.cat["table_units"].get(doc_id, [])

    async def fetch(self, sql: str, *args):
        self.queries.append(("fetch", sql))
        if "FROM env_rag.documents" in sql and "unknown_fields" in sql:
            wanted = args[2].lower()
            return [
                dict(doc_id=d, **meta, title_confidence=1.0, unknown_fields=[])
                for d, meta in DOCS.items()
                if (meta["self_code"] or "").lower() == wanted
            ]
        if "unit_kind='table'" in sql and "unit_id, caption, heading" in sql:
            return [
                {"unit_id": u["unit_id"], "caption": u["caption"], "heading": u["heading"]}
                for u in self._table_units(args[2])
            ]
        if "unit_kind='table'" in sql:
            return [dict(u) for u in self._table_units(args[2])]
        if "scope_units su" in sql:
            members = self.cat["scope_units"].get(args[2], [])
            return [{"unit_id": m} for m in members]
        if "FROM env_rag.scopes" in sql and "number=$4" in sql:
            return [dict(s) for s in self.cat["scopes"].get((args[2], args[3]), [])]
        if "unit_chunk_links" in sql:
            links = self.cat["links"].get((args[2], args[3]), [])
            return [{"chunk_id": c, "chunk_order": i + 1} for i, c in enumerate(links)]
        return []

    async def fetchrow(self, sql: str, *args):
        self.queries.append(("fetchrow", sql))
        if "corpus_runs" in sql:
            return {"snapshot_id": SNAP, "source_fingerprint": {"value": FP}}
        if "self_code_version FROM env_rag.documents" in sql:
            meta = DOCS.get(args[2])
            return dict(meta) if meta else None
        if "requires_span" in sql:
            return self.cat["units"].get((args[2], args[3]))
        return None

    async def fetchval(self, sql: str, *args):
        self.queries.append(("fetchval", sql))
        if "count(*)" in sql:
            wanted = args[2].lower()
            return sum(1 for meta in DOCS.values() if (meta["self_code"] or "").lower() == wanted)
        if "doc_name FROM env_rag.documents" in sql:
            meta = DOCS.get(args[2])
            return meta["doc_name"] if meta else None
        return None

    async def close(self):
        pass


class FakeAdapter:
    def __init__(self, dsn):
        self.dsn = dsn

    async def get_chunk(self, workspace: str, chunk_id: str):
        row = CHUNKS.get(chunk_id)
        if row is None:
            return {"full_doc_id": "", "content": None}
        return {"full_doc_id": row["doc_id"], "content": row["content"]}


CHUNKS = {
    C1: {"doc_id": DOC_8978, "content": "表 1 第一类污染物 总汞 0.05 mg/L"},
    C2: {"doc_id": DOC_8978, "content": "表 1（续） pH 6~9 色度 50"},
    CP12: {"doc_id": DOC_2012, "content": "GB3095-2012 表 1 PM2.5 35"},
    CP26: {"doc_id": DOC_2026, "content": "GB3095-2026 表 1 PM2.5 25"},
}


def _catalog() -> dict:
    cat = {
        "table_units": {
            DOC_8978: [
                {
                    "unit_id": FRAG1,
                    "unit_order": 1,
                    "table_seq": 1,
                    "caption": "表 1 第一类污染物最高允许排放浓度",
                    "heading": "4",
                    "locator": json.dumps({"blockid": FRAG1}),
                },
                {
                    "unit_id": FRAG2,
                    "unit_order": 2,
                    "table_seq": 2,
                    "caption": "表 1（续）",
                    "heading": "4",
                    "locator": json.dumps({"blockid": FRAG2}),
                },
            ],
            DOC_2012: [
                {
                    "unit_id": "tb-2012-0001",
                    "unit_order": 1,
                    "table_seq": 1,
                    "caption": "表 1 环境空气质量功能区划分",
                    "heading": "3",
                    "locator": json.dumps({"blockid": "tb-2012-0001"}),
                }
            ],
            DOC_2026: [
                {
                    "unit_id": "tb-2026-0001",
                    "unit_order": 1,
                    "table_seq": 1,
                    "caption": "表 1 环境空气质量功能区划分（2026）",
                    "heading": "3",
                    "locator": json.dumps({"blockid": "tb-2026-0001"}),
                }
            ],
        },
        "scope_units": {"d18466:3": ["bl-18466-0001"]},
        "units": {
            (DOC_18466, "bl-18466-0001"): {
                "unit_id": "bl-18466-0001",
                "unit_kind": "block",
                "heading": "3",
                "requires_span": False,
                "content_length": len(PROSE_3),
                "locator": json.dumps({"blockid": "bl-18466-0001"}),
            }
        },
        "scopes": {
            (DOC_18466, "3"): [
                {
                    "scope_id": "d18466:3",
                    "scope_kind": "chapter",
                    "title": "术语和定义",
                    "number": "3",
                    "confirm_status": "confirmed",
                }
            ]
        },
        "links": {
            (DOC_8978, FRAG1): [C1],
            (DOC_8978, FRAG2): [C2],
            (DOC_2012, "tb-2012-0001"): [CP12],
            (DOC_2026, "tb-2026-0001"): [CP26],
        },
    }
    return cat


def _write_parsed(tmp_path: Path) -> None:
    parsed = {
        "gb8978.pdf": {
            "tables": {
                FRAG1: {"content": _TBL1_8978_F1, "caption": "表 1 第一类污染物最高允许排放浓度"},
                FRAG2: {"content": _TBL1_8978_F2, "caption": "表 1（续）"},
            },
            "blocks": [],
        },
        "gb18466.pdf": {
            "tables": {},
            "blocks": [{"type": "content", "blockid": "bl-18466-0001", "content": PROSE_3}],
        },
        "gb3095-2012.pdf": {
            "tables": {
                "tb-2012-0001": {
                    "content": _air_table("35", "15"),
                    "caption": "表 1 环境空气质量功能区划分",
                }
            },
            "blocks": [],
        },
        "gb3095-2026.pdf": {
            "tables": {
                "tb-2026-0001": {
                    "content": _air_table("25", "10"),
                    "caption": "表 1 环境空气质量功能区划分（2026）",
                }
            },
            "blocks": [],
        },
    }
    for name, data in parsed.items():
        pdir = tmp_path / f"{name}.parsed"
        pdir.mkdir()
        (pdir / "x.tables.json").write_text(
            json.dumps({"tables": data["tables"]}, ensure_ascii=False), encoding="utf-8"
        )
        lines = ['{"meta":true}'] + [json.dumps(b, ensure_ascii=False) for b in data["blocks"]]
        (pdir / "x.blocks.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# replay fixtures (real 5.3/5.4 shapes)
# ---------------------------------------------------------------------------


def _identity(**over):
    ident = {
        "matches_frozen": True,
        "problems": [],
        "counts": {"lightrag_llm_cache": 16514, "lightrag_doc_chunks": 5709},
        "source_fingerprint": FP,
        "catalog_active": {"run_id": RUN, "snapshot_id": SNAP},
        "search_active": SEARCH,
        "gold_sha": GOLD_SHA,
        "env_sha": "env-1",
    }
    ident.update(over)
    return ident


def _usable(chunk_id: str, doc_id: str, content: str, discovery="code_exact") -> dict:
    return {
        "workspace": WS,
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "verified": True,
        "content_sha256": _sha(content),
        "content_len": len(content),
        "content": content,
        "paths": [
            {
                "path": "pg",
                "workspace": WS,
                "chunk_id": chunk_id,
                "doc_id": doc_id,
                "heading": content[:20],
                "discovery": discovery,
                "score": {"kind": "pg_ts_rank", "value": 0.01},
            }
        ],
    }


def _fused(
    qid: str,
    question: str,
    usable: list,
    status="ok",
    degraded=None,
    typed=None,
    budget=None,
    targets=None,
):
    if typed is None and usable:
        seen: list[str] = []
        for u in usable:
            if u["doc_id"] not in seen:
                seen.append(u["doc_id"])
        typed = [
            {"target_type": "doc", "workspace": WS, "doc_id": d, "discovery": "code_exact"}
            for d in seen
        ]
    return {
        "query_id": qid,
        "query": question,
        "workspace": WS,
        "pg": {
            "status": status,
            "search_id": SEARCH,
            "catalog_snapshot_id": SNAP,
            "source_snapshot_id": FP,
            "discovery_total": len(usable),
        },
        "targets_resolved": targets or [],
        "typed_targets": typed or [],
        "usable": usable,
        "status": status,
        "degraded": degraded or [],
        "budget": budget or {"limit": 40, "kept": len(usable), "truncated": []},
    }


def _rerank(qid: str, ordered: list, status="ok", degraded=None):
    return {
        "query_id": qid,
        "status": status,
        "degraded": degraded or [],
        "ordered": ordered,
        "typed_targets": [],
        "call": {"status": "success", "latency_ms": 900},
    }


def _ordered(input_index, chunk_id, doc_id, content, score):
    return {
        "input_index": input_index,
        "workspace": WS,
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "content_sha256": _sha(content),
        "rerank_score": score,
        "paths": [],
        "source_order": "rerank",
    }


def _write_replay(tmp_path: Path, fused_list: list, rerank_list: list, ident_over=None):
    ident = _identity(**(ident_over or {}))
    fused = {
        "task": "5.3 two-path candidate fusion (read-only, guarded)",
        "started_at": "2026-10-07T08:03:15+0800",
        "identity_before": ident,
        "identity_after": ident,
        "results": fused_list,
    }
    rerank = {
        "task": "5.4 joint rerank over fused candidates (bounded, recorded)",
        "started_at": "2026-10-07T11:56:13+0800",
        "identity_before": ident,
        "identity_after": ident,
        "results": rerank_list,
    }
    fp = tmp_path / "fusion-runtime-latest.json"
    rp = tmp_path / "rerank-runtime-latest.json"
    fp.write_text(json.dumps(fused, ensure_ascii=False), encoding="utf-8")
    rp.write_text(json.dumps(rerank, ensure_ascii=False), encoding="utf-8")
    return fp, rp


VALUES = {
    "POSTGRES_HOST": "fixture-postgres-host-value-0001",
    "POSTGRES_PORT": "5432",
    "POSTGRES_USER": "fixture-postgres-user-value-0002",
    "POSTGRES_PASSWORD": "fixture-postgres-password-value-0003-not-a-real-secret",
    "POSTGRES_DATABASE": "fixture-postgres-database-value-0004",
    "LLM_BINDING_HOST": "https://llm.invalid",
    "LLM_MODEL": "fixture-answer-model-0005",
    "LLM_BINDING_API_KEY": "fixture-llm-api-key-value-0006-synthetic",
    "EMBEDDING_MODEL": "fixture-embedding-model-0007",
    "EMBEDDING_DIM": "2560",
    "RERANK_MODEL": "fixture-rerank-model-0008",
    "RERANK_BINDING_HOST": "https://rr.invalid",
    "RERANK_BINDING_API_KEY": "fixture-rerank-api-key-value-0009-synthetic",
}

Q_TABLE = "GB 8978-1996 表 1（第一类污染物）共列出哪些污染物及其限值？逐行列出"
Q_FACT = "GB 8978-1996 表 1 中总汞的最高允许排放浓度是多少？"
Q_FACT_MISS = "GB 8978-1996 表 1 中总铊的最高允许排放浓度是多少？"
Q_PROSE = "GB 18466-2005 中 3 章定义了哪些术语？逐项列出编号和中文名。"
Q_PROSE_RANGE = "GB 18466-2005 的 3.1 至 3.5 分别定义了哪些术语？逐条列出"
Q_FILE = "库内有哪些 GB 8978 标准的文档？列出文件名和版本年份。"
Q_SYN = "对比 GB 3095-2012 与 GB 3095-2026 表 1 中 PM2.5 的年平均二级限值。"


def _install(monkeypatch, tmp_path, questions, counters=()):
    cat = _catalog()
    conn = FakeEnvConn(cat)
    _write_parsed(tmp_path)
    (tmp_path / "gold.json").write_text(
        json.dumps(
            {
                "questions": questions,
                "counter_examples": [
                    {
                        "counter_id": c.get("counter_id") or c["query_id"],
                        "question": c["question"],
                        "type": c.get("type"),
                    }
                    for c in counters
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(an, "GOLD_PATH", tmp_path / "gold.json")
    monkeypatch.setattr(an, "verify_gold_guard", lambda p: GOLD_SHA)

    def guard(values, workspace):
        if any(k in values for k in ("QDRANT_WORKSPACE", "NEO4J_WORKSPACE", "POSTGRES_WORKSPACE")):
            raise an.AdapterError("workspace override env forbidden")

    monkeypatch.setattr(an, "verify_config_guard", guard)
    calls = {"identity": 0}

    async def capture(values):
        calls["identity"] += 1
        return {
            "identity": {
                "public_counts": {"lightrag_llm_cache": 16514, "lightrag_doc_chunks": 5709},
                "catalog_active": {"run_id": RUN, "snapshot_id": SNAP},
                "source_fingerprint": FP,
                "search_active": SEARCH,
                "gold_sha": GOLD_SHA,
                "env_sha": "env-1",
            },
            "problems": [],
            "matches_frozen": True,
        }

    monkeypatch.setattr(an, "_capture_identity", capture)

    async def current(conn_, **kwargs):
        return {"state": "current", "active_snapshot_id": SNAP, "stored_fingerprint": FP}

    import env_rag_final.catalog.builder as builder
    import env_rag_final.catalog.source as source_mod
    import env_rag_final.enumerate_.table_enum as table_enum_mod
    import env_rag_final.search.expand as expand_mod

    monkeypatch.setattr(builder, "check_stale", current)
    monkeypatch.setattr(table_enum_mod, "check_stale", current)

    async def no_live_fp(conn_, workspace):
        return ""

    monkeypatch.setattr(builder, "_live_source_fingerprint", no_live_fp)

    async def fresh(conn_, workspace, parsed_root=None):
        return {"state": "current", "catalog_snapshot_id": SNAP, "search_id": SEARCH}

    monkeypatch.setattr(expand_mod, "check_search_stale", fresh)
    monkeypatch.setattr(source_mod, "SourceAdapter", FakeAdapter)
    monkeypatch.setattr(audit_identity, "PARSED_ROOT", tmp_path)

    def boom(**kwargs):
        raise AssertionError("answer must never open its own connection in tests")

    monkeypatch.setattr(an.asyncpg, "connect", boom)
    calls["conn"] = conn
    calls["cat"] = cat
    calls["queries"] = lambda: len(conn.queries)
    return conn, calls


def _gold_q(qid, question, category):
    return {"query_id": qid, "question": question, "workspace": WS, "category": category}


# ---------------------------------------------------------------------------
# class 1: rerank priority never truncates membership — continuation fragment
# ranked LAST, discovery carried one chunk, yet all 13 rows + independent
# raw-row re-reads
# ---------------------------------------------------------------------------


def test_continuation_low_rank_full_membership_and_row_rereads(monkeypatch, tmp_path):
    conn, calls = _install(monkeypatch, tmp_path, [_gold_q("q-table", Q_TABLE, "table_enum")])
    fp, rp = _write_replay(
        tmp_path,
        [
            _fused(
                "q-table",
                Q_TABLE,
                [
                    _usable(C1, DOC_8978, CHUNKS[C1]["content"]),
                    _usable(C2, DOC_8978, CHUNKS[C2]["content"]),
                ],
            )
        ],
        [
            # continuation chunk deliberately LAST with the lowest score
            _rerank(
                "q-table",
                [
                    _ordered(0, C1, DOC_8978, CHUNKS[C1]["content"], 0.95),
                    _ordered(1, C2, DOC_8978, CHUNKS[C2]["content"], 0.02),
                ],
            )
        ],
    )
    report = _run(
        an.run_answer(
            tmp_path / "out",
            ["q-table"],
            rerank_report_path=rp,
            fused_report_path=fp,
            values=VALUES,
            conn=conn,
        )
    )
    res = report["results"][0]
    assert res["coverage_status"] == "complete"
    assert report["model_calls_used"] == 0
    assert len(res["answer"]["items"]) == 13
    # the continuation fragment's rows are present with their OWN fragment identity
    frag2_rows = [
        it for it in res["answer"]["items"] if (it.get("citation") or {}).get("table_id") == FRAG2
    ]
    assert [r["cells"][0] for r in frag2_rows] == ["12", "13"]
    assert all(it["citation_reverified"] for it in res["answer"]["items"])
    assert res["reverification"]["items_checked"] == 13
    assert res["reverification"]["problems"] == []
    # scope priority is the rerank order (C1 first), never a truncation
    priority = res["scope_selection"]["priority"]
    assert priority[0]["doc_id"] == DOC_8978
    # header/units/footnotes retained (matrix: 表头/单位/注脚)
    assert res["expansions"][0]["warnings"], "table_structure warning carried"
    assert res["replay"]["rerank_status"] == "ok"
    assert res["replay"]["rerank_ordered_chunks"] == 2


def test_fact_row_located_from_full_membership_with_unit_and_caption(monkeypatch, tmp_path):
    conn, calls = _install(monkeypatch, tmp_path, [_gold_q("q-fact", Q_FACT, "fact")])
    fp, rp = _write_replay(
        tmp_path,
        [_fused("q-fact", Q_FACT, [_usable(C1, DOC_8978, CHUNKS[C1]["content"])])],
        [_rerank("q-fact", [_ordered(0, C1, DOC_8978, CHUNKS[C1]["content"], 0.9)])],
    )
    report = _run(
        an.run_answer(
            tmp_path / "out",
            ["q-fact"],
            rerank_report_path=rp,
            fused_report_path=fp,
            values=VALUES,
            conn=conn,
        )
    )
    res = report["results"][0]
    items = res["answer"]["items"]
    assert res["coverage_status"] == "complete"
    assert len(items) == 1, "only the 总汞 row survives the question-term selection"
    assert items[0]["cells"][0:2] == ["1", "总汞"]
    assert items[0]["citation_reverified"] is True
    assert items[0]["caption"] == "表 1 第一类污染物最高允许排放浓度"
    # selection was made from the QUESTION terms over the full membership —
    # never from gold text
    assert "总汞" in res["answer"]["selection"]["terms"]


def test_fact_target_not_located_is_partial_not_guessed(monkeypatch, tmp_path):
    conn, _ = _install(monkeypatch, tmp_path, [_gold_q("q-fact-miss", Q_FACT_MISS, "fact")])
    fp, rp = _write_replay(
        tmp_path,
        [_fused("q-fact-miss", Q_FACT_MISS, [_usable(C1, DOC_8978, CHUNKS[C1]["content"])])],
        [_rerank("q-fact-miss", [_ordered(0, C1, DOC_8978, CHUNKS[C1]["content"], 0.9)])],
    )
    report = _run(
        an.run_answer(
            tmp_path / "out",
            ["q-fact-miss"],
            rerank_report_path=rp,
            fused_report_path=fp,
            values=VALUES,
            conn=conn,
        )
    )
    res = report["results"][0]
    assert res["coverage_status"] == "partial"
    assert res["answer"]["items"] == []
    assert "not located" in res["answer"]["not_located"]


# ---------------------------------------------------------------------------
# class 2: prose clause boundaries — full scope read, missing clause stays
# partial, never an empty complete
# ---------------------------------------------------------------------------


def test_prose_chapter_scope_items_verified(monkeypatch, tmp_path):
    conn, _ = _install(monkeypatch, tmp_path, [_gold_q("q-prose", Q_PROSE, "prose_enum")])
    fp, rp = _write_replay(
        tmp_path,
        [
            _fused(
                "q-prose",
                Q_PROSE,
                [
                    _usable(
                        "chunk-18466-001", DOC_18466, "3 术语和定义 3.1 医疗机构污水", "code_exact"
                    )
                ],
            )
        ],
        [],  # no rerank generation for this query id
    )
    report = _run(
        an.run_answer(
            tmp_path / "out",
            ["q-prose"],
            rerank_report_path=rp,
            fused_report_path=fp,
            values=VALUES,
            conn=conn,
        )
    )
    res = report["results"][0]
    assert res["coverage_status"] == "complete"
    assert [it["clause"] for it in res["answer"]["items"]] == ["3.1", "3.2", "3.3", "3.4"]
    assert all(
        it["citation_verified"] and it["citation_reverified"] for it in res["answer"]["items"]
    )
    # rerank absent is recorded honestly and never fabricates scores
    assert res["replay"]["rerank_status"] == "absent"
    assert res["replay"]["rerank_ordered_chunks"] == 0
    assert any("no rerank replay" in f for f in res["flags"])


def test_prose_missing_requested_clause_stays_partial(monkeypatch, tmp_path):
    conn, _ = _install(monkeypatch, tmp_path, [_gold_q("q-prose-r", Q_PROSE_RANGE, "prose_enum")])
    fp, rp = _write_replay(
        tmp_path,
        [
            _fused(
                "q-prose-r",
                Q_PROSE_RANGE,
                [_usable("chunk-18466-001", DOC_18466, "3 术语和定义", "code_exact")],
            )
        ],
        [_rerank("q-prose-r", [_ordered(0, "chunk-18466-001", DOC_18466, "3 术语和定义", 0.8)])],
    )
    report = _run(
        an.run_answer(
            tmp_path / "out",
            ["q-prose-r"],
            rerank_report_path=rp,
            fused_report_path=fp,
            values=VALUES,
            conn=conn,
        )
    )
    res = report["results"][0]
    assert res["coverage_status"] == "partial"
    assert any("3.5" in f and "missing" in f for f in res["flags"])
    assert len(res["answer"]["items"]) == 4, "the four found clauses are still delivered"


# ---------------------------------------------------------------------------
# class 3: file enumeration — FULL paged set, independent versions
# ---------------------------------------------------------------------------


def test_file_enum_full_paged_set_and_versions_are_independent_sources(monkeypatch, tmp_path):
    conn, _ = _install(monkeypatch, tmp_path, [_gold_q("q-file", Q_FILE, "file_enum")])
    fp, rp = _write_replay(
        tmp_path,
        [_fused("q-file", Q_FILE, [_usable(C1, DOC_8978, CHUNKS[C1]["content"])])],
        [_rerank("q-file", [_ordered(0, C1, DOC_8978, CHUNKS[C1]["content"], 0.7)])],
    )
    report = _run(
        an.run_answer(
            tmp_path / "out",
            ["q-file"],
            rerank_report_path=rp,
            fused_report_path=fp,
            values=VALUES,
            conn=conn,
        )
    )
    res = report["results"][0]
    names = {it["doc_name"] for it in res["answer"]["items"]}
    assert names == {"gb8978.pdf", "gb8978-1989.pdf"}, "the whole matching set, not top-k"
    assert {it["self_code_version"] for it in res["answer"]["items"]} == {"1996", "1989"}
    doc_ids = [it["doc_id"] for it in res["answer"]["items"]]
    assert len(doc_ids) == len(set(doc_ids)), "same-code versions are never merged"
    assert res["coverage_status"] == "complete"
    enum_stage = res["expansions"][-1]
    assert enum_stage["members_total"] == enum_stage["members_processed"] == 2


# ---------------------------------------------------------------------------
# class 4: budget / empty / stale / degraded replay semantics
# ---------------------------------------------------------------------------


def test_fused_stale_replay_never_expanded_and_never_complete(monkeypatch, tmp_path):
    conn, _ = _install(monkeypatch, tmp_path, [_gold_q("q-table", Q_TABLE, "table_enum")])
    fp, rp = _write_replay(
        tmp_path, [_fused("q-table", Q_TABLE, [], status="stale")], [_rerank("q-table", [])]
    )
    report = _run(
        an.run_answer(
            tmp_path / "out",
            ["q-table"],
            rerank_report_path=rp,
            fused_report_path=fp,
            values=VALUES,
            conn=conn,
        )
    )
    res = report["results"][0]
    assert res["coverage_status"] == "stale"
    assert res["expansions"] == []
    # only the identity guard read happened — no scope/catalog expansion reads
    assert not any("scopes" in sql or "scope_units" in sql for _kind, sql in conn.queries)


def test_rerank_degraded_replay_allows_explicit_degraded_answer(monkeypatch, tmp_path):
    conn, _ = _install(monkeypatch, tmp_path, [_gold_q("q-table", Q_TABLE, "table_enum")])
    fp, rp = _write_replay(
        tmp_path,
        [
            _fused(
                "q-table",
                Q_TABLE,
                [_usable(C1, DOC_8978, CHUNKS[C1]["content"])],
                degraded=["vector coverage incomplete → weight fallback (5.2 semantics)"],
            )
        ],
        [
            _rerank(
                "q-table",
                [
                    {
                        "input_index": 0,
                        "workspace": WS,
                        "chunk_id": C1,
                        "doc_id": DOC_8978,
                        "content_sha256": _sha(CHUNKS[C1]["content"]),
                        "rerank_score": None,
                        "paths": [],
                        "source_order": "fusion-fallback",
                    }
                ],
                status="degraded",
                degraded=["rerank call failed; original fusion order kept, NO fabricated scores"],
            )
        ],
    )
    report = _run(
        an.run_answer(
            tmp_path / "out",
            ["q-table"],
            rerank_report_path=rp,
            fused_report_path=fp,
            values=VALUES,
            conn=conn,
        )
    )
    res = report["results"][0]
    assert res["replay"]["rerank_status"] == "degraded"
    assert any("never a claimed rerank success" in f for f in res["flags"])
    # full sources present → the answer itself may be explicit-degraded complete
    assert res["coverage_status"] == "complete"
    assert len(res["answer"]["items"]) == 13


def test_fusion_budget_truncation_can_never_be_complete(monkeypatch, tmp_path):
    conn, _ = _install(monkeypatch, tmp_path, [_gold_q("q-table", Q_TABLE, "table_enum")])
    fp, rp = _write_replay(
        tmp_path,
        [
            _fused(
                "q-table",
                Q_TABLE,
                [_usable(C1, DOC_8978, CHUNKS[C1]["content"])],
                budget={"limit": 1, "kept": 1, "truncated": [C2]},
            )
        ],
        [_rerank("q-table", [_ordered(0, C1, DOC_8978, CHUNKS[C1]["content"], 0.9)])],
    )
    report = _run(
        an.run_answer(
            tmp_path / "out",
            ["q-table"],
            rerank_report_path=rp,
            fused_report_path=fp,
            values=VALUES,
            conn=conn,
        )
    )
    res = report["results"][0]
    assert res["coverage_status"] == "partial"
    assert any("NOT complete" in f for f in res["flags"])


def test_counter_replay_missing_is_missing_not_complete(monkeypatch, tmp_path):
    conn, _ = _install(
        monkeypatch,
        tmp_path,
        [],
        counters=[
            {"counter_id": "neg-x", "question": "库里不存在的标准 GB0000-0000", "type": "missing"}
        ],
    )
    fp, rp = _write_replay(
        tmp_path,
        [
            {
                "query_id": "neg-x",
                "query": "库里不存在的标准 GB0000-0000",
                "workspace": WS,
                "pg": {},
                "typed_targets": [],
                "usable": [],
                "status": "missing",
                "degraded": [],
                "budget": {},
            }
        ],
        [],
    )
    report = _run(
        an.run_answer(
            tmp_path / "out",
            ["neg-x"],
            rerank_report_path=rp,
            fused_report_path=fp,
            values=VALUES,
            conn=conn,
        )
    )
    res = report["results"][0]
    assert res["coverage_status"] == "missing"
    assert res["answer"] is None or not (res["answer"].get("items") or [])


# ---------------------------------------------------------------------------
# class 5: synthesis with the ONE answer model call and strict claim checks
# ---------------------------------------------------------------------------


def _syn_replay(tmp_path):
    return _write_replay(
        tmp_path,
        [
            _fused(
                "q-syn",
                Q_SYN,
                [
                    _usable(CP12, DOC_2012, CHUNKS[CP12]["content"]),
                    _usable(CP26, DOC_2026, CHUNKS[CP26]["content"]),
                ],
            )
        ],
        [],
    )


def _model_transport(content_obj_or_str, status=200, sink=None):
    content = (
        content_obj_or_str
        if isinstance(content_obj_or_str, str)
        else json.dumps(content_obj_or_str, ensure_ascii=False)
    )
    body = {"choices": [{"message": {"content": content}}]}

    async def transport(url, headers, payload):
        if sink is not None:
            sink.append((url, headers, payload))
        return SimpleNamespace(status_code=status, json=lambda: body)

    return transport


_GOOD_SYN = {
    "summary": "2026 版二级限值更严。",
    "items": [
        {
            "edition": "gb3095-2012",
            "claim": "2012版PM2.5年平均二级限值为35μg/m³",
            "quote": "PM2.5 | 年平均 | 15 | 35",
        },
        {
            "edition": "gb3095-2026",
            "claim": "2026版PM2.5年平均二级限值收严为25μg/m³",
            "quote": "PM2.5 | 年平均 | 10 | 25",
        },
    ],
}


def test_synthesis_one_model_call_bound_claims_and_receipt(monkeypatch, tmp_path):
    conn, _ = _install(monkeypatch, tmp_path, [_gold_q("q-syn", Q_SYN, "synthesis")])
    fp, rp = _syn_replay(tmp_path)
    sink = []
    report = _run(
        an.run_answer(
            tmp_path / "out",
            ["q-syn"],
            rerank_report_path=rp,
            fused_report_path=fp,
            values=VALUES,
            conn=conn,
            transport=_model_transport(_GOOD_SYN, sink=sink),
        )
    )
    assert report["model_calls_used"] == 1
    assert len(sink) == 1, "exactly ONE exchange"
    res = report["results"][0]
    assert res["coverage_status"] == "complete"
    claims = res["answer"]["items"]
    assert len(claims) == 2
    # edition identity is BOUND BY THE APPLICATION, not model prose
    by_doc = {c["edition"]["doc_id"]: c for c in claims}
    assert set(by_doc) == {DOC_2012, DOC_2026}
    assert by_doc[DOC_2012]["edition"]["snapshot_id"] == SNAP
    assert all(c["citation_verified"] for c in claims)
    # the EXACT context sent to the model is preserved (hashed + quoted inside)
    assert res["model"]["context_sha256"]
    sent = sink[0][2]["messages"][1]["content"]
    assert "PM2.5 | 年平均 | 15 | 35" in sent
    assert sink[0][1]["Authorization"].endswith("synthetic")  # header not persisted
    runtime = (tmp_path / "out" / "answer-runtime-latest.json").read_text()
    assert "Bearer" not in runtime


def test_synthesis_missing_edition_is_incomplete_zero_calls(monkeypatch, tmp_path):
    conn, _ = _install(monkeypatch, tmp_path, [_gold_q("q-syn", Q_SYN, "synthesis")])
    # replay carries ONLY the 2012 document — the comparison is short one edition
    fp, rp = _write_replay(
        tmp_path,
        [_fused("q-syn", Q_SYN, [_usable(CP12, DOC_2012, CHUNKS[CP12]["content"])])],
        [],
    )
    sink = []
    report = _run(
        an.run_answer(
            tmp_path / "out",
            ["q-syn"],
            rerank_report_path=rp,
            fused_report_path=fp,
            values=VALUES,
            conn=conn,
            transport=_model_transport(_GOOD_SYN, sink=sink),
        )
    )
    assert report["model_calls_used"] == 0
    assert sink == []
    res = report["results"][0]
    assert res["coverage_status"] == "partial"
    assert res["model"]["status"] == "incomplete_conditions"
    assert "gb3095-2026" in res["model"]["failure"]


def test_synthesis_second_query_refused_by_budget(monkeypatch, tmp_path):
    q2 = "对比 GB 3095-2012 与 GB 3095-2026 表 1 中 PM10 的年平均二级限值。"
    conn, _ = _install(
        monkeypatch,
        tmp_path,
        [_gold_q("q-syn", Q_SYN, "synthesis"), _gold_q("q-syn2", q2, "synthesis")],
    )
    fp, rp = _write_replay(
        tmp_path,
        [
            _fused(
                "q-syn",
                Q_SYN,
                [
                    _usable(CP12, DOC_2012, CHUNKS[CP12]["content"]),
                    _usable(CP26, DOC_2026, CHUNKS[CP26]["content"]),
                ],
            ),
            _fused(
                "q-syn2",
                q2,
                [
                    _usable(CP12, DOC_2012, CHUNKS[CP12]["content"]),
                    _usable(CP26, DOC_2026, CHUNKS[CP26]["content"]),
                ],
            ),
        ],
        [],
    )
    report = _run(
        an.run_answer(
            tmp_path / "out",
            ["q-syn", "q-syn2"],
            rerank_report_path=rp,
            fused_report_path=fp,
            values=VALUES,
            conn=conn,
            transport=_model_transport(_GOOD_SYN),
        )
    )
    assert report["model_calls_used"] == 1
    first, second = report["results"]
    assert first["coverage_status"] == "complete"
    assert second["model"]["status"] == "model_budget_refused"
    assert second["coverage_status"] == "partial"


def test_synthesis_fabricated_or_wrong_year_claim_is_refused(monkeypatch, tmp_path):
    conn, _ = _install(monkeypatch, tmp_path, [_gold_q("q-syn", Q_SYN, "synthesis")])
    fp, rp = _syn_replay(tmp_path)
    bad = {
        "items": [
            {
                "edition": "gb3095-2012",
                "claim": "2012版PM2.5年平均二级限值为44μg/m³",  # number NOT in the quote
                "quote": "PM2.5 | 年平均 | 15 | 35",
            }
        ]
    }
    report = _run(
        an.run_answer(
            tmp_path / "out",
            ["q-syn"],
            rerank_report_path=rp,
            fused_report_path=fp,
            values=VALUES,
            conn=conn,
            transport=_model_transport(bad),
        )
    )
    res = report["results"][0]
    assert res["coverage_status"] == "partial"
    assert res["model"]["status"] == "model_failure"
    assert any(
        "value tokens" in p or "not supported by the quote" in p
        for p in res["model"]["verification_problems"]
    )


def test_synthesis_http_failure_keeps_receipt_no_fabricated_answer(monkeypatch, tmp_path):
    conn, _ = _install(monkeypatch, tmp_path, [_gold_q("q-syn", Q_SYN, "synthesis")])
    fp, rp = _syn_replay(tmp_path)
    report = _run(
        an.run_answer(
            tmp_path / "out",
            ["q-syn"],
            rerank_report_path=rp,
            fused_report_path=fp,
            values=VALUES,
            conn=conn,
            transport=_model_transport({"irrelevant": 1}, status=401),
        )
    )
    res = report["results"][0]
    assert res["coverage_status"] == "partial"
    assert res["model"]["call"]["status"] == "failure"
    assert res["model"]["call"]["error"] == "http_401"
    assert res["model"]["raw_response"] is None
    assert res["answer"]["items"] == []


def test_terminal_sanitizes_configured_secrets_in_messages(monkeypatch, tmp_path):
    conn, _ = _install(monkeypatch, tmp_path, [_gold_q("q-syn", Q_SYN, "synthesis")])
    fp, rp = _syn_replay(tmp_path)
    leaky = {
        "items": [
            {
                "edition": "gb3095-2012",
                "claim": "限值35（旁白 " + VALUES["LLM_BINDING_API_KEY"] + "）",
                "quote": "年平均 | 15 | 35",
            }
        ]
    }
    report = _run(
        an.run_answer(
            tmp_path / "out",
            ["q-syn"],
            rerank_report_path=rp,
            fused_report_path=fp,
            values=VALUES,
            conn=conn,
            transport=_model_transport(leaky),
        )
    )
    body = (tmp_path / "out" / "answer-runtime-latest.json").read_text(encoding="utf-8")
    assert VALUES["LLM_BINDING_API_KEY"] not in body
    assert "<redacted>" in body
    # the leaked claim itself also fails numeric verification — refusal kept
    assert report["results"][0]["model"]["status"] == "model_failure"


# ---------------------------------------------------------------------------
# class 6: pre-flight ordering, generation binding, failure terminals
# ---------------------------------------------------------------------------


def test_unknown_query_id_terminal_before_any_identity_capture(monkeypatch, tmp_path):
    conn, calls = _install(monkeypatch, tmp_path, [_gold_q("q-table", Q_TABLE, "table_enum")])
    fp, rp = _write_replay(tmp_path, [], [])
    try:
        _run(
            an.run_answer(
                tmp_path / "out",
                ["does-not-exist"],
                rerank_report_path=rp,
                fused_report_path=fp,
                values=VALUES,
                conn=conn,
            )
        )
        raise AssertionError("must refuse an unknown query id")
    except an.AdapterError as exc:
        assert "does-not-exist" in str(exc)
    assert calls["identity"] == 0
    assert conn.queries == []
    failure_files = list((tmp_path / "out").glob("answer-runtime-*.json"))
    assert failure_files
    body = json.loads(failure_files[0].read_text())
    assert body["failure"]["stage"] == "unknown-query-id"
    assert body["failure_service_records"]["note"].startswith("pre-flight rejection")


def test_replay_generation_identity_mismatch_refused_before_reads(monkeypatch, tmp_path):
    conn, calls = _install(monkeypatch, tmp_path, [_gold_q("q-table", Q_TABLE, "table_enum")])
    fp, rp = _write_replay(
        tmp_path,
        [_fused("q-table", Q_TABLE, [_usable(C1, DOC_8978, CHUNKS[C1]["content"])])],
        [],
        ident_over={"source_fingerprint": "fp-FROM-A-DIFFERENT-GENERATION"},
    )
    try:
        _run(
            an.run_answer(
                tmp_path / "out",
                ["q-table"],
                rerank_report_path=rp,
                fused_report_path=fp,
                values=VALUES,
                conn=conn,
            )
        )
        raise AssertionError("must refuse a replay from another generation")
    except an.AdapterError as exc:
        assert "generation" in str(exc)
    assert calls["identity"] == 1  # the guard read happened
    # but NOT a single catalog/expansion read
    assert conn.queries == []


def test_workspace_override_rejected_before_identity(monkeypatch, tmp_path):
    conn, calls = _install(monkeypatch, tmp_path, [_gold_q("q-table", Q_TABLE, "table_enum")])
    fp, rp = _write_replay(
        tmp_path,
        [_fused("q-table", Q_TABLE, [_usable(C1, DOC_8978, CHUNKS[C1]["content"])])],
        [],
    )
    bad = dict(VALUES, QDRANT_WORKSPACE="override")
    try:
        _run(
            an.run_answer(
                tmp_path / "out",
                ["q-table"],
                rerank_report_path=rp,
                fused_report_path=fp,
                values=bad,
                conn=conn,
            )
        )
        raise AssertionError("workspace override must be rejected")
    except an.AdapterError as exc:
        assert "override" in str(exc)
    assert calls["identity"] == 0


def test_replay_query_binding_mismatch_raises_with_terminal(monkeypatch, tmp_path):
    conn, calls = _install(monkeypatch, tmp_path, [_gold_q("q-table", Q_TABLE, "table_enum")])
    fp, rp = _write_replay(
        tmp_path,
        [
            _fused(
                "q-table",
                "另一道题目的回放",  # different question — must never feed this query
                [_usable(C1, DOC_8978, CHUNKS[C1]["content"])],
            )
        ],
        [],
    )
    try:
        _run(
            an.run_answer(
                tmp_path / "out",
                ["q-table"],
                rerank_report_path=rp,
                fused_report_path=fp,
                values=VALUES,
                conn=conn,
            )
        )
        raise AssertionError("binding mismatch must refuse")
    except an.AdapterError as exc:
        assert "binding mismatch" in str(exc)
    body = json.loads((tmp_path / "out" / "answer-runtime-latest.json").read_text())
    assert body["failure"]["stage"] == "answer"
    assert body["failure_service_records"]["call_records"] == []
    assert "binding mismatch" in body["failure"]["detail"]


def test_resolved_target_missing_from_discovery_is_still_fully_read(monkeypatch, tmp_path):
    # matrix class 1's other half: even if discovery/top-k carried ONLY the
    # continuation chunk (or another document), the resolved target document
    # is registered for the FULL membership read
    conn, _ = _install(monkeypatch, tmp_path, [_gold_q("q-table", Q_TABLE, "table_enum")])
    fp, rp = _write_replay(
        tmp_path,
        [
            _fused(
                "q-table",
                Q_TABLE,
                [_usable(C2, DOC_8978, CHUNKS[C2]["content"], "keyword_and")],
                typed=[
                    {
                        "target_type": "table_unit",
                        "workspace": WS,
                        "doc_id": DOC_8978,
                        "unit_id": FRAG1,
                        "table_id": FRAG1,
                    }
                ],
                targets=[{"code": "GB8978", "version": "1996", "docs": [DOC_8978]}],
            )
        ],
        [_rerank("q-table", [_ordered(0, C2, DOC_8978, CHUNKS[C2]["content"], 0.9)])],
    )
    report = _run(
        an.run_answer(
            tmp_path / "out",
            ["q-table"],
            rerank_report_path=rp,
            fused_report_path=fp,
            values=VALUES,
            conn=conn,
        )
    )
    res = report["results"][0]
    assert res["coverage_status"] == "complete"
    assert len(res["answer"]["items"]) == 13
    assert res["scope_selection"]["selected_docs"] == [DOC_8978]
    assert not any("absent from the replayed candidates" in f for f in res["flags"])


def test_noise_candidate_document_cannot_degrade_selected_scope(monkeypatch, tmp_path):
    # an incidental candidate from a document WITHOUT the requested logical
    # table is recorded but never degrades/ambiguates the selected scope
    conn, _ = _install(monkeypatch, tmp_path, [_gold_q("q-table", Q_TABLE, "table_enum")])
    fp, rp = _write_replay(
        tmp_path,
        [
            _fused(
                "q-table",
                Q_TABLE,
                [
                    _usable(C1, DOC_8978, CHUNKS[C1]["content"]),
                    _usable(
                        "chunk-8978old-001", DOC_8978_OLD, "旧版污水标准 任意内容", "keyword_or"
                    ),
                ],
                typed=[
                    {
                        "target_type": "doc",
                        "workspace": WS,
                        "doc_id": DOC_8978,
                        "discovery": "code_exact",
                    }
                ],
                targets=[{"code": "GB8978", "version": "1996", "docs": [DOC_8978]}],
            )
        ],
        [_rerank("q-table", [_ordered(0, C1, DOC_8978, CHUNKS[C1]["content"], 0.9)])],
    )
    report = _run(
        an.run_answer(
            tmp_path / "out",
            ["q-table"],
            rerank_report_path=rp,
            fused_report_path=fp,
            values=VALUES,
            conn=conn,
        )
    )
    res = report["results"][0]
    assert res["coverage_status"] == "complete"
    assert len(res["answer"]["items"]) == 13
    unsel = [e for e in res["expansions"] if e.get("selected") is False]
    assert unsel and unsel[0]["doc_id"] == DOC_8978_OLD
    assert any("cannot degrade the selected scope" in f for f in res["flags"])
    # the noise document never contributed items and was never re-verified
    assert res["reverification"]["items_checked"] == 13


def test_ambiguous_table_two_replay_keeps_ambiguous_never_complete(monkeypatch, tmp_path):
    # a second same-number logical table in another chapter keeps the formal
    # ambiguous outcome (原表2歧义 preserved)
    conn, _ = _install(
        monkeypatch,
        tmp_path,
        [_gold_q("q-t2", "GB 8978-1996 表 2 的限值有哪些？逐行列出", "table_enum")],
    )
    cat = conn.cat
    cat["table_units"][DOC_8978] += [
        {
            "unit_id": "tb-8978-0010",
            "unit_order": 3,
            "table_seq": 3,
            "caption": "表 2 第二类污染物最高允许排放浓度",
            "heading": "4",
            "locator": json.dumps({"blockid": "tb-8978-0010"}),
        },
        {
            "unit_id": "tb-8978-0011",
            "unit_order": 4,
            "table_seq": 4,
            "caption": "表 2 修订版限值",
            "heading": "5",
            "locator": json.dumps({"blockid": "tb-8978-0011"}),
        },
    ]
    (tmp_path / "gb8978.pdf.parsed" / "x.tables.json").write_text(
        json.dumps(
            {
                "tables": {
                    FRAG1: {"content": _TBL1_8978_F1},
                    FRAG2: {"content": _TBL1_8978_F2},
                    "tb-8978-0010": {
                        "content": "<table>"
                        + _HDR
                        + "<tr><td>1</td><td>pH</td><td>6~9</td><td></td></tr></table>"
                    },
                    "tb-8978-0011": {
                        "content": "<table>"
                        + _HDR
                        + "<tr><td>1</td><td>pH</td><td>6~9</td><td></td></tr></table>"
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    fp, rp = _write_replay(
        tmp_path,
        [
            _fused(
                "q-t2",
                "GB 8978-1996 表 2 的限值有哪些？逐行列出",
                [_usable(C1, DOC_8978, CHUNKS[C1]["content"])],
            )
        ],
        [],
    )
    report = _run(
        an.run_answer(
            tmp_path / "out",
            ["q-t2"],
            rerank_report_path=rp,
            fused_report_path=fp,
            values=VALUES,
            conn=conn,
        )
    )
    res = report["results"][0]
    assert res["coverage_status"] == "ambiguous"
    assert res["answer"]["items"] == []


def test_synthesis_readonly_check_without_model_authorization_is_zero_calls(monkeypatch, tmp_path):
    # the delivery protocol: first verify both editions' scopes/citations
    # READ-ONLY (allow_model=False) — synthesis stays explicitly incomplete,
    # never answered from gold, with 0 model calls
    conn, _ = _install(monkeypatch, tmp_path, [_gold_q("q-syn", Q_SYN, "synthesis")])
    fp, rp = _syn_replay(tmp_path)
    sink = []
    report = _run(
        an.run_answer(
            tmp_path / "out",
            ["q-syn"],
            rerank_report_path=rp,
            fused_report_path=fp,
            values=VALUES,
            conn=conn,
            transport=_model_transport(_GOOD_SYN, sink=sink),
            allow_model=False,
        )
    )
    assert report["model_calls_used"] == 0
    assert sink == []
    res = report["results"][0]
    assert res["coverage_status"] == "partial"
    assert res["model"]["status"] == "model_not_authorized"
    assert len(res["model"]["sections"]) == 2  # both editions' read context verified
    assert all(s["item_count"] == 3 for s in res["model"]["sections"])


# ---------------------------------------------------------------------------
# rev-1 additions (answer-review r1 A1–A3): required positives via owning entry
# ---------------------------------------------------------------------------


def test_fact_unit_from_source_cell_is_complete_with_unit_fields(monkeypatch, tmp_path):
    conn, _ = _install(monkeypatch, tmp_path, [_gold_q("q-fact", Q_FACT, "fact")])
    fp, rp = _write_replay(
        tmp_path,
        [_fused("q-fact", Q_FACT, [_usable(C1, DOC_8978, CHUNKS[C1]["content"])])],
        [_rerank("q-fact", [_ordered(0, C1, DOC_8978, CHUNKS[C1]["content"], 0.9)])],
    )
    report = _run(
        an.run_answer(
            tmp_path / "out",
            ["q-fact"],
            rerank_report_path=rp,
            fused_report_path=fp,
            values=VALUES,
            conn=conn,
        )
    )
    res = report["results"][0]
    assert res["coverage_status"] == "complete"
    it = res["answer"]["items"][0]
    assert it["unit_status"] == "source_unit" and it["unit"] == "mg/L"
    assert res["answer"]["unit_blockers"] == []


def test_fact_dimensionless_declared_by_source_is_complete(monkeypatch, tmp_path):
    # 无量纲 judgment criterion = the READ source declares it explicitly
    conn, _ = _install(
        monkeypatch,
        tmp_path,
        [_gold_q("q-ph", "GB 8978-1996 表 8 中臭气浓度指标值是多少？", "fact")],
    )
    cat = conn.cat
    cat["table_units"][DOC_8978].append(
        {
            "unit_id": "tb-8978-0008",
            "unit_order": 5,
            "table_seq": 5,
            "caption": "表 8 无量纲控制指标",
            "heading": "4",
            "locator": json.dumps({"blockid": "tb-8978-0008"}),
        }
    )
    tables = json.loads((tmp_path / "gb8978.pdf.parsed" / "x.tables.json").read_text())["tables"]
    tables["tb-8978-0008"] = {
        "content": "<table><tr><th>序号</th><th>指标</th><th>值</th></tr>"
        "<tr><td>1</td><td>臭气浓度</td><td>20</td></tr></table>",
        "caption": "表 8 无量纲控制指标",
    }
    (tmp_path / "gb8978.pdf.parsed" / "x.tables.json").write_text(
        json.dumps({"tables": tables}, ensure_ascii=False), encoding="utf-8"
    )
    fp, rp = _write_replay(
        tmp_path,
        [_fused("q-ph", Q_FACT, [_usable(C1, DOC_8978, CHUNKS[C1]["content"])], typed=[])],
        [],
    )
    # the fused replay query must be bound to THIS gold question
    fused = json.loads(fp.read_text())
    fused["results"][0]["query"] = "GB 8978-1996 表 8 中臭气浓度指标值是多少？"
    fp.write_text(json.dumps(fused, ensure_ascii=False), encoding="utf-8")
    report = _run(
        an.run_answer(
            tmp_path / "out",
            ["q-ph"],
            rerank_report_path=rp,
            fused_report_path=fp,
            values=VALUES,
            conn=conn,
        )
    )
    res = report["results"][0]
    assert res["coverage_status"] == "complete", res["flags"]
    it = res["answer"]["items"][0]
    assert it["unit_status"] == "dimensionless"
    assert "臭气浓度" in "".join(it["cells"])


def test_fact_unit_from_header_text_is_source_context(monkeypatch, tmp_path):
    conn, _ = _install(
        monkeypatch,
        tmp_path,
        [_gold_q("q-unit-hdr", "GB 8978-1996 表 9 中石油类的限值是多少？", "fact")],
    )
    cat = conn.cat
    cat["table_units"][DOC_8978].append(
        {
            "unit_id": "tb-8978-0009",
            "unit_order": 6,
            "table_seq": 6,
            "caption": "表 9 石油类浓度限值（mg/L）",
            "heading": "4",
            "locator": json.dumps({"blockid": "tb-8978-0009"}),
        }
    )
    tables = json.loads((tmp_path / "gb8978.pdf.parsed" / "x.tables.json").read_text())["tables"]
    tables["tb-8978-0009"] = {
        "content": "<table><tr><th>序号</th><th>污染物</th><th>排放限值</th></tr>"
        "<tr><td>1</td><td>石油类</td><td>5.0</td></tr></table>",
        "caption": "表 9 石油类浓度限值（mg/L）",
    }
    (tmp_path / "gb8978.pdf.parsed" / "x.tables.json").write_text(
        json.dumps({"tables": tables}, ensure_ascii=False), encoding="utf-8"
    )
    fp, rp = _write_replay(
        tmp_path,
        [_fused("q-unit-hdr", Q_FACT, [_usable(C1, DOC_8978, CHUNKS[C1]["content"])], typed=[])],
        [],
    )
    fused = json.loads(fp.read_text())
    fused["results"][0]["query"] = "GB 8978-1996 表 9 中石油类的限值是多少？"
    fp.write_text(json.dumps(fused, ensure_ascii=False), encoding="utf-8")
    report = _run(
        an.run_answer(
            tmp_path / "out",
            ["q-unit-hdr"],
            rerank_report_path=rp,
            fused_report_path=fp,
            values=VALUES,
            conn=conn,
        )
    )
    res = report["results"][0]
    assert res["coverage_status"] == "complete"
    it = res["answer"]["items"][0]
    assert it["unit_status"] == "source_context" and it["unit"] == "mg/L"


def test_cli_answer_reports_ok_only_when_post_guard_clean(tmp_path, monkeypatch, capsys):
    import env_rag_final.cli as cli

    async def fake_ok(report_dir, queries, **kw):
        return {
            "results": [{"query_id": "q", "coverage_status": "complete", "answer": {"items": [1]}}],
            "model_calls_used": 0,
        }

    monkeypatch.setattr(an, "run_answer", fake_ok)
    args = SimpleNamespace(
        report_dir=tmp_path / "out",
        query_id="q",
        rerank_report=None,
        fused_report=None,
        allow_model=True,
    )
    cli._run_answer(args, VALUES)
    assert "Answer OK" in capsys.readouterr().out


def test_cli_answer_exits_nonzero_when_run_answer_raises(tmp_path, monkeypatch, capsys):
    import env_rag_final.cli as cli

    async def fake_fail(report_dir, queries, **kw):
        raise an.AdapterError("post-guard failure recorded, results are not trustworthy")

    monkeypatch.setattr(an, "run_answer", fake_fail)
    args = SimpleNamespace(
        report_dir=tmp_path / "out",
        query_id="q",
        rerank_report=None,
        fused_report=None,
        allow_model=False,
    )
    with pytest.raises(SystemExit):
        cli._run_answer(args, VALUES)
    assert "Answer OK" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# rev-2 necessary positives (answer-review r2 B1/B2/B3 companions)
# ---------------------------------------------------------------------------


_POSITIVE_SYN = {
    "items": [
        {
            "edition": "gb3095-2012",
            # explicit "+" sign and a SPACE-separated unit: same quantity,
            # binding unit present — must still pass the relation checks
            "claim": "2012版PM2.5年平均二级限值为+35 μg/m³",
            "quote": "PM2.5 | 年平均 | 15 | 35",
        },
        {
            "edition": "gb3095-2012",
            # the row that really states 24小时平均 — averaging-time POSITIVE
            "claim": "2012版PM2.5的24小时平均二级限值为150μg/m³",
            "quote": "PM2.5 | 24小时平均 | 80 | 150",
        },
        {
            "edition": "gb3095-2026",
            "claim": "2026版pm2.5年平均二级限值收严为25μg/m³",
            "quote": "PM2.5 | 年平均 | 10 | 25",
        },
    ]
}


def test_model_positive_signed_spaced_unit_and_average_time(monkeypatch, tmp_path):
    conn, _ = _install(monkeypatch, tmp_path, [_gold_q("q-syn", Q_SYN, "synthesis")])
    fp, rp = _syn_replay(tmp_path)
    report = _run(
        an.run_answer(
            tmp_path / "out",
            ["q-syn"],
            rerank_report_path=rp,
            fused_report_path=fp,
            values=VALUES,
            conn=conn,
            allow_model=True,
            transport=_model_transport(_POSITIVE_SYN),
        )
    )
    res = report["results"][0]
    # grounding: elements come from the QUESTION ∩ read rows (never header-only
    # words, never hardcoded)
    assert res["model"]["question_elements"] == ["pm2.5", "年平均"]
    assert res["coverage_status"] == "complete", (res["model"], res["answer"])
    assert len(res["answer"]["items"]) == 3
    assert all(c["citation_verified"] for c in res["answer"]["items"])


def test_dimensionless_note_binds_its_own_row_only(monkeypatch, tmp_path):
    # B3 companion positive: under "表 12 控制指标（pH为无量纲）", the pH row
    # gets the attributed 無量綱 judgment (note applies because THIS row's
    # subject is pH), while another row in the same table keeps its own unit —
    # a note never propagates as 無量綱 to rows it does not name.
    conn, _ = _install(
        monkeypatch,
        tmp_path,
        [_gold_q("q-ph", "GB 8978-1996 表 12 中pH的指标値是多少？", "fact")],
    )
    cat = conn.cat
    cat["table_units"][DOC_8978].append(
        {
            "unit_id": "tb-8978-0012",
            "unit_order": 7,
            "table_seq": 7,
            "caption": "表 12 控制指标（pH为无量纲）",
            "heading": "4",
            "locator": json.dumps({"blockid": "tb-8978-0012"}),
        }
    )
    tables = json.loads((tmp_path / "gb8978.pdf.parsed" / "x.tables.json").read_text())["tables"]
    tables["tb-8978-0012"] = {
        "content": "<table><tr><th>序号</th><th>指标</th><th>値</th><th>単位</th></tr>"
        "<tr><td>1</td><td>pH</td><td>6~9</td><td></td></tr>"
        "<tr><td>2</td><td>色度</td><td>50</td><td>倍</td></tr></table>",
        "caption": "表 12 控制指标（pH为无量纲）",
    }
    (tmp_path / "gb8978.pdf.parsed" / "x.tables.json").write_text(
        json.dumps({"tables": tables}, ensure_ascii=False), encoding="utf-8"
    )
    fp, rp = _write_replay(
        tmp_path,
        [
            fx_q := _fused(
                "q-ph",
                "GB 8978-1996 表 12 中pH的指标値是多少？",
                [_usable(C1, DOC_8978, CHUNKS[C1]["content"])],
            )
        ],
        [],
    )
    report = _run(
        an.run_answer(
            tmp_path / "out",
            ["q-ph"],
            rerank_report_path=rp,
            fused_report_path=fp,
            values=VALUES,
            conn=conn,
            allow_model=False,
        )
    )
    res = report["results"][0]
    assert res["coverage_status"] == "complete", (res["flags"], res["answer"])
    item = res["answer"]["items"][0]
    assert item["cells"] == ["1", "pH", "6~9", ""]
    assert item["unit_status"] == "dimensionless"


# ---------------------------------------------------------------------------
# 5.5 rev-3 (answer-review r3 C1-C3): verbatim prose proof, the question slot
# matrix, and LOCAL unit-note scope — all through the owning entry.
# ---------------------------------------------------------------------------

_Q_HG_CD = "对比 GB 3095-2012 与 GB 3095-2026 第3章的总汞、总镉限值。"
_Q_TWO_AVG = "对比 GB 3095-2012 与 GB 3095-2026 表 1 中 PM2.5 的年平均和24小时平均二级限值。"
_LIMITS_QUOTE = "3.1 污染物限值 总汞限值为0.05 mg/L，总镉限值为0.1 mg/L。"


def _load_limits_chapter(conn, tmp_path):
    """Chapter-3 prose fixture for both editions (independent reads)."""
    for doc_id, year in [(DOC_2012, "2012"), (DOC_2026, "2026")]:
        unit_id, scope_id = f"block-{year}", f"{doc_id}:scope:3"
        body = "3 污染物限值\n" + _LIMITS_QUOTE + "\n"
        conn.cat["scopes"][(doc_id, "3")] = [
            {
                "scope_id": scope_id,
                "scope_kind": "chapter",
                "title": "污染物限值",
                "number": "3",
                "confirm_status": "confirmed",
            }
        ]
        conn.cat["scope_units"][scope_id] = [unit_id]
        conn.cat["units"][(doc_id, unit_id)] = {
            "unit_id": unit_id,
            "unit_kind": "block",
            "heading": "3",
            "requires_span": False,
            "content_length": len(body),
            "locator": json.dumps({"blockid": unit_id}),
        }
        conn.cat["links"][(doc_id, unit_id)] = []
        path = tmp_path / f"gb3095-{year}.pdf.parsed" / "x.blocks.jsonl"
        path.write_text(
            '{"meta":true}\n'
            + json.dumps({"type": "content", "blockid": unit_id, "content": body})
            + "\n"
        )


def _syn_env(monkeypatch, tmp_path, question):
    conn, _ = _install(monkeypatch, tmp_path, [_gold_q("q-syn", question, "synthesis")])
    fp, rp = _write_replay(
        tmp_path,
        [
            _fused(
                "q-syn",
                question,
                [
                    _usable(CP12, DOC_2012, CHUNKS[CP12]["content"]),
                    _usable(CP26, DOC_2026, CHUNKS[CP26]["content"]),
                ],
            )
        ],
        [],
    )
    return conn, fp, rp


def _run_syn(tmp_path, conn, fp, rp, payload):
    return _run(
        an.run_answer(
            tmp_path / "out",
            ["q-syn"],
            fused_report_path=fp,
            rerank_report_path=rp,
            values=VALUES,
            conn=conn,
            transport=_model_transport(payload),
            allow_model=True,
        )
    )["results"][0]


def test_prose_verbatim_claim_with_edition_prefix_is_complete(monkeypatch, tmp_path):
    # C1 positive: the ONLY added decoration is the application-side edition
    # prefix; the statement itself remains a continuous verbatim source claim.
    conn, fp, rp = _syn_env(monkeypatch, tmp_path, _Q_HG_CD)
    _load_limits_chapter(conn, tmp_path)
    payload = {
        "items": [
            {
                "edition": f"gb3095-{year}",
                "claim": f"{year}版总汞限值为0.05 mg/L，总镉限值为0.1 mg/L。",
                "quote": _LIMITS_QUOTE,
            }
            for year in ["2012", "2026"]
        ]
    }
    res = _run_syn(tmp_path, conn, fp, rp, payload)
    assert res["model"]["question_elements"] == ["总汞", "总镉"]
    assert res["coverage_status"] == "complete", (res["model"], res["answer"])
    assert len(res["answer"]["items"]) == 2


def test_prose_reordered_clauses_rejected_without_second_call(monkeypatch, tmp_path):
    # C1 negative: every clause correct, every term and number present — but
    # the claim is not a CONTINUOUS verbatim statement, so it is refused
    # outright (no word-set pass, no re-ask).
    conn, fp, rp = _syn_env(monkeypatch, tmp_path, _Q_HG_CD)
    _load_limits_chapter(conn, tmp_path)
    payload = {
        "items": [
            {
                "edition": f"gb3095-{year}",
                "claim": "总镉限值为0.1 mg/L，总汞限值为0.05 mg/L。",
                "quote": _LIMITS_QUOTE,
            }
            for year in ["2012", "2026"]
        ]
    }
    res = _run_syn(tmp_path, conn, fp, rp, payload)
    assert res["coverage_status"] == "partial", res["answer"]
    assert res["answer"].get("model_failure")
    assert any("continuous verbatim" in p for p in res["answer"]["unverified_claims"])


def test_slot_matrix_multi_averaging_times_jointly_covered_is_complete(monkeypatch, tmp_path):
    # C2 positive: FOUR slots (2 editions x 2 averaging times at 二级) are
    # filled JOINTLY by four separate claims — no single claim has to carry
    # every condition of the question.
    conn, fp, rp = _syn_env(monkeypatch, tmp_path, _Q_TWO_AVG)
    payload = {
        "items": [
            {
                "edition": "gb3095-2012",
                "claim": "2012版PM2.5年平均二级限值为35μg/m³",
                "quote": "PM2.5 | 年平均 | 15 | 35",
            },
            {
                "edition": "gb3095-2012",
                "claim": "2012版PM2.5的24小时平均二级限值为150μg/m³",
                "quote": "PM2.5 | 24小时平均 | 80 | 150",
            },
            {
                "edition": "gb3095-2026",
                "claim": "2026版PM2.5年平均二级限值为25μg/m³",
                "quote": "PM2.5 | 年平均 | 10 | 25",
            },
            {
                "edition": "gb3095-2026",
                "claim": "2026版PM2.5的24小时平均二级限值为150μg/m³",
                "quote": "PM2.5 | 24小时平均 | 80 | 150",
            },
        ]
    }
    res = _run_syn(tmp_path, conn, fp, rp, payload)
    assert res["model"]["question_elements"] == ["pm2.5", "年平均", "24小时平均"]
    assert res["model"]["question_levels"] == ["二级"]
    assert res["coverage_status"] == "complete", (res["model"], res["answer"])
    assert len(res["answer"]["items"]) == 4


def test_slot_matrix_missing_second_averaging_time_stays_partial(monkeypatch, tmp_path):
    # C2 companion: the annual claims alone leave the 24小时平均 slots of BOTH
    # editions unfilled — evidence kept, coverage explicitly incomplete.
    conn, fp, rp = _syn_env(monkeypatch, tmp_path, _Q_TWO_AVG)
    res = _run_syn(tmp_path, conn, fp, rp, _GOOD_SYN)
    assert res["coverage_status"] == "partial", res["answer"]
    assert len(res["answer"]["items"]) == 2
    missing = res["answer"]["missing_answer_editions"]
    assert any("24小时平均" in m for m in missing), missing


def test_prose_claim_answering_only_cadmium_leaves_mercury_slots_missing(monkeypatch, tmp_path):
    # D1 (answer-review r4) mirror: the model answers 总镉 alone per edition.
    # 总汞 was READ (it sits in the cited paragraph) but never ANSWERED — the
    # read scope cannot fill the mercury slots; the cadmium items stay as
    # verified evidence and the missing side is explicit.
    conn, fp, rp = _syn_env(monkeypatch, tmp_path, _Q_HG_CD)
    _load_limits_chapter(conn, tmp_path)
    payload = {
        "items": [
            {
                "edition": f"gb3095-{year}",
                "claim": "总镉限值为0.1 mg/L。",
                "quote": "总镉限值为0.1 mg/L。",
            }
            for year in ["2012", "2026"]
        ]
    }
    res = _run_syn(tmp_path, conn, fp, rp, payload)
    assert res["reverification"]["problems"] == []
    assert len(res["answer"]["items"]) == 2, "answered cadmium claims stay as evidence"
    assert res["coverage_status"] == "partial", res["answer"]
    missing = res["answer"]["missing_answer_editions"]
    assert any("总汞" in m for m in missing), missing


@pytest.mark.parametrize(
    "caption",
    [
        "表 8 控制指标（均为无量纲）",
        # D2 (answer-review r4) companion: internal splitting must not destroy
        # an unattributed table-wide clause.
        "表 8 控制指标（均为无量纲，单位略）",
    ],
)
def test_bracketed_unattributed_dimensionless_note_covers_whole_table(
    monkeypatch, tmp_path, caption
):
    # C3 positive: "（均为无量纲）" attributes to no named subject — the note
    # IS the table-wide declaration and still applies.
    conn, _ = _install(
        monkeypatch,
        tmp_path,
        [_gold_q("q-ph", "GB 8978-1996 表 8 中臭气浓度指标值是多少？", "fact")],
    )
    conn.cat["table_units"][DOC_8978].append(
        {
            "unit_id": "tb-8978-0008",
            "unit_order": 5,
            "table_seq": 5,
            "caption": caption,
            "heading": "4",
            "locator": json.dumps({"blockid": "tb-8978-0008"}),
        }
    )
    tables = json.loads((tmp_path / "gb8978.pdf.parsed" / "x.tables.json").read_text())["tables"]
    tables["tb-8978-0008"] = {
        "content": "<table><tr><th>序号</th><th>指标</th><th>值</th></tr>"
        "<tr><td>1</td><td>臭气浓度</td><td>20</td></tr></table>",
        "caption": caption,
    }
    (tmp_path / "gb8978.pdf.parsed" / "x.tables.json").write_text(
        json.dumps({"tables": tables}, ensure_ascii=False), encoding="utf-8"
    )
    fp, rp = _write_replay(
        tmp_path,
        [_fused("q-ph", Q_FACT, [_usable(C1, DOC_8978, CHUNKS[C1]["content"])], typed=[])],
        [],
    )
    fused = json.loads(fp.read_text())
    fused["results"][0]["query"] = "GB 8978-1996 表 8 中臭气浓度指标值是多少？"
    fp.write_text(json.dumps(fused, ensure_ascii=False), encoding="utf-8")
    report = _run(
        an.run_answer(
            tmp_path / "out",
            ["q-ph"],
            rerank_report_path=rp,
            fused_report_path=fp,
            values=VALUES,
            conn=conn,
            allow_model=False,
        )
    )
    res = report["results"][0]
    assert res["coverage_status"] == "complete", (res["flags"], res["answer"])
    assert res["answer"]["items"][0]["unit_status"] == "dimensionless"
