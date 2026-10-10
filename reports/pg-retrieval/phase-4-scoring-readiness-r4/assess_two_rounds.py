"""Round-1 offline assessment — generation r3 (incremental fixes R1–R3, 2026-10-08).

Same scope: score the 123 already-executed legs against the frozen gold using
ONLY local artifacts — zero model/embedding/rerank/PG/Qdrant/Neo4j requests,
zero DB, no production edits, no re-runs. The r1/r2 generations stay
byte-identical; this generation layers on top of r2's A1–A6 corrections:

R1  the WHOLE DELIVERED DECLARATION is source-bound, not just a quote:
    * both gold shapes bind the declared clause number (dict clause AND a
      leading number in string gold); a fabricated number fails even when the
      text is real; number-less name projections never get a fabricated number;
    * an item's declared doc_id and its citation doc_id must agree (no OR
      scope mask over a contradiction) and both must resolve to protected
      source;
    * the delivered full text must be re-readable from the declared raw unit
      span / declared-order cross-unit segments (whitespace-normalized
      containment — an explicit auditable rule, no second LLM); quote==text
      is NOT required because legal quotes truncate at 120 chars while the
      declared span may back the whole clause. Real prose-enum-001/002 stay
      PASS; the genuine 4.3.4 (20,636 chars vs a 20,626-char declared-segment
      concatenation over 6 segments) is recorded as a position/source failure
      without touching the stored artifact.

R2  counter finals = WHOLE-QUESTION BEHAVIOUR CONTRACT per the main agent's
    explicit ruling table (2026-10-08). "No unsafe delivery" safety
    observations (no false complete, PG quota gate refused early, no foreign
    workspace seen on THIS leg) are recorded in a SEPARATE field and can no
    longer convert into a whole-question PASS. Runtime failure / missing
    artifact is never an evidence-backed refusal. The 18 positive synthesis
    rows stay manual FAIL; denominators remain 93+30; summaries come from
    canonical rows.

R3  the rejection boundary is closed: post-run identity is MANDATORY
    (structure + agreement with the frozen anchor and the pre-state;
    finished_at and matches_frozen booleans cannot stand in for the actual
    fields); parsed evidence is CONTENT-BOUND by recomputing the accepted
    audit fingerprint (parsed_blocks_tables_bytes) against the Gate-0 frozen
    component — a directory merely existing is not bound content; and main's
    verify/read/parse phase has ONE sanitized reject path that always writes
    the input-rejection diagnostic and never publishes an adjudication.

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

Run:  uv run python reports/pg-retrieval/phase-4-round-1-assessment-r3/assess_round1.py
The frozen review matrices are run against this file via
ENV_RAG_ASSESSMENT_SCRIPT=<abs path> (see the r1/r2 review handoffs).

PHASE-4 SCORING READINESS COPY (this file):
* default/compat mode keeps the accepted r3 behaviour byte-for-functionally
  identical, including the Round-1 `_MANUAL` conclusions (they apply ONLY
  here, never to a new generation);
* generation-bound mode (--generations) scores any future round directory:
  run_dir + approved anchor + run manifest + fixed gold + actual pre/post
  identity are verified BEFORE any scoring; a different code lineage requires
  its own explicit anchor (no exemptions, anchors are never rewritten);
* new-generation human conclusions are external RECORDS bound to
  (run, round, qid, path, answer-runtime SHA, response-evidence SHA or an
  explicit absent marker, reviewer, verdict, reason, checked items). A new
  output never inherits a Round-1 verdict: same qid/path with a different
  runtime SHA simply matches no record. Records bound with a wrong SHA or a
  wrong round are REJECTED loudly. PASS resolves only the semantic/carrier
  gaps the record explicitly audited — never an established identity,
  citation, numeric-support, set or coverage failure, and never "raw model
  was right but the app delivered nothing".
* mechanical decisive FAILs stay FAIL with or without records; unaudited
  semantic rows stay PENDING (the synthesis rows are NOT auto-FAILed from
  silence in a new generation).
Rules kept identical in both modes: collection projection, clause numbers +
full raw span re-read, identity/filename evidence, counter behaviour-first,
decisive-failure precedence, denominators never shrink, masked-pending
details, expected-never-routes, reject-before-scoring with sanitized
diagnostics and no adjudication file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from env_rag_final import answer as an  # noqa: E402  (accepted contract, read-only reuse)
from env_rag_final.audit import identity as audit_identity  # noqa: E402  (PARSED_ROOT only)
from env_rag_final.audit.snapshot import fingerprint_artifacts as audit_fingerprint  # noqa: E402

ROUND1 = REPO / "reports/pg-retrieval/phase-4-round-1"
GOLD_PATH = REPO / "reports/pg-retrieval/gate-2/review-r5/gold-approved.json"
ANCHOR_PATH = REPO / "reports/pg-retrieval/phase-4/phase-4-config-anchor.json"
GATE0_EVIDENCE = REPO / "reports/pg-retrieval/gate-0/re-review-evidence.json"
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

# --- generation context (scoring readiness) ---------------------------------
# "round1-compat" keeps the accepted r3 behaviour verbatim: ROUND1 below, the
# frozen Round-1 anchor, the r1 leg tag and the historical _MANUAL table.
# "generation" binds every read to one explicit future run: directory, round,
# approved anchor and run manifest — never an implicit fallback to Round 1.
MODE = "round1-compat"
ROUND_TAG = "r1"
RUN_MANIFEST_NAME = "pilot-manifest.json"
GEN_ROUND: int | None = None

# --- S1 (r2): required lineage, consumed-artifact registry ------------------
# A deleted key may not turn into "skip the comparison": the accepted lineage
# is enumerated structurally first, then SHA-compared.
REQUIRED_CODE_ANCHORS = {
    "answer.py",
    "fusion.py",
    "rerank.py",
    "local_adapter.py",
    "compat_runtime.py",
    "synthesis_system_prompt_sha256",
}
REQUIRED_EVAL_ANCHORS = {
    "src/env_rag_final/evaluation.py",
    "src/env_rag_final/cli.py",
    "src/env_rag_final/search/expand.py",
    "src/env_rag_final/search/query.py",
    "src/env_rag_final/enumerate_/doc_enum.py",
    "src/env_rag_final/enumerate_/prose_enum.py",
}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
CONSUMED: set = set()  # absolute paths actually READ in generation mode
# R4 r3: during the real generation MAIN scoring, answer/fusion/local result
# rows MUST carry a legal query_id/workspace (missing is a refusal, not a
# skip). Bare interface calls (e.g. typed fixture probes) keep the lenient
# "present-then-match" semantics — real artifacts and approved anchors are
# validated first for required fields, then by value.
_STRICT_BIND = False


def _consume(p) -> None:
    if _generation_mode():
        CONSUMED.add(str(Path(p).resolve()))


def configure_generation(
    run_dir: Path, round_no: int, anchor_path: Path, manifest_name: str
) -> None:
    """Every generation starts from a clean binding: no leaked records,
    mapping or consumed registry from a previous round/directory."""
    global ROUND1, ANCHOR_PATH, FROZEN_IDENTITY, MODE, ROUND_TAG, RUN_MANIFEST_NAME, GEN_ROUND
    global CONSUMED, REVIEW_RECORDS, REVIEW_RECORDS_PATH, MAPPING, MAPPING_REJECTED
    CONSUMED = set()
    REVIEW_RECORDS, REVIEW_RECORDS_PATH = {}, None
    MAPPING, MAPPING_REJECTED = None, []
    ROUND1 = Path(run_dir)
    ANCHOR_PATH = Path(anchor_path)
    try:
        FROZEN_IDENTITY = _frozen_identity()
    except Exception:  # noqa: BLE001
        FROZEN_IDENTITY = None
    MODE = "generation"
    ROUND_TAG = f"r{int(round_no)}"
    GEN_ROUND = int(round_no)
    RUN_MANIFEST_NAME = manifest_name


def _generation_mode() -> bool:
    return MODE == "generation"


# ---------------------------------------------------------------------------
# 1. input verification — A4: reject before scoring, never publish on mismatch
# ---------------------------------------------------------------------------


def verify_inputs() -> dict:
    problems: list[str] = []
    report = {"manifest": {}, "gold": {}, "identity": {}, "code": {}, "parsed": {}, "problems": []}

    man_path = ROUND1 / RUN_MANIFEST_NAME
    if not man_path.exists():
        problems.append(f"run manifest missing ({RUN_MANIFEST_NAME})")
        man = {}
    else:
        man = json.loads(man_path.read_text(encoding="utf-8"))["files"]
    bad = [
        rel for rel, digest in man.items() if not (REPO / rel).exists() or sha(REPO / rel) != digest
    ]
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
                    "source_fingerprint": ident.get("source_fingerprint")
                    == fi["source_fingerprint"],
                    "catalog_run_snapshot": f"{cat.get('run_id')}/{cat.get('snapshot_id')}"
                    == fi["catalog_run_snapshot"],
                    "search_active": ident.get("search_active") == fi["search_active"],
                    "gold_sha": ident.get("gold_sha") == GOLD_SHA,
                }

            def struct_ok(ident: dict) -> list:
                missing = []
                if not ident.get("source_fingerprint"):
                    missing.append("source_fingerprint")
                cat = ident.get("catalog_active") or {}
                if not cat.get("run_id") or not cat.get("snapshot_id"):
                    missing.append("catalog_active.run_id/snapshot_id")
                if not ident.get("search_active"):
                    missing.append("search_active")
                if not ident.get("gold_sha"):
                    missing.append("gold_sha")
                return missing

            a_pre, a_post = agree(pre), (agree(post) if post else {})
            m_pre = struct_ok(pre)
            m_post = ["identity_after present"] if not post else struct_ok(post)
            report["identity"] = {
                "pre": a_pre,
                "post": a_post or "absent",
                "pre_missing_fields": m_pre,
                "post_missing_fields": m_post,
                "matches_frozen_pre": pre.get("matches_frozen"),
                "matches_frozen_post": post.get("matches_frozen") if post else None,
                "run_failure": terminal.get("failure"),
                "finished_at": terminal.get("finished_at"),
            }
            # R3: actual post fields are mandatory; finished_at/matches_frozen
            # booleans can never stand in for them.
            if m_pre:
                problems.append(f"pre-identity fields incomplete: {m_pre}")
            if not post:
                problems.append(
                    "post-run identity MISSING — a finished run without actual post fields is rejected before scoring"
                )
            elif m_post:
                problems.append(f"post-identity fields incomplete: {m_post}")
            if not all(a_pre.values()) or pre.get("matches_frozen") is not True:
                problems.append("run pre-identity disagrees with frozen anchor")
            if post and (not all(a_post.values()) or post.get("matches_frozen") is not True):
                problems.append("run post-identity disagrees with frozen anchor")
            if post:
                for key in ("source_fingerprint", "search_active", "gold_sha"):
                    if post.get(key) != pre.get(key):
                        problems.append(f"post-identity {key} disagrees with pre-identity")
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
            if _generation_mode():
                # A new generation binds its WHOLE approved lineage: every
                # code_anchors .py entry and every evaluation_code_anchors
                # repo-relative path must match disk. A different lineage needs
                # its own explicit anchor — never an exemption, never an
                # anchor rewritten from current values.
                for key, want in ca.items():
                    if not key.endswith(".py") or key in ("answer.py", "fusion.py"):
                        continue
                    got = sha(REPO / "src/env_rag_final" / key)
                    code_ok[key] = {"match": bool(want) and got == want}
                    if not code_ok[key]["match"]:
                        problems.append(f"approved lineage drift: {key}")
                for rel, want in (anchor.get("evaluation_code_anchors") or {}).items():
                    got = sha(REPO / rel)
                    code_ok[rel] = {"match": bool(want) and got == want}
                    if not code_ok[rel]["match"]:
                        problems.append(f"approved lineage drift: {rel}")
                if terminal.get("round") != GEN_ROUND:
                    problems.append(
                        f"terminal round {terminal.get('round')!r} does not match bound generation r{GEN_ROUND}"
                    )
                n_pos = sum(1 for t in terminal.get("results") or [] if not t.get("is_counter"))
                n_cnt = sum(1 for t in terminal.get("results") or [] if t.get("is_counter"))
                if (n_pos, n_cnt) != (93, 30):
                    problems.append(f"generation denominators wrong: {n_pos}+{n_cnt} != 93+30")
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

    # R3: content-bind the parsed evidence — recompute the ACCEPTED audit
    # fingerprint over all blocks/tables bytes and compare with the Gate-0
    # frozen component. Directory existence alone is never "bound content".
    frozen_art = None
    try:
        ev = json.loads(GATE0_EVIDENCE.read_text(encoding="utf-8"))
        frozen_art = ev["source_snapshot_fingerprint"]["components"]["parsed_blocks_tables_bytes"]
    except Exception as exc:  # noqa: BLE001 — missing/unreadable frozen evidence rejects
        problems.append(f"Gate-0 parsed-evidence component unreadable: {type(exc).__name__}")
    if frozen_art:
        computed = audit_fingerprint(Path(audit_identity.PARSED_ROOT))
        report["parsed"]["artifact_bytes_fingerprint"] = {
            "expected_gate0": frozen_art,
            "computed": computed,
            "match": computed == frozen_art,
        }
        if computed != frozen_art:
            problems.append("parsed blocks/tables bytes differ from the Gate-0 frozen component")

    if _generation_mode():
        problems.extend(_generation_verify(man))
    report["problems"] = problems
    report["ok"] = not problems
    return report


_COUNT_KEYS = [
    "lightrag_doc_full",
    "lightrag_doc_chunks",
    "lightrag_doc_status",
    "lightrag_llm_cache",
    "lightrag_entity_chunks",
    "lightrag_full_entities",
    "lightrag_full_relations",
    "lightrag_relation_chunks",
]


def _generation_verify(man) -> list:
    """S1 r2: the generation input contract as ONE uniform structural check —
    consumed coverage, identity fields, lineage keys, unique gold matrix.
    Never relaxes the compat rules."""
    problems: list = []
    anchor = _load_anchor()
    terminal = json.loads((ROUND1 / "eval-runtime-latest.json").read_text(encoding="utf-8"))
    fi = anchor["frozen_identity"]
    ca = anchor.get("code_anchors") or {}
    eva = anchor.get("evaluation_code_anchors") or {}
    # required keys present BEFORE any comparison — deletion is refusal, not skip
    miss = sorted(REQUIRED_CODE_ANCHORS - set(ca))
    if miss:
        problems.append(f"anchor code_anchors missing required keys: {miss}")
    miss2 = sorted(REQUIRED_EVAL_ANCHORS - set(eva))
    if miss2:
        problems.append(f"anchor evaluation_code_anchors missing required keys: {miss2}")
    for k, v in ca.items():
        if k == "synthesis_system_prompt_sha256":
            if not (isinstance(v, str) and _HEX64.match(v)):
                problems.append("anchor prompt key malformed")
            continue
        if k.endswith(".py") and not (isinstance(v, str) and _HEX64.match(v)):
            problems.append(f"anchor code_anchors[{k}] malformed")
    # identity: every frozen field actual-valued; env and counts included
    pre = terminal["identity_before"]
    post = terminal.get("identity_after") or {}
    for side, ident in (("pre", pre), ("post", post)):
        if not ident:
            continue
        if not ident.get("env_sha"):
            problems.append(f"{side}-identity env_sha missing")
        if not ident.get("counts"):
            problems.append(f"{side}-identity counts missing")
    if post:
        if pre.get("env_sha") != post.get("env_sha"):
            problems.append("env_sha drifts between pre and post identity")
        gen_env = (anchor.get("generation") or {}).get("env_sha256")
        if gen_env:
            for side, ident in (("pre", pre), ("post", post)):
                if ident.get("env_sha") != gen_env:
                    problems.append(
                        f"{side}-identity env_sha disagrees with the approved env anchor"
                    )
        if pre.get("counts") != post.get("counts"):
            problems.append("counts drift between pre and post identity")
        eight = fi.get("eight_table_counts")
        if not (
            isinstance(eight, list)
            and len(eight) == 8
            and all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in eight)
        ):
            # R4 r3: frozen counts are REQUIRED structure — absent/short/
            # malformed is an input refusal, never a skipped comparison.
            problems.append(
                "approved anchor eight_table_counts missing/malformed — required frozen counts"
            )
        if isinstance(eight, list) and len(eight) == 8:
            want = dict(zip(_COUNT_KEYS, eight))
            for side, ident in (("pre", pre), ("post", post)):
                gotc = ident.get("counts") or {}
                if {k: gotc.get(k) for k in _COUNT_KEYS} != want:
                    problems.append(
                        f"{side}-counts disagree with the approved anchor frozen counts"
                    )
    # unique gold matrix (not just 93+30 counts)
    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))  # fixed, SHA-verified
    qcat = {q["query_id"]: q.get("category") for q in gold["questions"]}
    cc = {c["counter_id"] for c in gold["counter_examples"]}
    expected = {(qid, path) for qid in qcat for path in POSITIVE_PATHS} | {
        (cid, path) for cid in cc for path in POSITIVE_PATHS
    }
    seen = set()
    for r in terminal["results"]:
        key = (r["query_id"], r["path"])
        if key in seen:
            problems.append(f"duplicate terminal key {key}")
            continue
        seen.add(key)
        ic = bool(r.get("is_counter"))
        if ic != (key[0] in cc):
            problems.append(f"is_counter mismatch for {key}")
        if not ic and r.get("category") != qcat.get(key[0]):
            problems.append(f"category mismatch for {key}")
    if seen != expected or len(terminal["results"]) != 123:
        problems.append(
            f"terminal must cover exactly the unique 31x3+10x3 matrix; got {len(seen)} unique / {len(terminal['results'])} rows"
        )
    # consumed coverage: every artifact this generation will READ must be in
    # the bound manifest — walking only manifest entries is NOT enough
    man_paths = {str((REPO / rel).resolve()) for rel in man}
    required_reads = {str((ROUND1 / "eval-runtime-latest.json").resolve())}
    for r in terminal["results"]:
        qid, path = r["query_id"], r["path"]
        for relp in (
            ROUND1 / "legs" / ROUND_TAG / path / qid / "answer" / "answer-runtime-latest.json",
            ROUND1 / "legs" / ROUND_TAG / path / qid / "fusion" / "fusion-runtime-latest.json",
            ROUND1 / "inputs" / "local" / f"{qid}-fusion.json",
        ):
            if Path(relp).exists():
                required_reads.add(str(Path(relp).resolve()))
    for inp in (ROUND1 / "inputs").rglob("*.json"):
        required_reads.add(str(inp.resolve()))
    unreg = sorted(required_reads - man_paths)
    if unreg:
        problems.append(
            f"consumed artifacts missing from bound manifest: {len(unreg)} (e.g. {unreg[:2]})"
        )
    return problems


# ---------------------------------------------------------------------------
# 2. artifact loading + citation re-verification (contract-faithful + identity)
# ---------------------------------------------------------------------------


def _bind_leg_identity(kind: str, qid: str, res: dict) -> None:
    """generation mode: a placed artifact must bind THIS question (and this
    workspace) — never consume another question's first results row."""
    if not _generation_mode():
        return
    # R4 r3 + r4 scope: during the FULL formal generation consumption path
    # (answer scoring AND the recall/typed discovery reads), a SUCCESSFUL
    # result row must carry a legal query_id/workspace — missing fields may
    # never skip the comparison. Explicit failure / no-results / absent legs
    # returned before this call keep their failure/absent semantics, and
    # direct bare-interface callers run with the switch restored to False.
    got_q = res.get("query_id")
    if got_q is None and _STRICT_BIND:
        raise InputIntegrityError(
            f"{kind} artifact for {qid!r} lacks the required query_id binding"
        )
    if got_q is not None and got_q != qid:
        raise InputIntegrityError(
            f"{kind} artifact query_id {got_q!r} bound to wrong question {qid!r}"
        )
    got_ws = res.get("workspace")
    if got_ws is None and _STRICT_BIND:
        raise InputIntegrityError(
            f"{kind} artifact for {qid!r} lacks the required workspace binding"
        )
    if got_ws is not None and FROZEN_IDENTITY and got_ws != FROZEN_IDENTITY.get("workspace"):
        raise InputIntegrityError(
            f"{kind} artifact workspace {got_ws!r} foreign to bound generation"
        )


