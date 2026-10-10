"""Bounded read-only checks of the NEW arbitrary-question owning entry.

No keyword/model/embedding/rerank requests. Fixed gold is only an independent
post-answer oracle; no question IDs or gold content reach ask_question.
"""

import argparse
import asyncio
import hashlib
import json
import re
from pathlib import Path

import asyncpg
from dotenv import dotenv_values

from env_rag_final.ask import Question, ask_question, write_result
from env_rag_final.audit.identity import PARSED_ROOT
from env_rag_final.enumerate_.tables import read_html_table

ROOT = Path(__file__).resolve().parents[3]
GOLD = ROOT / "reports/pg-retrieval/gate-2/review-r5/gold-approved.json"
INVENTORY = ROOT / "reports/pg-retrieval/phase-0/inventory.jsonl"
TABLES = (
    "lightrag_doc_full",
    "lightrag_doc_chunks",
    "lightrag_doc_status",
    "lightrag_llm_cache",
    "lightrag_full_entities",
    "lightrag_full_relations",
    "lightrag_entity_chunks",
    "lightrag_relation_chunks",
)


def norm(text):
    return re.sub(r"\s+", "", text)


def read_raw(name):
    directory = PARSED_ROOT / (name + ".parsed")
    blocks = [
        json.loads(x) for x in next(directory.glob("*.blocks.jsonl")).read_text().splitlines()
    ]
    return directory, {b["blockid"]: b["content"] for b in blocks if b.get("blockid")}


def cases_and_expected():
    gold = json.loads(GOLD.read_text())
    by_id = {q["query_id"]: q for q in gold["questions"]}
    docs = {
        r["doc_id"]: r["doc_name"]
        for line in INVENTORY.read_text().splitlines()
        if (r := json.loads(line)).get("kind") == "db_doc"
    }
    base = [
        (
            "versions",
            "file-enum-001",
            Question("列出库内 GB3095 标准的全部文档及版本", kind="files"),
        ),
        ("amendments", "file-enum-005", Question("库内有哪些 GB18466-2005 的文档（含修改单）？")),
        (
            "terms",
            "prose-enum-001",
            Question(
                "列出第3章的全部术语和定义",
                kind="prose",
                document=docs["doc-68a03b50e1ba1ffc6a0116529f694fe1"],
            ),
        ),
        ("clauses", "prose-enum-003", Question("列出 GB8978-1996 第4.3节的全部要求")),
        (
            "continued_table",
            "table-enum-001",
            Question("列出 GB8978-1996 表1的全部项目及限值", top_k=1),
        ),
        ("edition", "prose-enum-006", Question("列出4.2的全部规定", code="GB3095", version="2012")),
    ]
    expected = {}
    # Build and validate truth BEFORE answer generation.
    for label, qid, _ in base:
        q = by_id[qid]
        g = q["gold"]
        d = [
            x["doc_id"] if isinstance(x, dict) else x
            for x in (g.get("expected_doc_ids") or q["target_docs"])
        ]
        if q["category"] == "file_enum":
            for doc in d:
                read_raw(docs[doc])
            keys = d
        elif q["category"] == "table_enum":
            directory, _ = read_raw(docs[d[0]])
            tables = json.loads(next(directory.glob("*.tables.json")).read_text())["tables"]
            raw_rows = []
            for evidence in g["target_evidence"]:
                grid = read_html_table(tables[evidence["unit_id"]]["content"])
                raw_rows += [r for r in grid if r and re.fullmatch(r"\d+", r[0].strip())]
            wanted = [it["cells"] for it in g["expected_items"]]
            assert [[norm(c) for c in r] for r in raw_rows] == [
                [norm(c) for c in r] for r in wanted
            ]
            keys = [json.dumps([norm(c) for c in r], ensure_ascii=False) for r in wanted]
        else:
            _, blocks = read_raw(docs[d[0]])
            source = "\n".join(blocks[e["unit_id"]] for e in g["target_evidence"])
            wanted = g["expected_items"]
            for it in wanted:
                if isinstance(it, dict):
                    assert norm(it["text"]) in norm(source)
                else:
                    assert norm(it) in norm(source)
            keys = [it["clause"] if isinstance(it, dict) else it.split()[0] for it in wanted]
        expected[label] = {
            "qid_oracle_only": qid,
            "doc_ids": d,
            "keys": keys,
            "items": g.get("expected_items"),
            "status": "complete",
        }
    base += [
        ("ambiguous_table", None, Question("列出 GB8978-1996 表2的全部项目")),
        ("judgement", None, Question("GB3838-2002 的表1与 GB3095-2012 的表1是同一张表吗？")),
    ]
    expected["ambiguous_table"] = {
        "status": "ambiguous",
        "basis": "unconfirmed base-caption group",
        "doc_ids": ["doc-b45c510232ed4d2452b0f5b2a13434e4"],
    }
    expected["judgement"] = {
        "status": "ambiguous",
        "basis": "not an enumeration intent",
        "keys": [],
    }
    return base, expected, docs


