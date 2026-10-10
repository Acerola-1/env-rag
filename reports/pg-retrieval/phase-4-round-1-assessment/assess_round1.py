"""Round-1 offline assessment (6.2 pause point): scores the 123 already-executed
legs against the frozen gold using ONLY local artifacts — zero model/embedding/
rerank/PG/Qdrant/Neo4j requests, zero DB, no production edits, no re-runs.

Pipeline: (1) verify inputs (manifest SHAs, gold SHA, identity/config agreement
between the anchor and the run terminals); (2) re-verify every delivered citation
against the original parsed sidecars REUSING the accepted answer-contract
functions (raw grid row coordinates / raw unit-relative complete spans /
catalog-row metadata), so scoring and generation share one citation semantics;
(3) per-category projection adjudication (missing/extra/content/wrong-doc/
unverified/incomplete-coverage) with denominators preserved — non-complete
expansion never counts exact; (4) counter behaviour judged as ACTUAL behaviour
(expected never routes); (5) doc-level recall@20 from pre-expansion discovery
only, typed evidence recall marked pending where offline mapping is insufficient;
(6) ledger/timing account corrections (reserved vs issued per leg, inclusive
rerank discovery, recorded-vs-wall attribution left unexplained).

Run:  uv run python reports/pg-retrieval/phase-4-round-1-assessment/assess_round1.py
"""

from __future__ import annotations

import hashlib
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from env_rag_final import answer as an  # noqa: E402  (accepted contract, read-only reuse)

ROUND1 = REPO / "reports/pg-retrieval/phase-4-round-1"
GOLD_PATH = REPO / "reports/pg-retrieval/gate-2/review-r5/gold-approved.json"
ANCHOR_PATH = REPO / "reports/pg-retrieval/phase-4/phase-4-config-anchor.json"
GOLD_SHA = "1bf130077c21583a89c5ca14695694d9552c558a7d8dc5d45ff0d9f72cfd7a5e"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# 1. input verification
# ---------------------------------------------------------------------------


def verify_inputs() -> dict:
    report = {"manifest": {}, "gold": {}, "identity": {}}
    man = json.loads((ROUND1 / "pilot-manifest.json").read_text(encoding="utf-8"))["files"]
    bad = []
    for rel, digest in man.items():
        p = REPO / rel
        if not p.exists() or sha(p) != digest:
            bad.append(rel)
    report["manifest"] = {"entries": len(man), "mismatches": bad}

    report["gold"] = {
        "sha": sha(GOLD_PATH),
        "expected": GOLD_SHA,
        "match": sha(GOLD_PATH) == GOLD_SHA,
    }

    terminal = json.loads((ROUND1 / "eval-runtime-latest.json").read_text(encoding="utf-8"))
    anchor = json.loads(ANCHOR_PATH.read_text(encoding="utf-8"))
    frozen = anchor["frozen_identity"]
    pre = terminal["identity_before"]
    post = terminal.get("identity_after") or {}

    def agree(ident: dict) -> dict:
        cat = ident.get("catalog_active") or {}
        return {
            "source_fingerprint": ident.get("source_fingerprint") == frozen["source_fingerprint"],
            "catalog_run_snapshot": f"{cat.get('run_id')}/{cat.get('snapshot_id')}"
            == frozen["catalog_run_snapshot"],
            "search_active": ident.get("search_active") == frozen["search_active"],
            "gold_sha": ident.get("gold_sha") == GOLD_SHA,
        }

    report["identity"] = {
        "pre": agree(pre),
        "post": agree(post) if post else "absent",
        "matches_frozen_pre": pre.get("matches_frozen"),
        "matches_frozen_post": post.get("matches_frozen"),
        "drift": terminal.get("identity_after", {}).get("problems", "n/a"),
        "run_failure": terminal.get("failure"),
        "finished_at": terminal.get("finished_at"),
    }
    return report


# ---------------------------------------------------------------------------
# 2. artifact loading + citation re-verification (contract-faithful)
# ---------------------------------------------------------------------------