def load_terminal() -> dict:
    p = ROUND1 / "eval-runtime-latest.json"
    _consume(p)
    return json.loads(p.read_text(encoding="utf-8"))


def answer_items(path: str, qid: str) -> tuple[list, dict]:
    p = ROUND1 / "legs" / ROUND_TAG / path / qid / "answer" / "answer-runtime-latest.json"
    if not p.exists():
        return [], {"runtime": "absent"}
    _consume(p)
    d = json.loads(p.read_text(encoding="utf-8"))
    if d.get("failure"):
        return [], {"runtime": "failure", "detail": d["failure"]}
    results = d.get("results") or []
    if not results:
        return [], {"runtime": "no-results"}
    res = results[0]
    _bind_leg_identity("answer", qid, res)
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
                    reg.setdefault(
                        did, {"file_path": u["file_path"], "name": Path(u["file_path"]).name}
                    )
    return reg


def _identity_problems(cit: dict, ident: dict) -> list[str]:
    probs = []
    ws = cit.get("workspace")
    if ws != ident["workspace"]:
        probs.append(f"citation workspace {ws!r} != frozen guard {ident['workspace']!r}")
    snap = cit.get("snapshot_id")
    if snap != ident["catalog_snapshot_id"]:
        probs.append(
            f"citation snapshot {snap!r} != frozen catalog snapshot {ident['catalog_snapshot_id']!r}"
        )
    return probs


