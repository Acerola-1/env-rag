"""Phase-4 improvement group 3: catalog-layer full-set file union (改进组3).

Every scenario drives OWNING entries offline — evaluation._synthesized_fused_result
(discovery shape) + answer.run_answer (publication) + the formal
enumerate_/doc_enum entries — over explicit fake READ-ONLY catalogs. Service
boundary: real asyncpg.connect, httpx posting, write SQL, unknown SQL and any
search_documents read all blow up; allow_model=False, transport=None, zero
network/DB/model. Attribution judgement and pagination run as REAL code.
Assertions check the FINAL published answer + trace statistics, never one
helper. Catalog fixtures are declared 构造 rows (or read-only replays of stored
gate-2 shapes); gold is consulted only post-hoc.
"""

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
import test_answer as fx

from env_rag_final import answer as an
from env_rag_final import evaluation as ev
from env_rag_final.enumerate_ import doc_enum as de
from env_rag_final.search.query import SearchResult

ROOT = Path(".")


def _run(coro):
    return asyncio.run(coro)


def _sha(t):
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


IDENT = {
    "matches_frozen": True,
    "problems": [],
    "counts": {"lightrag_doc_chunks": 5709},
    "source_fingerprint": fx.FP,
    "catalog_active": {"run_id": fx.RUN, "snapshot_id": fx.SNAP},
    "search_active": fx.SEARCH,
    "gold_sha": fx.GOLD_SHA,
    "env_sha": "env-1",
}


def doc(doc_name, code=None, version=None, title="", doc_type="standard", missing=False):
    return {
        "doc_name": doc_name,
        "self_code": code,
        "self_code_version": version,
        "title": title,
        "doc_type": doc_type,
        "row_missing": missing,
    }


