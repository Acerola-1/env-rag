"""Offline acceptance of four fresh local legs; no service connections."""

import hashlib
import json
from collections import Counter
from pathlib import Path

from env_rag_final import answer as an

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
RUN = ROOT / "reports/pg-retrieval/phase-4-improvements123-local-validation-r1"
PARSED = ROOT.parent / "LightRAG/inputs/__parsed__"
GOLD = ROOT / "reports/pg-retrieval/gate-2/review-r5/gold-approved.json"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    files = json.loads((RUN / "local-validation-manifest.json").read_text())["files"]
    assert all(sha(ROOT / path) == expected for path, expected in files.items())
    runtime = json.loads((RUN / "eval-runtime-latest.json").read_text())
    identity = runtime["identity_before"]
    assert identity == runtime["identity_after"] and identity["matches_frozen"]
    assert identity["problems"] == [] and runtime.get("finished_at")
    assert not runtime.get("failure") and identity["env_sha"] == sha(ROOT / ".env")
    anchor = json.loads(
        (
            ROOT
            / "reports/pg-retrieval/phase-4/phase-4-config-anchor-improvements123-local-r1.json"
        ).read_text()
    )["frozen_identity"]
    assert identity["source_fingerprint"] == anchor["source_fingerprint"]
    assert (
        identity["catalog_active"]["run_id"] + "/" + identity["catalog_active"]["snapshot_id"]
        == anchor["catalog_run_snapshot"]
    )
    assert identity["search_active"] == anchor["search_active"]
    assert identity["gold_sha"] == sha(GOLD) == anchor["gold_sha256"]
    assert list(identity["counts"].values()) == anchor["eight_table_counts"]
    gold = {q["query_id"]: q for q in json.loads(GOLD.read_text())["questions"]}
    expected_services = {"llm": 4, "embedding": 11, "qdrant": 11, "neo4j": 20, "pg": 439}
    ledger = runtime["budget_snapshot_end"]
    assert ledger["reserved_total"] == ledger["issued_total"] == expected_services
    assert ledger["refusal_count"] == 0
    reserved, issued = Counter(), Counter()
    for event in ledger["events"]:
        assert event["kind"] in ("reserved", "issued")
        assert event["service"] in expected_services and type(event["amount"]) is int
        (reserved if event["kind"] == "reserved" else issued)[event["service"], event["where"]] += (
            event["amount"]
        )
    assert reserved == issued
    by_service = Counter()
    for (service, _where), count in issued.items():
        by_service[service] += count
    assert dict(by_service) == expected_services
    receipts_count = Counter()
    rows = []
    for leg in runtime["results"]:
        qid = leg["query_id"]
        assert leg["path"] == "local" and leg["execution_attribution"] == "real_entry"
        assert not leg.get("failure") and not leg.get("budget_failure")
        receipts = leg["receipts"]
        assert not receipts["degraded"] and not receipts["refused_candidates"]
        for call in receipts["call_records"]:
            assert call["status"] == "success"
            receipts_count[call["service"]] += 1
            if call["service"] == "llm":
                assert call["operation"] == "keyword_extraction"
        vectors = receipts["sorting_sources"]["chunk_pick_vectors"]
        assert (
            vectors["vector_backed"]
            and receipts["sorting_sources"]["chunk_pick"] == "vector-similarity"
        )
        fused = json.loads((RUN / f"inputs/local/{qid}-fusion.json").read_text())["results"][0]
        assert fused["pg"]["search_id"] == "" and not fused["targets_confirmed"]
        assert fused["targets_resolved"] == fused["typed_targets"] == []
        assert fused["path_provenance"]["discovery_only"]
        discovered = {c["doc_id"] for c in fused["usable"]}
        for candidate in fused["usable"]:
            assert candidate["workspace"] == "default" and candidate["verified"]
            assert len(candidate["content"]) == candidate["content_len"]
            assert (
                hashlib.sha256(candidate["content"].encode()).hexdigest()
                == candidate["content_sha256"]
            )
        answer = json.loads(
            (RUN / f"legs/r1/local/{qid}/answer/answer-runtime-latest.json").read_text()
        )
        assert answer["identity_before"] == answer["identity_after"] == identity
        assert answer["model_calls_used"] == 0 and not answer.get("failure")
        result = answer["results"][0]
        assert result["coverage_status"] == "complete" and result["status"] == "ok"
        items = result["answer"]["items"]
        published_docs = {i["doc_id"] for i in items}
        for item in items:
            cit = item["citation"]
            assert item["citation_verified"] and item["citation_reverified"]
            assert cit["workspace"] == "default" and cit["doc_id"] == item["doc_id"]
            assert cit["snapshot_id"] == identity["catalog_active"]["snapshot_id"]
        record = {
            "query_id": qid,
            "is_counter": leg["is_counter"],
            "items": len(items),
            "discovered_docs": sorted(discovered),
        }
        if qid != "file-enum-005":
            confirmation = result["scope_selection"]["target_confirmation"]
            excluded = confirmation["rejected"] + confirmation["unresolved"]
            excluded_ids = {r["doc_id"] for r in excluded}
            assert excluded_ids and excluded_ids <= discovered
            assert excluded_ids.isdisjoint(published_docs)
            assert all(r["doc_id"] in " ".join(result["flags"]) for r in excluded)
            assert published_docs == set(confirmation["allowed"])
            record["excluded_discovered_documents"] = excluded
        if qid == "file-enum-005":
            assert published_docs == set(gold[qid]["gold"]["expected_doc_ids"]) and len(items) == 3
            assert sum(i["self_code"] is None for i in items) == 2
            record["catalog_citations_bound_and_reverified"] = True
        elif qid == "neg-004":
            expected = gold["table-enum-001"]["gold"]["expected_items"]
            assert len(items) == 13 and [i["seq"] for i in items] == [str(i) for i in range(1, 14)]
            assert [i["cells"] for i in items] == [i["cells"] for i in expected]
            fragments = set()
            for item in items:
                cit = item["citation"]
                name = next(
                    c["file_path"] for c in fused["usable"] if c["doc_id"] == item["doc_id"]
                )
                parsed = an._doc_parsed_dir(name)
                table = an._tables_sidecar(parsed)[cit["table_id"]]
                grid = an.read_html_table(table["content"])
                assert grid[cit["row_in_fragment"]] == item["cells"]
                fragments.add(cit["table_id"])
            assert len(fragments) == 2
            record["raw_grid_rows_equal"] = 13
            record["physical_fragments"] = sorted(fragments)
        else:
            expected = gold[qid]["gold"]["expected_items"]
            clauses = [i["clause"] for i in items]
            assert len(items) == len(expected)
            assert published_docs == {
                target["doc_id"] for target in gold[qid]["gold"]["target_evidence"]
            }
            checks = []
            for item in items:
                cit = item["citation"]
                name = next(
                    c["file_path"] for c in fused["usable"] if c["doc_id"] == item["doc_id"]
                )
                assert an._doc_parsed_dir(name).name == cit["locator"]["parsed_dir"]
                raw = an._unit_text_from_blocks(
                    PARSED / cit["locator"]["parsed_dir"], cit["unit_id"]
                )
                lo, hi = cit["unit_rel_start"], cit["unit_rel_end"]
                assert type(lo) is int and type(hi) is int and 0 <= lo < hi <= len(raw)
                assert raw[lo:hi].strip() == item["text"] and cit["quote"] in raw[lo:hi]
                checks.append(
                    {
                        "clause": item["clause"],
                        "text_len": len(item["text"]),
                        "full_declared_span_equal": True,
                    }
                )
            if qid == "prose-enum-001":
                assert clauses == ["3.1", "3.2", "3.3", "3.4"]
                for item, exp in zip(items, expected, strict=True):
                    assert exp in item["text"]
            else:
                assert clauses == ["4.2"] and items[0]["text"] == expected[0]["text"]
            record["prose_source_checks"] = checks
        rows.append(record)
    for service in ("llm", "embedding", "qdrant", "neo4j"):
        assert receipts_count[service] == expected_services[service]
    assert len(rows) == 4 and sum(r["is_counter"] for r in rows) == 1
    (OUT / "offline-verification.json").write_text(
        json.dumps(
            {
                "verdict": "accepted four-local batch",
                "artifact_hashes": len(files),
                "identity_equal": True,
                "ledger_totals": expected_services,
                "raw_source_checks": "5 full prose spans + 13 raw grid rows",
                "rows": rows,
                "reviewer_real_requests": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(
        "accepted four legs; 5 prose spans / 13 grid rows; keyword4 / embedding11; real observed noise excluded"
    )


if __name__ == "__main__":
    main()