def _declared_support(parsed_dir, cit: dict, text: str) -> tuple[bool, dict]:
    """R1 auditable rule: the WHOLE delivered text must be re-readable from the
    declared raw unit span (single unit) or the concatenation of declared
    cross-unit segments IN THEIR DECLARED ORDER, after whitespace
    normalisation. This deliberately does NOT require text == quote (legal
    quotes truncate at 120 chars) and does not consult gold or word sets.
    No LLM is used."""
    segs = cit.get("unit_segments")
    if not segs:
        if (
            cit.get("unit_id") is None
            or cit.get("unit_rel_start") is None
            or cit.get("unit_rel_end") is None
        ):
            return False, {"note": "no declared unit-relative span on citation"}
        segs = [
            {
                "unit_id": cit.get("unit_id"),
                "rel_start": cit.get("unit_rel_start"),
                "rel_end": cit.get("unit_rel_end"),
            }
        ]
    parts = []
    for sg in segs:
        raw = an._unit_text_from_blocks(parsed_dir, sg.get("unit_id"))
        if raw is None:
            return False, {"note": f"declared unit {sg.get('unit_id')!r} unreadable"}
        start = sg.get("rel_start")
        end = sg.get("rel_end")
        if not isinstance(start, int) or not isinstance(end, int):
            return False, {"note": "segment missing integer rel coordinates"}
        parts.append(raw[start:end])
    joined = norm("".join(parts))
    t = norm(text or "")
    meta = {"nsegs": len(segs), "len_text": len(t), "len_span": len(joined)}
    if not t:
        return True, meta
    return (t in joined), (
        meta if t in joined else {**meta, "note": "text not contained in declared-order span"}
    )


_FILENAME_CODE = re.compile(r"(GB\s?\d+(?:\.\d+)?)[-–—](\d{4})")


def _catalog_name_check(
    it: dict, cit: dict, reg_entry: dict | None
) -> tuple[bool, list[str], bool]:
    """A3: real-name/metadata grounded in the SHA-guarded run inputs only.
    Returns (grounded, problems, gap_note)."""
    problems: list[str] = []
    if reg_entry is None:
        # no independent evidence at all: a metadata GAP to adjudicate as
        # pending, never a silent pass and never the answer self-certifying
        return (
            False,
            ["catalog doc not present in SHA-guarded run inputs (no independent evidence)"],
            True,
        )
    base = reg_entry["name"]
    gap = False
    cited_name = cit.get("doc_name")
    if cited_name is None:
        # redundant field absent: located through the independent input mapping
        gap = True
    elif norm(str(cited_name)) != norm(base):
        problems.append(
            f"catalog doc_name mismatch: citation {cited_name!r} vs independent input {base!r}"
        )
    item_name = it.get("doc_name")
    if item_name is not None and norm(str(item_name)) != norm(base) and not problems:
        problems.append(f"item doc_name mismatch: {item_name!r} vs independent input {base!r}")
    code = it.get("self_code")
    ver = it.get("self_code_version")
    if code or ver:
        m = _FILENAME_CODE.search(base)
        if m:
            if code and norm(str(code)).replace(" ", "") != m.group(1).replace(" ", ""):
                problems.append(
                    f"self_code {code!r} contradicts independent filename code {m.group(1)!r}"
                )
            if ver and str(ver) != m.group(2):
                problems.append(
                    f"self_code_version {ver!r} contradicts independent filename year {m.group(2)!r}"
                )
    return not problems, problems, gap


def verify_citations(items: list, doc_reg: dict, identity: dict | None = None) -> list[dict]:
    """Independent re-read via the ACCEPTED contract functions (raw grid rows /
    raw unit-relative spans), PLUS the frozen guard identity of A3: workspace,
    catalog snapshot, and doc presence in SHA-guarded run inputs are checked
    for table/prose/catalog alike; content re-read existence is only one part.
    A re-read that passes cannot rescue a citation with wrong identity, and a
    catalog reference cannot self-certify: its name/metadata must agree with
    the independent input evidence."""
    ident = (
        identity
        or FROZEN_IDENTITY
        or {"workspace": "default", "catalog_snapshot_id": "4919b3938ad93747"}
    )
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
            # R1: a declared item-level doc_id must agree with the citation's
            # protected doc — a contradiction is an identity failure, never
            # hidden by scope OR-logic downstream.
            if (
                cit.get("doc_id")
                and it.get("doc_id")
                and norm(str(it["doc_id"])) != norm(str(cit["doc_id"]))
            ):
                idp.append(
                    f"declared item doc_id {it['doc_id']!r} conflicts with citation doc_id {cit['doc_id']!r}"
                )
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
                verdicts[i] = {
                    "verified": False,
                    "problems": (
                        idp + [f"citation kind {cit.get('kind')!r} not re-readable offline"]
                    )[:3],
                }
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
            subset = [
                (i, dict(it), idp)
                for i, it, idp in remaining
                if (it.get("citation") or {}).get("kind") == kind
            ]
            if not subset:
                continue
            copies = [c for _, c, _ in subset]
            problems = fn(copies, parsed_dir)
            for i, copy, idp in subset:
                if copy.get("citation_reverified") and not idp and kind == "char_span":
                    # R1: re-read of the quote proves the SPANS exist; the
                    # DELIVERED DECLARATION itself must additionally be
                    # re-readable from the declared span / declared-order
                    # segments. Quote-truncation is fine; extra unsupported
                    # wording is not.
                    supported, meta = _declared_support(
                        parsed_dir, copy.get("citation") or {}, copy.get("text")
                    )
                    if not supported:
                        verdicts[i] = {
                            "verified": False,
                            "text_unsupported": True,
                            "support_meta": meta,
                            "problems": [
                                f"delivered declaration not re-readable from declared span (R1): {meta}"[
                                    :180
                                ]
                            ],
                        }
                        continue
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
    # R1: BOTH gold shapes bind the clause — a leading number in string gold
    # constrains item.clause exactly as dict.clause does; number-less name
    # projections ("一级", bare names) get NO fabricated number requirement.
    m = re.match(r"^(\d+(?:\.\d+)*)\s", s)
    clause = m.group(1) if m else ""
    return {"clause": clause, "content": s, "display": s}


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
    unsupported = [
        {
            "idx": i,
            "clause": items[i].get("clause"),
            "doc_id": (items[i].get("citation") or {}).get("doc_id"),
            "nsegs": (v.get("support_meta") or {}).get("nsegs"),
            "len_text": (v.get("support_meta") or {}).get("len_text"),
            "len_span": (v.get("support_meta") or {}).get("len_span"),
            "problems": v["problems"],
        }
        for i, v in enumerate(verdicts)
        if v.get("text_unsupported")
    ]
    if unsupported:
        v_out["unsupported_declarations"] = unsupported  # R1: 位置/来源问题分列记录
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

        # R1: scope is AND-qualified with declared identity — every doc an
        # item states (item-level and citation-level) must exist, agree, and
        # be a target; an OR over conflicting docs no longer masks the clash.
        def _it_scope_ok(it: dict) -> bool:
            cit_doc = (it.get("citation") or {}).get("doc_id")
            item_doc = it.get("doc_id")
            if cit_doc and item_doc and norm(str(cit_doc)) != norm(str(item_doc)):
                return False
            docs = {d for d in (cit_doc, item_doc) if d}
            return bool(docs) and docs <= target_docs

        in_scope = [it for it in items if _it_scope_ok(it)]
        out_of_scope = [it for it in items if not _it_scope_ok(it)]
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
    (
        "syn-001",
        "pg",
    ): "incomplete_conditions：请求版本对（GB3095-2012/2026）未在读取范围全部解决 → HTTP 未发出、0 交付 → 整题失败（未回答）",
    (
        "syn-001",
        "local",
    ): "incomplete_conditions：同左（版本对未解决）→ HTTP 未发出、0 交付 → 整题失败",
    ("syn-001", "fusion"): "incomplete_conditions：同左 → HTTP 未发出、0 交付 → 整题失败",
    (
        "syn-002",
        "pg",
    ): "HTTP 200；合同交付 4 条绑定真实来源（4.1 执行表1 / 消毒控制 / 禁排区 / 脱氯 0.5 mg/L），但缺 gold 要求的 6.1 取样监测与表2/预处理标准侧 → 整题失败；4 条记正确片段，不为整题补分",
    (
        "syn-002",
        "local",
    ): "incomplete_conditions（GB18466-2005 版本未解决）→ HTTP 未发出、0 交付 → 整题失败",
    ("syn-002", "fusion"): "HTTP 200；raw 9 claims 合同全拒、0 交付 → 整题失败",
    ("syn-003", "pg"): "HTTP 200；raw 0 合格 claims（合同全拒）、0 交付 → 整题失败",
    (
        "syn-003",
        "local",
    ): "incomplete_conditions（GB8978-1996 版本未解决）→ HTTP 未发出、0 交付 → 整题失败",
    (
        "syn-003",
        "fusion",
    ): "HTTP 200；交付 5 条绑定真实引用（4.1/4.2 标准级别选择条款）——不对题：gold 要求 6.1 采样位置（车间排放口/单位排放口），quote 真≠答案被支持 → 整题失败；5 片段记为真实但跑题",
    (
        "syn-004",
        "pg",
    ): "HTTP 200（raw 10 条）合同全拒、0 交付；raw summary 媒体映射对不为失败补分 → 整题失败",
    (
        "syn-004",
        "local",
    ): "incomplete_conditions（GB3095-2012/GB3838-2002 版本对未解决）→ HTTP 未发出、0 交付 → 整题失败",
    ("syn-004", "fusion"): "HTTP 200（raw 8 条）合同全拒、0 交付 → 整题失败",
    ("syn-005", "pg"): "HTTP 200；合同拒收后 0 交付 → 整题失败",
    ("syn-005", "local"): "HTTP 200（coverage ambiguous，附录混载）；合同拒收后 0 交付 → 整题失败",
    ("syn-005", "fusion"): "HTTP 200；raw 0 合格 claims、0 交付 → 整题失败",
    (
        "syn-006",
        "pg",
    ): "incomplete_conditions（过渡期/批准日期条件装配未成立）→ HTTP 未发出、0 交付 → 整题失败",
    ("syn-006", "local"): "incomplete_conditions（同左）→ HTTP 未发出、0 交付 → 整题失败",
    ("syn-006", "fusion"): "incomplete_conditions（同左）→ HTTP 未发出、0 交付 → 整题失败",
    (
        "neg-010",
        "pg",
    ): "model_failure/条件不足、HTTP 未发出、0 交付——expected 为应答，整题未回答 FAIL；保守不发不等同契约满足（无 over-claim 另行记录）",
    (
        "neg-010",
        "local",
    ): "incomplete_conditions、HTTP 未发出、0 交付——整题未回答 FAIL；保守不发不等同契约满足",
    (
        "neg-010",
        "fusion",
    ): "HTTP 200；交付 4 条原标准 4.1 系条款（排放/消毒/禁排/脱氯）来源真实，但未回答『2026 修改单能否替代原标准』之关系——主 agent 2026-10-08 语义裁决整题 FAIL；真实条款保留为片段记录",
}


