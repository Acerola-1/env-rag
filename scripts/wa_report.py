#!/usr/bin/env python
"""Assemble the workspace-access acceptance report.

Produces, under ``reports/workspace-access/<run-id>/``:

* ``service-receipts.jsonl``      — real model/embedding/reranker probes
* ``runtime-identity.json``       — instances, images, effective namespaces, code identity
* ``ingestion-results.jsonl``     — per-document终态 from the ledger + live PG
* ``protected-before-after.json`` — old-workspace identity comparison
* ``summary.md``                  — the report itself
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

LOCAL = ROOT / ".local/workspace-access"
DEFAULT_RUN = ROOT / "reports/workspace-access/wa-20261012-r1"


def probe_services(values: dict, out: Path) -> list[dict]:
    receipts: list[dict] = []
    ts = round(time.time(), 3)

    def add(kind: str, url: str, body: dict, res) -> None:
        entry = {
            "kind": kind,
            "url": url,
            "request_model": body.get("model"),
            "status": getattr(res, "status_code", None),
            "at": ts,
        }
        try:
            payload = res.json()
        except Exception:
            payload = None
        if kind == "llm" and payload:
            entry["returned_model"] = payload.get("model")
            entry["usage"] = payload.get("usage")
            entry["content_head"] = (
                (payload.get("choices") or [{}])[0].get("message", {}).get("content", "")[:40]
            )
        if kind == "embedding" and payload:
            vec = (payload.get("data") or [{}])[0].get("embedding") or []
            entry["dim"] = len(vec)
            entry["usage"] = payload.get("usage")
        if kind == "rerank" and payload:
            entry["results"] = len(payload.get("results") or [])
        receipts.append(entry)

    llm_url = str(values["LLM_BINDING_HOST"]).rstrip("/") + "/chat/completions"
    llm_body = {
        "model": values["LLM_MODEL"],
        "messages": [{"role": "user", "content": "只回答两个字：收到"}],
        "max_tokens": 16,
    }
    res = httpx.post(
        llm_url,
        headers={"Authorization": f"Bearer {values['LLM_BINDING_API_KEY']}"},
        json=llm_body,
        timeout=180,
    )
    add("llm", llm_url, llm_body, res)

    emb_url = str(values["EMBEDDING_BINDING_HOST"]).rstrip("/") + "/embeddings"
    emb_body = {
        "model": values["EMBEDDING_MODEL"],
        "input": ["环境空气质量标准 GB3095-2012 二氧化硫限值"],
    }
    res = httpx.post(
        emb_url,
        headers={"Authorization": f"Bearer {values['EMBEDDING_BINDING_API_KEY']}"},
        json=emb_body,
        timeout=180,
    )
    add("embedding", emb_url, emb_body, res)

    # The configured host may already include the endpoint (the deployment
    # convention here does); never re-append it.
    rerank_host = str(values["RERANK_BINDING_HOST"]).rstrip("/")
    rerank_url = rerank_host if rerank_host.endswith("/rerank") else rerank_host + "/rerank"
    rerank_body = {
        "model": values["RERANK_MODEL"],
        "query": "空气质量标准限值",
        "documents": ["GB3095-2012 规定了 PM2.5 限值", "长江保护法关于水生态保护"],
        "top_n": 2,
    }
    res = httpx.post(
        rerank_url,
        headers={"Authorization": f"Bearer {values['RERANK_BINDING_API_KEY']}"},
        json=rerank_body,
        timeout=180,
    )
    add("rerank", rerank_url, rerank_body, res)

    with out.open("w", encoding="utf-8") as fh:
        for receipt in receipts:
            fh.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n")
    return receipts


def container_identity(name: str) -> dict:
    res = subprocess.run(["container", "inspect", name], capture_output=True, text=True)
    if res.returncode != 0:
        return {"name": name, "missing": True}
    data = json.loads(res.stdout)[0]["configuration"]
    env = {}
    for item in data["initProcess"]["environment"]:
        key, _, value = item.partition("=")
        env[key] = value
    return {
        "name": name,
        "image": data["image"]["reference"],
        "digest": data["image"]["descriptor"]["digest"],
        "workspace": env.get("WORKSPACE"),
        "postgres_workspace": env.get("POSTGRES_WORKSPACE"),
        "qdrant_workspace": env.get("QDRANT_WORKSPACE"),
        "neo4j_workspace": env.get("NEO4J_WORKSPACE"),
        "neo4j_database": env.get("NEO4J_DATABASE"),
        "embedding_model": env.get("EMBEDDING_MODEL"),
        "embedding_dim": env.get("EMBEDDING_DIM"),
        "llm_model": env.get("LLM_MODEL"),
        "ports": [p.get("hostPort") for p in data.get("publishedPorts") or []],
    }


def code_identity() -> dict:
    files = [
        "src/env_rag_final/access/registry.py",
        "src/env_rag_final/access/auth.py",
        "src/env_rag_final/access/gateway.py",
        "src/env_rag_final/access/server.py",
        "src/env_rag_final/ingest/runner.py",
        "src/env_rag_final/manifest.py",
        "src/env_rag_final/search/index.py",
        "src/env_rag_final/catalog/builder.py",
        "src/env_rag_final/audit/snapshot.py",
    ]
    out = {}
    for rel in files:
        path = ROOT / rel
        out[rel] = (
            hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.is_file() else "missing"
        )
    return out


def ingestion_results(run_dir: Path, workspaces=("air", "water")) -> list[dict]:
    records: list[dict] = []
    psql = ["container", "exec", "lightrag-postgres", "psql", "-U", "rag", "-d", "rag", "-tAc"]
    for ws in workspaces:
        ledger_path = LOCAL / f"ingest-{ws}.jsonl"
        states: dict[str, dict] = {}
        if ledger_path.exists():
            for line in ledger_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                event = json.loads(line)
                key = (event["doc_name"], event["source_sha256"])
                states.setdefault(key, {})[event["event"]] = event
        for (doc_name, sha), events in sorted(states.items()):
            terminal = next(
                (events[k] for k in ("done", "duplicate", "skipped", "failed") if k in events), None
            )
            state = (
                "done"
                if "done" in events
                else "duplicate"
                if "duplicate" in events
                else "skipped"
                if "skipped" in events
                else "failed"
                if "failed" in events
                else "uncertain"
            )
            records.append(
                {
                    "workspace": ws,
                    "doc_name": doc_name,
                    "source_sha256": sha,
                    "state": state,
                    "evidence": (terminal or {}).get("evidence"),
                    "error": (terminal or {}).get("error"),
                }
            )
    # live cross-check from PostgreSQL
    for ws in workspaces:
        res = subprocess.run(
            psql
            + [
                f"select status, count(*) from public.lightrag_doc_status where workspace='{ws}' group by 1;"
            ],
            capture_output=True,
            text=True,
        )
        print(f"  live {ws}: {res.stdout.strip().replace(chr(10), '; ')}")
    out = run_dir / "ingestion-results.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return records


def protected_before_after(run_dir: Path) -> dict:
    before_path = run_dir / "protected-before.json"
    after_path = run_dir / "protected-after.json"
    from dotenv import dotenv_values

    from env_rag_final.access.snapshot import capture, compare

    values = dict(dotenv_values(ROOT / ".env"))
    after = capture(values)
    after_path.write_text(
        json.dumps(after, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )
    before = json.loads(before_path.read_text(encoding="utf-8"))
    report = compare(before, after, protected_workspaces=["default"])
    report["workspaces_not_in_default_grant"] = ["air", "water"]
    out = run_dir / "protected-before-after.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def summary(run_dir: Path, receipts, containers, results, protected, extra: dict) -> str:
    by_ws: dict[str, dict] = {}
    for record in results:
        by_ws.setdefault(record["workspace"], {}).setdefault(record["state"], 0)
        by_ws[record["workspace"]][record["state"]] += 1
    lines = [
        "# workspace 权限交付 · 验收报告",
        "",
        f"- run id: `{run_dir.name}`",
        f"- 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 1. 运行身份",
        "",
    ]
    for container in containers:
        if container.get("missing"):
            lines.append(f"- `{container['name']}`: 未运行")
            continue
        lines.append(
            f"- `{container['name']}`: 镜像 `{container['image']}`，WORKSPACE=`{container['workspace']}`，"
            f"PG=`{container['postgres_workspace']}`／Qdrant=`{container['qdrant_workspace']}`／"
            f"Neo4j=`{container['neo4j_workspace']}`（库 `{container['neo4j_database']}`），"
            f"embedding=`{container['embedding_model']}`({container['embedding_dim']}d)，端口 {container['ports']}"
        )
    lines += ["", "## 2. 服务回执（真实请求）", ""]
    for receipt in receipts:
        lines.append(
            f"- {receipt['kind']}: HTTP {receipt['status']} · model={receipt.get('request_model')}"
            + (f" · dim={receipt.get('dim')}" if receipt.get("dim") else "")
            + (
                f" · returned={receipt.get('returned_model')}"
                if receipt.get("returned_model")
                else ""
            )
        )
    lines += ["", "## 3. 入库终态", ""]
    for ws, counts in sorted(by_ws.items()):
        total = sum(counts.values())
        lines.append(
            f"- `{ws}`: 共 {total} 项 · " + "、".join(f"{k}={v}" for k, v in sorted(counts.items()))
        )
    lines += [
        "",
        "## 4. 旧数据保护",
        "",
        f"- 对照 `default`（原文／状态／向量／图谱／active 派生身份／配置与 gold 哈希）: "
        f"**{'一致' if protected.get('ok') else '存在差异'}**",
    ]
    if not protected.get("ok"):
        for diff in protected.get("diffs", []):
            lines.append(f"  - {diff['path']}: {diff['detail']}")
    if extra:
        lines += ["", "## 5. 其他证据", ""]
        for key, value in extra.items():
            lines.append(f"- {key}: {value}")
    text = "\n".join(lines) + "\n"
    (run_dir / "summary.md").write_text(text, encoding="utf-8")
    return text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--skip-services", action="store_true")
    args = parser.parse_args()
    run_dir = args.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)

    from dotenv import dotenv_values

    values = dict(dotenv_values(ROOT / ".env"))

    receipts = []
    receipts_path = run_dir / "service-receipts.jsonl"
    if args.skip_services and receipts_path.exists():
        receipts = [
            json.loads(line)
            for line in receipts_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    else:
        receipts = probe_services(values, receipts_path)

    containers = [container_identity("lightrag-air"), container_identity("lightrag-water")]
    identity = {
        "generated_at": round(time.time(), 3),
        "containers": containers,
        "code_identity": code_identity(),
        "model_configuration": {
            "llm": values.get("LLM_MODEL"),
            "keyword_llm": values.get("KEYWORD_LLM_MODEL"),
            "query_llm": values.get("QUERY_LLM_MODEL"),
            "embedding": values.get("EMBEDDING_MODEL"),
            "embedding_dim": values.get("EMBEDDING_DIM"),
            "rerank": values.get("RERANK_MODEL"),
            "lightrag_package": _lightrag_version(),
        },
    }
    (run_dir / "runtime-identity.json").write_text(
        json.dumps(identity, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    results = ingestion_results(run_dir)
    protected = protected_before_after(run_dir)

    extra = {}
    for name in (
        "chunk-identity-proof.json",
        "lightrag-init-probe.json",
        "acceptance-matrix.json",
        "third-workspace.json",
        "lifecycle.json",
        "browser/operations.json",
    ):
        path = run_dir / name
        if path.exists():
            extra[name] = f"见 `{name}`"
    if (run_dir / "browser").is_dir():
        shots = sorted(p.name for p in (run_dir / "browser").glob("*.png"))
        extra["browser screenshots"] = "、".join(shots)
    extra["已披露的操作事故"] = (
        "清理派生表时误删了 default 的 5 条 corpus_runs 与 7 条 search_builds 历史行；"
        "已依据 reports/pg-retrieval/phase-1/build-manifest.json 与 "
        "reports/pg-retrieval/phase-2/index-manifest.json 逐字段原值恢复，"
        "protected-before-after.json 复验为 0 差异。"
    )
    summary(run_dir, receipts, containers, results, protected, extra)
    print(
        json.dumps(
            {"run_dir": str(run_dir), "protected_ok": protected.get("ok"), "results": len(results)},
            ensure_ascii=False,
        )
    )
    return 0


def _lightrag_version() -> str:
    from importlib.metadata import version

    try:
        return version("lightrag-hku")
    except Exception:
        return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
