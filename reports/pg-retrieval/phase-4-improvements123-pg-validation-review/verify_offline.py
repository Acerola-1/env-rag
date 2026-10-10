"""Offline acceptance of the five real PG receipts; no backend connections."""

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from env_rag_final import answer as an

ROOT = Path(__file__).resolve().parents[3]
RUN = ROOT / "reports/pg-retrieval/phase-4-improvements123-pg-validation-r1"
OUT = Path(__file__).resolve().parent
GOLD = ROOT / "reports/pg-retrieval/gate-2/review-r5/gold-approved.json"
PARSED = ROOT.parent / "LightRAG/inputs/__parsed__"


def norm(text):
    return " ".join(text.split())


def main():
    def sha(p):
        return hashlib.sha256(p.read_bytes()).hexdigest()

    manifest = json.loads((RUN / "pg-validation-manifest.json").read_text())["files"]
    assert all(sha(ROOT / p) == expected for p, expected in manifest.items())
    guard = json.loads((RUN / "eval-runtime-latest.json").read_text())
    ident = guard["identity_before"]
    assert ident == guard["identity_after"] and ident["matches_frozen"]
    assert ident["problems"] == [] and guard.get("finished_at") and not guard.get("failure")
    anchor = json.loads(
        (
            ROOT / "reports/pg-retrieval/phase-4/phase-4-config-anchor-improvements123-pg-r1.json"
        ).read_text()
    )["frozen_identity"]
    assert ident["source_fingerprint"] == anchor["source_fingerprint"]
    assert "/".join(ident["catalog_active"].values()) == anchor["catalog_run_snapshot"]
    assert ident["search_active"] == anchor["search_active"]
    assert ident["gold_sha"] == sha(GOLD) == anchor["gold_sha256"]
    assert ident["env_sha"] == sha(ROOT / ".env")
    assert list(ident["counts"].values()) == anchor["eight_table_counts"]
    gold = {q["query_id"]: q for q in json.loads(GOLD.read_text())["questions"]}
    ledger = guard["budget_snapshot_end"]
    reserved = Counter()
    issued = Counter()
    for event in ledger["events"]:
        assert event["service"] == "pg" and event["kind"] in ("reserved", "issued")
        assert type(event["amount"]) is int and event["amount"] > 0
        (reserved if event["kind"] == "reserved" else issued)[event["where"]] += event["amount"]
    assert reserved == issued and sum(issued.values()) == 556
    assert ledger["issued_total"] == ledger["reserved_total"] == {"pg": 556}
    assert ledger["refusal_count"] == 0 and max(issued.values()) == 128
    rows = []
    for leg in guard["results"]:
        qid = leg["query_id"]
        assert leg["path"] == "pg" and leg["execution_attribution"] == "real_entry"
        assert not leg.get("budget_failure") and not leg.get("failure")
        terminal = RUN / f"legs/r1/pg/{qid}/answer/answer-runtime-latest.json"
        report = json.loads(terminal.read_text())
        assert report["identity_before"] == report["identity_after"] == ident
        assert report["model_calls_used"] == 0 and not report.get("failure")
        result = report["results"][0]
        assert result["coverage_status"] == "complete" and result["status"] == "ok"
        items = result["answer"]["items"]
        assert all(it["citation_verified"] and it["citation_reverified"] for it in items)
        record = {"query_id": qid, "count": len(items), "items": []}
        for item in items:
            cit = item["citation"]
            assert cit["workspace"] == "default" and cit["doc_id"] == item["doc_id"]
            assert cit["snapshot_id"] == ident["catalog_active"]["snapshot_id"]
        if qid.startswith("file"):
            expected = set(gold[qid]["gold"]["expected_doc_ids"])
            assert {it["doc_id"] for it in items} == expected
            assert len(items) == len(expected)
            for item in items:
                assert "doc-" + hashlib.md5(item["doc_name"].encode()).hexdigest() == item["doc_id"]
            if qid == "file-enum-005":
                assert sum(it.get("self_code") is None for it in items) == 2
                assert sum(bool(it.get("attribution")) for it in items) == 2
            else:
                years = [re.findall(r"20\d{2}", it["doc_name"])[-1] for it in items]
                assert sorted(years) == ["2021", "2022", "2023", "2024", "2025"]
            record["expected_doc_ids"] = sorted(expected)
            record["missing"] = record["extra"] = []
        else:
            targets = {it["clause"]: it["text"] for it in gold[qid]["gold"]["expected_items"]}
            assert {it["clause"] for it in items} == set(targets) and len(items) == len(targets)
            expected_docs = {it["doc_id"] for it in gold[qid]["gold"]["target_evidence"]}
            for item in items:
                cit = item["citation"]
                assert item["doc_id"] in expected_docs
                raw = an._unit_text_from_blocks(
                    PARSED / cit["locator"]["parsed_dir"], cit["unit_id"]
                )
                lo, hi = cit["unit_rel_start"], cit["unit_rel_end"]
                assert type(lo) is int and type(hi) is int and 0 <= lo < hi <= len(raw)
                text = item["text"]
                assert raw[lo:hi].strip() == text and cit["quote"] in raw[lo:hi]
                assert "<table" not in text.lower()
                assert norm(targets[item["clause"]]) in norm(text)
                record["items"].append(
                    {
                        "clause": item["clause"],
                        "text_len": len(text),
                        "raw_declared_span_full_text_equal_after_outer_trim": True,
                        "whole_gold_required_body_present": True,
                        "published_text_exact_gold_body": norm(text)
                        == norm(targets[item["clause"]]),
                        "source_unit_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                        "unit_id": cit["unit_id"],
                    }
                )
        record["pg_issued"] = issued[f"r1/pg/{qid}:pg"]
        rows.append(record)
    assert len(rows) == 5
    result = {
        "verdict": "accepted bounded PG live batch",
        "artifact_hashes_checked": len(manifest),
        "identity_matched": True,
        "pg_issued": 556,
        "max_leg_pg": 128,
        "non_pg_issued": 0,
        "reviewer_backend_requests": 0,
        "rows": rows,
        "gold_wording_note": "Required bodies all present; full published text need not equal gold body: clause prefixes/periods and one source GB footer are retained. Do not label them all exact-gold-body strings.",
    }
    (OUT / "offline-verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print("accepted five legs / raw span rereads 7 / pg 556 / peak 128 / reviewer real requests 0")


if __name__ == "__main__":
    main()