# generation-mode external review records (see manual-review-format.md):
# each record binds run/round/qid/path + the SHA of the reviewed answer
# runtime (+ response/context SHA or an explicit absent marker) + reviewer +
# verdict + reason + checked items. Records are loaded from an EXPLICIT
# attachment path; nothing here searches Round-1 answers implicitly.
REVIEW_RECORDS: dict = {}
REVIEW_RECORDS_PATH: Path | None = None

# required audit coverage for PASS on each evidence-gap bucket
_GAP_CHECK_REQUIRED = {
    "pending_fact_carrier_review": ["subject", "value", "unit", "time_or_grade", "verbatim_source"],
    "pending_citation_metadata_gap": ["doc_name_evidence"],
    "pending_gold_projection": ["gold_projection"],
    "pending_artifact_masking": ["masked_cells_reread"],
}


def load_review_records(path: Path) -> dict:
    """S2 r2: ONE binding-validation entry. WRONG-ROUND submissions are refused
    (a round-2 verdict must never be applied to a round-1 run by silently
    "not matching"); duplicate/conflicting keys, malformed fields and unnamed
    reviewers are refused. Missing record = PENDING later; that is the only
    leniency."""
    global REVIEW_RECORDS, REVIEW_RECORDS_PATH
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != "manual-review-records/r1":
        raise InputIntegrityError(f"review records schema unsupported: {data.get('schema')!r}")
    REVIEW_RECORDS_PATH = Path(path)
    _consume(path)
    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    valid_ids = {q["query_id"] for q in gold["questions"]} | {
        c["counter_id"] for c in gold["counter_examples"]
    }
    recs = {}
    for rec in data.get("records") or []:
        missing = {
            k
            for k in (
                "round",
                "qid",
                "path",
                "answer_runtime_sha256",
                "reviewer",
                "verdict",
                "reason",
                "checked_items",
            )
            if k not in rec
        }
        if missing:
            raise InputIntegrityError(f"review record incomplete: missing {sorted(missing)}")
        if rec["verdict"] not in ("PASS", "FAIL", "PENDING"):
            raise InputIntegrityError(f"review verdict invalid: {rec['verdict']!r}")
        has_response = "response_evidence_sha256" in rec
        absent_marker = rec.get("response_evidence") == "absent"
        if not has_response and not absent_marker:
            raise InputIntegrityError(
                f"review record for {rec['qid']}/{rec['path']} must bind response/context SHA or say absent"
            )
        if not isinstance(rec["round"], int) or rec["round"] < 1:
            raise InputIntegrityError(f"review record round invalid: {rec['round']!r}")
        if rec["round"] != GEN_ROUND:
            raise InputIntegrityError(
                f"review record bound to round {rec['round']} while scoring r{GEN_ROUND} — "
                "rounds must not borrow each other's verdicts"
            )
        if rec["qid"] not in valid_ids or rec["path"] not in POSITIVE_PATHS:
            raise InputIntegrityError(
                f"review record key not in the bound matrix: {rec['qid']}/{rec['path']}"
            )
        if not isinstance(rec["reviewer"], str) or not rec["reviewer"].strip():
            raise InputIntegrityError("review record needs a named reviewer")
        if not isinstance(rec["reason"], str) or not rec["reason"].strip():
            raise InputIntegrityError("review record needs a reason")
        if not isinstance(rec["checked_items"], list) or any(
            not isinstance(x, str) for x in rec["checked_items"]
        ):
            raise InputIntegrityError("review record checked_items must be a list of strings")
        if rec["verdict"] == "PASS" and not rec["checked_items"]:
            raise InputIntegrityError("PASS record must list the items actually audited")
        if not (
            isinstance(rec["answer_runtime_sha256"], str)
            and _HEX64.match(rec["answer_runtime_sha256"])
        ):
            raise InputIntegrityError("review record answer_runtime_sha256 malformed")
        if "response_evidence_sha256" in rec and not (
            isinstance(rec["response_evidence_sha256"], str)
            and _HEX64.match(rec["response_evidence_sha256"])
        ):
            raise InputIntegrityError("review record response_evidence_sha256 malformed")
        key = (rec["round"], rec["qid"], rec["path"])
        if key in recs:
            raise InputIntegrityError(f"duplicate/conflicting review record for {key}")
        recs[key] = rec
    REVIEW_RECORDS = recs
    return recs


def _answer_runtime_path(path: str, qid: str) -> Path:
    return ROUND1 / "legs" / ROUND_TAG / path / qid / "answer" / "answer-runtime-latest.json"


def manual_review_for(v_out: dict, issued_legs: dict) -> dict | None:
    if not _generation_mode():
        # Round-1 compat: the historical table applies exactly as accepted.
        key = (v_out["qid"], v_out["path"])
        reason = _MANUAL.get(key)
        if reason is None:
            return None
        leg = f"{ROUND_TAG}/{v_out['path']}/{v_out['qid']}"
        return {
            "verdict": "FAIL",
            "reason": reason,
            "delivered_items": v_out.get("delivered"),
            "coverage": v_out.get("coverage"),
            "model_used": bool((v_out.get("_model") or {}).get("used"))
            if isinstance(v_out.get("_model"), dict)
            else None,
            "answer_http_issued": int(issued_legs.get(leg, 0)),
            "artifact": f"legs/{ROUND_TAG}/{v_out['path']}/{v_out['qid']}/answer/answer-runtime-latest.json",
            "reviewer": "执行agent 离线人工复核（逐题，2026-10-08）",
        }
    # generation mode: ONLY explicit bound records; no Round-1 inheritance.
    rec = REVIEW_RECORDS.get((GEN_ROUND, v_out["qid"], v_out["path"]))
    if rec is None:
        return None
    art = _answer_runtime_path(v_out["path"], v_out["qid"])
    if not art.exists():
        raise InputIntegrityError(
            f"review record for {rec['qid']}/{rec['path']} points at a missing answer runtime"
        )
    got_sha = sha(art)
    if got_sha != rec["answer_runtime_sha256"]:
        # the same qid/path in a NEW run has a different output: an old or
        # mis-bound verdict must never apply — refuse loudly instead of
        # silently ignoring (scenario: 人工记录绑错 round/runtime 拒绝).
        raise InputIntegrityError(
            f"review record SHA mismatch for {rec['qid']}/{rec['path']} r{rec['round']}: "
            f"bound {rec['answer_runtime_sha256'][:12]} vs actual {got_sha[:12]}"
        )
    model = v_out.get("_model") or {}
    has_response = bool(model.get("raw_response"))
    if has_response and rec.get("response_evidence") == "absent":
        raise InputIntegrityError(
            f"review record says absent but the runtime holds a response: {rec['qid']}/{rec['path']}"
        )
    if not has_response and "response_evidence_sha256" in rec:
        raise InputIntegrityError(
            f"review record binds a response SHA the runtime never produced: {rec['qid']}/{rec['path']}"
        )
    if has_response:
        canon = json.dumps(model.get("raw_response"), sort_keys=True, ensure_ascii=False).encode(
            "utf-8"
        )
        got_resp = hashlib.sha256(canon).hexdigest()
        if rec.get("response_evidence_sha256") != got_resp:
            raise InputIntegrityError(
                f"review record response SHA mismatch for {rec['qid']}/{rec['path']}: "
                f"bound {str(rec.get('response_evidence_sha256'))[:12]} vs actual {got_resp[:12]}"
            )
    leg = f"{ROUND_TAG}/{v_out['path']}/{v_out['qid']}"
    return {
        "verdict": rec["verdict"],
        "reason": rec["reason"],
        "checked_items": rec["checked_items"],
        "delivered_items": v_out.get("delivered"),
        "coverage": v_out.get("coverage"),
        "model_used": bool(model.get("used")) if isinstance(model, dict) else None,
        "answer_http_issued": int(issued_legs.get(leg, 0)),
        "artifact": str(art),
        "reviewer": rec["reviewer"],
        "binding": {
            "answer_runtime_sha256": rec["answer_runtime_sha256"],
            "response_evidence": rec.get("response_evidence_sha256") or "absent",
        },
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
    # generation mode: unaudited synthesis rows stay PENDING (the Round-1
    # conservative-FAIL fallback is a historical human conclusion and must
    # not leak into a new run; in compat every synthesis row carries a
    # manual note anyway, so this addition cannot change compat output).
    "synthesis_pending_human_review",
}