class UnionConn:
    """Fake read-only catalog. Routes the REAL SQL shapes of the base
    enumeration, the new attribution scan, the publication guard and the
    answer re-read; ANY search_documents read raises (the enumeration must
    never touch the search layer)."""

    def __init__(self, cat: dict, *, snap_seq=None, window_seq=None, fail_full_read_after=None):
        self.cat = cat
        self.snap_seq = list(snap_seq or [])
        self.window_seq = list(window_seq or [])
        self.queries = []
        self._snap_i = 0
        self._win_i = 0
        # F1 transport knob: the Nth FULL metadata scan (no predicate) raises —
        # used to make the final publication-window re-read unverifiable while
        # the branch scans (fewer full reads) still complete.
        self.fail_full_read_after = fail_full_read_after
        self._full_reads = 0

    # -- helpers ------------------------------------------------------------
    def _rows(self, sql: str, args: tuple):
        """Evaluate the known predicate shapes over the declared catalog."""
        import re

        m = re.search(r"AND \((.*)\)", sql)
        rows = list(self.cat.items())
        if m and "FROM env_rag.documents" in sql and "search" not in sql:
            pred = m.group(1)
            out = []
            cb = re.findall(
                r"\(self_code = \$(\d+)(?: AND self_code_version IN \(([^)]*)\))?\)", pred
            )
            lk = re.search(r"doc_name LIKE '%' \|\| \$(\d+) \|\| '%'", pred)
            for d, r in rows:
                if r.get("row_missing"):
                    continue
                hit = False
                for n, vers in cb:
                    code = args[int(n) - 1]
                    if (r["self_code"] or "") != code:
                        continue
                    if vers:
                        wanted = [args[int(v) - 1] for v in re.findall(r"\$(\d+)", vers)]
                        if (r["self_code_version"] or "") not in wanted:
                            continue
                    hit = True
                if lk and not cb:
                    phrase = args[int(lk.group(1)) - 1]
                    hit = phrase in (r["doc_name"] or "")
                if hit:
                    out.append((d, r))
            rows = out
        rows.sort(key=lambda kv: kv[1]["doc_name"])
        return rows

    def _meta_row(self, d, r):
        return {
            "doc_id": d,
            "doc_name": r["doc_name"],
            "title": r["title"],
            "title_confidence": 1.0,
            "self_code": r["self_code"],
            "self_code_version": r["self_code_version"],
            "doc_type": r.get("doc_type"),
            "unknown_fields": [],
        }

    def _snap(self):
        if self._snap_i < len(self.snap_seq):
            v = self.snap_seq[self._snap_i]
        else:
            v = self.snap_seq[-1] if self.snap_seq else fx.SNAP
        self._snap_i += 1
        return v

    def _next_window(self):
        if self._win_i < len(self.window_seq):
            v = self.window_seq[self._win_i]
            self._win_i += 1
            return [self._meta_row(d, self.cat[d]) for d in v]
        self._win_i += 1
        return None  # fall through to normal evaluation

    # -- asyncpg surface -----------------------------------------------------
    async def fetch(self, sql: str, *args):
        self.queries.append(("fetch", sql, list(map(str, args))))
        u = sql.upper()
        assert "INSERT" not in u and "UPDATE" not in u and "DELETE" not in u and "CREATE" not in u
        if "SEARCH_DOCUMENTS" in u or "SEARCH_CHUNKS" in u:
            raise AssertionError(
                "file enumeration must not read the search layer (improvement-3 root cause)"
            )
        if "FROM ENV_RAG.DOCUMENTS" in u and "UNKNOWN_FIELDS" in u.upper():
            import re

            rows = self._rows(sql, args)
            metas = [self._meta_row(d, r) for d, r in rows]
            m = re.search(r"LIMIT (\d+) OFFSET (\d+)", sql)
            if m:
                lim, off = int(m.group(1)), int(m.group(2))
                # the attribution scan's FULL-WINDOW read is the only query
                # above 1000 rows in these fixtures — it may be overridden to
                # simulate a content change mid-scan (构造, not a production
                # mock of the enumeration itself)
                if lim > 1000 and "AND (" not in sql:
                    self._full_reads += 1
                    if (
                        self.fail_full_read_after is not None
                        and self._full_reads > self.fail_full_read_after
                    ):
                        raise RuntimeError("simulated catalog transport failure mid-guard")
                    nxt = self._next_window()
                    if nxt is not None:
                        return nxt
                metas = metas[off : off + lim]
            return metas
        if "unit_chunk_links" in sql:
            return []
        raise AssertionError(f"unexpected SQL: {sql[:130]!r}")

    async def fetchrow(self, sql: str, *args):
        self.queries.append(("fetchrow", sql, list(map(str, args))))
        u = sql.upper()
        assert "INSERT" not in u and "UPDATE" not in u and "DELETE" not in u
        if "CORPUS_RUNS" in u:
            return {"snapshot_id": self._snap(), "source_fingerprint": {"value": fx.FP}}
        if "SELF_CODE_VERSION FROM ENV_RAG.DOCUMENTS" in u:
            r = self.cat.get(args[2])
            if not r or r.get("row_missing"):
                return None
            return {
                "doc_name": r["doc_name"],
                "self_code": r["self_code"],
                "self_code_version": r["self_code_version"],
            }
        if "REQUIRES_SPAN" in u:
            return None
        raise AssertionError(f"unexpected SQL: {sql[:130]!r}")

    async def fetchval(self, sql: str, *args):
        self.queries.append(("fetchval", sql, list(map(str, args))))
        if "COUNT(*)" in sql.upper():
            return len(self._rows(sql, args))
        if "DOC_NAME FROM ENV_RAG.DOCUMENTS" in sql.upper():
            r = self.cat.get(args[2])
            return r["doc_name"] if r and not r.get("row_missing") else None
        raise AssertionError(f"unexpected SQL: {sql[:130]!r}")

    async def close(self):
        pass


def _install(monkeypatch, conn, ident=None):
    ib = dict(ident or IDENT)

    async def capture(_v):
        return {
            "identity": {
                "public_counts": ib["counts"],
                "catalog_active": ib["catalog_active"],
                "source_fingerprint": ib["source_fingerprint"],
                "search_active": ib["search_active"],
                "gold_sha": ib["gold_sha"],
                "env_sha": ib["env_sha"],
            },
            "problems": [],
            "matches_frozen": True,
        }

    monkeypatch.setattr(an, "_capture_identity", capture)

    def guard(values, workspace):
        if any(k in values for k in ("QDRANT_WORKSPACE", "NEO4J_WORKSPACE", "POSTGRES_WORKSPACE")):
            raise an.AdapterError("workspace override env forbidden")

    monkeypatch.setattr(an, "verify_config_guard", guard)
    monkeypatch.setattr(an, "verify_gold_guard", lambda p: fx.GOLD_SHA)

    async def current(_c, **_kw):
        return {
            "state": "current",
            "active_snapshot_id": ib["catalog_active"]["snapshot_id"],
            "stored_fingerprint": ib["source_fingerprint"],
        }

    import env_rag_final.catalog.builder as builder
    import env_rag_final.catalog.source as source_mod

    monkeypatch.setattr(builder, "check_stale", current)

    async def no_fp(_c, _w):
        return ""

    monkeypatch.setattr(builder, "_live_source_fingerprint", no_fp)
    monkeypatch.setattr(source_mod, "SourceAdapter", fx.FakeAdapter)

    def boom(**_kw):
        raise AssertionError("no real DB connection in the offline diagnosis")

    monkeypatch.setattr(an.asyncpg, "connect", boom)

    def http_boom(*_a, **_k):
        raise AssertionError("no HTTP in the offline diagnosis")

    monkeypatch.setattr(an.httpx.AsyncClient, "post", http_boom)
    return conn


