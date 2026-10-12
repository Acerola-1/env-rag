"""Read-only identity capture and ownership guard for workspace access work.

Records the identity of everything this change must not disturb: the existing
``default`` workspace data in PostgreSQL, Qdrant and Neo4j, the ``env_rag``
derived tables, the corpus/gold/config files, and the active catalog/search
builds.  Snapshots are compared before and after the work to prove the old
data kept its identity.

Every query here is read-only.  No storage client is instantiated through
LightRAG; connections are raw drivers.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from env_rag_final.paths import PROJECT_ROOT

SNAPSHOT_FORMAT = "workspace-access/protected-snapshot-r1"

PROTECTED_FILES = (
    ".env",
    "datasets/manifest.json",
    "datasets/evaluation/gold-approved.json",
    "datasets/evaluation/unit-mapping.json",
    "premium-ui.json",
    "WEB_RAG.md",
    "DESIGN.md",
    "UX-CONTRACT.md",
    "ENUMERATION.md",
)

# Tables whose per-workspace row identity must not change for old workspaces.
PG_LIGHTRAG_TABLES = (
    "lightrag_doc_full",
    "lightrag_doc_chunks",
    "lightrag_doc_status",
    "lightrag_llm_cache",
    "lightrag_entity_chunks",
    "lightrag_relation_chunks",
    "lightrag_full_entities",
    "lightrag_full_relations",
)
PG_ENV_RAG_TABLES = (
    "corpus_runs",
    "documents",
    "source_units",
    "unit_chunk_links",
    "scopes",
    "scope_units",
    "search_builds",
    "search_documents",
    "search_chunks",
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_fingerprints(root: Path = PROJECT_ROOT) -> dict:
    out = {}
    for rel in PROTECTED_FILES:
        path = root / rel
        if path.is_file():
            out[rel] = {
                "bytes": path.stat().st_size,
                "sha256": _sha256_bytes(path.read_bytes()),
            }
        else:
            out[rel] = {"missing": True}
    return out


def _id_digest(values: list[str]) -> str:
    h = hashlib.sha256()
    for v in sorted(values):
        h.update(v.encode())
        h.update(b"\n")
    return h.hexdigest()[:32]


def pg_snapshot(psql) -> dict:
    """Per-workspace row counts and id digests (read-only)."""

    def q(sql: str) -> list[list[str]]:
        res = subprocess.run(psql + [sql], capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(res.stderr.strip()[:400])
        return [line.split("|") for line in res.stdout.splitlines() if line.strip()]

    snapshot: dict = {"tables": {}, "env_rag": {}}
    for table in PG_LIGHTRAG_TABLES:
        rows = q("select workspace, count(*)::text from public.%s group by 1 order by 1;" % table)
        per_ws = {r[0]: int(r[1]) for r in rows if len(r) == 2}
        entry = {"counts": per_ws}
        if table in ("lightrag_doc_full", "lightrag_doc_status"):
            ids = q("select workspace, id from public.%s order by 1,2;" % table)
            grouped: dict[str, list[str]] = {}
            for r in ids:
                if len(r) == 2:
                    grouped.setdefault(r[0], []).append(r[1])
            entry["id_digest"] = {k: _id_digest(v) for k, v in grouped.items()}
        if table == "lightrag_doc_chunks":
            ids = q("select workspace, id from public.lightrag_doc_chunks order by 1,2;")
            grouped = {}
            for r in ids:
                if len(r) == 2:
                    grouped.setdefault(r[0], []).append(r[1])
            entry["id_digest"] = {k: _id_digest(v) for k, v in grouped.items()}
        snapshot["tables"][table] = entry

    for table in PG_ENV_RAG_TABLES:
        rows = q("select workspace, count(*)::text from env_rag.%s group by 1 order by 1;" % table)
        snapshot["env_rag"][table] = {"counts": {r[0]: int(r[1]) for r in rows if len(r) == 2}}
    active = q(
        "select workspace, snapshot_id, run_id from env_rag.corpus_runs "
        "where status='active' order by 1;"
    )
    snapshot["env_rag"]["active_catalog"] = {
        r[0]: {"snapshot_id": r[1], "run_id": r[2]} for r in active if len(r) == 3
    }
    builds = q(
        "select workspace, search_id, catalog_snapshot_id, status from env_rag.search_builds "
        "where status='active' order by 1;"
    )
    snapshot["env_rag"]["active_search"] = {
        r[0]: {"search_id": r[1], "catalog_snapshot_id": r[2], "status": r[3]}
        for r in builds
        if len(r) == 4
    }
    return snapshot


def qdrant_snapshot(url: str, api_key: str | None = None) -> dict:
    import httpx

    headers = {"api-key": api_key} if api_key else {}
    out: dict = {"collections": {}}
    cols = httpx.get(f"{url.rstrip('/')}/collections", headers=headers, timeout=30).json()
    for col in cols["result"]["collections"]:
        name = col["name"]
        info = httpx.get(
            f"{url.rstrip('/')}/collections/{name}", headers=headers, timeout=30
        ).json()["result"]
        entry = {"points": info.get("points_count")}
        # Scroll point ids grouped by workspace_id payload (bounded pages).
        groups: dict[str, list[str]] = {}
        offset = None
        for _ in range(200):
            body = {
                "limit": 1000,
                "with_payload": ["workspace_id"],
                "with_vector": False,
            }
            if offset is not None:
                body["offset"] = offset
            res = httpx.post(
                f"{url.rstrip('/')}/collections/{name}/points/scroll",
                headers=headers,
                json=body,
                timeout=60,
            ).json()["result"]
            for point in res.get("points", []):
                ws = (point.get("payload") or {}).get("workspace_id")
                groups.setdefault(str(ws), []).append(str(point["id"]))
            offset = res.get("next_page_offset")
            if not offset:
                break
        entry["by_workspace"] = {
            k: {"count": len(v), "id_digest": _id_digest(v)} for k, v in groups.items()
        }
        out["collections"][name] = entry
    return out


def neo4j_snapshot(uri: str, user: str, password: str, database: str | None = None) -> dict:
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(uri, auth=(user, password))
    out: dict = {"labels": {}}
    try:
        with driver.session(database=database) as session:
            labels = [
                r["label"]
                for r in session.run("CALL db.labels() YIELD label RETURN label ORDER BY label")
            ]
            for label in labels:
                node_count = session.run(f"MATCH (n:`{label}`) RETURN count(n) AS c").single()["c"]
                ids = [
                    r["eid"] for r in session.run(f"MATCH (n:`{label}`) RETURN n.entity_id AS eid")
                ]
                rel_count = session.run(
                    f"MATCH (:`{label}`)-[r]->() RETURN count(r) AS c"
                ).single()["c"]
                out["labels"][label] = {
                    "nodes": node_count,
                    "relationships_out": rel_count,
                    "entity_id_digest": _id_digest([i for i in ids if i]),
                }
    finally:
        driver.close()
    return out


def capture(env: dict, *, psql_argv: list[str] | None = None) -> dict:
    """Capture the full protected snapshot using the given env mapping."""
    psql = psql_argv or [
        "container",
        "exec",
        "lightrag-postgres",
        "psql",
        "-U",
        "rag",
        "-d",
        "rag",
        "-tAc",
    ]
    snap = {
        "format": SNAPSHOT_FORMAT,
        "files": file_fingerprints(),
        "pg": pg_snapshot(psql),
        "qdrant": qdrant_snapshot(env["QDRANT_URL"], env.get("QDRANT_API_KEY")),
        "neo4j": neo4j_snapshot(
            env["NEO4J_URI"],
            env["NEO4J_USERNAME"],
            env["NEO4J_PASSWORD"],
            env.get("NEO4J_DATABASE") or None,
        ),
    }
    return snap


def compare(before: dict, after: dict, *, protected_workspaces: list[str]) -> dict:
    """Compare two snapshots, ignoring non-protected workspaces."""
    report: dict = {"protected_workspaces": protected_workspaces, "ok": True, "diffs": []}

    def note(path: str, detail) -> None:
        report["ok"] = False
        report["diffs"].append({"path": path, "detail": detail})

    for rel, meta in before["files"].items():
        if after["files"].get(rel) != meta:
            note(f"files.{rel}", {"before": meta, "after": after["files"].get(rel)})

    for table, entry in before["pg"]["tables"].items():
        aft = after["pg"]["tables"].get(table, {})
        for ws in protected_workspaces:
            if entry["counts"].get(ws) != aft.get("counts", {}).get(ws):
                note(
                    f"pg.{table}.{ws}.count",
                    [entry["counts"].get(ws), aft.get("counts", {}).get(ws)],
                )
            if "id_digest" in entry and entry["id_digest"].get(ws) != aft.get("id_digest", {}).get(
                ws
            ):
                note(f"pg.{table}.{ws}.id_digest", "digest changed")

    for table, entry in before["pg"]["env_rag"].items():
        if table in ("active_catalog", "active_search"):
            for ws in protected_workspaces:
                if entry.get(ws) != after["pg"]["env_rag"].get(table, {}).get(ws):
                    note(
                        f"env_rag.{table}.{ws}",
                        [entry.get(ws), after["pg"]["env_rag"].get(table, {}).get(ws)],
                    )
            continue
        for ws in protected_workspaces:
            if entry["counts"].get(ws) != after["pg"]["env_rag"].get(table, {}).get(
                "counts", {}
            ).get(ws):
                note(
                    f"env_rag.{table}.{ws}.count",
                    [
                        entry["counts"].get(ws),
                        after["pg"]["env_rag"].get(table, {}).get("counts", {}).get(ws),
                    ],
                )

    for col, entry in before["qdrant"]["collections"].items():
        aft = after["qdrant"]["collections"].get(col, {}).get("by_workspace", {})
        for ws in protected_workspaces:
            b = entry["by_workspace"].get(ws)
            a = aft.get(ws)
            if b != a:
                note(f"qdrant.{col}.{ws}", [b, a])

    for label, entry in before["neo4j"]["labels"].items():
        if label in protected_workspaces:
            a = after["neo4j"]["labels"].get(label)
            if entry != a:
                note(f"neo4j.{label}", [entry, a])

    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    from dotenv import dotenv_values

    parser = argparse.ArgumentParser(prog="wa-snapshot")
    parser.add_argument("--out", required=True)
    parser.add_argument("--compare", help="previous snapshot to compare against")
    parser.add_argument("--protected-workspace", action="append", default=["default"])
    args = parser.parse_args(argv)

    env = dict(dotenv_values(PROJECT_ROOT / ".env"))
    env.update(
        {k: v for k, v in os.environ.items() if k.startswith(("POSTGRES", "NEO4J", "QDRANT"))}
    )
    snap = capture(env)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print(f"wrote {out}")
    if args.compare:
        before = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        report = compare(before, snap, protected_workspaces=args.protected_workspace)
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0 if report["ok"] else 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