def _mechanical_positive(v_out: dict) -> tuple[str, str, str]:
    """Mechanical final (status, basis, reason) WITHOUT any manual layer."""
    j = v_out["judgement"]
    if j == "pass_mechanical":
        return (
            "PASS",
            "mechanical_projection+citations+coverage",
            "投影集合全等、引用经冻结守卫身份独立重读、覆盖 complete（仍受主agent抽审）",
        )
    if j in _POS_FAIL:
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
            det.append(
                f"masked_citation_details={v_out['masked_citations']}（局部 unknown，不改整题结论）"
            )
        if v_out.get("judgement") == "unverified_citation":
            det.append(f"unverified={v_out.get('unverified_citations', [])[:1]}")
        return ("FAIL", "mechanical", f"judgement={j}; " + "; ".join(det))
    if j in _POS_PENDING:
        return (
            "PENDING",
            "evidence_gap",
            f"judgement={j}; masked={v_out.get('masked_citations', 0)} gaps={v_out.get('citation_gaps', 0)}",
        )
    return ("PENDING", "unclassified", f"judgement={j}")


def _hard_positive_failure(v_out: dict) -> str | None:
    """S2 r2: facts that a manual PASS can NEVER override, computed BEFORE the
    manual layer (a synthesis judgement pinned to pending must not dodge
    them): budget/runtime failure, coverage not complete, zero delivery on an
    ok runtime, missing/extra/foreign set violations, citation verification
    failures that are not pure masking."""
    det = []
    if v_out.get("budget_failure"):
        det.append(f"budget_failure={v_out['budget_failure']}")
    rt = v_out.get("runtime")
    if rt not in ("ok", None, "absent"):
        det.append(f"runtime={rt}")
    if rt == "ok":
        cov = v_out.get("coverage")
        if cov != "complete":
            det.append(f"coverage={cov}（非 complete）")
        n = v_out.get("delivered")
        n_items = n if isinstance(n, int) else (len(n) if n else 0)
        if n_items == 0:
            det.append("0 交付——raw 正确不等于应用完成")
        for k in ("missing", "extra", "extra_rows", "extra_out_of_scope", "extra_in_scope"):
            if v_out.get(k):
                det.append(f"{k}={v_out[k]}")
        if v_out.get("foreign_table_docs"):
            det.append(f"foreign_docs={v_out['foreign_table_docs'][:2]}")
        if (
            v_out.get("unverified_citations")
            and v_out.get("judgement") != "pending_artifact_masking"
        ):
            det.append(f"unverified_citations={len(v_out['unverified_citations'])}")
    return "; ".join(det) or None


def finalize_positive(v_out: dict, manual: dict | None) -> dict:
    """A6: canonical final_status. A decisive whole-question failure can never
    be softened to PENDING by an item-level unknown; PENDING only when nothing
    decisive is established either way.
    Generation mode adds the RECORD channel: FAIL overrides; PASS resolves
    ONLY an evidence-gap PENDING whose record audited the gap's required
    items — it can never rescue an established failure (wrong source/value/
    missing/uncited), and 'raw model was right but the app delivered 0' is
    not completion. Round-1 compat behaviour is byte-for-function identical
    (its table contains FAILs only)."""
    j = v_out["judgement"]
    v_out.pop("_model", None)
    if _generation_mode() and j == "synthesis_pending_human_review":
        # R1 r3: established hard failures (partial coverage, fabricated/
        # unverified citations, zero delivery, set violations) are decided
        # BEFORE any manual branch — including no-record — so "unaudited"
        # never softens a known incomplete synthesis into PENDING. Real
        # fragments and any submitted record stay visible on the row.
        hard = _hard_positive_failure(v_out)
        if hard is not None:
            if manual is not None:
                v_out["manual_review"] = manual
            v_out["final_status"] = "FAIL"
            v_out["final_basis"] = "mechanical_hard_failure"
            v_out["final_reason"] = hard + "（已证实的硬失败不依赖人工状态，也不因未审而软化）"
            return v_out
    if manual is not None:
        v_out["manual_review"] = manual
        if manual["verdict"] == "FAIL":
            v_out["final_status"] = "FAIL"
            v_out["final_basis"] = "manual"
            v_out["final_reason"] = manual["reason"]
            return v_out
        if manual["verdict"] == "PASS":
            m_status, m_basis, m_reason = _mechanical_positive(v_out)
            hard = _hard_positive_failure(v_out)
            if hard is not None:
                v_out["final_status"] = "FAIL"
                v_out["final_basis"] = "hard_failure_before_manual"
                v_out["final_reason"] = (
                    f"{hard}；PASS 记录不能把整题升级（部分真实片段保留为诊断，不折算通过）"
                )
                v_out["manual_pass_refused"] = hard
                return v_out
            if j not in _POS_PENDING | {"synthesis_pending_human_review"}:
                v_out["final_status"] = m_status
                v_out["final_basis"] = m_basis
                v_out["final_reason"] = m_reason + "; 未知 judgement 不允许任意 PASS"
                return v_out
            if j == "synthesis_pending_human_review" and not (
                {"semantic_answer", "whole_question_semantics"}
                & set(manual.get("checked_items") or [])
            ):
                v_out["final_status"] = "PENDING"
                v_out["final_basis"] = "evidence_gap"
                v_out["final_reason"] = (
                    m_reason + "; 合成 PASS 须具名整题语义审查（semantic_answer）"
                )
                return v_out
            delivered = v_out.get("delivered")
            n_items = (
                delivered if isinstance(delivered, int) else (len(delivered) if delivered else 0)
            )
            if m_status == "FAIL" or n_items == 0:
                v_out["final_status"] = m_status
                v_out["final_basis"] = m_basis
                v_out["final_reason"] = m_reason
                v_out["manual_pass_refused"] = (
                    "PASS 记录不能救已证实的机械失败/零交付（raw 正确≠应用交付完成）；"
                    "行保持机械终判，冲突公开记录"
                )
                return v_out
            if m_status == "PENDING":
                required = _GAP_CHECK_REQUIRED.get(j)
                if required and not set(required) <= set(manual.get("checked_items") or []):
                    v_out["final_status"] = "PENDING"
                    v_out["final_basis"] = "evidence_gap"
                    v_out["final_reason"] = m_reason + f"; PASS 记录缺已核项 {required}"
                    return v_out
                v_out["final_status"] = "PASS"
                v_out["final_basis"] = "manual_record_audited_gap"
                v_out["final_reason"] = manual["reason"]
                return v_out
            # mechanical PASS stands; a concordant record just annotates it
            return _mech_pass_finalize(v_out)
        # verdict == PENDING: human reviewed but could not decide — never
        # below mechanical FAIL, above nothing: mechanical PASS downgrades to
        # PENDING only when the record says why.
        m_status, m_basis, m_reason = _mechanical_positive(v_out)
        if m_status == "FAIL":
            v_out["final_status"], v_out["final_basis"], v_out["final_reason"] = (
                m_status,
                m_basis,
                m_reason,
            )
            return v_out
        v_out["final_status"] = "PENDING"
        v_out["final_basis"] = "manual_record_pending"
        v_out["final_reason"] = manual["reason"]
        return v_out
    return (
        _mech_pass_finalize(v_out) if j == "pass_mechanical" else _mechanical_finalize_rest(v_out)
    )


def _mech_pass_finalize(v_out: dict) -> dict:
    st, basis, reason = _mechanical_positive(v_out)
    v_out["final_status"], v_out["final_basis"], v_out["final_reason"] = st, basis, reason
    return v_out


def _mechanical_finalize_rest(v_out: dict) -> dict:
    st, basis, reason = _mechanical_positive(v_out)
    v_out["final_status"], v_out["final_basis"], v_out["final_reason"] = st, basis, reason
    return v_out