def load_terminal() -> dict:
    return json.loads((ROUND1 / "eval-runtime-latest.json").read_text(encoding="utf-8"))


def answer_items(path: str, qid: str) -> tuple[list, dict]:
    p = ROUND1 / "legs" / "r1" / path / qid / "answer" / "answer-runtime-latest.json"
    if not p.exists():
        return [], {"runtime": "absent"}
    d = json.loads(p.read_text(encoding="utf-8"))
    if d.get("failure"):
        return [], {"runtime": "failure", "detail": d["failure"]}
    results = d.get("results") or []
    if not results:
        return [], {"runtime": "no-results"}
    res = results[0]
    items = (res.get("answer") or {}).get("items") or []
    meta = {
        "runtime": "ok",
        "coverage": res.get("coverage_status"),
        "model": res.get("model") or {},
        "expansions": res.get("expansions") or [],
        "reverification": res.get("reverification") or {},
    }
    return items, meta


def doc_registry() -> dict:
    """doc_id -> file_path/name map assembled from this run's own inputs and
    answer artifacts (no live lookups). Used for metadata checks & counter
    self-code sets; docs never seen in the run stay unmapped."""
    reg: dict[str, dict] = {}
    for p in (ROUND1 / "inputs").rglob("*-fusion.json"):
        data = json.loads(p.read_text(encoding="utf-8"))
        for r in data.get("results") or []:
            for u in r.get("usable") or []:
                did = u.get("doc_id")
                if did and u.get("file_path"):
                    reg.setdefault(did, {"file_path": u["file_path"]})
    return reg


def verify_citations(items: list, doc_reg: dict) -> list[dict]:
    """Independent re-read via the ACCEPTED contract functions (they re-read
    the raw parsed sidecars offline; here on copied item dicts so the frozen
    run artifacts are never mutated). Per-item verdicts, index-aligned."""
    verdicts: list[dict] = [{"verified": False, "problems": ["not re-read"]} for _ in items]
    by_doc: dict[str, list] = defaultdict(list)
    for i, it in enumerate(items):
        did = (it.get("citation") or {}).get("doc_id") or it.get("doc_id")
        if did:
            by_doc[did].append((i, it))
    for did, pair in by_doc.items():
        # catalog_row citations are self-contained metadata references —
        # re-checked WITHOUT needing the parsed sidecars
        remaining = []
        for i, it in pair:
            cit = it.get("citation") or {}
            if cit.get("kind") == "catalog_row":
                doc_ok = cit.get("doc_id") == it.get("doc_id")
                name_ok = bool(cit.get("doc_name"))
                # doc_id match but doc_name field absent in the citation (title-
                # attribution path ships no name) — a METADATA GAP to record,
                # not a content failure; never silently pass either
                verdicts[i] = {
                    "verified": bool(doc_ok and name_ok),
                    "citation_gap": bool(doc_ok and not name_ok),
                    "problems": [] if doc_ok else ["catalog row doc mismatch"],
                }
            else:
                remaining.append((i, it))
        if not remaining:
            continue
        file_path = doc_reg.get(did, {}).get("file_path")
        parsed_dir = None
        if file_path:
            try:
                parsed_dir = an._doc_parsed_dir(file_path)
            except Exception:  # noqa: BLE001 — unresolved parsed dir
                parsed_dir = None
        if parsed_dir is None or not parsed_dir.exists():
            for i, _it in remaining:
                verdicts[i] = {
                    "verified": False,
                    "problems": [f"parsed artifact unresolved for doc {did}"],
                }
            continue
        for kind, fn in (
            ("table_row", an._reverify_table_items),
            ("char_span", an._reverify_prose_items),
        ):
            subset = [
                (i, dict(it))
                for i, it in remaining
                if (it.get("citation") or {}).get("kind") == kind
            ]
            if not subset:
                continue
            copies = [c for _, c in subset]
            problems = fn(copies, parsed_dir)
            for i, copy in subset:
                if copy.get("citation_reverified"):
                    verdicts[i] = {"verified": True, "problems": []}
                else:
                    tid = (copy.get("citation") or {}).get("table_id") or ""
                    uid = (copy.get("citation") or {}).get("unit_id") or ""
                    seq = str(copy.get("seq") or "")
                    mine = [
                        p
                        for p in problems
                        if (tid and tid in p) or (uid and uid in p) or (seq and f"[{seq}]" in p)
                    ]
                    masked = any("<redacted>" in p for p in mine)
                    verdicts[i] = {
                        "verified": False,
                        "masked_cell": masked,
                        "problems": (mine or ["unverified (see row problems)"])[:1],
                    }
    return verdicts


