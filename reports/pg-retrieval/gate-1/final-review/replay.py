"""Final Gate 1 acceptance: real SELECT-only reads and an isolated HTTP reply."""

import asyncio
import contextlib
import hashlib
import importlib
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import asyncpg

from env_rag_final import cli
from env_rag_final.audit import identity
from env_rag_final.config import read_environment
from env_rag_final.enumerate_.prose_enum import (
    UnitText,
    bind_citations,
    verify_citations,
)

OUT = Path(__file__).parent
spec = importlib.util.spec_from_file_location(
    "prior_replay", "reports/pg-retrieval/gate-1/re-review/replay.py"
)
prior = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prior)
data = {"live": asyncio.run(prior.live())}
d = data["live"]
pdir = next(identity.PARSED_ROOT.glob("*18466*.parsed"))
blocks = {
    b["blockid"]: b["content"]
    for b in [
        json.loads(line) for line in next(pdir.glob("*.blocks.jsonl")).read_text().splitlines()
    ]
    if b.get("type") == "content"
}
data["prose_reread"] = []
for it in d["prose3_manually_bound"]["items"]:
    c = it["citation"]
    part = blocks[c["unit_id"]][c["unit_rel_start"] : c["unit_rel_end"]]
    data["prose_reread"].append(
        {"clause": it["clause"], "citation": c, "quote_matches": c["quote"] in part}
    )
v = read_environment(Path(".env"))
dsn = dict(
    host=v["POSTGRES_HOST"],
    port=int(v["POSTGRES_PORT"]),
    user=v["POSTGRES_USER"],
    password=v["POSTGRES_PASSWORD"],
    database=v["POSTGRES_DATABASE"],
    statement_cache_size=0,
    server_settings={"default_transaction_read_only": "on", "statement_timeout": "30000"},
)


async def scope_info():
    conn = await asyncpg.connect(**dsn)
    try:
        return [
            dict(r)
            for r in await conn.fetch(
                "SELECT doc_id,scope_id,number FROM env_rag.scopes WHERE workspace='default' AND snapshot_id=$1 AND ((doc_id=$2 AND number='4.1') OR (doc_id=$3 AND number='4'))",
                d["start"]["active_snapshot_id"],
                prior.GB18466,
                "doc-257d8cf3fdf90e76c31908c4f92fc1a1",
            )
        ]
    finally:
        await conn.close()


scopes = asyncio.run(scope_info())
data["extra_cli"] = []
for r in scopes:
    targets = (
        ["4.1.1,4.1.2,4.1.3,4.1.4,4.1.5", "4.1.1,4.1.2,4.1.3,4.1.4,4.1.5,4.1.6"]
        if r["number"] == "4.1"
        else ["4.1,4.2"]
    )
    for wanted in targets:
        path = OUT / f"cli-{len(data['extra_cli'])}.json"
        cmd = [
            ".venv/bin/env-rag-final",
            "enum-prose",
            "--doc-id",
            r["doc_id"],
            "--scope-id",
            r["scope_id"],
            "--clause-wanted",
            wanted,
            "--out",
            str(path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        data["extra_cli"].append(
            {
                "command": cmd,
                "exit_code": result.returncode,
                "stderr": result.stderr,
                "result": json.loads(path.read_text()) if path.exists() else None,
            }
        )
for module in cli.DEPENDENCIES.values():
    importlib.import_module(module)
real_connect = asyncpg.connect


async def readonly_connect(*a, **kw):
    ss = dict(kw.get("server_settings") or {})
    ss.update(default_transaction_read_only="on", statement_timeout="30000")
    kw["server_settings"] = ss
    return await real_connect(*a, **kw)


class Reply:
    def raise_for_status(self):
        pass

    def json(self):
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            [{"clause": "3.2", "text": "污水", "citation": {"quote": "污水"}}],
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }


class Client:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def post(self, *a, **kw):
        return Reply()


path = OUT / "model-ambiguous.json"
args = [
    "env-rag-final",
    "enum-prose",
    "--doc-id",
    prior.GB18466,
    "--scope-id",
    d["scope3"]["scope_id"],
    "--with-model",
    "--predicate",
    "列出该章出现的词语污水，并提供精确原文位置",
    "--out",
    str(path),
]
std = io.StringIO()
exit_code = 0
error = ""
with (
    patch("asyncpg.connect", readonly_connect),
    patch("httpx.AsyncClient", lambda **k: Client()),
    patch.object(sys, "argv", args),
    contextlib.redirect_stdout(std),
):
    try:
        cli.main()
    except SystemExit as exc:
        exit_code = 1
        error = str(exc)
data["ambiguous_model_cli"] = {
    "command": args,
    "exit_code": exit_code,
    "error": error,
    "result": json.loads(path.read_text()) if path.exists() else None,
    "real_model_calls": 0,
    "http_response": Reply().json(),
}
units = [
    UnitText("a", "污水", ["c"], {}, 0, 2, False, "parsed_block"),
    UnitText("b", "污水", ["c"], {}, 4, 6, False, "parsed_block"),
]
item = {"text": "污水", "citation": {"quote": "污水"}, "citation_verified": True}
bound = bind_citations([item], "default", "d", "s", units)
data["ambiguous_bind_then_verify"] = {
    "after_bind": json.loads(json.dumps(bound)),
    "after_verify": verify_citations(bound, "污水\n\n污水"),
}
data["code_sha256"] = {
    str(p): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in [
        *sorted(Path("src/env_rag_final/enumerate_").glob("*.py")),
        Path("src/env_rag_final/cli.py"),
    ]
}
(OUT / "replay.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))
print(
    json.dumps(
        {
            "saved": str(OUT / "replay.json"),
            "table_quotes_ok": sum(r["matches"] for r in d["row_citation_reread"]),
            "prose_quotes_ok": sum(r["quote_matches"] for r in data["prose_reread"]),
            "extra_cli_exit_codes": [r["exit_code"] for r in data["extra_cli"]],
            "ambiguous_model_exit": exit_code,
            "ambiguous_model_coverage": data["ambiguous_model_cli"]["result"].get("coverage_status")
            if data["ambiguous_model_cli"]["result"]
            else None,
        },
        ensure_ascii=False,
    )
)