def finalize_counter(v_out: dict) -> dict:
    """R2 (main agent ruling table, 2026-10-08): the whole-question verdict
    asks whether the FROZEN BEHAVIOUR CONTRACT was met from this leg's actual
    evidence. Safety observations — no false complete, the PG quota gate
    refused before the request, no foreign workspace seen on THIS leg — are
    recorded in `local_safety_observations` and can NEVER convert into a
    whole-question PASS. Runtime failure / missing artifact is a third
    category, distinct from an explicit refusal answer. expected_status stays
    a post-hoc label; nothing here routes the run."""
    qid = v_out.get("qid")
    j = str(v_out.get("judgement"))
    cov = v_out.get("coverage")
    runtime = v_out.get("runtime")
    n = v_out.get("delivered")
    if isinstance(n, list):
        n = len(n)
    if not isinstance(n, int):
        n = None
    obs: list = []

    def done(status, basis, reason):
        v_out["final_status"] = status
        v_out["final_basis"] = basis
        v_out["final_reason"] = reason
        v_out["local_safety_observations"] = obs
        return v_out

    if qid in ("neg-003", "neg-004"):
        if j == "behaviour_ok_mechanical":
            return done(
                "PASS",
                "frozen_behaviour_contract",
                "整题行为有结构证据：集合/覆盖/引用身份全部通过"
                + ("（neg-003 自身编号集合）" if qid == "neg-003" else "（合并合同 13 项 exact）"),
            )
        det = []
        if v_out.get("foreign_table_docs"):
            det.append(f"foreign_docs={v_out['foreign_table_docs'][:2]}")
        if v_out.get("extra_rows"):
            det.append(f"extra_rows={v_out['extra_rows']}")
        if v_out.get("all_citations_verified") is False:
            obs.append("引用身份未证，行为不可判成")
        return done("FAIL", "frozen_behaviour_contract", f"judgement={j}; " + "; ".join(det))

    if qid == "neg-005":
        if j == "behaviour_violation_merges_or_overclaims":
            return done(
                "FAIL",
                "frozen_behaviour_contract",
                f"跨 {len(v_out.get('docs_cited') or [])} 文档 complete 交付，不符冻结 ambiguous（仅判当前行为，不宣称底层表身份串并）",
            )
        return done("PENDING", "content_review", "ambiguous 状态形态相符，77 行内容待复核")

    if qid in ("neg-001", "neg-006"):
        if runtime != "ok":
            obs.append("0 交付但工件缺失——记录，不能当作 explicit missing 答复")
            return done("PENDING", "evidence_absent", f"runtime={runtime}")
        if cov == "missing" and n == 0:
            obs.append("未用版本替代")
            return done(
                "PASS",
                "frozen_behaviour_contract",
                "显式 missing 答复（missing 形态、0 交付）——有证据支持",
            )
        if n == 0:
            obs.append("未乱答 / 无 false complete")
            return done(
                "FAIL",
                "frozen_behaviour_contract",
                f"coverage={cov}，未明确回答 missing——仅 partial/条件不足不等同冻结答复合同",
            )
        return done("FAIL", "frozen_behaviour_contract", "存在交付而期望为 missing 答复")

    if qid == "neg-002":
        obs.append("本腿未见外来 workspace（观测级隔离，非 same-id 对抗实弹）")
        return done(
            "PENDING", "isolation_contract_unproven", "隔离合同需对抗证据；观测不升格为 PASS"
        )

    if qid == "neg-007":
        if n == 0:
            obs.append("保守拒绝，未编造表号")
        if cov == "ambiguous" and runtime == "ok":
            return done("PENDING", "content_review", "ambiguous 形态到达，内容待复核")
        return done(
            "FAIL",
            "frozen_behaviour_contract",
            f"coverage={cov} ≠ 冻结 ambiguous——保守拒绝不等同合同满足",
        )

    if qid == "neg-008":
        obs.append("PG 请求前额度闸门拒绝执行正常（该控制项单独记录为有效）")
        return done(
            "PENDING",
            "coverage_gap",
            "该成员/字符展开预算反例未获生产实测——整题不可标 PASS；闸门成功控制独立记录",
        )

    if qid == "neg-009":
        obs.append("本结果不构成内容丢失或版本乱答的证据")
        if runtime != "ok":
            return done("PENDING", "evidence_absent", f"runtime={runtime}")
        if n == 0:
            return done(
                "FAIL", "frozen_behaviour_contract", "expected 应答（ok）而 0 交付——整题未回答"
            )
        return done("PENDING", "content_review", "有交付，内容待复核")

    if qid == "neg-010":
        if runtime != "ok":
            return done("PENDING", "evidence_absent", f"runtime={runtime}")
        if n == 0:
            obs.append(f"{v_out.get('model_status')}（保守不发记录，无 over-claim）")
            return done(
                "FAIL",
                "frozen_behaviour_contract",
                "expected 应答而 0 交付——整题未回答（model_failure/条件不足保留）",
            )
        if n == 4 and not _generation_mode():
            # the "delivered 4 real clauses without answering the replacement
            # relation" reading is the Round-1 semantic verdict of the main
            # agent — a historical human conclusion. A NEW generation may not
            # inherit it: it lands in content_review and a bound record
            # decides.
            return done(
                "FAIL",
                "frozen_behaviour_contract",
                "四条原标准 4.1 条款来源真实但未回答替代关系——主 agent 语义裁决整题 FAIL",
            )
        return done("PENDING", "content_review", "有交付，内容待复核")

    # any other counter leg: never auto-PASS from silence
    if runtime not in ("ok", None):
        return done(
            "PENDING",
            "evidence_absent",
            f"runtime={runtime}, judgement={j}——证据缺失不等同明确拒绝答复",
        )
    if n == 0:
        obs.append("无 false complete")
    return done("PENDING", "behaviour_review", f"judgement={j}（无整题裁决证据，不自动通过）")


def apply_counter_record(v_out: dict) -> dict:
    """Generation mode: a bound review record may decide a counter row's
    semantics. Same safety direction as positives: FAIL is decisive; PASS
    resolves ONLY a mechanical PENDING and can never override an established
    behaviour-contract FAIL; unbound/unrecorded rows keep their mechanical
    status. Compat mode: no-op."""
    if not _generation_mode():
        return v_out
    rec = REVIEW_RECORDS.get((GEN_ROUND, v_out["qid"], v_out["path"]))
    if rec is None:
        return v_out
    art = _answer_runtime_path(v_out["path"], v_out["qid"])
    if not art.exists() or sha(art) != rec["answer_runtime_sha256"]:
        raise InputIntegrityError(
            f"counter review record binding mismatch for {rec['qid']}/{rec['path']} r{rec['round']}"
        )
    v_out["manual_review"] = {
        "verdict": rec["verdict"],
        "reason": rec["reason"],
        "checked_items": rec["checked_items"],
        "reviewer": rec["reviewer"],
        "binding": {"answer_runtime_sha256": rec["answer_runtime_sha256"]},
    }
    mech = v_out["final_status"]
    if rec["verdict"] == "FAIL":
        v_out["final_status"] = "FAIL"
        v_out["final_basis"] = "manual_record"
        v_out["final_reason"] = rec["reason"]
    elif rec["verdict"] == "PASS":
        if mech == "FAIL":
            v_out["manual_pass_refused"] = "PASS 记录不能覆盖已证实的行为合同失败"
        elif mech == "PENDING":
            if not (rec.get("checked_items") or []):
                v_out["manual_pass_refused"] = "PASS 记录未列已核项，行保留 PENDING"
            elif v_out.get("all_citations_verified") is False or (v_out.get("delivered") == 0):
                v_out["manual_pass_refused"] = (
                    "反例 PASS 记录不能覆盖引用失败/0 交付（raw 正确≠应用完成）"
                )
            else:
                v_out["final_status"] = "PASS"
                v_out["final_basis"] = "manual_record_audited_gap"
                v_out["final_reason"] = rec["reason"]
    elif rec["verdict"] == "PENDING" and mech == "PASS":
        v_out["final_status"] = "PENDING"
        v_out["final_basis"] = "manual_record_pending"
        v_out["final_reason"] = rec["reason"]
    return v_out


# ---------------------------------------------------------------------------
# 4. recall — A5: typed discovery + chunk candidates, separate segments
# ---------------------------------------------------------------------------


def _fusion_segments(qid: str, path: str) -> dict | None:
    """Read the SAVED pre-expansion shapes of a pg/fusion leg exactly as
    fusion._normalize_pg wrote them: chunk candidates (ordered) and typed
    targets (doc/scope/table_unit discovery). Never borrows usable or
    targets_resolved (post-resolve), never the answers."""
    p = ROUND1 / "legs" / ROUND_TAG / path / qid / "fusion" / "fusion-runtime-latest.json"
    if not p.exists():
        return None
    _consume(p)
    r0 = json.loads(p.read_text(encoding="utf-8")).get("results", [{}])[0]
    _bind_leg_identity("fusion", qid, r0)
    cands, tt = r0.get("candidates"), r0.get("typed_targets")
    if not isinstance(cands, list) or not isinstance(tt, list):
        return None
    pgblk = r0.get("pg") or {}
    if pgblk.get("discovery_captured") is False:
        return None
    chunk_docs = [c.get("doc_id") for c in cands if isinstance(c, dict) and c.get("doc_id")]
    chunk_ids = [
        {
            "workspace": c.get("workspace"),
            "doc_id": c.get("doc_id"),
            "chunk_id": c.get("chunk_id"),
        }
        for c in cands
        if isinstance(c, dict) and c.get("chunk_id")
    ]
    typed = []
    for t in tt:
        if isinstance(t, dict) and t.get("doc_id"):
            # R2 r3: keep the FULL published identity (unit_id/table_id/
            # scope_id/citation/basis/status) — copying only doc fields and
            # then expecting downstream to read unit_id/scope_id dropped them.
            typed.append(dict(t))
    return {"chunk_docs": chunk_docs, "chunk_ids": chunk_ids, "typed": typed}


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
    _consume(p)
    d = json.loads(p.read_text(encoding="utf-8"))
    r0 = d.get("results", [{}])[0]
    _bind_leg_identity("local-input", qid, r0)
    return [u.get("doc_id") for u in r0.get("usable") or [] if u.get("doc_id")]


def local_discovery_identities(qid: str):
    """raw (workspace, doc_id, chunk_id) of verified pre-expansion local
    discovery, or None when the artifact/shape is unavailable."""
    p = ROUND1 / "inputs" / "local" / f"{qid}-fusion.json"
    if not p.exists():
        return None
    _consume(p)
    d = json.loads(p.read_text(encoding="utf-8"))
    r0 = d.get("results", [{}])[0]
    _bind_leg_identity("local-input", qid, r0)
    out = []
    for u in r0.get("usable") or []:
        if isinstance(u, dict) and u.get("chunk_id"):
            out.append(
                {
                    "workspace": u.get("workspace"),
                    "doc_id": u.get("doc_id"),
                    "chunk_id": u.get("chunk_id"),
                }
            )
    return out


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
                    "chunk_recall_at_20": round(
                        len(({d for d in chunks[:20]}) & expected) / len(expected), 3
                    ),
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
                        "usable_recall_at_20": round(
                            len({d for d in docs[:20]} & expected) / len(expected), 3
                        ),
                        "explicit_zero": len(docs) == 0,
                    }
        out["per_question"][q["query_id"]] = row
    return out


# ---------------------------------------------------------------------------
# 4b. unit-mapping channel (generation mode ONLY; compat never reads it)
# ---------------------------------------------------------------------------

MAPPING: dict | None = None
MAPPING_REJECTED: list = []


