#!/usr/bin/env python
"""Lifecycle checks: restart, scoped withdrawal, and the effect on the other library.

Uses the ``coastal`` trial library (this round's own space) so the frozen
air/water corpora are never touched.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
LOCAL = ROOT / ".local/workspace-access"

GATEWAY = "http://127.0.0.1:8099"
TRIAL = "coastal"
TRIAL_DOC = "water-01_国家法律法规数据库_中华人民共和国长江保护法_2021.pdf"
KEEP = ("air", "water")


def sh(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, **kw)


def psql(sql: str) -> str:
    return sh(
        ["container", "exec", "lightrag-postgres", "psql", "-U", "rag", "-d", "rag", "-tAc", sql]
    ).stdout.strip()


def counts() -> dict:
    def rows(inner: str, column: str) -> list[str]:
        out = psql(f"select workspace || '=' || {column} from {inner} order by workspace;")
        return [line for line in out.splitlines() if line.strip()]

    return {
        "chunks": rows(
            "(select workspace, count(*)::text as n from public.lightrag_doc_chunks"
            " group by workspace) t",
            "n",
        ),
        "docs": rows(
            "(select workspace, count(*)::text as n from public.lightrag_doc_full"
            " group by workspace) t",
            "n",
        ),
        "active_search": rows(
            "(select workspace, search_id from env_rag.search_builds where status='active') t",
            "search_id",
        ),
    }


def keep_only(detail: dict, keep=KEEP) -> dict:
    return {k: [x for x in v if x.split("=")[0] in keep] for k, v in detail.items()}


def query(user: str, workspace, question: str, route: str = "pg") -> dict:
    creds = json.loads((LOCAL / "credentials.json").read_text(encoding="utf-8"))
    client = httpx.Client(timeout=600)
    login = client.post(
        f"{GATEWAY}/api/login", json={"user_id": user, "password": creds[user]["password"]}
    ).json()
    res = client.post(
        f"{GATEWAY}/api/query",
        json={"workspace": workspace, "question": question, "route": route, "no_record": True},
        headers={"X-RAG-Token": login["csrf"]},
    )
    if res.status_code != 200:
        return {"http": res.status_code}
    result = res.json()["result"]
    return {
        "http": 200,
        "status": result["status"],
        "evidence": len(result["evidence"]),
        "workspaces": result["workspaces"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out", default=str(ROOT / "reports/workspace-access/wa-20261012-r1/lifecycle.json")
    )
    args = parser.parse_args()
    report: dict = {"steps": []}

    def step(name: str, detail) -> None:
        report["steps"].append({"step": name, "detail": detail, "at": round(time.time(), 3)})

    before = counts()
    report["before"] = before
    report["trial_query_before"] = query("coastal-reader", TRIAL, "长江保护法 水生态保护")
    step("trial.query.before", report["trial_query_before"])

    # ---- restart instances + gateway ------------------------------------
    sh(
        ["bash", "scripts/wa_instances.sh", "stop"],
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "WA_WORKSPACES": "air water"},
    )
    sh(
        ["bash", "scripts/wa_instances.sh", "start"],
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "WA_WORKSPACES": "air water"},
    )
    subprocess.run(["pkill", "-f", "env_rag_final.access --port 8099"])
    time.sleep(1)
    subprocess.Popen(
        [str(ROOT / ".venv/bin/python"), "-m", "env_rag_final.access", "--port", "8099"],
        cwd=ROOT,
        stdout=open("/tmp/wa-gateway.log", "a"),
        stderr=subprocess.STDOUT,
    )
    for _ in range(60):
        try:
            if httpx.get(f"{GATEWAY}/health", timeout=2).status_code == 200:
                break
        except Exception:
            time.sleep(1)
    report["restart_query_after"] = query(
        "dual-reader", ["air", "water"], "空气质量标准与地表水环境质量标准"
    )
    step("restart.query", report["restart_query_after"])
    after_restart = counts()
    report["after_restart"] = after_restart
    report["restart_preserved_identity"] = keep_only(before) == keep_only(after_restart)
    step("restart.identity_preserved", report["restart_preserved_identity"])

    # ---- scoped withdrawal from the trial library only -------------------
    psql(
        f"delete from public.lightrag_doc_chunks where workspace='{TRIAL}';"
        f"delete from public.lightrag_doc_full where workspace='{TRIAL}';"
        f"delete from public.lightrag_doc_status where workspace='{TRIAL}';"
        f"delete from env_rag.documents where workspace='{TRIAL}';"
        f"delete from env_rag.source_units where workspace='{TRIAL}';"
        f"delete from env_rag.unit_chunk_links where workspace='{TRIAL}';"
        f"delete from env_rag.scopes where workspace='{TRIAL}';"
        f"delete from env_rag.scope_units where workspace='{TRIAL}';"
        f"delete from env_rag.search_documents where workspace='{TRIAL}';"
        f"delete from env_rag.search_chunks where workspace='{TRIAL}';"
        f"delete from env_rag.search_builds where workspace='{TRIAL}';"
        f"delete from env_rag.corpus_runs where workspace='{TRIAL}';"
    )
    for name in ("chunks", "entities", "relationships"):
        httpx.post(
            f"http://localhost:6333/collections/lightrag_vdb_{name}_qwen_qwen3_embedding_4b_2560d/points/delete",
            json={"filter": {"must": [{"key": "workspace_id", "match": {"value": TRIAL}}]}},
            timeout=60,
        )
    sh(
        [
            "container",
            "exec",
            "lightrag-neo4j",
            "cypher-shell",
            "-u",
            "neo4j",
            "-p",
            _neo4j_password(),
            f"MATCH (n:`{TRIAL}`) DETACH DELETE n;",
        ]
    )
    step(
        "withdraw.trial-doc",
        psql(f"select count(*) from public.lightrag_doc_chunks where workspace='{TRIAL}';"),
    )
    # A withdrawal is an administrative act: the ingestion checkpoints for that
    # library must be cleared too, otherwise a later re-ingest would consider the
    # document still done.  The checkpoint file is retired and the fact recorded.
    ledger_path = LOCAL / f"ingest-{TRIAL}.jsonl"
    if ledger_path.exists():
        ledger_path.rename(ledger_path.with_suffix(".jsonl.withdrawn"))
    step("withdraw.checkpoint-cleared", not ledger_path.exists())
    report["after_withdraw"] = counts()
    report["other_libraries_unchanged"] = (
        keep_only(before) == keep_only(report["after_withdraw"])
        and not any(x.startswith(f"{TRIAL}=") for x in report["after_withdraw"]["chunks"])
    )
    step("withdraw.others_unchanged", report["other_libraries_unchanged"])
    report["trial_query_after_withdraw"] = query("coastal-reader", TRIAL, "长江保护法 水生态保护")
    step("trial.query.after_withdraw", report["trial_query_after_withdraw"])

    # ---- restore ---------------------------------------------------------
    ingest = sh(
        [
            ".venv/bin/env-rag-final",
            "workspace-ingest",
            "--workspace",
            TRIAL,
            "--doc-name",
            TRIAL_DOC,
            "--extra-doc",
            TRIAL_DOC,
            "--set",
            "EMBEDDING_TIMEOUT=300",
        ]
    )
    step("restore.ingest", (ingest.stdout or ingest.stderr)[-300:])
    for command in ("workspace-catalog", "workspace-index"):
        res = sh([".venv/bin/env-rag-final", command, "--workspace", TRIAL])
        step(f"restore.{command}", (res.stdout or res.stderr)[-200:])
    report["trial_query_after_restore"] = query("coastal-reader", TRIAL, "长江保护法 水生态保护")
    step("trial.query.after_restore", report["trial_query_after_restore"])

    out = Path(args.out)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        json.dumps({k: v for k, v in report.items() if k != "steps"}, ensure_ascii=False, indent=1)
    )
    return 0


def _neo4j_password() -> str:
    from dotenv import dotenv_values

    return dotenv_values(ROOT / ".env")["NEO4J_PASSWORD"]


if __name__ == "__main__":
    raise SystemExit(main())
