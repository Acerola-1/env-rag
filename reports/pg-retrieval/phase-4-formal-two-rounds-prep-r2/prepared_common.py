"""Offline checks for the explicit formal evaluation bundle; no backend access."""

import hashlib
import json
from pathlib import Path

from env_rag_final.config import read_environment
from env_rag_final.evaluation import validate_phase4_anchor

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ANCHOR = HERE / "config-anchor.json"
SCORER = ROOT / "reports/pg-retrieval/phase-4-scoring-readiness-r4/assess_two_rounds.py"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_bundle():
    seal = json.loads((HERE / "preparation-manifest.json").read_text())
    for relative, expected in seal["files"].items():
        if digest(ROOT / relative) != expected:
            raise RuntimeError(f"prepared bundle drift: {relative}")
    anchor = json.loads(ANCHOR.read_text())
    for group in ("evaluation_code_anchors", "assessment_code_anchors"):
        for relative, expected in anchor[group].items():
            if digest(ROOT / relative) != expected:
                raise RuntimeError(f"approved lineage drift: {relative}")
    values = read_environment(ROOT / ".env")
    if digest(ROOT / ".env") != anchor["generation"]["env_sha256"]:
        raise RuntimeError("environment byte identity changed; a new review is required")
    expected = validate_phase4_anchor(anchor_path=ANCHOR, values=values)
    expected["env_sha"] = anchor["generation"]["env_sha256"]
    return anchor, values, expected


def round_path(number):
    if type(number) is not int or number not in (1, 2):
        raise ValueError("only the two prepared rounds are permitted")
    return ROOT / f"reports/pg-retrieval/phase-4-formal-fixed-round-{number}"


def check_terminal(terminal, caps):
    """Completion/identity/budgets, without treating business failures as PASS."""
    if terminal.get("failure") or not terminal.get("finished_at"):
        raise RuntimeError("round has no successful owning terminal; stop without retry")
    before, after = terminal["identity_before"], terminal["identity_after"]
    for key in (
        "counts",
        "source_fingerprint",
        "catalog_active",
        "search_active",
        "gold_sha",
        "env_sha",
    ):
        if before.get(key) != after.get(key):
            raise RuntimeError(f"round identity drift: {key}")
    if before.get("matches_frozen") is not True or after.get("matches_frozen") is not True:
        raise RuntimeError("round identities do not match the frozen source")
    rows = terminal["results"]
    if len(rows) != 123 or len({(x["query_id"], x["path"]) for x in rows}) != 123:
        raise RuntimeError("round must contain all 123 distinct legs")
    ledger = terminal["budget_snapshot_end"]
    for name in ("reserved_total", "issued_total"):
        for service, count in ledger[name].items():
            if count > caps.get(service, 0):
                raise RuntimeError(f"round service cap exceeded: {service}")
    for row in rows:
        if row.get("failure") or row.get("runtime") == "failure" or row.get("error"):
            raise RuntimeError("a hard leg failure requires review before the next round")
        if row.get("budget_failure") and row.get("query_id") != "neg-008":
            raise RuntimeError("unexpected budget failure; no automatic second round")
    by_leg = {}
    for event in ledger["events"]:
        if event["service"] == "pg" and event["kind"] == "issued":
            leg = event["where"].split(":", 1)[0]
            by_leg[leg] = by_leg.get(leg, 0) + event["amount"]
    if max(by_leg.values(), default=0) > 512:
        raise RuntimeError("PG peak exceeds the prepared review threshold; stop before round 2")


def verify_artifact_manifest(path, required=()):
    data = json.loads(Path(path).read_text())
    if not isinstance(data.get("files"), dict) or not data["files"]:
        raise RuntimeError("empty or malformed evidence manifest")
    for relative, expected in data["files"].items():
        if digest(ROOT / relative) != expected:
            raise RuntimeError(f"evidence manifest mismatch: {relative}")
    bound = {str((ROOT / relative).resolve()) for relative in data["files"]}
    if any(str(Path(p).resolve()) not in bound for p in required):
        raise RuntimeError("required evidence is not covered by the manifest")
    return data
