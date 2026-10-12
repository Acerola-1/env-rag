"""One fresh PG request for the unchanged archived shared failure; no retry."""

import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path("/Users/acerola/Dev/Python/RAG/env-rag-final")
OLD = ROOT.parent / "LightRAG"
OUT = Path(__file__).parent
source_paths = [
    "runs/eval/frozen/rag_eval_dataset_v2.json",
    "runs/ragas/answers_local_v2fresh_fresh.json",
    "runs/ragas/answers_mix_v2fresh_fresh.json",
    "runs/ragas/ragas_local_v2fresh_20261004_000707_fixed_patched.json",
    "runs/ragas/ragas_mix_v2fresh_20261004_005653_fixed_patched.json",
    "runs/ragas/RESULT_final_rerank_cold_20261004.md",
]
gold = json.loads((OLD / source_paths[0]).read_text())["test_cases"]
case = next(q for q in gold if q["id"] == "enum-15")
baseline = {
    "case": case,
    "historical_source_sha256": {
        str(OLD / p): hashlib.sha256((OLD / p).read_bytes()).hexdigest() for p in source_paths
    },
}
for mode in ["local", "mix"]:
    answers = json.loads((OLD / f"runs/ragas/answers_{mode}_v2fresh_fresh.json").read_text())
    row = next(r for r in answers if r["question"] == case["question"])
    baseline[mode] = {
        "answer": row["answer"],
        "latency_seconds": row.get("latency"),
        "contexts_contain_target_terms": {
            term: any(term.lower() in c.lower() for c in row["contexts"])
            for term in case["expected_items"]
        },
    }
(OUT / "historical-shared-failure.json").write_text(
    json.dumps(baseline, ensure_ascii=False, indent=2)
)
headers = {"Content-Type": "application/json", "Origin": "http://127.0.0.1:8091"}
cfg = json.load(urllib.request.urlopen("http://127.0.0.1:8091/api/config", timeout=15))
before = cfg["budget"]
(OUT / "usage-before.json").write_text(json.dumps(before, ensure_ascii=False, indent=2))
headers["X-RAG-Token"] = cfg["token"]
body = {
    "query": case["question"],
    "strategies": ["pg"],
    "generate": True,
    "top_k": 20,
    "submission_id": "historical-enum-15-pg-20261011-r1",
}
(OUT / "request.json").write_text(json.dumps(body, ensure_ascii=False, indent=2))
t0 = time.monotonic()
try:
    req = urllib.request.Request(
        "http://127.0.0.1:8091/api/query",
        data=json.dumps(body).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as response:
        result = json.load(response)
    with (OUT / "pg-runtime.json").open("x") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(
        json.dumps(
            {
                "results": [
                    {
                        "record_id": r.get("record_id"),
                        "status": r.get("status"),
                        "generation_status": r.get("generation_status"),
                        "answer": r.get("answer"),
                        "warnings": r.get("warnings"),
                        "enumeration_status": (r.get("enumeration") or {}).get("coverage_status"),
                    }
                    for r in result.get("results", [])
                ],
                "wall_seconds": round(time.monotonic() - t0, 3),
            },
            ensure_ascii=False,
        )
    )
except urllib.error.HTTPError as exc:
    raw = exc.read().decode(errors="replace")
    (OUT / "request-failure.json").write_text(
        json.dumps(
            {"status": exc.code, "message": raw, "wall_seconds": time.monotonic() - t0},
            ensure_ascii=False,
            indent=2,
        )
    )
    raise
finally:
    after = json.load(urllib.request.urlopen("http://127.0.0.1:8091/api/config", timeout=15))[
        "budget"
    ]
    (OUT / "usage-after.json").write_text(json.dumps(after, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {
                "issued_delta": {
                    k: after["issued"].get(k, 0) - before["issued"].get(k, 0)
                    for k in before["caps"]
                }
            },
            ensure_ascii=False,
        )
    )
