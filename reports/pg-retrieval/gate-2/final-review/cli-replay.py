"""Two formal SELECT-only CLI invocations; save complete stdout and parsed output."""

import json
import subprocess
from pathlib import Path

OUT = Path(__file__).parent
runs = []
for name, question, top_k in [
    ("category", "GB3838-2002 第3章水域功能和标准分类有哪些类别？", "20"),
    ("table_top1", "GB8978-1996 表1有哪些污染物", "1"),
]:
    command = [
        ".venv/bin/env-rag-final",
        "search-query",
        "--query",
        question,
        "--expand",
        "--top-k",
        top_k,
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    (OUT / f"cli-{name}.txt").write_text(result.stdout)
    runs.append(
        {
            "name": name,
            "command": command,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    )
    print(name, result.returncode)
gold = json.loads(Path("reports/pg-retrieval/gate-2/review-r5/gold-approved.json").read_text())
q = next(q for q in gold["questions"] if q["query_id"] == "prose-enum-001")
doc_id = q["target_docs"][0]["doc_id"]
command = [
    ".venv/bin/env-rag-final",
    "enum-prose",
    "--doc-id",
    doc_id,
    "--scope-id",
    doc_id + ":scope:3",
    "--clause-wanted",
    "3.1,3.2,3.3,3.4",
]
result = subprocess.run(command, capture_output=True, text=True, check=False)
(OUT / "cli-prose-direct.txt").write_text(result.stdout)
runs.append(
    {
        "name": "prose-direct",
        "command": command,
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
)
print("prose-direct", result.returncode)
(OUT / "cli-runs.json").write_text(json.dumps(runs, ensure_ascii=False, indent=2) + "\n")
