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
(OUT / "cli-runs.json").write_text(json.dumps(runs, ensure_ascii=False, indent=2) + "\n")