# ---------------------------------------------------------------------------
# 3. per-category projection adjudication
# ---------------------------------------------------------------------------


def norm(s: str) -> str:
    return " ".join((s or "").split())


def row_proj(cells: list) -> tuple:
    return tuple(norm(str(c)) for c in cells)


def _cell_names_hit(item: dict, name: str) -> bool:
    """A gold 'name' is hit by a delivered row when one of its ACTUAL cells
    equals the name or the name plus a chemical-formula parenthesis — not by
    word-set or prefix matching."""
    cells = [norm(str(c)) for c in (item.get("cells") or [])]
    for c in cells:
        if c == name or (c.startswith(name + "(") and c.endswith(")")):
            return True
    return False


def table_projection(gold_expected: list) -> dict:
    """Detect the gold projection form and compare against delivered rows.
    - row+cells: raw grid row index + full cells (no re-numbering)
    - seq+cells: full cells incl. avg/level/unit distinctions
    - seq+name: identity pair
    - name only: name projection — SAME-NAME sub-rows collapse (set semantics),
      extras are still extras; a non-complete expansion can never be exact."""
    if not gold_expected:
        return {"mode": "empty_projection", "ok": False, "note": "no gold projection"}
    ks = [set(e.keys()) for e in gold_expected]
    if all({"row_in_fragment", "cells"} <= k for k in ks):
        mode = "row_cells"
    elif all({"seq", "cells"} <= k for k in ks):
        mode = "seq_cells"
    elif all({"seq", "name"} <= k for k in ks):
        mode = "seq_name"
    elif all("name" in e for e in gold_expected):
        mode = "name"
    else:
        return {"mode": "unknown_projection", "ok": False, "note": "mixed/unknown projection"}
    return {"mode": mode, "expected": gold_expected}


def table_compare(mode: str, gold_expected: list, items: list) -> dict:
    tr = [it for it in items if it.get("kind") == "table_row"]
    if mode == "row_cells":
        exp = {(e["row_in_fragment"], row_proj(e["cells"])) for e in gold_expected}
        got = {
            ((it.get("citation") or {}).get("row_in_fragment"), row_proj(it.get("cells") or []))
            for it in tr
        }
    elif mode == "seq_cells":
        exp = {(norm(str(e["seq"])), row_proj(e["cells"])) for e in gold_expected}
        got = {(norm(str(it.get("seq") or "")), row_proj(it.get("cells") or [])) for it in tr}
    elif mode == "seq_name":
        exp = {(norm(str(e["seq"])), norm(e["name"])) for e in gold_expected}
        got = set()
        for it in tr:
            for e in gold_expected:
                if norm(str(it.get("seq") or "")) == norm(str(e["seq"])) and _cell_names_hit(
                    it, norm(e["name"])
                ):
                    got.add((norm(str(e["seq"])), norm(e["name"])))
    elif mode == "name":
        exp = {norm(e["name"]) for e in gold_expected}
        got = set()
        for it in tr:
            for e in gold_expected:
                if _cell_names_hit(it, norm(e["name"])):
                    got.add(norm(e["name"]))
        # extras: delivered subject rows hitting NO expected name
        hit_any = {
            norm(e["name"])
            for e in gold_expected
            for it in tr
            if _cell_names_hit(it, norm(e["name"]))
        }
        extras = [
            it for it in tr if not any(_cell_names_hit(it, norm(e["name"])) for e in gold_expected)
        ]
        return {
            "ok": exp.issubset(got) and not extras,
            "missing": sorted(exp - got),
            "extra_rows": len(extras),
            "matched": len(hit_any),
        }
    else:
        return {"ok": False, "note": f"unsupported mode {mode}"}
    return {
        "ok": exp == got,
        "missing": sorted(str(x) for x in (exp - got)),
        "extra_rows": len(got - exp),
        "matched": len(got & exp),
    }