VALUES = dict(fx.VALUES)
import env_rag_final.local_adapter as la  # noqa: E402

VALUES["EMBEDDING_MODEL"] = la.EMBEDDING_MODEL
VALUES["EMBEDDING_DIM"] = str(la.EMBEDDING_DIM)


def _usable(doc_id, file_path, content="x"):
    return {
        "workspace": "default",
        "chunk_id": f"{doc_id}-chunk-001",
        "doc_id": doc_id,
        "file_path": file_path,
        "verified": True,
        "content_sha256": _sha(content),
        "content_len": len(content),
        "content": content,
        "paths": [
            {
                "path": "local",
                "workspace": "default",
                "chunk_id": f"{doc_id}-chunk-001",
                "doc_id": doc_id,
                "file_path": file_path,
                "discovery": "entity",
                "score": None,
                "similarity_order": 0,
                "reached_via": ["entity:test"],
            }
        ],
    }


def _run_leg(monkeypatch, tmp_path, question, cat, *, search_id="", usable=None, qid="uq"):
    """conversion (evaluation synthesis) + full publication (run_answer) over
    the SAME fake catalog — the owning file_enum entry."""
    q = {"query_id": qid, "question": question, "workspace": "default"}
    fused_result = ev._synthesized_fused_result(q, usable or [], path_label="local")
    fused_result["pg"]["search_id"] = search_id
    conn = UnionConn(cat)
    _install(monkeypatch, conn)
    fp = tmp_path / "fusion-runtime-latest.json"
    rp = tmp_path / "rerank-runtime-latest.json"
    fp.write_text(
        json.dumps(
            {"task": "t", "identity_before": IDENT, "results": [fused_result]}, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    rp.write_text(
        json.dumps({"task": "t", "identity_before": IDENT, "results": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "gold.json").write_text(
        json.dumps(
            {"questions": [dict(q, category="file_enum")], "counter_examples": []},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(an, "GOLD_PATH", tmp_path / "gold.json")
    report = _run(
        an.run_answer(
            tmp_path / "run",
            [qid],
            rerank_report_path=rp,
            fused_report_path=fp,
            conn=conn,
            values=VALUES,
            allow_model=False,
            transport=None,
        )
    )
    out = report["results"][0]
    enum = next((e for e in out["expansions"] if e.get("stage") == "document_enumeration"), {})
    return report, out, enum, conn


# catalog fixture: the standard + two amendments carrying the code in title/name
CAT_005 = {
    "doc-std": doc(
        "synth-GB18466-2005.pdf",
        "GB18466",
        "2005",
        title="医疗机构水污染物排放标准",
        doc_type="standard",
    ),
    "doc-m1": doc(
        "synth-含2026修改单整合版.pdf", title="GB 18466—2005（含2026年修改单）", doc_type="standard"
    ),
    "doc-m2": doc(
        "synth-GB18466-修改单.pdf",
        title="《医疗机构水污染物排放标准》（GB 18466—2005）修改单",
        doc_type="amendment",
    ),
}

Q_WITH = "库内有哪些GB 18466-2005的文档（含修改单）？"
Q_SELF = "GB 18466-2005 自身编号的文档有哪些？"


# ---- 1. local empty search_id delivers the full union; search SQL is never touched
def test_local_empty_search_id_delivers_full_union(monkeypatch, tmp_path):
    usable = [_usable("doc-std", "synth-GB18466-2005.pdf", "正文")]
    report, out, enum, conn = _run_leg(
        monkeypatch, tmp_path, Q_WITH, CAT_005, search_id="", usable=usable
    )
    items = out["answer"]["items"]
    assert {it["doc_id"] for it in items} == {"doc-std", "doc-m1", "doc-m2"}
    assert out["coverage_status"] == "complete", out
    assert enum["base_total"] == 1 and enum["base_processed"] == 1
    # the scan sees THREE carriers (std canonical + two amendments); only the
    # non-canonical carries are related EVIDENCE; the standard stays overlap
    assert enum["related_matches"] == 3 and enum["related_evidence"] == 2
    assert enum["attribution_added"] == 2 and enum["overlap_evidence"] == []
    assert enum["overlap_canonical"] == ["doc-std"]
    assert enum["members_total"] == 3 and enum["members_processed"] == 3
    assert enum["catalog_snapshot_id"] == fx.SNAP
    # independent re-read verified every item against the catalog row
    assert all(it.get("citation_verified") and it.get("citation_reverified") for it in items)
    for it in items:
        cit = it["citation"]
        assert cit["workspace"] == "default" and cit["snapshot_id"] == fx.SNAP
    assert report["model_calls_used"] == 0
    # structural proof: the search layer was NEVER read (any attempt raises)
    assert not any("SEARCH_DOCUMENTS" in sql.upper() for _k, sql, _a in conn.queries)


@pytest.mark.parametrize("search_id", ["", "search-from-other-generation", "872d689343a9cbb6"])
def test_search_id_value_never_changes_the_union(monkeypatch, tmp_path, search_id):
    """Filling a real search_id can no longer fix — or break — anything: the
    same-snapshot catalog scan decides, identically for every search_id."""
    _report, out, enum, conn = _run_leg(
        monkeypatch,
        tmp_path,
        Q_WITH,
        CAT_005,
        search_id=search_id,
        usable=[_usable("doc-std", "synth-GB18466-2005.pdf")],
    )
    assert out["coverage_status"] == "complete"
    assert enum["related_evidence"] == 2 and enum["attribution_added"] == 2
    assert {it["doc_id"] for it in out["answer"]["items"]} == {"doc-std", "doc-m1", "doc-m2"}
    assert not any("SEARCH_DOCUMENTS" in sql.upper() for _k, sql, _a in conn.queries)


def test_discovered_amendment_not_double_counted_union_of_three(monkeypatch, tmp_path):
    """Amendment docs present in the local discovery stay ONE published row
    each with both paths — discovery is audit, the union is the answer set."""
    usable = [
        _usable("doc-std", "synth-GB18466-2005.pdf"),
        _usable("doc-m1", "synth-含2026修改单整合版.pdf"),
    ]
    _report, out, enum, _conn = _run_leg(monkeypatch, tmp_path, Q_WITH, CAT_005, usable=usable)
    ids = [it["doc_id"] for it in out["answer"]["items"]]
    assert sorted(ids) == ["doc-m1", "doc-m2", "doc-std"]
    assert len(ids) == len(set(ids)) == 3
    assert enum["attribution_added"] == 2  # both amendments newly added by the scan
    assert out["scope_selection"]["candidates"] >= 2  # discovery retained for audit


# ---- 2. self-numbering never opens the related channel
def test_self_numbering_never_opens_related(monkeypatch, tmp_path):
    _report, out, enum, _conn = _run_leg(
        monkeypatch,
        tmp_path,
        Q_SELF,
        CAT_005,
        usable=[_usable("doc-std", "synth-GB18466-2005.pdf")],
    )
    assert enum["attribution_branch"] is False
    assert enum["related_coverage"] == "not-requested"
    assert {it["doc_id"] for it in out["answer"]["items"]} == {"doc-std"}
    assert out["coverage_status"] == "complete"


# ---- 3. zero related matches under an explicit request: never silent complete
def test_related_request_zero_evidence_is_partial_not_complete(monkeypatch, tmp_path):
    cat = {
        "doc-std": doc(
            "synth-GB18466-2005.pdf", "GB18466", "2005", title="医疗机构水污染物排放标准"
        ),
        # a similarly-named file WITHOUT any code carry: not an attribution
        "doc-junk": doc("synth-某医院排污指南.pdf", title="医院排污指南"),
    }
    _report, out, enum, _conn = _run_leg(
        monkeypatch,
        tmp_path,
        Q_WITH,
        cat,
        usable=[_usable("doc-std", "synth-GB18466-2005.pdf")],
    )
    assert enum["related_evidence"] == 0
    assert out["coverage_status"] == "partial", out
    assert {it["doc_id"] for it in out["answer"]["items"]} == {"doc-std"}
    assert "confirmed NO related evidence" in enum["related_request_note"]
    assert "not a claim that none exist" in enum["related_request_note"]
    assert out["coverage_status"] != "missing"  # this-path refusal, never corpus missing


# ---- 4. version conflicts / similar prefixes / cross-year branches refuse
def test_wrong_year_amendment_excluded_correct_one_kept(monkeypatch, tmp_path):
    cat = {
        "doc-std": doc(
            "synth-GB18466-2005.pdf", "GB18466", "2005", title="医疗机构水污染物排放标准"
        ),
        "doc-m2005": doc("synth-含2026修改单整合版.pdf", title="GB 18466—2005（含2026年修改单）"),
        "doc-m2018": doc("synth-GB18466-2018修改单.pdf", title="GB 18466—2018 修改单"),
    }
    _report, out, enum, _conn = _run_leg(
        monkeypatch,
        tmp_path,
        Q_WITH,
        cat,
        usable=[_usable("doc-std", "synth-GB18466-2005.pdf")],
    )
    ids = {it["doc_id"] for it in out["answer"]["items"]}
    assert ids == {"doc-std", "doc-m2005"}  # the 2018 one never enters
    excl_ids = {e["doc_id"] for e in enum["related_excluded"]}
    assert excl_ids == {"doc-m2018"}
    assert enum["related_evidence"] == 1
    assert out["coverage_status"] == "complete"


def test_two_branch_request_never_merges_cross_year(monkeypatch, tmp_path):
    """A row that IS GB8978-1996 cannot satisfy the GB3095-2012 branch even
    when its title mentions 3095-2012 — stated identity conflict excludes it;
    the genuine 8978 amendment is attributed to its own branch only."""
    cat = {
        "doc-3095": doc("synth-GB3095-2012.pdf", "GB3095", "2012", title="环境空气质量标准"),
        "doc-8978": doc("synth-GB8978-1996.pdf", "GB8978", "1996", title="污水综合排放标准"),
        "doc-X": doc(
            "synth-协同修改单.pdf", "GB8978", "1996", title="《GB 3095—2012》协同修改单 GB8978"
        ),
        "doc-Y": doc(
            "synth-GB8978-1996含修改单.pdf", title="《污水综合排放标准》（GB 8978—1996）修改单"
        ),
    }
    q = "对比 GB 3095-2012 与 GB 8978-1996 的文档（含修改单）？"
    _report, out, enum, _conn = _run_leg(
        monkeypatch,
        tmp_path,
        q,
        cat,
        usable=[_usable("doc-3095", "synth-GB3095-2012.pdf")],
    )
    ids = {it["doc_id"] for it in out["answer"]["items"]}
    assert "doc-Y" in ids  # real 8978 amendment (newly added by the scan)
    # doc-X IS a legal base row (its own canonical GB8978-1996 identity) but
    # its stated 1996 must never satisfy the 3095-2012 branch:
    assert "doc-X" in {e["doc_id"] for e in enum["related_excluded"]}
    assert "doc-X" not in enum["overlap_evidence"]
    assert enum["related_evidence"] == 1 and enum["attribution_added"] == 1
    # every published row's attribution only ever concerns its own carried code
    for it in out["answer"]["items"]:
        for b in it.get("attribution_branches") or []:
            assert b["status"] == "attributed"
    assert {it["doc_id"] for it in out["answer"]["items"]} >= {"doc-3095", "doc-8978", "doc-Y"}


def test_similar_prefix_code_not_attributed(monkeypatch, tmp_path):
    cat = {
        "doc-std": doc(
            "synth-GB18466-2005.pdf", "GB18466", "2005", title="医疗机构水污染物排放标准"
        ),
        "doc-near": doc("synth-GB1846-2005修改单.pdf", title="GB 1846—2005 修改单"),
    }
    _report, out, enum, _conn = _run_leg(
        monkeypatch,
        tmp_path,
        Q_WITH,
        cat,
        usable=[_usable("doc-std", "synth-GB18466-2005.pdf")],
    )
    ids = {it["doc_id"] for it in out["answer"]["items"]}
    assert "doc-near" not in ids
    assert out["coverage_status"] == "partial"  # zero related evidence


# ---- 5. legal overlap: related non-zero, added zero → complete allowed
def test_overlap_evidence_added_zero_still_complete(monkeypatch, tmp_path):
    """catalog row with 2-digit stored version satisfies the base predicate
    (IN 2012/12) while its name/title carries the code — one published row,
    BOTH source paths kept, related matches non-zero, new additions zero:
    the union is complete and never downgraded by 'added==0 → partial'."""
    cat = {
        "doc-std12": doc(
            "synth-GB3095-2012含修改单整合版.pdf", "GB3095", "12", title="GB 3095—2012（含修改单）"
        ),
    }
    q = "库内有哪些GB 3095-2012的文档（含修改单）？"
    _report, out, enum, _conn = _run_leg(
        monkeypatch,
        tmp_path,
        q,
        cat,
        usable=[_usable("doc-std12", "synth-GB3095-2012含修改单整合版.pdf")],
    )
    items = out["answer"]["items"]
    assert {it["doc_id"] for it in items} == {"doc-std12"}
    assert enum["related_evidence"] == 1
    assert enum["attribution_added"] == 0
    assert enum["overlap_evidence"] == ["doc-std12"]
    assert out["coverage_status"] == "complete", out
    # unknown self_code stays unknown in the published row (no fabrication)
    assert items[0]["self_code"] == "GB3095" and items[0]["self_code_version"] == "12"


def test_multi_version_all_kept_and_amendment_added(monkeypatch, tmp_path):
    cat = {
        "doc-12": doc("synth-GB3095-2012.pdf", "GB3095", "2012", title="环境空气质量标准"),
        "doc-26": doc("synth-GB3095-2026.pdf", "GB3095", "2026", title="环境空气质量标准"),
        "doc-m": doc("synth-含修改单.pdf", title="GB 3095—2026（含2027年修改单）"),
    }
    q = "库内有哪些GB 3095标准的文档（含修改单）？"
    _report, out, enum, _conn = _run_leg(
        monkeypatch,
        tmp_path,
        q,
        cat,
        usable=[_usable("doc-12", "synth-GB3095-2012.pdf")],
    )
    ids = {it["doc_id"] for it in out["answer"]["items"]}
    assert ids == {"doc-12", "doc-26", "doc-m"}  # every catalog version kept
    assert enum["attribution_added"] == 1
    assert out["coverage_status"] == "complete"


# ---- 6. related-scan guards at the formal entry (stale / budget / snapshot)
def test_attributed_scan_budget_truncation_is_partial(monkeypatch):
    import env_rag_final.catalog.builder as builder

    async def no_fp(_c, _w):
        return ""

    monkeypatch.setattr(builder, "_live_source_fingerprint", no_fp)
    cat = {
        f"doc-{i}": doc(f"n{i}.pdf", "GB18466", "2005", title=f"GB 18466—2005 第{i}号")
        for i in range(5)
    }
    conn = UnionConn(cat)
    res = _run(
        de.enumerate_attributed_documents(
            conn,
            [{"code": "GB18466", "version": "2005"}],
            "default",
            expected_snapshot_id=fx.SNAP,
            expected_source=fx.FP,
            page_size=2,
            max_pages=2,  # budget 4 rows < 5
        )
    )
    assert res.coverage_status == "partial"
    assert "budget" in (res.fail_stage or "").lower() or any("budget" in w for w in res.warnings)
    assert res.members_processed < res.members_total


def test_attributed_scan_active_replaced_after_last_page_is_stale(monkeypatch):
    import env_rag_final.catalog.builder as builder

    async def no_fp(_c, _w):
        return ""

    monkeypatch.setattr(builder, "_live_source_fingerprint", no_fp)
    cat = {
        "doc-m": doc("synth-含修改单.pdf", title="GB 18466—2005（含2026年修改单）"),
        "doc-o": doc("synth-其他.pdf", "GB18466", "2005", title="标准"),
    }
    # snapshot sequence: initial ok, per-page ok, FINAL guard sees the swap
    conn = UnionConn(cat, snap_seq=[fx.SNAP, fx.SNAP, "snap-replaced"])
    res = _run(
        de.enumerate_attributed_documents(
            conn,
            [{"code": "GB18466", "version": "2005"}],
            "default",
            expected_snapshot_id=fx.SNAP,
            expected_source=fx.FP,
        )
    )
    assert res.coverage_status == "stale"
    assert any("snapshot" in w for w in res.warnings)


def test_attributed_scan_same_count_content_change_is_stale(monkeypatch):
    import env_rag_final.catalog.builder as builder

    async def no_fp(_c, _w):
        return ""

    monkeypatch.setattr(builder, "_live_source_fingerprint", no_fp)
    cat = {
        "doc-m": doc("synth-含修改单.pdf", title="GB 18466—2005（含2026年修改单）"),
    }
    # the second full-window read shows a DIFFERENT same-count matching set
    conn = UnionConn(cat)
    conn.window_seq = [["doc-m"], []]  # final re-window reports no matches
    res = _run(
        de.enumerate_attributed_documents(
            conn,
            [{"code": "GB18466", "version": "2005"}],
            "default",
            expected_snapshot_id=fx.SNAP,
            expected_source=fx.FP,
        )
    )
    assert res.coverage_status == "stale"


def test_base_complete_cannot_mask_related_stale(monkeypatch):
    cat = {
        "doc-std": doc("synth-GB18466-2005.pdf", "GB18466", "2005", title="标准"),
        "doc-m": doc("synth-含修改单.pdf", title="GB 18466—2005（含2026年修改单）"),
    }

    async def stale_scan(conn, codes, workspace, **kw):
        from env_rag_final.enumerate_.contract import EnumResult

        return EnumResult(
            "q",
            "document",
            workspace,
            kw.get("expected_snapshot_id", fx.SNAP),
            fx.FP,
            predicate="scan",
            coverage_status="stale",
            fail_stage="snapshot",
            warnings=["related scan saw a replaced snapshot"],
        )

    monkeypatch.setattr(de, "enumerate_attributed_documents", stale_scan)
    import env_rag_final.catalog.builder as builder
    import env_rag_final.search.expand as expmod

    async def no_fp(_c, _w):
        return ""

    monkeypatch.setattr(builder, "_live_source_fingerprint", no_fp)

    # the expand orchestrator imports the scan by name at call time — patch that too
    result = SearchResult("q", "default")
    result.query_text = Q_WITH
    result.parsed_codes = [{"code": "GB18466", "version": "2005"}]
    result.parsed_code = result.parsed_codes[0]
    result.candidates = [{"doc_id": "x", "chunk_id": "cx", "workspace": "default"}]
    discovery_before = [{"doc_id": "x"}]
    result.discovery_candidates = list(discovery_before)
    conn = UnionConn(cat)
    _run(expmod._expand_documents(conn, result, "default"))
    stage = [t for t in result.trace if t["stage"] == "document_enumeration"][-1]
    assert stage["coverage_status"] == "stale"  # base completeness cannot override
    assert result.status == "stale"
    # discovery stays the original audit list — never backfilled from the union
    assert result.discovery_candidates == [{"doc_id": "x"}]


# ---- 7. the empty/self-granted citation cannot survive the answer re-read
def test_answer_rejects_borrowed_or_empty_snapshot_citation(monkeypatch, tmp_path):
    """A scan row whose citation carries an EMPTY snapshot (the old search
    identity) is never published as verified: the answer layer re-reads the
    catalog row and downgrades it, so the leg cannot be complete."""
    cat = {
        "doc-std": doc("synth-GB18466-2005.pdf", "GB18466", "2005", title="标准"),
        "doc-m": doc("synth-含修改单.pdf", title="GB 18466—2005（含2026年修改单）"),
    }
    real = de.enumerate_attributed_documents

    async def corrupt_scan(conn, codes, workspace, **kw):
        res = await real(conn, codes, workspace, **kw)
        for it in res.items:
            it["citation"]["snapshot_id"] = ""  # self-granted borrow from the search replay
        return res

    monkeypatch.setattr(de, "enumerate_attributed_documents", corrupt_scan)
    _report, out, enum, _conn = _run_leg(
        monkeypatch,
        tmp_path,
        Q_WITH,
        cat,
        usable=[_usable("doc-std", "synth-GB18466-2005.pdf")],
    )
    items = {it["doc_id"]: it for it in out["answer"]["items"]}
    assert items["doc-m"]["citation_verified"] is False
    assert items["doc-m"].get("citation_reverified") is False
    assert out["coverage_status"] != "complete"


def test_related_request_without_code_branch_is_conservative(monkeypatch, tmp_path):
    """A 相关文件 request WITHOUT any standard code has no verifiable branch
    to attribute: the leg must refuse the related set conservatively (never
    complete), while the phrase-predicate base rows stay visible in the audit.
    No PG/gold input is injected; the refusal is THIS-PATH only."""
    cat = {
        "doc-a": doc("synth-相关文件.pdf", title="相关文件汇编"),
    }
    q = "库内有哪些相关文件（含修改单）？"
    _report, out, enum, _conn = _run_leg(
        monkeypatch, tmp_path, q, cat, usable=[_usable("doc-a", "synth-相关文件.pdf")]
    )
    assert out["coverage_status"] in ("ambiguous", "partial"), out
    assert out["coverage_status"] != "complete"
    blob = json.dumps(out, ensure_ascii=False)
    assert "no parseable" in blob  # refusal recorded in the published stage
    assert enum["related_matches"] == 0


# ---- F1: final publication-window CONTENT guard (改进组3 r1 补正) ----------


def _inject_before_guard(monkeypatch, mutate):
    """Mutate the fake catalog right before the REAL final guard runs — the
    same injection discipline as the reviewer matrix: snapshot identity and
    row count stay constant, no validator is mocked."""
    original = de.verify_publication_snapshot
    state = {"done": False}

    async def inject_then_real(conn, workspace, snapshot_id, source_fp, *a, **kw):
        if not state["done"]:
            mutate()
            state["done"] = True
        return await original(conn, workspace, snapshot_id, source_fp, *a, **kw)

    monkeypatch.setattr(de, "verify_publication_snapshot", inject_then_real)
    return state


def test_window_change_published_row_stops_matching_refuses(monkeypatch, tmp_path):
    """A previously-matching amendment row loses its code-carrying title
    inside the window (reverse disappearance): the FULL matching-set re-read
    must catch it — the already-read rows stay published as diagnosis and the
    coverage is never complete."""
    cat = {
        "doc-std": dict(CAT_005["doc-std"]),
        "doc-m1": dict(CAT_005["doc-m1"]),
    }
    state = _inject_before_guard(monkeypatch, lambda: cat["doc-m1"].update(title="无关标题已改掉"))
    _report, out, enum, _conn = _run_leg(
        monkeypatch,
        tmp_path,
        Q_WITH,
        cat,
        usable=[_usable("doc-std", "synth-GB18466-2005.pdf")],
    )
    assert state["done"]
    assert out["coverage_status"] != "complete", out
    assert "publication window" in str(enum.get("publication_guard"))
    # old read retained as diagnosis (never silently replaced)
    assert {it["doc_id"] for it in out["answer"]["items"]} == {"doc-std", "doc-m1"}


def test_window_version_reregistration_refuses_and_old_fields_not_reverified(
    monkeypatch,
    tmp_path,
):
    """The standard re-registers version/title under the SAME snapshot inside
    the window: the full-match-set re-read AND the per-row identity re-read
    must refuse — the published OLD values stay for diagnosis but never keep
    verified+complete."""
    cat = {
        "doc-std": dict(CAT_005["doc-std"]),
        "doc-m1": dict(CAT_005["doc-m1"]),
    }

    def mutate():
        cat["doc-std"]["self_code_version"] = "2006"
        cat["doc-std"]["title"] = "当前登记已变为另一版本"

    state = _inject_before_guard(monkeypatch, mutate)
    _report, out, enum, _conn = _run_leg(
        monkeypatch,
        tmp_path,
        Q_WITH,
        cat,
        usable=[_usable("doc-std", "synth-GB18466-2005.pdf")],
    )
    assert state["done"]
    assert out["coverage_status"] != "complete", out
    assert "publication window" in str(enum.get("publication_guard"))
    std = next(it for it in out["answer"]["items"] if it["doc_id"] == "doc-std")
    assert std["citation_verified"] is False  # identity fields re-read refuses


def test_window_reread_unverifiable_never_silently_complete(monkeypatch, tmp_path):
    """When the FINAL window re-read itself cannot complete (catalog transport
    failure mid-guard), the leg must publish a non-complete terminal with the
    recorded reason — 'unverifiable' is never silently complete."""
    cat = {
        "doc-std": dict(CAT_005["doc-std"]),
        "doc-m1": dict(CAT_005["doc-m1"]),
    }
    q = Q_WITH
    # build the leg manually so the conn knob is set before run_answer
    qq = {"query_id": "uq", "question": q, "workspace": "default"}
    fused_result = ev._synthesized_fused_result(
        qq, [_usable("doc-std", "synth-GB18466-2005.pdf")], path_label="local"
    )
    fused_result["pg"]["search_id"] = ""
    conn = UnionConn(cat, fail_full_read_after=3)
    _install(monkeypatch, conn)
    fp = tmp_path / "fusion-runtime-latest.json"
    rp = tmp_path / "rerank-runtime-latest.json"
    fp.write_text(
        json.dumps(
            {"task": "t", "identity_before": IDENT, "results": [fused_result]}, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    rp.write_text(
        json.dumps({"task": "t", "identity_before": IDENT, "results": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "gold.json").write_text(
        json.dumps(
            {"questions": [dict(qq, category="file_enum")], "counter_examples": []},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(an, "GOLD_PATH", tmp_path / "gold.json")
    report = _run(
        an.run_answer(
            tmp_path / "run",
            ["uq"],
            rerank_report_path=rp,
            fused_report_path=fp,
            conn=conn,
            values=VALUES,
            allow_model=False,
            transport=None,
        )
    )
    out = report["results"][0]
    enum = next((e for e in out["expansions"] if e.get("stage") == "document_enumeration"), {})
    assert out["coverage_status"] != "complete", out
    assert "could not be completed" in str(enum.get("publication_guard"))