def load_mapping_manifest(path: Path) -> dict:
    """Format see mapping-collection-design.md. Entries bind the COMPOSITE
    key (workspace, doc_id, snapshot_id, unit_id) plus chunk ids and the
    content SHA. Foreign-workspace/foreign-snapshot entries are rejected
    (never mixed into this run's evidence); an EMPTY table is rejected as
    'not complete' rather than treated as coverage."""
    global MAPPING, MAPPING_REJECTED
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != "unit-mapping/r1":
        raise InputIntegrityError(f"mapping schema unsupported: {data.get('schema')!r}")
    ident = FROZEN_IDENTITY or {}
    ws, snap = ident.get("workspace"), ident.get("catalog_snapshot_id")
    if data.get("workspace") != ws or data.get("catalog_snapshot_id") != snap:
        raise InputIntegrityError("mapping manifest bound to a different workspace/snapshot")
    if data.get("source_fingerprint") != ident.get("source_fingerprint"):
        raise InputIntegrityError("mapping manifest bound to a different source fingerprint")
    entries = data.get("entries") or []
    if not entries:
        raise InputIntegrityError(
            "mapping table empty — missing mappings must stay pending, empty is not complete"
        )
    good, rejected = {}, []
    for e in entries:
        if e.get("workspace") != ws or e.get("snapshot_id") != snap:
            rejected.append(
                {"unit_id": e.get("unit_id"), "reason": "foreign workspace/snapshot reference"}
            )
            continue
        if (
            not e.get("unit_id")
            or not e.get("doc_id")
            or not e.get("chunk_ids")
            or not e.get("content_sha256")
        ):
            rejected.append(
                {"unit_id": e.get("unit_id"), "reason": "incomplete composite key/evidence"}
            )
            continue
        # S3 r2: FULL composite key (workspace, doc, snapshot, unit) — the
        # same unit_id on two documents must never overwrite each other.
        comp = (e["workspace"], e["doc_id"], e["snapshot_id"], e["unit_id"])
        if comp in good and good[comp] != e:
            raise InputIntegrityError(
                f"conflicting duplicate mapping entry for {comp[3]}@{comp[1]}"
            )
        good[comp] = e
    units_by_id = {}
    for c in good:
        units_by_id.setdefault(c[3], []).append(c)
    MAPPING = {
        "index": good,
        "units": units_by_id,
        "rejected": rejected,
        "manifest_sha": sha(Path(path)),
    }
    MAPPING_REJECTED = rejected
    return MAPPING


def typed_evidence_recall(gold: dict) -> dict | None:
    """Generation-mode typed EVIDENCE (unit-level) recall over PRE-EXPANSION
    discovery only — S3 r2: a unit is hit by its OWN identity (a discovered
    chunk that is actually inside the mapped unit's chunk_ids, or a typed
    target carrying that unit/scope identity), NEVER by "its document was
    discovered". mapping absent -> None (compat keeps pending). Unmapped
    expected units stay in the question's expectation; any unresolved unit
    makes the published metric null (pending) — the known parts are listed
    but a shrunk denominator can never produce a perfect score.
    Enumeration answers/rerank/expansion never feed this number."""
    if not _generation_mode() or MAPPING is None:
        return None
    ident = FROZEN_IDENTITY or {}
    ws, snap = ident.get("workspace"), ident.get("catalog_snapshot_id")
    per_q = {}
    for q in gold["questions"]:
        targets = [
            t
            for t in (q.get("gold") or {}).get("target_evidence") or []
            if isinstance(t, dict) and t.get("unit_id")
        ]
        if not targets:
            continue
        row = {}
        for path in POSITIVE_PATHS:
            typed = []
            if path in ("pg", "fusion"):
                seg = _fusion_segments(q["query_id"], path)
                if seg is None:
                    row[path] = "pending_no_artifact"
                    continue
                chunks = seg["chunk_ids"]
                typed = seg["typed"]
            else:
                ids = local_discovery_identities(q["query_id"])
                if ids is None:
                    row[path] = "pending_no_artifact"
                    continue
                chunks = ids
            chunk_set = {(c.get("workspace"), c.get("doc_id"), c.get("chunk_id")) for c in chunks}
            covered, missed, pending = [], [], []
            for tt in targets:
                comp = (tt.get("workspace", ws), tt.get("doc_id"), snap, tt["unit_id"])
                ent = MAPPING["index"].get(comp)
                if ent is None:
                    pending.append(comp[3])
                    continue
                hit = any(
                    w == comp[0] and d == comp[1] and cid in set(ent.get("chunk_ids") or [])
                    for (w, d, cid) in chunk_set
                )
                if not hit and typed:
                    # R2 r3: typed hits are bound by the FULL composite
                    # identity — the target's own workspace/doc must match the
                    # expected unit's; a same-named scope on another workspace
                    # or document never hits.
                    def _own(x):
                        return x.get("doc_id") == comp[1] and (x.get("workspace") or ws) == comp[0]

                    hit = any(
                        (x.get("unit_id") == comp[3] and _own(x))
                        or (
                            x.get("scope_id")
                            and _own(x)
                            and any(
                                s.get("scope_id") == x["scope_id"] for s in ent.get("scopes") or []
                            )
                        )
                        for x in typed
                    )
                (covered if hit else missed).append(comp[3])
            unresolved = bool(pending)
            denom = len(covered) + len(missed) + len(pending)
            row[path] = {
                "typed_evidence_recall": None
                if unresolved
                else (round(len(covered) / denom, 3) if denom else 0.0),
                "covered": sorted(covered),
                "missed": sorted(missed),
                "pending_unmapped": sorted(pending),
                "published_basis": "存在未解析 unit——发布指标置 null(pending)，已知分列但不缩分母"
                if unresolved
                else "期望 unit 全部按组合身份解析",
                "explicit_zero_discovery": len(chunk_set) == 0 and not typed,
                "backfill": "枚举/展开/精排结果一律不参与",
            }
        per_q[q["query_id"]] = row
    return {
        "per_question": per_q,
        "manifest_sha256": MAPPING["manifest_sha"],
        "rejected_entries": MAPPING_REJECTED,
        "note": "unit 命中=发现 chunk 真在该 unit 的 chunk_ids 内，或 typed 目标自带该 unit/scope 身份；"
        "typed-doc 发现只算文档存在，不自动命中其 unit；缺映射 pending；跨 workspace 条目加载即拒",
    }


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
    timings = {
        "discovery_inclusive_rerank_ms": pct(disc_incl),
        "discovery_exclusive_rerank_approx_ms": pct(disc_excl),
        "rerank_ms": pct(rer),
        "answer_ms_composite_unsplit": pct(ans),
        "total_ms_recorded": pct(tot),
        "answer_stage_stages_unavailable": "answer_ms 内含范围展开/生成/复核，独立阶段计时 unavailable；模型 call.latency 仅 HTTP 时间不冒充全生成",
    }
    if _generation_mode():
        return {
            "reserved_vs_issued_diffs": diffs,
            "refusals": {"events": refusals},
            "answer_http_by_leg": dict(answer_issued_by_leg(terminal)),
            "timings": timings,
            "recorded_total_sum_s": round(total_sum_ms / 1000, 3),
            "serial_cache_condition": "run structure as recorded by the owning entry; every value from THIS run's ledger receipts",
        }
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
        "timings": timings,
        "recorded_total_sum_s": round(total_sum_ms / 1000, 3),
        "wall_artifact_mtime_span_s": round(last_art - first_art, 1)
        if first_art and last_art
        else None,
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


def _sanitize(text: str) -> str:
    return re.sub(
        r"(?i)(api[_-]?key|secret|password|passwd|token|dsn)\s*[=:]\s*\S+",
        r"\1=<redacted>",
        str(text),
    )