def _prose_expected(x) -> str:
    if isinstance(x, str):
        return norm(x)
    if isinstance(x, dict):
        return norm(
            x.get("text") or f"{x.get('number') or x.get('clause') or ''} {x.get('name') or ''}"
        )
    return norm(str(x))


def score_row(
    qid: str, path: str, entry: dict, gold_q: dict, is_counter: bool, doc_reg: dict
) -> dict:
    """Adjudicate one leg. Returns verdict WITHOUT deleting any denominator:
    every row carries category, status, missing/extra/content/unverified lists.
    expected_status is post-hoc only — never routes."""
    cat = entry["category"]
    items, meta = entry["items"], entry["meta"]
    verdicts = verify_citations(items, doc_reg) if items else []
    masked_n = sum(1 for v in verdicts if v.get("masked_cell"))
    gap_n = sum(1 for v in verdicts if v.get("citation_gap"))
    unverified_n = sum(1 for v in verdicts if not v["verified"])
    v_out = {
        "qid": qid,
        "path": path,
        "category": cat,
        "is_counter": is_counter,
        "coverage": meta.get("coverage"),
        "model_status": (meta.get("model") or {}).get("status")
        if isinstance(meta.get("model"), dict)
        else meta.get("model"),
        "delivered": len(items),
        "runtime": meta.get("runtime"),
        "budget_failure": entry.get("budget_failure"),
        "unverified_citations": [v["problems"] for v in verdicts if not v["verified"]],
        "masked_citations": masked_n,
        "citation_gaps": gap_n,
        "citation_gap_only": bool(verdicts) and unverified_n == gap_n > 0,
        "all_citations_verified": unverified_n == 0 if verdicts else None,
    }
    masking_only = verdicts and unverified_n == masked_n
    gold = (gold_q.get("gold") or {}) if gold_q else {}
    if entry.get("budget_failure"):
        v_out["judgement"] = "budget_failure"
        return v_out
    if meta.get("runtime") != "ok":
        v_out["judgement"] = "no_answer_artifact"
        return v_out

    target_docs = {t.get("doc_id") for t in (gold_q.get("target_docs") or [])} if gold_q else set()

    if cat == "file_enum":
        expected = set(gold.get("expected_doc_ids") or [])
        got = {it.get("doc_id") for it in items if it.get("kind") == "document"}
        v_out["missing"] = sorted(expected - got)
        v_out["extra"] = sorted(got - expected)
        # versions: predicate may legitimately admit title-attributed docs whose
        # self_code_version is empty — report, never fail on ''
        v_out["delivered_versions"] = sorted(
            norm(it.get("self_code_version") or "") for it in items if it.get("kind") == "document"
        )
        if v_out["missing"] or v_out["extra"]:
            v_out["judgement"] = "set_mismatch"
        elif v_out["citation_gap_only"]:
            v_out["judgement"] = "pending_citation_metadata_gap"
        elif v_out["all_citations_verified"] is False:
            v_out["judgement"] = (
                "pending_artifact_masking" if masking_only else "unverified_citation"
            )
        elif v_out["coverage"] == "complete":
            v_out["judgement"] = "pass_mechanical"
        else:
            v_out["judgement"] = "coverage_not_complete"
        return v_out

    if cat == "prose_enum":
        expected = [_prose_expected(x) for x in (gold.get("expected_items") or [])]
        in_scope = [
            it
            for it in items
            if it.get("doc_id") in target_docs
            or (it.get("citation") or {}).get("doc_id") in target_docs
        ]
        out_of_scope = [it for it in items if it not in in_scope]
        matched = set()
        for e_idx, e in enumerate(expected):
            for it in in_scope:
                g = norm(it.get("text") or "")
                if g.startswith(e) or e in g:
                    matched.add(e_idx)
                    break
        missing = [expected[i] for i in range(len(expected)) if i not in matched]
        v_out["missing"] = missing
        v_out["extra_out_of_scope"] = len(out_of_scope)
        v_out["extra_in_scope"] = max(0, len(in_scope) - len(matched))
        if missing or out_of_scope or v_out["extra_in_scope"]:
            v_out["judgement"] = "projection_mismatch"
        elif v_out["all_citations_verified"] is False:
            v_out["judgement"] = (
                "pending_artifact_masking" if masking_only else "unverified_citation"
            )
        elif v_out["coverage"] == "complete":
            v_out["judgement"] = "pass_mechanical"
        else:
            v_out["judgement"] = "coverage_not_complete"
        return v_out

    if cat == "table_enum":
        exp = gold.get("expected_items") or []
        proj = table_projection(exp)
        v_out["projection_mode"] = proj["mode"]
        cmp_ = (
            table_compare(proj["mode"], proj.get("expected") or [], items)
            if proj["mode"] not in ("unknown_projection", "empty_projection")
            else {"ok": False, "note": proj.get("note")}
        )
        v_out["projection"] = cmp_
        tr_docs = {
            (it.get("citation") or {}).get("doc_id")
            for it in items
            if it.get("kind") == "table_row"
        }
        v_out["foreign_table_docs"] = sorted(
            d for d in tr_docs if target_docs and d not in target_docs
        )
        if v_out["foreign_table_docs"]:
            v_out["judgement"] = "foreign_doc_rows"
        elif not cmp_.get("ok"):
            v_out["judgement"] = "projection_mismatch"
        elif v_out["all_citations_verified"] is False:
            v_out["judgement"] = (
                "pending_artifact_masking" if masking_only else "unverified_citation"
            )
        elif v_out["coverage"] == "complete":
            v_out["judgement"] = "pass_mechanical"
        else:
            v_out["judgement"] = "coverage_not_complete"
        return v_out

    if cat == "fact":
        quote = gold.get("supporting_quote")
        if not quote:
            v_out["judgement"] = "pending_gold_projection"
            return v_out
        exp_row = row_proj(str(quote).split("|"))
        tr = [it for it in items if it.get("kind") == "table_row"]
        others = [it for it in items if it.get("kind") != "table_row"]
        matches = [it for it in tr if row_proj(it.get("cells") or []) == exp_row]
        # question-level binding tokens: subject(2)/average(3)/value(4)/unit(6)
        bind_tokens = (
            {exp_row[1], exp_row[2], exp_row[3], exp_row[5]} if len(exp_row) >= 7 else set()
        )
        prose_bound = []
        for it in others:
            plain = re.sub(r"<[^>]+>", " ", str(it.get("text") or ""))
            prose_bound.append(bool(bind_tokens) and all(tok in norm(plain) for tok in bind_tokens))
        v_out["row_candidates"] = len(tr)
        v_out["exact_row_delivered"] = bool(matches)
        v_out["prose_claims_bind_value"] = prose_bound
        if not items:
            v_out["judgement"] = f"no_delivery_coverage_{v_out.get('coverage')}"
        elif matches:
            if not v_out["all_citations_verified"]:
                v_out["judgement"] = (
                    "pending_artifact_masking" if masking_only else "unverified_citation"
                )
            elif v_out["coverage"] == "complete":
                v_out["judgement"] = "pass_mechanical"
            else:
                v_out["judgement"] = "partial_fragment_correct"
        elif others and all(prose_bound):
            v_out["judgement"] = (
                "pass_mechanical" if v_out["coverage"] == "complete" else "partial_fragment_correct"
            )
        elif others:
            v_out["judgement"] = "pending_fact_carrier_review"
        else:
            v_out["judgement"] = "value_not_bound_or_mismatched"
        return v_out

    if cat == "synthesis":
        expected = str(gold.get("expected") or "")
        cond_tokens = sorted(
            {
                t
                for grp in re.findall(r"[（(]([^（）()]+)[)）]", expected)
                for t in re.split(r"[、，,;；/]", grp)
                if norm(t)
            }
        )[:12]
        claim_blob = norm(
            " ".join(
                str((it.get("citation") or {}).get("claim") or "")
                + " "
                + str(it.get("claim") or "")
                + " "
                + str(it.get("text") or "")
                for it in items
            )
        )
        missing_conditions = [t for t in cond_tokens if t and t not in claim_blob]
        bound = all(bool((it.get("citation") or {}).get("quote")) for it in items) and (
            v_out["all_citations_verified"] is not False
        )
        v_out["gold_expected"] = expected[:140]
        v_out["condition_tokens"] = cond_tokens
        v_out["missing_conditions"] = missing_conditions
        v_out["all_claims_bound"] = bound if items else None
        v_out["judgement"] = "synthesis_pending_human_review"
        return v_out

    v_out["judgement"] = "unknown_category"
    return v_out


