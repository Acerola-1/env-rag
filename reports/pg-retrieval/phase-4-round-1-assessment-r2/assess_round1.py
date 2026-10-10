"""Round-1 offline assessment — generation r2 (fixes A1–A6, 2026-10-08).

Same scope as the withdrawn generation: score the 123 already-executed legs
against the frozen gold using ONLY local artifacts — zero model/embedding/
rerank/PG/Qdrant/Neo4j requests, zero DB, no production edits, no re-runs.
The original directory (phase-4-round-1-assessment/) is preserved untouched;
this generation replaces its mechanical verdicts.

Policy corrections carried here (per handoff-phase-4-offline-assessment-fixes-r1):

A1  prose adjudication binds the DECLARED CLAUSE NUMBER + asked content + doc/
    version scope (a real quote with a fabricated clause number fails);
    seq_name table projections are built FROM THE DELIVERED ROWS so unmatched
    genuine source rows count as extras instead of vanishing; legitimate
    same-name sub-row consumption in name-only projections is kept.
A2  fact: NO carrier may pass without independent citation verification;
    mechanical pass only when the gold answer ROW itself is delivered exactly;
    prose carriers are never mechanically bound by fixed-index token guessing —
    they stay for human review. fact-002-style correct fragments are retained.
A3  every citation (table/prose/catalog) is checked against the frozen guard
    identity: workspace + catalog snapshot + doc present in SHA-guarded run
    inputs; catalog doc_name must match the independent filename (or be
    located through it), never mere self-consistency; counter behaviour
    scoring cannot bypass this source qualification.
A4  input integrity is a pre-scoring REJECT GATE: manifest, gold SHA, anchor/
    config, pre/post run identity, reused-code SHA and parsed-evidence presence
    are verified first; any problem -> sanitized input-rejection diagnostic,
    non-zero raise, and NO adjudication is produced.
A5  discovery reads BOTH segments saved by fusion._normalize_pg: chunk
    candidates AND typed targets (file/scope discovery is real pre-expansion
    discovery, e.g. file-enum-005/pg discovery_total=3 chunks=0). Chunk-ranked
    recall and typed coverage are reported SEPARATELY; nothing is concatenated
    into a fake unified recall@20; usable/targets_resolved never backfill;
    the old pg 0.959 / local 0.952 / fusion 0.991 averages are WITHDRAWN.
A6  every canonical row carries final_status PASS/FAIL/PENDING + decisive
    reason; a decisive whole-question failure (projection/set/contract/
    coverage/manual) outranks any item-level unknown (masked cells stay
    recorded as pending details without turning the row PENDING); the 18
    audited synthesis failures are written per row with reason + actual
    delivery; counters keep behaviour-first judgement, expected never routes.

Run:  uv run python reports/pg-retrieval/phase-4-round-1-assessment-r2/assess_round1.py
The frozen review matrix is run against this file via
ENV_RAG_ASSESSMENT_SCRIPT=<abs path> (see the r1 review handoff).
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

POSITIVE_PATHS = ("pg", "local", "fusion")


class InputIntegrityError(RuntimeError):
    """Raised BEFORE any scoring when an input-identity problem is found."""


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _load_anchor() -> dict:
    return json.loads(ANCHOR_PATH.read_text(encoding="utf-8"))


def _frozen_identity() -> dict:
    """Guard identity frozen for this round: workspace/snapshot from the
    approved config anchor (zero-backend read of an already-frozen file)."""
    a = _load_anchor()
    fi = a["frozen_identity"]
    run_id, snap = fi["catalog_run_snapshot"].split("/")
    ws = re.search(r"PG (\S+) <->", fi["workspace_mapping"]).group(1)
    return {
        "workspace": ws,
        "catalog_snapshot_id": snap,
        "catalog_run_id": run_id,
        "source_fingerprint": fi["source_fingerprint"],
        "search_active": fi["search_active"],
    }


try:  # anchor is a frozen input; import stays offline
    FROZEN_IDENTITY = _frozen_identity()
except Exception:  # noqa: BLE001 — surfaced as an input problem in verify_inputs
    FROZEN_IDENTITY = None


# ---------------------------------------------------------------------------
# 1. input verification — A4: reject before scoring, never publish on mismatch
# ---------------------------------------------------------------------------


def verify_inputs() -> dict:
    problems: list[str] = []
    report = {"manifest": {}, "gold": {}, "identity": {}, "code": {}, "parsed": {}, "problems": []}

    man_path = ROUND1 / "pilot-manifest.json"
    if not man_path.exists():
        problems.append("run manifest missing")
        man = {}
    else:
        man = json.loads(man_path.read_text(encoding="utf-8"))["files"]
    bad = [rel for rel, digest in man.items() if not (REPO / rel).exists() or sha(REPO / rel) != digest]
    report["manifest"] = {"entries": len(man), "mismatches": bad}
    if bad or not man:
        problems.append(f"run manifest mismatch/empty: {len(bad)} of {len(man)}")

    gsha = sha(GOLD_PATH)
    report["gold"] = {"sha": gsha, "expected": GOLD_SHA, "match": gsha == GOLD_SHA}
    if gsha != GOLD_SHA:
        problems.append("gold SHA mismatch")

    if FROZEN_IDENTITY is None:
        problems.append("config anchor unreadable")
        report["identity"] = {"error": "anchor unreadable"}
    else:
        try:
            anchor = _load_anchor()
            terminal = load_terminal()
        except Exception as exc:  # noqa: BLE001
            problems.append(f"anchor/terminal unreadable: {type(exc).__name__}")
            report["identity"] = {"error": str(type(exc).__name__)}
            anchor = None
        if anchor is not None:
            fi = anchor["frozen_identity"]
            if fi.get("gold_sha256") != GOLD_SHA or fi.get("gold_file") != str(
                GOLD_PATH.relative_to(REPO)
            ):
                problems.append("anchor gold identity mismatch")
            pre = terminal["identity_before"]
            post = terminal.get("identity_after") or {}

            def agree(ident: dict) -> dict:
                cat = ident.get("catalog_active") or {}
                return {
                    "source_fingerprint": ident.get("source_fingerprint") == fi["source_fingerprint"],
                    "catalog_run_snapshot": f"{cat.get('run_id')}/{cat.get('snapshot_id')}"
                    == fi["catalog_run_snapshot"],
                    "search_active": ident.get("search_active") == fi["search_active"],
                    "gold_sha": ident.get("gold_sha") == GOLD_SHA,
                }

            a_pre, a_post = agree(pre), (agree(post) if post else {})
            report["identity"] = {
                "pre": a_pre,
                "post": a_post or "absent",
                "matches_frozen_pre": pre.get("matches_frozen"),
                "matches_frozen_post": post.get("matches_frozen") if post else None,
                "run_failure": terminal.get("failure"),
                "finished_at": terminal.get("finished_at"),
            }
            if not all(a_pre.values()) or pre.get("matches_frozen") is not True:
                problems.append("run pre-identity disagrees with frozen anchor")
            if post and (not all(a_post.values()) or post.get("matches_frozen") is not True):
                problems.append("run post-identity disagrees with frozen anchor")
            if terminal.get("failure") is not None:
                problems.append("run terminal carries a failure")
            if not terminal.get("finished_at"):
                problems.append("run terminal not finished")

            ca = anchor.get("code_anchors") or {}
            code_ok = {}
            for fname in ("answer.py", "fusion.py"):
                want = ca.get(fname)
                got = sha(REPO / "src/env_rag_final" / fname)
                code_ok[fname] = {"match": bool(want) and got == want}
                if not code_ok[fname]["match"]:
                    problems.append(f"reused code identity drift: {fname}")
            report["code"] = code_ok

    reg = doc_registry()
    if not reg:
        problems.append("doc registry empty (inputs unusable)")
    unresolved = []
    for did, ent in reg.items():
        try:
            pd = an._doc_parsed_dir(ent["file_path"])
        except Exception:  # noqa: BLE001
            pd = None
        if pd is None or not Path(pd).exists():
            unresolved.append(did)
    report["parsed"] = {"docs": len(reg), "unresolved": len(unresolved)}
    if unresolved:
        problems.append(f"parsed sidecars unavailable for {len(unresolved)} input docs")

    report["problems"] = problems
    report["ok"] = not problems
    return report


# ---------------------------------------------------------------------------
# 2. artifact loading + citation re-verification (contract-faithful + identity)
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
        "leg_workspace": res.get("workspace"),
    }
    return items, meta


def doc_registry() -> dict:
    """doc_id -> file_path/name assembled from this run's SHA-guarded inputs
    (pre-answer discovery artifacts), never from the answers themselves.
    Independent name/metadata evidence for A3 catalog checks."""
    reg: dict[str, dict] = {}
    for p in (ROUND1 / "inputs").rglob("*-fusion.json"):
        data = json.loads(p.read_text(encoding="utf-8"))
        for r in data.get("results") or []:
            for u in r.get("usable") or []:
                did = u.get("doc_id")
                if did and u.get("file_path"):
                    reg.setdefault(did, {"file_path": u["file_path"], "name": Path(u["file_path"]).name})
    return reg


def _identity_problems(cit: dict, ident: dict) -> list[str]:
    probs = []
    ws = cit.get("workspace")
    if ws != ident["workspace"]:
        probs.append(f"citation workspace {ws!r} != frozen guard {ident['workspace']!r}")
    snap = cit.get("snapshot_id")
    if snap != ident["catalog_snapshot_id"]:
        probs.append(f"citation snapshot {snap!r} != frozen catalog snapshot {ident['catalog_snapshot_id']!r}")
    return probs


_FILENAME_CODE = re.compile(r"(GB\s?\d+(?:\.\d+)?)[-–—](\d{4})")


def _catalog_name_check(it: dict, cit: dict, reg_entry: dict | None) -> tuple[bool, list[str], bool]:
    """A3: real-name/metadata grounded in the SHA-guarded run inputs only.
    Returns (grounded, problems, gap_note)."""
    problems: list[str] = []
    if reg_entry is None:
        # no independent evidence at all: a metadata GAP to adjudicate as
        # pending, never a silent pass and never the answer self-certifying
        return False, ["catalog doc not present in SHA-guarded run inputs (no independent evidence)"], True
    base = reg_entry["name"]
    gap = False
    cited_name = cit.get("doc_name")
    if cited_name is None:
        # redundant field absent: located through the independent input mapping
        gap = True
    elif norm(str(cited_name)) != norm(base):
        problems.append(f"catalog doc_name mismatch: citation {cited_name!r} vs independent input {base!r}")
    item_name = it.get("doc_name")
    if item_name is not None and norm(str(item_name)) != norm(base) and not problems:
        problems.append(f"item doc_name mismatch: {item_name!r} vs independent input {base!r}")
    code = it.get("self_code")
    ver = it.get("self_code_version")
    if code or ver:
        m = _FILENAME_CODE.search(base)
        if m:
            if code and norm(str(code)).replace(" ", "") != m.group(1).replace(" ", ""):
                problems.append(f"self_code {code!r} contradicts independent filename code {m.group(1)!r}")
            if ver and str(ver) != m.group(2):
                problems.append(f"self_code_version {ver!r} contradicts independent filename year {m.group(2)!r}")
    return not problems, problems, gap


def verify_citations(items: list, doc_reg: dict, identity: dict | None = None) -> list[dict]:
    """Independent re-read via the ACCEPTED contract functions (raw grid rows /
    raw unit-relative spans), PLUS the frozen guard identity of A3: workspace,
    catalog snapshot, and doc presence in SHA-guarded run inputs are checked
    for table/prose/catalog alike; content re-read existence is only one part.
    A re-read that passes cannot rescue a citation with wrong identity, and a
    catalog reference cannot self-certify: its name/metadata must agree with
    the independent input evidence."""
    ident = identity or FROZEN_IDENTITY or {"workspace": "default", "catalog_snapshot_id": "4919b3938ad93747"}
    verdicts: list[dict] = [{"verified": False, "problems": ["not re-read"]} for _ in items]
    by_doc: dict[str, list] = defaultdict(list)
    for i, it in enumerate(items):
        cit = it.get("citation") or {}
        did = cit.get("doc_id") or it.get("doc_id")
        if did:
            by_doc[did].append((i, it))
    for did, pair in by_doc.items():
        remaining = []
        for i, it in pair:
            cit = it.get("citation") or {}
            idp = _identity_problems(cit, ident)
            if cit.get("kind") == "catalog_row":
                if cit.get("doc_id") != it.get("doc_id"):
                    idp.append("catalog row doc mismatch")
                grounded, namep, gap = _catalog_name_check(it, cit, doc_reg.get(did))
                probs = idp + namep
                verdicts[i] = {
                    "verified": grounded and not idp,
                    "citation_gap": bool(gap),
                    "problems": probs[:3],
                }
            elif cit.get("kind") not in ("table_row", "char_span"):
                verdicts[i] = {"verified": False, "problems": (idp + [f"citation kind {cit.get('kind')!r} not re-readable offline"])[:3]}
            else:
                remaining.append((i, it, idp))
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
            for i, _it, idp in remaining:
                verdicts[i] = {
                    "verified": False,
                    "problems": (idp + [f"parsed artifact unresolved for doc {did}"])[:3],
                }
            continue
        for kind, fn in (
            ("table_row", an._reverify_table_items),
            ("char_span", an._reverify_prose_items),
        ):
            subset = [(i, dict(it), idp) for i, it, idp in remaining if (it.get("citation") or {}).get("kind") == kind]
            if not subset:
                continue
            copies = [c for _, c, _ in subset]
            problems = fn(copies, parsed_dir)
            for i, copy, idp in subset:
                if copy.get("citation_reverified") and not idp:
                    verdicts[i] = {"verified": True, "problems": []}
                elif copy.get("citation_reverified"):
                    # A3: source existence alone cannot qualify a wrong identity
                    verdicts[i] = {"verified": False, "problems": idp[:3]}
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
                        "problems": (idp + (mine or ["unverified (see row problems)"]))[:3],
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
    - seq+name: identity pair — the projection is formed FROM DELIVERED ROWS
      (A1): a genuine source row that matches no expected (seq,name) pair is
      an EXTRA, not an invisible row; legitimate same-pair duplicates collapse
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
        extras: list[dict] = []
        for it in tr:
            hit = None
            for e in gold_expected:
                if norm(str(it.get("seq") or "")) == norm(str(e["seq"])) and _cell_names_hit(
                    it, norm(e["name"])
                ):
                    hit = (norm(str(e["seq"])), norm(e["name"]))
                    break
            if hit is not None:
                got.add(hit)
            else:
                extras.append(
                    {
                        "seq": norm(str(it.get("seq") or "")),
                        "row_cells_head": row_proj((it.get("cells") or [])[:2]),
                    }
                )
        return {
            "ok": exp == got and not extras,
            "missing": sorted(str(x) for x in (exp - got)),
            "extra_rows": len(extras),
            "extras": extras[:5],
            "matched": len(got & exp),
        }
    elif mode == "name":
        exp = {norm(e["name"]) for e in gold_expected}
        got = set()
        for it in tr:
            for e in gold_expected:
                if _cell_names_hit(it, norm(e["name"])):
                    got.add(norm(e["name"]))
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


def _prose_spec(x) -> dict:
    """A1: gold prose expectations bind the CLAUSE NUMBER and the asked
    content separately when the gold carries them."""
    if isinstance(x, dict):
        clause = norm(str(x.get("clause") or x.get("number") or ""))
        content = norm(str(x.get("text") or ""))
        if not content:
            content = norm(f"{clause} {x.get('name') or ''}".strip())
        return {"clause": clause, "content": content, "display": _prose_expected(x)}
    s = norm(str(x))
    return {"clause": "", "content": s, "display": s}


def _prose_match(spec: dict, it: dict) -> bool:
    g = norm(it.get("text") or "")
    if spec["clause"]:
        if norm(str(it.get("clause") or "")) != spec["clause"]:
            return False
    return bool(spec["content"]) and spec["content"] in g


def _coverage_fail(v_out: dict) -> str:
    """A6: non-complete expansion is a DECISIVE whole-question failure, not a
    hold-for-unknown. Masked/unverified details stay recorded separately."""
    return "coverage_not_complete"


def score_row(
    qid: str, path: str, entry: dict, gold_q: dict, is_counter: bool, doc_reg: dict
) -> dict:
    """Frozen-matrix interface: adjudicate one leg and return the verdict
    WITHOUT deleting any denominator. Positive rows carry their canonical
    final_status directly (A6); counter rows receive final_status only after
    score_counter_row overrides the behaviour judgement."""
    v_out = _score_row_impl(qid, path, entry, gold_q, is_counter, doc_reg)
    if not is_counter:
        finalize_positive(v_out, None)
    return v_out


def _score_row_impl(
    qid: str, path: str, entry: dict, gold_q: dict, is_counter: bool, doc_reg: dict
) -> dict:
    """expected_status is post-hoc only — never routes."""
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
        v_out["delivered_versions"] = sorted(
            norm(it.get("self_code_version") or "") for it in items if it.get("kind") == "document"
        )
        if v_out["missing"] or v_out["extra"]:
            v_out["judgement"] = "set_mismatch"
        elif v_out["coverage"] != "complete":
            v_out["judgement"] = _coverage_fail(v_out)
        elif v_out["citation_gap_only"]:
            # set + coverage clean but citation location could not be grounded
            # in independent evidence — pending, never silently passed
            v_out["judgement"] = "pending_citation_metadata_gap"
        elif v_out["all_citations_verified"] is False:
            v_out["judgement"] = (
                "pending_artifact_masking" if masking_only else "unverified_citation"
            )
        else:
            v_out["judgement"] = "pass_mechanical"
        return v_out

    if cat == "prose_enum":
        specs = [_prose_spec(x) for x in (gold.get("expected_items") or [])]
        in_scope = [
            it
            for it in items
            if it.get("doc_id") in target_docs
            or (it.get("citation") or {}).get("doc_id") in target_docs
        ]
        out_of_scope = [it for it in items if it not in in_scope]
        used: set[int] = set()
        matched_idx = set()
        for e_idx, spec in enumerate(specs):
            for j, it in enumerate(in_scope):
                if j in used:
                    continue
                if _prose_match(spec, it):
                    used.add(j)
                    matched_idx.add(e_idx)
                    break
        missing = [specs[i]["display"] for i in range(len(specs)) if i not in matched_idx]
        v_out["missing"] = missing
        v_out["extra_out_of_scope"] = len(out_of_scope)
        v_out["extra_in_scope"] = len(in_scope) - len(used)
        if missing or out_of_scope or v_out["extra_in_scope"]:
            v_out["judgement"] = "projection_mismatch"
        elif v_out["coverage"] != "complete":
            v_out["judgement"] = _coverage_fail(v_out)
        elif v_out["all_citations_verified"] is False:
            v_out["judgement"] = (
                "pending_artifact_masking" if masking_only else "unverified_citation"
            )
        else:
            v_out["judgement"] = "pass_mechanical"
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
        elif v_out["coverage"] != "complete":
            v_out["judgement"] = _coverage_fail(v_out)
        elif v_out["all_citations_verified"] is False:
            v_out["judgement"] = (
                "pending_artifact_masking" if masking_only else "unverified_citation"
            )
        else:
            v_out["judgement"] = "pass_mechanical"
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
        # A2: NO fixed-index token guessing. Mechanical pass requires the gold
        # answer ROW itself delivered exactly; prose carriers can never pass
        # mechanically — they stay for human review with citation status
        # recorded.
        v_out["row_candidates"] = len(tr)
        v_out["exact_row_delivered"] = bool(matches)
        if not items:
            v_out["judgement"] = f"no_delivery_coverage_{v_out.get('coverage')}"
        elif matches:
            if v_out["all_citations_verified"] is False and v_out["coverage"] != "complete":
                v_out["judgement"] = "partial_unverified"
            elif v_out["all_citations_verified"] is False:
                v_out["judgement"] = (
                    "pending_artifact_masking" if masking_only else "unverified_citation"
                )
            elif v_out["coverage"] == "complete":
                v_out["judgement"] = "pass_mechanical"
            else:
                v_out["judgement"] = "partial_fragment_correct"
                v_out["correct_fragments"] = [row_proj(it.get("cells") or []) for it in matches]
        elif tr:
            v_out["judgement"] = "value_not_bound_or_mismatched"
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
    """A3: counter behaviour cannot bypass the common source qualification —
    behaviour_ok requires citations verified under the same guard."""
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
            and v_out["all_citations_verified"] is True
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
            and v_out["all_citations_verified"] is True
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
        # NOT claiming underlying table identity interleaving — only the
        # frozen ambiguous/complete behaviour contract is judged here.
    elif qid == "neg-008":
        v_out["judgement"] = "budget_refused_at_pg_guard_expected"
        v_out["coverage_gap"] = (
            "members/chars expansion path NOT exercised in production this round"
        )
    else:
        v_out["judgement"] = (
            f"behaviour_recorded coverage={v_out.get('coverage')} delivered={v_out.get('delivered')}"
        )
    v_out["counter_expected_status"] = counter.get("expected_status")
    return v_out


# ---------------------------------------------------------------------------
# 3c. A6 final adjudication layer (canonical final_status)
# ---------------------------------------------------------------------------

_MANUAL = {
    ("syn-001", "pg"): "incomplete_conditions：请求版本对（GB3095-2012/2026）未在读取范围全部解决 → HTTP 未发出、0 交付 → 整题失败（未回答）",
    ("syn-001", "local"): "incomplete_conditions：同左（版本对未解决）→ HTTP 未发出、0 交付 → 整题失败",
    ("syn-001", "fusion"): "incomplete_conditions：同左 → HTTP 未发出、0 交付 → 整题失败",
    ("syn-002", "pg"): "HTTP 200；合同交付 4 条绑定真实来源（4.1 执行表1 / 消毒控制 / 禁排区 / 脱氯 0.5 mg/L），但缺 gold 要求的 6.1 取样监测与表2/预处理标准侧 → 整题失败；4 条记正确片段，不为整题补分",
    ("syn-002", "local"): "incomplete_conditions（GB18466-2005 版本未解决）→ HTTP 未发出、0 交付 → 整题失败",
    ("syn-002", "fusion"): "HTTP 200；raw 9 claims 合同全拒、0 交付 → 整题失败",
    ("syn-003", "pg"): "HTTP 200；raw 0 合格 claims（合同全拒）、0 交付 → 整题失败",
    ("syn-003", "local"): "incomplete_conditions（GB8978-1996 版本未解决）→ HTTP 未发出、0 交付 → 整题失败",
    ("syn-003", "fusion"): "HTTP 200；交付 5 条绑定真实引用（4.1/4.2 标准级别选择条款）——不对题：gold 要求 6.1 采样位置（车间排放口/单位排放口），quote 真≠答案被支持 → 整题失败；5 片段记为真实但跑题",
    ("syn-004", "pg"): "HTTP 200（raw 10 条）合同全拒、0 交付；raw summary 媒体映射对不为失败补分 → 整题失败",
    ("syn-004", "local"): "incomplete_conditions（GB3095-2012/GB3838-2002 版本对未解决）→ HTTP 未发出、0 交付 → 整题失败",
    ("syn-004", "fusion"): "HTTP 200（raw 8 条）合同全拒、0 交付 → 整题失败",
    ("syn-005", "pg"): "HTTP 200；合同拒收后 0 交付 → 整题失败",
    ("syn-005", "local"): "HTTP 200（coverage ambiguous，附录混载）；合同拒收后 0 交付 → 整题失败",
    ("syn-005", "fusion"): "HTTP 200；raw 0 合格 claims、0 交付 → 整题失败",
    ("syn-006", "pg"): "incomplete_conditions（过渡期/批准日期条件装配未成立）→ HTTP 未发出、0 交付 → 整题失败",
    ("syn-006", "local"): "incomplete_conditions（同左）→ HTTP 未发出、0 交付 → 整题失败",
    ("syn-006", "fusion"): "incomplete_conditions（同左）→ HTTP 未发出、0 交付 → 整题失败",
    ("neg-010", "fusion"): "HTTP 200；交付 4 条真实引用但未回答 2026 修改单适用范围之问——over-answer 疑点，人工待审（不作 PASS）",
}


def manual_review_for(v_out: dict, issued_legs: dict) -> dict | None:
    key = (v_out["qid"], v_out["path"])
    reason = _MANUAL.get(key)
    if reason is None:
        return None
    leg = f"r1/{v_out['path']}/{v_out['qid']}"
    return {
        "verdict": "FAIL" if v_out["qid"] != "neg-010" else "PENDING",
        "reason": reason,
        "delivered_items": v_out.get("delivered"),
        "coverage": v_out.get("coverage"),
        "model_used": bool((v_out.get("_model") or {}).get("used")) if isinstance(v_out.get("_model"), dict) else None,
        "answer_http_issued": int(issued_legs.get(leg, 0)),
        "artifact": f"legs/r1/{v_out['path']}/{v_out['qid']}/answer/answer-runtime-latest.json",
        "reviewer": "执行agent 离线人工复核（逐题，2026-10-08）",
    }


_POS_FAIL = {
    "set_mismatch",
    "projection_mismatch",
    "foreign_doc_rows",
    "coverage_not_complete",
    "unverified_citation",
    "partial_unverified",
    "partial_fragment_correct",
    "value_not_bound_or_mismatched",
    "no_delivery_coverage_complete",
    "no_delivery_coverage_partial",
    "no_delivery_coverage_ambiguous",
    "no_delivery_coverage_None",
    "budget_failure",
    "no_answer_artifact",
}
_POS_PENDING = {
    "pending_artifact_masking",
    "pending_citation_metadata_gap",
    "pending_fact_carrier_review",
    "pending_gold_projection",
}


def finalize_positive(v_out: dict, manual: dict | None) -> dict:
    """A6: canonical final_status. A decisive whole-question failure can never
    be softened to PENDING by an item-level unknown; PENDING only when nothing
    decisive is established either way."""
    j = v_out["judgement"]
    v_out.pop("_model", None)
    if manual is not None:
        v_out["manual_review"] = manual
        if manual["verdict"] == "FAIL":
            v_out["final_status"] = "FAIL"
            v_out["final_basis"] = "manual"
            v_out["final_reason"] = manual["reason"]
            return v_out
    if j == "pass_mechanical":
        v_out["final_status"] = "PASS"
        v_out["final_basis"] = "mechanical_projection+citations+coverage"
        v_out["final_reason"] = "投影集合全等、引用经冻结守卫身份独立重读、覆盖 complete（仍受主agent抽审）"
    elif j in _POS_FAIL:
        v_out["final_status"] = "FAIL"
        v_out["final_basis"] = "mechanical"
        det = []
        if v_out.get("missing"):
            det.append(f"missing={v_out['missing'][:3]}")
        for k in ("extra", "extra_rows", "extra_out_of_scope", "extra_in_scope"):
            if v_out.get(k):
                det.append(f"{k}={v_out[k] if k != 'projection' else ''}")
        proj = v_out.get("projection") or {}
        if proj.get("extra_rows"):
            det.append(f"projection extra_rows={proj['extra_rows']}")
        if v_out.get("foreign_table_docs"):
            det.append(f"foreign_docs={v_out['foreign_table_docs'][:2]}")
        if v_out.get("coverage") not in (None, "complete"):
            det.append(f"coverage={v_out['coverage']}（非 complete 整题 exact 不成立）")
        if v_out.get("masked_citations"):
            det.append(f"masked_citation_details={v_out['masked_citations']}（局部 unknown，不改整题结论）")
        if v_out.get("judgement") == "unverified_citation":
            det.append(f"unverified={v_out.get('unverified_citations', [])[:1]}")
        v_out["final_reason"] = f"judgement={j}; " + "; ".join(det)
    elif j in _POS_PENDING:
        v_out["final_status"] = "PENDING"
        v_out["final_basis"] = "evidence_gap"
        v_out["final_reason"] = (
            f"judgement={j}; masked={v_out.get('masked_citations', 0)} gaps={v_out.get('citation_gaps', 0)}"
        )
    else:
        v_out["final_status"] = "PENDING"
        v_out["final_basis"] = "unclassified"
        v_out["final_reason"] = f"judgement={j}"
    return v_out


_REFUSAL_EXPECTATIONS = ("missing", "partial", "ambiguous", "isolation")


def finalize_counter(v_out: dict) -> dict:
    """Counter finals from ACTUAL behaviour first; expected_status only as a
    post-hoc comparison label (it never routed scoring). Conservative refusal
    vs. wrong delivery are separated per handoff; a refusal where the gold
    expected an answer is recorded as a pending quality gap, never forced."""
    j = str(v_out["judgement"])
    exp = v_out.get("counter_expected_status")
    if j in ("behaviour_ok_mechanical", "budget_refused_at_pg_guard_expected"):
        v_out["final_status"] = "PASS"
        v_out["final_basis"] = "behaviour+source-qualified"
        v_out["final_reason"] = (
            "实际行为符合（集合/覆盖/引用身份全通过）"
            if j == "behaviour_ok_mechanical"
            else "PG 构造守卫按预期拒绝；覆盖空白：成员/字符展开未在生产实测"
        )
    elif j in ("behaviour_violation_or_incomplete", "set_violation", "behaviour_violation_merges_or_overclaims"):
        v_out["final_status"] = "FAIL"
        v_out["final_basis"] = "behaviour"
        det = []
        if v_out.get("foreign_table_docs"):
            det.append(f"foreign_docs={v_out['foreign_table_docs'][:2]}")
        if v_out.get("unverified_citations") and v_out["all_citations_verified"] is False:
            det.append("citations_unverified_or_wrong_identity")
        if v_out.get("coverage") == "complete" and (v_out.get("docs_cited") or [None])[0]:
            if "merge" in j:
                det.append(f"跨 {len(v_out['docs_cited'])} 文档 complete 交付，不符冻结 ambiguous（仅判当前行为，不宣称底层表身份串并）")
        if v_out.get("extra_rows"):
            det.append(f"extra_rows={v_out['extra_rows']}")
        v_out["final_reason"] = f"judgement={j}; " + "; ".join(det)
    else:
        cov = v_out.get("coverage")
        n = v_out.get("delivered")
        if isinstance(n, list):
            n = len(n)
        if isinstance(n, int) and n == 0 and cov != "complete" and not v_out.get("budget_failure"):
            if exp in _REFUSAL_EXPECTATIONS:
                v_out["final_status"] = "PASS"
                v_out["final_basis"] = "conservative_non_delivery_posthoc"
                extra = (
                    "仅观测级隔离，非 same-id 对抗实弹"
                    if exp == "isolation"
                    else "无 false complete/over-claim"
                )
                v_out["final_reason"] = f"0 交付、coverage={cov}；事后对照 expected={exp} 属保守拒绝侧一致（{extra}）"
            else:
                v_out["final_status"] = "PENDING"
                v_out["final_basis"] = "quality_gap_posthoc"
                v_out["final_reason"] = (
                    f"0 交付、coverage={cov}，expected={exp}（期望作答）——保守拒绝与应答未答的质量缺口，如实上报待主 agent 裁决；非 false complete"
                )
        elif n == 0 and cov == "complete":
            v_out["final_status"] = "FAIL"
            v_out["final_basis"] = "overclaim"
            v_out["final_reason"] = "complete 却 0 交付=over-claim"
        else:
            v_out["final_status"] = "PENDING"
            v_out["final_basis"] = "behaviour_review"
            v_out["final_reason"] = f"judgement={j}; expected={exp} 事后对照仅记录"
    return v_out


# ---------------------------------------------------------------------------
# 4. recall — A5: typed discovery + chunk candidates, separate segments
# ---------------------------------------------------------------------------


def _fusion_segments(qid: str, path: str) -> dict | None:
    """Read the SAVED pre-expansion shapes of a pg/fusion leg exactly as
    fusion._normalize_pg wrote them: chunk candidates (ordered) and typed
    targets (doc/scope/table_unit discovery). Never borrows usable or
    targets_resolved (post-resolve), never the answers."""
    p = ROUND1 / "legs" / "r1" / path / qid / "fusion" / "fusion-runtime-latest.json"
    if not p.exists():
        return None
    r0 = json.loads(p.read_text(encoding="utf-8")).get("results", [{}])[0]
    cands, tt = r0.get("candidates"), r0.get("typed_targets")
    if not isinstance(cands, list) or not isinstance(tt, list):
        return None
    pgblk = r0.get("pg") or {}
    if pgblk.get("discovery_captured") is False:
        return None
    chunk_docs = [c.get("doc_id") for c in cands if isinstance(c, dict) and c.get("doc_id")]
    typed = []
    for t in tt:
        if isinstance(t, dict) and t.get("doc_id"):
            typed.append(
                {
                    "target_type": t.get("target_type"),
                    "doc_id": t["doc_id"],
                    "workspace": t.get("workspace"),
                    "discovery": t.get("discovery"),
                }
            )
    return {"chunk_docs": chunk_docs, "typed": typed}


def pre_expansion_docs(qid: str, path: str) -> list | None:
    """Pre-expansion discovery docs, BOTH segments (typed + chunks), in saved
    order within each segment. Explicit zero discovery stays zero. Returns
    None only when the artifact/shape is unavailable (unknown, not zero)."""
    if path in ("pg", "fusion"):
        seg = _fusion_segments(qid, path)
        if seg is None:
            return None
        docs: list[str] = []
        seen = set()
        for t in seg["typed"]:
            if t["doc_id"] not in seen:
                seen.add(t["doc_id"])
                docs.append(t["doc_id"])
        for d in seg["chunk_docs"]:
            if d not in seen:
                seen.add(d)
                docs.append(d)
        return docs
    p = ROUND1 / "inputs" / "local" / f"{qid}-fusion.json"
    if not p.exists():
        return None
    r0 = json.loads(p.read_text(encoding="utf-8")).get("results", [{}])[0]
    return [u.get("doc_id") for u in r0.get("usable") or [] if u.get("doc_id")]


def recall_report(gold: dict) -> dict:
    """A5: chunk-ordered and typed segments reported SEPARATELY. There is no
    saved global ordering across the two segments, so no unified recall@20 is
    claimed; the withdrawn previous averages (pg 0.959 / local 0.952 /
    fusion 0.991) read only chunk candidates and lost real typed discovery
    (e.g. file-enum-005/pg had discovery_total=3, chunks=0). Typed EVIDENCE
    (unit/chunk) recall stays pending: offline mapping insufficient."""
    out = {
        "per_question": {},
        "typed_evidence_recall": "pending",
        "published_aggregates": None,
        "withdrawn_previous_averages": {
            "pg": 0.959,
            "local": 0.952,
            "fusion": 0.991,
            "reason": "漏读 typed discovery，不能作为可比较的发现召回结论；本轮按分段口径重算，汇总留待口径审查",
        },
        "method": {
            "chunk_ordered_recall_at_20": "chunk 候选按保存顺序前 20 文档命中/期望文档数（仅当有 chunk 候选）",
            "typed_discovery_coverage": "typed 目标文档集命中/期望（typed 无排序声明，不称 @20）",
            "union_discovery_coverage": "两段并集命中/期望（无序存在性覆盖）",
            "backfill": "枚举答案/targets_resolved/usable(仅 local 段口径)/精排/展开一律不回填；显式 0 发现保持 0",
        },
        "notes": "pre-expansion only；local usable=adapter 已验发现（展开前），pg/fusion 读 fusion runtime typed_targets+candidates 两段",
    }
    for q in gold["questions"]:
        expected = {t.get("doc_id") for t in q.get("target_docs") or []}
        if not expected:
            continue
        row = {}
        for path in POSITIVE_PATHS:
            if path in ("pg", "fusion"):
                seg = _fusion_segments(q["query_id"], path)
                if seg is None:
                    row[path] = "pending_no_artifact"
                    continue
                chunks, typed_docs = seg["chunk_docs"], {t["doc_id"] for t in seg["typed"]}
                union = ({d for d in chunks[:20]} | typed_docs) & expected
                row[path] = {
                    "chunk_n": len(chunks),
                    "chunk_recall_at_20": round(len(({d for d in chunks[:20]}) & expected) / len(expected), 3),
                    "typed_n": len(typed_docs),
                    "typed_coverage": round(len(typed_docs & expected) / len(expected), 3),
                    "union_coverage": round(len(union) / len(expected), 3),
                    "explicit_zero": len(chunks) == 0 and len(typed_docs) == 0,
                }
            else:
                docs = pre_expansion_docs(q["query_id"], path)
                if docs is None:
                    row[path] = "pending_no_artifact"
                else:
                    row[path] = {
                        "usable_ordered_n": len(docs),
                        "usable_recall_at_20": round(len({d for d in docs[:20]} & expected) / len(expected), 3),
                        "explicit_zero": len(docs) == 0,
                    }
        out["per_question"][q["query_id"]] = row
    return out


# ---------------------------------------------------------------------------
# 5. ledger + timing corrections
# ---------------------------------------------------------------------------


def answer_issued_by_leg(terminal: dict) -> dict:
    out = defaultdict(int)
    for e in terminal["budget_snapshot_end"]["events"]:
        leg = e["where"].split(":")[0]
        if e["service"] == "answer_llm" and e["kind"] == "issued":
            out[leg] += e["amount"]
    return dict(out)


def ledger_corrections(terminal: dict) -> dict:
    snap = terminal["budget_snapshot_end"]
    per = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    refusals = []
    for e in snap["events"]:
        leg = e["where"].split(":")[0]
        if e["kind"] == "reserved":
            per[leg][e["service"]][0] += e["amount"]
        elif e["kind"] == "issued":
            per[leg][e["service"]][1] += e["amount"]
        elif e["kind"] == "budget_refusal":
            refusals.append({"where": e["where"], "service": e["service"]})
    diffs = []
    for leg, svcs in sorted(per.items()):
        for svc, (r, i) in svcs.items():
            if r != i:
                diffs.append({"leg": leg, "service": svc, "reserved": r, "issued": i})

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
        "note_prev_claim": "round-1-report §2 '除 neg-008 外 120 腿逐服务 issued==reserved' 系误写：其余服务相等，但 answer_llm 有 10 条腿预留 1 实发 0（incomplete_conditions，HTTP 未发出）——以本表为准",
        "refusals_round1": {
            "events": refusals,
            "note": "第一轮预算拒绝=3 条（neg-008 三路，PG 构造守卫，issued=0）；此前引用的'15 条拒绝'为旧试点数字，不属本轮",
        },
        "answer_http_corrections": {
            "positive_synthesis_legs_http_issued": 9,
            "neg_010_legs_http_issued": 2,
            "round_answer_http_total": 11,
            "note": "订正旧表述'18 行中 11 行发生真实 HTTP'：按账本凭证，正例合成实发 HTTP 为 9 腿，另 2 腿为 neg-010，全轮合计 11",
        },
        "timings": {
            "discovery_inclusive_rerank_ms": pct(disc_incl),
            "discovery_exclusive_rerank_approx_ms": pct(disc_excl),
            "rerank_ms": pct(rer),
            "answer_ms_composite_unsplit": pct(ans),
            "total_ms_recorded": pct(tot),
            "answer_stage_stages_unavailable": "answer_ms 内含范围展开/生成/复核，独立阶段计时 unavailable；模型 call.latency 仅 HTTP 时间不冒充全生成",
        },
        "recorded_total_sum_s": round(total_sum_ms / 1000, 3),
        "wall_artifact_mtime_span_s": round(last_art - first_art, 1) if first_art and last_art else None,
        "wall_note": "前报告 '约44分钟' 为作者报告（依据后台任务起止通知时刻差），非工件自证；已记录总和与墙钟差不可归因部分不做解释",
        "serial_cache_condition": "单轮串行执行、无跨题缓存复用（每腿新发现/回读/冷生成）；数值不代表并发或热缓存性能",
    }


# ---------------------------------------------------------------------------
# main — A4: guard first, score second
# ---------------------------------------------------------------------------


def _summary(rows: list) -> dict:
    out = {"positive": {}, "counter": {}, "totals": {"positive": {}, "counter": {}}}
    for r in rows:
        side = "counter" if r["is_counter"] else "positive"
        cat = r.get("category") or ("counter" if r["is_counter"] else "none")
        bucket = out[side].setdefault(f"{cat}", {}).setdefault(r["path"], defaultdict(int))
        bucket[r["final_status"]] += 1
        out["totals"][side][r["final_status"]] = out["totals"][side].get(r["final_status"], 0) + 1
    # convert defaultdicts for json
    return json.loads(json.dumps(out, ensure_ascii=False))


def main() -> None:
    out_dir = Path(__file__).resolve().parent

    verification = verify_inputs()
    if not verification["ok"]:
        (out_dir / "input-rejection.json").write_text(
            json.dumps(
                {"schema": "assessment-input-rejection/r2", "problems": verification["problems"]},
                ensure_ascii=False,
                indent=1,
            )
            + "\n",
            encoding="utf-8",
        )
        raise InputIntegrityError(
            "assessment inputs failed integrity verification: " + "; ".join(verification["problems"])
        )

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
    issued_legs = answer_issued_by_leg(terminal)
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
            v = score_row(qid, r["path"], entry, gq, True, doc_reg)
            v["counter_type"] = gq["counter"].get("type")
            v["counter_expected_status"] = gq["counter"].get("expected_status")
            if qid in ("neg-003", "neg-004", "neg-005", "neg-008"):
                v = score_counter_row(qid, r["path"], v, entry, gq["counter"], doc_reg, table13)
            elif v["judgement"].startswith("projection") or v["judgement"] == "unknown_category":
                v["judgement"] = "pending_behaviour_review"
            else:
                v["judgement"] = f"counter_{v['judgement']}"
            v["_model"] = meta.get("model")
            note = manual_review_for(v, issued_legs)
            v_out = finalize_counter(v)
            v_out.pop("_model", None)
            if note is not None:
                v_out["manual_review"] = note
        else:
            v = score_row(qid, r["path"], entry, gq, bool(r["is_counter"]), doc_reg)
            v["_model"] = meta.get("model")
            manual = manual_review_for(v, issued_legs)
            if v["category"] == "synthesis" and manual is None:
                manual = {
                    "verdict": "FAIL",
                    "reason": "合成题人工复核未记录理由——按整题未证通过处理（保守 FAIL，不冒充已审）",
                    "delivered_items": v.get("delivered"),
                    "coverage": v.get("coverage"),
                    "answer_http_issued": int(issued_legs.get(f"r1/{v['path']}/{qid}", 0)),
                    "artifact": f"legs/r1/{v['path']}/{qid}/answer/answer-runtime-latest.json",
                    "reviewer": "执行agent 离线人工复核（逐题，2026-10-08）",
                }
            v_out = finalize_positive(v, manual)
        verdicts.append(v_out)

    recall = recall_report(gold)
    ledger = ledger_corrections(terminal)
    results = {
        "schema": "round-1-assessment/r2",
        "supersedes": "reports/pg-retrieval/phase-4-round-1-assessment/ (机械 verdicts withdrawn; 原目录保留作历史)",
        "inputs_verification": verification,
        "rows": verdicts,
        "summary": _summary(verdicts),
        "recall": recall,
        "ledger_and_timing": ledger,
        "policy_notes": {
            "final_layering": "final_status 从整题决定性证据出发：投影/集合/合同/覆盖/人工失败优先；掩码等细项 unknown 单列不软化整题结论",
            "recall": "typed 与 chunk 分段呈现，无统一 @20 声明；typed 证据召回 pending；旧均值撤下",
            "source_qualification": "workspace/snapshot/doc 身份经冻结守卫+SHA 守卫输入独立核对后方为 verified；catalog 名称须经独立输入证据定位",
            "expected_routing": "expected 仅事后对照，从不路由；反例判实际行为",
        },
    }
    (out_dir / "adjudication.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print("rows:", len(verdicts))
    print(json.dumps(results["summary"]["totals"], ensure_ascii=False))
    byj = defaultdict(int)
    for v in verdicts:
        byj[v["judgement"]] += 1
    print(json.dumps(dict(byj), ensure_ascii=False, indent=1))
    print("inputs ok:", verification["ok"], "| manifest entries:", verification["manifest"]["entries"])
    print(
        "ledger diffs:",
        len(ledger["reserved_vs_issued_diffs"]),
        "| refusals:",
        len(ledger["refusals_round1"]["events"]),
        "| recorded total s:",
        ledger["recorded_total_sum_s"],
        "| wall span s:",
        ledger["wall_artifact_mtime_span_s"],
    )


if __name__ == "__main__":
    main()