def _write_rejection(out_dir: Path, problems: list, exc: Exception | None = None) -> None:
    """R3: one sanitized reject diagnostic; the real exception TYPE and reason
    are preserved (truncated, credential-pattern scrubbed)."""
    diag: dict = {
        "schema": "assessment-input-rejection/r3",
        "problems": [_sanitize(p)[:300] for p in problems],
    }
    if exc is not None:
        diag["exception"] = {"type": type(exc).__name__, "message": _sanitize(str(exc))[:300]}
    (out_dir / "input-rejection.json").write_text(
        json.dumps(diag, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


def _load_gold_by():
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
    return gold, gold_by


def _score_legs(terminal: dict, gold_by: dict, doc_reg: dict, issued_legs: dict) -> list:
    table13 = next(
        (q["gold"].get("expected_items") or [])
        for q in json.loads(GOLD_PATH.read_text(encoding="utf-8"))["questions"]
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
            if note is not None and qid == "neg-010" and r["path"] == "fusion":
                # R2: the semantic FAIL carries the four actually-delivered
                # fragments' positions, not just a boolean.
                note["delivered_item_citations"] = [
                    {
                        "doc_id": (it.get("citation") or {}).get("doc_id"),
                        "unit_id": (it.get("citation") or {}).get("unit_id"),
                        "clause": it.get("clause"),
                        "quote_head": str((it.get("citation") or {}).get("quote") or "")[:28],
                    }
                    for it in items
                ]
            if note is not None:
                v["manual_review"] = note
            v_out = apply_counter_record(finalize_counter(v))
            v_out.pop("_model", None)
        else:
            v = score_row(qid, r["path"], entry, gq, bool(r["is_counter"]), doc_reg)
            v["_model"] = meta.get("model")
            manual = manual_review_for(v, issued_legs)
            if v["category"] == "synthesis" and manual is None and not _generation_mode():
                manual = {
                    "verdict": "FAIL",
                    "reason": "合成题人工复核未记录理由——按整题未证通过处理（保守 FAIL，不冒充已审）",
                    "delivered_items": v.get("delivered"),
                    "coverage": v.get("coverage"),
                    "answer_http_issued": int(issued_legs.get(f"{ROUND_TAG}/{v['path']}/{qid}", 0)),
                    "artifact": f"legs/{ROUND_TAG}/{v['path']}/{qid}/answer/answer-runtime-latest.json",
                    "reviewer": "执行agent 离线人工复核（逐题，2026-10-08）",
                }
            v_out = finalize_positive(v, manual)
        verdicts.append(v_out)
    return verdicts


def _assemble_results(verdicts, verification, recall, ledger, gen_mode) -> dict:
    return {
        "schema": "phase-4-generation-assessment/r2" if gen_mode else "round-1-assessment/r3",
        "supersedes": (
            f"this adjudication supersedes nothing; bound to {ROUND1} r{GEN_ROUND}"
            if gen_mode
            else "reports/pg-retrieval/phase-4-round-1-assessment/ (r1 机械 verdicts) 与 phase-4-round-1-assessment-r2/ (r2 层) 均保留作历史；本 r3 为最终裁决代次"
        ),
        "inputs_verification": verification,
        "rows": verdicts,
        "summary": _summary(verdicts),
        "recall": recall,
        "ledger_and_timing": ledger,
        "policy_notes": {
            "final_layering": "final_status 从整题决定性证据出发：投影/集合/合同/覆盖/人工失败优先；掩码等细项 unknown 单列不软化整题结论",
            "recall": "typed 与 chunk 分段呈现，无统一 @20 声明；typed 证据召回按组合身份；旧均值撤下",
            "source_qualification": "workspace/snapshot/doc 身份经冻结守卫+SHA 守卫输入独立核对后方为 verified；catalog 名称须经独立输入证据定位",
            "declaration_support": "R1：所交付全文须由声明的原始 unit 跨度/按声明顺序的跨 unit segments 完整回读（空白归一包含，非 LLM）；item.doc_id 与 citation.doc_id 必须一致；两种金标形状的编号都绑定 item.clause",
            "counter_layering": "R2：整题裁决=冻结行为合同是否达成（主 agent 2026-10-08 裁决表）；'无 false complete/额度闸门拒绝/本腿未见外 workspace'等安全观测单列于 local_safety_observations，不折算整题 PASS；runtime 失败/工件缺失为第三类",
            "reject_boundary": "R3：后置身份必验（结构+与冻结及 before 一致）；解析证据内容绑定=Gate-0 parsed_blocks_tables_bytes 复算对账；verify/读/解析统一拒绝边界，诊断净化后非零抛出",
            "expected_routing": "expected 仅事后对照，从不路由；反例判实际行为",
        },
    }


def _write_rejection_unique(rej_dir: Path, problems, exc=None) -> Path:
    """S4: publish a refusal diagnostic WITHOUT overwriting another
    generation's/round's diagnostics in the same directory."""
    cand = rej_dir / "input-rejection.json"
    n = 1
    while cand.exists():
        cand = rej_dir / f"input-rejection-{n}.json"
        n += 1
    diag = {
        "schema": "assessment-input-rejection/r2",
        "problems": [_sanitize(p)[:300] for p in problems],
    }
    if exc is not None:
        diag["exception"] = {"type": type(exc).__name__, "message": _sanitize(str(exc))[:300]}
    cand.write_text(json.dumps(diag, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return cand


def _atomic_publish(out_file: Path, text: str) -> None:
    tmp = out_file.with_name(out_file.name + ".partial")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, out_file)


def main(argv=()) -> None:
    """Default (no argv) = Round-1 compat, byte-for-function identical to the
    accepted r3 scorer (frozen matrices call main() directly). Generation
    binding is opt-in via explicit CLI arguments only; S4 makes the WHOLE
    generation flow share one rejection boundary that covers records/mapping
    loading, input verification, every artifact read/parse, scoring, recall,
    ledger and result assembly — any ordinary exception (InputIntegrityError
    included) publishes a sanitized diagnostic and never an adjudication."""
    ap = argparse.ArgumentParser(description="phase-4 scoring readiness copy (compat by default)")
    ap.add_argument("--run-dir", help="generation mode: this run's report dir")
    ap.add_argument("--round", type=int, help="generation mode: actual round number (r{N} tag)")
    ap.add_argument("--anchor", help="generation mode: the APPROVED anchor for this lineage")
    ap.add_argument(
        "--manifest", default="pilot-manifest.json", help="generation mode: run manifest file name"
    )
    ap.add_argument("--records", help="generation mode: bound human review records")
    ap.add_argument("--mapping", help="generation mode: unit-mapping manifest")
    ap.add_argument("--out", help="generation mode: adjudication output path")
    args = ap.parse_args(argv)

    if args.run_dir:
        # ---------------- generation mode: single owning failure boundary ----
        if not args.round or not args.anchor:
            raise SystemExit("--run-dir requires --round and --anchor (generation binding)")
        out_file = (
            Path(args.out) if args.out else Path(args.run_dir) / f"adjudication-r{args.round}.json"
        )
        if out_file.exists():
            raise SystemExit(f"generation adjudication output already exists: {out_file}")
        configure_generation(Path(args.run_dir), args.round, Path(args.anchor), args.manifest)
        rej_dir = out_file.parent
        rej_dir.mkdir(parents=True, exist_ok=True)
        diag_written = False
        try:
            if args.records:
                load_review_records(Path(args.records))
            if args.mapping:
                load_mapping_manifest(Path(args.mapping))
            verification = verify_inputs()
            if not verification["ok"]:
                _write_rejection_unique(rej_dir, verification["problems"])
                diag_written = True
                raise InputIntegrityError(
                    "assessment inputs failed integrity verification: "
                    + "; ".join(verification["problems"])
                )
            gold, gold_by = _load_gold_by()
            terminal = load_terminal()
            doc_reg = doc_registry()
            issued_legs = answer_issued_by_leg(terminal)
            global _STRICT_BIND
            prev_strict = _STRICT_BIND
            _STRICT_BIND = True
            try:
                verdicts = _score_legs(terminal, gold_by, doc_reg, issued_legs)
                # S1: every file actually consumed must be bound by the manifest
                man = json.loads((ROUND1 / RUN_MANIFEST_NAME).read_text(encoding="utf-8"))["files"]
                bound = {str((REPO / k).resolve()) for k in man}  # absolute k stays k
                # explicit attachments (anchor/records/mapping) bind by CLI argument
                # with their SHA recorded in generation_binding — they live outside
                # the run directory by design and are not run-manifest artifacts.
                attachments = {
                    str(Path(ANCHOR_PATH).resolve()),
                    str(REVIEW_RECORDS_PATH.resolve()) if REVIEW_RECORDS_PATH else None,
                    str(Path(args.mapping).resolve()) if args.mapping else None,
                } - {None}
                unbound = sorted(p for p in CONSUMED if p not in bound | attachments)
                if unbound:
                    raise InputIntegrityError(
                        f"consumed artifacts not bound by manifest: {len(unbound)} (e.g. {unbound[:2]})"
                    )
                # r4 scope: strict identity binding spans the WHOLE formal
                # consumption path. recall_report/typed_evidence_recall
                # re-read the same official fusion/local artifacts through
                # _fusion_segments / pre_expansion_docs /
                # local_discovery_identities; running them AFTER the switch
                # had closed let a placed SUCCESS row missing
                # query_id/workspace pass as a lenient bare probe. The S1
                # coverage check moves with them so fusion/local artifacts
                # consumed here are manifest-bound before publish, and the
                # finally restores the pre-entry value on success AND on
                # every exception — direct (bare-interface) callers outside
                # main never enter this scope and keep lenient probe
                # semantics.
                recall = recall_report(gold)
                typed = typed_evidence_recall(gold)
                if typed is not None:
                    recall["typed_evidence_recall"] = typed
            finally:
                _STRICT_BIND = prev_strict
            ledger = ledger_corrections(terminal)
            results = _assemble_results(verdicts, verification, recall, ledger, gen_mode=True)
            results["generation_binding"] = {
                "run_dir": str(ROUND1),
                "round": GEN_ROUND,
                "anchor": str(ANCHOR_PATH),
                "anchor_sha256": sha(ANCHOR_PATH),
                "run_manifest": RUN_MANIFEST_NAME,
                "manual_records": str(REVIEW_RECORDS_PATH) if REVIEW_RECORDS_PATH else None,
                "manual_records_sha256": sha(REVIEW_RECORDS_PATH) if REVIEW_RECORDS_PATH else None,
                "records_bound": sum(1 for v in verdicts if "manual_review" in v),
                "mapping_manifest_sha256": (MAPPING or {}).get("manifest_sha"),
                "consumed_files": len(CONSUMED),
            }
            _atomic_publish(out_file, json.dumps(results, ensure_ascii=False, indent=1) + "\n")
        except (SystemExit, KeyboardInterrupt):
            raise
        except Exception as exc:  # noqa: BLE001 — the ONE generation boundary
            # R3 r3: the PRESENCE of an earlier invocation's diagnostic must
            # never silence this one's; _write_rejection_unique appends a new
            # uniquely-named file and the per-call flag prevents a double
            # write for the same failure. Every rejection keeps its own cause.
            if not diag_written:
                _write_rejection_unique(rej_dir, ["generation flow failed before publish"], exc)
            raise InputIntegrityError(
                f"generation assessment rejected: {type(exc).__name__}: {_sanitize(str(exc))[:200]}"
            ) from exc
        print("rows:", len(verdicts))
        print(json.dumps(results["summary"]["totals"], ensure_ascii=False))
        print("inputs ok: True | manifest entries:", verification["manifest"]["entries"])
        return

    # ---------------- Round-1 compat: accepted r3 flow, untouched ------------
    out_dir = Path(__file__).resolve().parent
    rej_dir = out_dir
    try:
        verification = verify_inputs()
        if not verification["ok"]:
            _write_rejection(rej_dir, verification["problems"])
            raise InputIntegrityError(
                "assessment inputs failed integrity verification: "
                + "; ".join(verification["problems"])
            )
        gold, gold_by = _load_gold_by()
        terminal = load_terminal()
        doc_reg = doc_registry()
        issued_legs = answer_issued_by_leg(terminal)
    except InputIntegrityError:
        raise
    except Exception as exc:  # noqa: BLE001 — the one unified reject path
        _write_rejection(rej_dir, ["input verification/read/parse error before scoring"], exc)
        raise InputIntegrityError(
            f"assessment inputs unreadable before scoring: {type(exc).__name__}: {_sanitize(str(exc))[:200]}"
        ) from exc

    verdicts = _score_legs(terminal, gold_by, doc_reg, issued_legs)
    recall = recall_report(gold)
    typed = typed_evidence_recall(gold)
    if typed is not None:
        recall["typed_evidence_recall"] = typed
    ledger = ledger_corrections(terminal)
    results = _assemble_results(verdicts, verification, recall, ledger, gen_mode=False)
    (out_dir / "adjudication.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print("rows:", len(verdicts))
    print(json.dumps(results["summary"]["totals"], ensure_ascii=False))
    byj = defaultdict(int)
    for v in verdicts:
        byj[v["judgement"]] += 1
    print(json.dumps(dict(byj), ensure_ascii=False, indent=1))
    print(
        "inputs ok:", verification["ok"], "| manifest entries:", verification["manifest"]["entries"]
    )
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
    main(sys.argv[1:])