# ---------------------------------------------------------------------------
# 3b. counter-example behaviour judgements (expected never routes)
# ---------------------------------------------------------------------------


def self_code_docs(doc_reg: dict, needle: str) -> set:
    return {d for d, e in doc_reg.items() if needle in str(e.get("file_path", ""))}


def score_counter_row(
    qid: str, path: str, v_out: dict, entry: dict, counter: dict, doc_reg: dict, table13: list
) -> dict:
    items = entry["items"]
    if qid == "neg-003":
        expected = self_code_docs(doc_reg, "GB3838-2002")
        got = {it.get("doc_id") for it in items if it.get("kind") == "document"}
        v_out["self_code_subset_expected"] = sorted(expected)
        v_out["delivered"] = sorted(got)
        v_out["extra_citation_only"] = sorted(got - expected)
        v_out["missing_self_code"] = sorted(expected - got)
        v_out["judgement"] = (
            "behaviour_ok_mechanical"
            if expected
            and not v_out["extra_citation_only"]
            and not v_out["missing_self_code"]
            and v_out["coverage"] == "complete"
            else "behaviour_violation_or_incomplete"
        )
    elif qid == "neg-004":
        cmp_ = table_compare("seq_cells", table13, items)
        foreign_docs = sorted(
            {
                (it.get("citation") or {}).get("doc_id")
                for it in items
                if (it.get("citation") or {}).get("doc_id")
                != "doc-b45c510232ed4d2452b0f5b2a13434e4"
            }
        )
        v_out["projection"] = cmp_
        v_out["target13_complete"] = not cmp_.get("missing")
        v_out["extra_rows"] = cmp_.get("extra_rows")
        v_out["foreign_table_docs"] = foreign_docs
        v_out["judgement"] = (
            "behaviour_ok_mechanical"
            if cmp_.get("ok")
            and not foreign_docs
            and v_out["all_citations_verified"]
            and v_out["coverage"] == "complete"
            else "set_violation"
        )
    elif qid == "neg-005":
        docs = sorted(
            {
                (it.get("citation") or {}).get("doc_id")
                for it in items
                if (it.get("citation") or {}).get("doc_id")
            }
        )
        v_out["delivered_rows"] = len(items)
        v_out["docs_cited"] = docs
        merged_cross_doc = len(docs) > 1 and v_out["coverage"] == "complete"
        v_out["judgement"] = (
            "behaviour_violation_merges_or_overclaims"
            if (merged_cross_doc or (v_out["coverage"] == "complete" and docs))
            else "pending_status_review"
        )
    elif qid == "neg-008":
        v_out["judgement"] = (
            "budget_refused_at_pg_guard; members/chars expansion path NOT exercised in production"
        )
    else:
        v_out["judgement"] = (
            f"behaviour_recorded coverage={v_out.get('coverage')} delivered={v_out.get('delivered')}"
        )
    v_out["counter_expected_status"] = counter.get("expected_status")
    return v_out