def assess(label, result, expected, docs):
    items = result["answer"]["items"]
    category = result["kind"]
    if category == "files":
        keys = [it["doc_id"] for it in items]
    elif category == "table":
        keys = [json.dumps([norm(c) for c in it["cells"]], ensure_ascii=False) for it in items]
    else:
        keys = [it["clause"] for it in items]
    wanted = expected.get("keys")
    missing = sorted(set(wanted or []) - set(keys)) if wanted is not None else None
    extra = sorted(set(keys) - set(wanted or [])) if wanted is not None else None
    problems = list((result.get("reverification") or {}).get("problems") or [])
    if expected.get("doc_ids"):
        if any(it["doc_id"] not in expected["doc_ids"] for it in items):
            problems.append("foreign document")
    if len(keys) != len(set(keys)):
        problems.append("duplicate item")
    for item in items:
        cit = item.get("citation") or {}
        if not (item.get("citation_verified") and item.get("citation_reverified")):
            problems.append("unverified citation")
        if cit.get("workspace") != "default" or cit.get("doc_id") != item["doc_id"]:
            problems.append("citation identity mismatch")
        if cit.get("snapshot_id") != result["identity_before"]["catalog_snapshot_id"]:
            problems.append("citation snapshot mismatch")
        if category == "table":
            directory, _ = read_raw(docs[item["doc_id"]])
            tables = json.loads(next(directory.glob("*.tables.json")).read_text())["tables"]
            row = read_html_table(tables[cit["table_id"]]["content"])[cit["row_in_fragment"]]
            if [norm(x) for x in row] != [norm(x) for x in item["cells"]]:
                problems.append("raw grid mismatch")
    if category == "prose" and expected.get("items"):
        actual = {it["clause"]: it["text"] for it in items}
        for item in expected["items"]:
            if isinstance(item, dict):
                text = actual.get(item["clause"], "")
                stripped = re.sub(r"^\s*#{0,4}\s*" + re.escape(item["clause"]) + r"\s*", "", text)
                if norm(stripped) != norm(item["text"]):
                    problems.append("clause body differs from independent gold")
            else:
                clause, name = item.split(" ", 1)
                if norm(item) not in norm(actual.get(clause, "")):
                    problems.append("term identity missing")
    passed = result["coverage_status"] == expected["status"] and not problems
    if wanted is not None:
        passed = passed and not missing and not extra
    return {
        "case": label,
        "question": result["query"],
        "expected": expected,
        "actual_status": result["coverage_status"],
        "actual_keys": keys,
        "missing": missing,
        "extra": extra,
        "citation_problems": problems,
        "passed": passed,
        "elapsed_ms": result.get("elapsed_ms"),
        "evidence_mode": (
            "production_readonly"
            if result["evidence_mode"] == "caller_supplied_connection"
            else result["evidence_mode"]
        ),
        "original_local_baseline": "unverified",
    }


async def main(outdir):
    cases, expected, docs = cases_and_expected()
    outdir.mkdir(parents=True, exist_ok=False)
    write_result(outdir / "expected-before-run.json", expected)
    values = dict(dotenv_values(ROOT / ".env"))
    conn = await asyncpg.connect(
        host=values["POSTGRES_HOST"],
        port=int(values["POSTGRES_PORT"]),
        user=values["POSTGRES_USER"],
        password=values["POSTGRES_PASSWORD"],
        database=values["POSTGRES_DATABASE"],
        statement_cache_size=0,
        timeout=15,
        server_settings={"default_transaction_read_only": "on", "statement_timeout": "30000"},
    )
    results = []
    try:
        before = {t: await conn.fetchval(f"SELECT count(*) FROM public.{t}") for t in TABLES}
        for label, _, question in cases:
            result = await ask_question(question, values, conn=conn)
            write_result(outdir / (label + ".json"), result)
            row = assess(label, result, expected[label], docs)
            results.append(row)
            print(
                label,
                result["coverage_status"],
                len(result["answer"]["items"]),
                row["passed"],
                flush=True,
            )
        after = {t: await conn.fetchval(f"SELECT count(*) FROM public.{t}") for t in TABLES}
    finally:
        await conn.close()
    write_result(
        outdir / "acceptance.json",
        {
            "cases": results,
            "public_counts_before": before,
            "public_counts_after": after,
            "counts_unchanged": before == after,
            "gold_sha": hashlib.sha256(GOLD.read_bytes()).hexdigest(),
            "all_passed": before == after and all(r["passed"] for r in results),
            "code_sha256": {
                name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                for name in (
                    "src/env_rag_final/ask.py",
                    "src/env_rag_final/cli.py",
                    "src/env_rag_final/lightrag_enum_bridge.py",
                )
            },
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.out_dir))
