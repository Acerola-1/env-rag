import asyncio
import contextlib
import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import asyncpg

from env_rag_final import cli
from env_rag_final.audit import identity
from env_rag_final.config import read_environment
from env_rag_final.enumerate_.prose_enum import (
    UnitText,
    _quote_supports,
    bind_citations,
    extract_clauses_regex,
)

out = Path("reports/pg-retrieval/gate-1/review-3")
spec = importlib.util.spec_from_file_location(
    "previous_replay", "reports/pg-retrieval/gate-1/re-review/replay.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


async def fixed_live(*a, **k):
    return "f"


async def off():
    with patch("env_rag_final.catalog.builder._live_source_fingerprint", fixed_live):
        old = await m.offline()
    old["quote_overlap_false_support"] = {
        "claim": "门诊停车场",
        "quote": "门诊、病房",
        "accepted": _quote_supports("门诊停车场", "门诊、病房"),
    }
    text = "7.5 请求条款。"
    u = UnitText("u", text, ["c"], {"blockid": "u"}, 0, len(text), True, "parsed_block", 30)
    items = bind_citations(extract_clauses_regex(text, ["7.5"]), "default", "d", "s", [u])
    old["slice_offset_ignored"] = {"original_span_offset": 30, "items": items}
    return old


data = {"offline": asyncio.run(off())}
data["live"] = asyncio.run(m.live())
d = data["live"]
name = next(identity.PARSED_ROOT.glob("*18466*.parsed"))
raw = {
    b["blockid"]: b["content"]
    for b in [
        json.loads(line) for line in next(name.glob("*.blocks.jsonl")).read_text().splitlines()
    ]
    if b.get("type") == "content"
}
rereads = []
for item in d["prose3_manually_bound"]["items"]:
    c = item["citation"]
    body = raw[c["unit_id"]]
    part = body[c["unit_rel_start"] : c["unit_rel_end"]]
    rereads.append(
        {
            "clause": item["clause"],
            "citation": c,
            "slice_text": part,
            "quote_in_bound_slice": c["quote"] in part,
            "start_nonnegative": c["unit_rel_start"] >= 0,
        }
    )
data["prose_citation_rereads"] = rereads
(out / "replay.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))
for module in cli.DEPENDENCIES.values():
    importlib.import_module(module)
values = read_environment(Path(".env"))
real_connect = asyncpg.connect


async def readonly_connect(*a, **kw):
    ss = dict(kw.get("server_settings") or {})
    ss.update(default_transaction_read_only="on", statement_timeout="30000")
    kw["server_settings"] = ss
    return await real_connect(*a, **kw)


class Resp:
    def raise_for_status(self):
        pass

    def json(self):
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            [{"clause": "3.2", "text": "门诊", "citation": {"quote": "门诊"}}],
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }


class Http:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def post(self, *a, **kw):
        return Resp()


args = [
    "env-rag-final",
    "enum-prose",
    "--doc-id",
    m.GB18466,
    "--scope-id",
    d["scope3"]["scope_id"],
    "--with-model",
]
stdout, stderr = io.StringIO(), io.StringIO()
code = 0
err = ""
with (
    patch("asyncpg.connect", readonly_connect),
    patch("httpx.AsyncClient", lambda **k: Http()),
    patch.object(sys, "argv", args),
    contextlib.redirect_stdout(stdout),
    contextlib.redirect_stderr(stderr),
):
    try:
        cli.main()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
        err = "" if isinstance(e.code, int) else str(e.code)
data["model_cli_http_success_fixture"] = {
    "command": args,
    "exit_code": code,
    "error": err,
    "stderr": stderr.getvalue(),
    "stdout_tail": stdout.getvalue()[-1200:],
    "http_response": Resp().json(),
    "real_model_calls": 0,
    "postgres_mode": "forced_readonly",
}
data["code_sha256"] = {
    str(p): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in [
        *sorted(Path("src/env_rag_final/enumerate_").glob("*.py")),
        Path("src/env_rag_final/cli.py"),
        Path("src/env_rag_final/catalog/builder.py"),
    ]
}
(out / "replay.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))
print(
    json.dumps(
        {
            "saved": str(out / "replay.json"),
            "public_unchanged": d["public_unchanged"],
            "table_row_matches": sum(r["matches"] for r in d["row_citation_reread"]),
            "prose_quote_matches": sum(r["quote_in_bound_slice"] for r in rereads),
            "model_cli_success_fixture_exit": code,
        },
        ensure_ascii=False,
    )
)