# ---------------------------------------------------------------------------
# 4. recall (pre-expansion discovery only)
# ---------------------------------------------------------------------------


def pre_expansion_docs(qid: str, path: str) -> list | None:
    """Discovery candidate doc list BEFORE expansion/rerank, per path."""
    if path in ("pg", "fusion"):
        p = ROUND1 / "legs" / "r1" / path / qid / "fusion" / "fusion-runtime-latest.json"
        if not p.exists():
            return None
        r0 = json.loads(p.read_text(encoding="utf-8")).get("results", [{}])[0]
        cands = r0.get("candidates")
        if not isinstance(cands, list):
            return None
        docs: list[str] = []
        for c in cands:
            did = c.get("doc_id") if isinstance(c, dict) else None
            if did:
                docs.append(did)
        return docs
    # local: inputs fused usable == the adapter's verified discovery (expansion
    # happened afterwards in the answer stage)
    p = ROUND1 / "inputs" / "local" / f"{qid}-fusion.json"
    if not p.exists():
        return None
    r0 = json.loads(p.read_text(encoding="utf-8")).get("results", [{}])[0]
    return [u.get("doc_id") for u in r0.get("usable") or [] if u.get("doc_id")]


def recall_report(gold: dict) -> dict:
    out = {
        "doc_recall": {},
        "typed_evidence_recall": "pending",
        "notes": "doc-level only; chunk->unit typed mapping not available offline (catalog-side), marked pending per handoff; pre-expansion lists, no rerank/expansion backfill",
    }
    for q in gold["questions"]:
        expected = {t.get("doc_id") for t in q.get("target_docs") or []}
        if not expected:
            continue
        row = {}
        for path in ("pg", "local", "fusion"):
            docs = pre_expansion_docs(q["query_id"], path)
            if docs is None:
                row[path] = "pending"
            else:
                hit = len({d for d in docs[:20]} & expected)
                row[path] = {"n": len(docs), "recall": round(hit / len(expected), 3)}
        out["doc_recall"][q["query_id"]] = row
    return out


# ---------------------------------------------------------------------------
# 5. ledger + timing corrections
# ---------------------------------------------------------------------------


def ledger_corrections(terminal: dict) -> dict:
    snap = terminal["budget_snapshot_end"]
    per = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # leg -> svc -> [reserved, issued]
    for e in snap["events"]:
        leg = e["where"].split(":")[0]
        if e["kind"] == "reserved":
            per[leg][e["service"]][0] += e["amount"]
        elif e["kind"] == "issued":
            per[leg][e["service"]][1] += e["amount"]
    diffs = []
    for leg, svcs in sorted(per.items()):
        for svc, (r, i) in svcs.items():
            if r != i:
                diffs.append({"leg": leg, "service": svc, "reserved": r, "issued": i})

    # timing
    def pct(vals):
        vals = sorted(vals)
        if not vals:
            return None
        idx = min(len(vals) - 1, int(round(0.95 * (len(vals) - 1))))
        return {"n": len(vals), "p50": statistics.median(vals), "p95": vals[idx], "max": vals[-1]}

    disc_incl, disc_excl, rer, ans, tot = [], [], [], [], []
    for r in terminal["results"]:
        t = r.get("timings", {})
        d = t.get("discovery_ms")
        rk = t.get("rerank_ms")
        if d is not None:
            disc_incl.append(d)
            if rk is not None:
                disc_excl.append(d - rk)
        if rk is not None:
            rer.append(rk)
        a = (r.get("answer") or {}).get("latency_ms")
        if a is not None:
            ans.append(a)
        if t.get("total_ms") is not None:
            tot.append(t["total_ms"])
    total_sum_ms = sum(t["timings"].get("total_ms", 0) for t in terminal["results"])
    first_art = min((f.stat().st_mtime for f in ROUND1.rglob("*") if f.is_file()), default=None)
    last_art = max((f.stat().st_mtime for f in ROUND1.rglob("*") if f.is_file()), default=None)
    return {
        "reserved_vs_issued_diffs": diffs,
        "note_prev_claim": "round-1-report §2 '除 neg-008 外 120 腿逐服务 issued==reserved' 系误写：PG/qdrant/... 相等，但 answer_llm 有 10 条腿预留 1 实发 0（incomplete_conditions，HTTP 未发出）——以本表为准",
        "timings": {
            "discovery_inclusive_rerank_ms": pct(disc_incl),
            "discovery_exclusive_rerank_approx_ms": pct(disc_excl),
            "rerank_ms": pct(rer),
            "answer_ms_composite_unsplit": pct(ans),
            "total_ms_recorded": pct(tot),
            "answer_stage_stages_unavailable": "answer_ms 内含范围展开/生成/复核，独立阶段计时 unavailable；模型 call.latency 仅 HTTP 时间不冒充全生成",
        },
        "recorded_total_sum_s": round(total_sum_ms / 1000, 3),
        "wall_artifact_mtime_span_s": round(last_art - first_art, 1)
        if first_art and last_art
        else None,
        "wall_note": "前报告 '约44分钟' 为作者报告（依据后台任务起止通知时刻差），非工件自证；已记录总和与墙钟差不可归因部分不做解释",
        "serial_cache_condition": "单轮串行执行、无跨题缓存复用（每腿新发现/回读/冷生成）；数值不代表并发或热缓存性能",
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    out_dir = Path(__file__).parent
    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    gold_by = {q["query_id"]: q for q in gold["questions"]}
    for c in gold["counter_examples"]:
        gold_by[c["counter_id"]] = {
            "query_id": c["counter_id"],
            "category": None,
            "target_docs": [],
            "gold": {},
            "counter": c,
        }
    terminal = load_terminal()
    doc_reg = doc_registry()
    table13 = next(
        (q["gold"].get("expected_items") or [])
        for q in gold["questions"]
        if q["query_id"] == "table-enum-001"
    )
    verdicts = []
    for r in terminal["results"]:
        qid = r["query_id"]
        entry = {
            "category": r["category"],
            "items": [],
            "meta": {"runtime": "absent"},
            "budget_failure": (r.get("budget_failure") or {}).get("stage"),
        }
        items, meta = answer_items(r["path"], qid)
        entry["items"], entry["meta"] = items, meta
        gq = gold_by.get(qid) or {}
        if gq.get("category") is None and gq.get("counter"):
            # counters: behaviour over the CURRENT artifacts; the category
            # projection only runs where gold gives one (neg-003/004/005 do)
            v = score_row(qid, r["path"], entry, gq, True, doc_reg)
            v["counter_type"] = gq["counter"].get("type")
            v["counter_expected_status"] = gq["counter"].get("expected_status")
            if qid in ("neg-003", "neg-004", "neg-005"):
                v = score_counter_row(qid, r["path"], v, entry, gq["counter"], doc_reg, table13)
            elif v["judgement"].startswith("projection") or v["judgement"] == "unknown_category":
                v["judgement"] = "pending_behaviour_review"
            else:
                v["judgement"] = f"counter_{v['judgement']}"
        else:
            v = score_row(qid, r["path"], entry, gq, bool(r["is_counter"]), doc_reg)
        verdicts.append(v)
    results = {
        "inputs_verification": verify_inputs(),
        "rows": verdicts,
        "recall": recall_report(gold),
        "ledger_and_timing": ledger_corrections(terminal),
    }
    (out_dir / "adjudication.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    # summary
    byj = defaultdict(int)
    for v in verdicts:
        byj[v["judgement"]] += 1
    print("rows:", len(verdicts))
    print(json.dumps(dict(byj), ensure_ascii=False, indent=1))
    print("inputs:", json.dumps(results["inputs_verification"]["manifest"], ensure_ascii=False))
    print(
        "gold match:",
        results["inputs_verification"]["gold"]["match"],
        "| identity agree:",
        results["inputs_verification"]["identity"]["pre"],
    )
    print(
        "ledger diffs count:",
        len(results["ledger_and_timing"]["reserved_vs_issued_diffs"]),
        "| recorded total s:",
        results["ledger_and_timing"]["recorded_total_sum_s"],
        "| wall span s:",
        results["ledger_and_timing"]["wall_artifact_mtime_span_s"],
    )


if __name__ == "__main__":
    main()
