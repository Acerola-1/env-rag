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

SNAPSHOT_FORMAT = "workspace-access/protected-snapshot-r2"

PROTECTED_FILES = (
    ".env",
    "datasets/manifest.json",
    "datasets/evaluation/gold-approved.json",
    "datasets/evaluation/unit-mapping.json",
    "assets/legacy-comparison-web/premium-ui.json",
    "assets/legacy-comparison-web/WEB_RAG.md",
    "assets/legacy-comparison-web/DESIGN.md",
    "assets/legacy-comparison-web/UX-CONTRACT.md",
    "assets/pg-retrieval/ENUMERATION.md",
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
    """Hash every column of every row, including historical builds (read-only)."""

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
    # PostgreSQL canonical JSON includes content, attributes, timestamps and
    # historical rows. Sorted row hashes make the final digest order-independent.
    for schema, tables, target in (
        ("public", PG_LIGHTRAG_TABLES, "tables"),
        ("env_rag", PG_ENV_RAG_TABLES, "env_rag"),
    ):
        for table in tables:
            rows = q(
                f"SELECT workspace,count(*)::text, "
                "encode(sha256(convert_to(string_agg(h,'' ORDER BY h),'UTF8')),'hex') "
                f"FROM (SELECT workspace,encode(sha256(convert_to(to_jsonb(t)::text,'UTF8')),'hex') h "
                f"FROM {schema}.{table} t) r GROUP BY workspace ORDER BY workspace"
            )
            snapshot[target][table]["content_digest"] = {r[0]: r[2] for r in rows}
    snapshot["complete_content_scan"] = True
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
        content_groups: dict[str, list[str]] = {}
        offset = None
        seen_offsets = set()
        for _ in range(10000):
            body = {
                "limit": 1000,
                "with_payload": True,
                "with_vector": True,
            }
            if offset is not None:
                body["offset"] = offset
            res = httpx.post(
                f"{url.rstrip('/')}/collections/{name}/points/scroll",
                headers=headers,
                json=body,
                timeout=60,
            ).json()["result"]
            if not isinstance(res.get("points"), list) or "next_page_offset" not in res:
                raise RuntimeError("Qdrant response lacks pagination proof")
            for point in res["points"]:
                ws = (point.get("payload") or {}).get("workspace_id")
                groups.setdefault(str(ws), []).append(str(point["id"]))
                content_groups.setdefault(str(ws), []).append(
                    _sha256_bytes(
                        json.dumps(
                            point, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                        ).encode()
                    )
                )
            offset = res.get("next_page_offset")
            if offset is None:
                break
            token = json.dumps(offset, sort_keys=True)
            if token in seen_offsets:
                raise RuntimeError("Qdrant pagination repeated an offset")
            seen_offsets.add(token)
        else:
            raise RuntimeError("Qdrant pagination did not finish; no snapshot proof")
        entry["complete_content_scan"] = True
        entry["by_workspace"] = {
            k: {
                "count": len(v),
                "id_digest": _id_digest(v),
                "content_digest": _id_digest(content_groups[k]),
            }
            for k, v in groups.items()
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
                escaped = label.replace("`", "``")
                node_count = session.run(f"MATCH (n:`{escaped}`) RETURN count(n) AS c").single()[
                    "c"
                ]
                ids = [
                    r["eid"]
                    for r in session.run(f"MATCH (n:`{escaped}`) RETURN n.entity_id AS eid")
                ]
                rel_count = session.run(
                    f"MATCH (:`{escaped}`)-[r]->() RETURN count(r) AS c"
                ).single()["c"]
                node_hashes = [
                    _sha256_bytes(json.dumps(dict(r), sort_keys=True, default=str).encode())
                    for r in session.run(
                        f"MATCH (n:`{escaped}`) RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS properties ORDER BY id"
                    )
                ]
                relation_hashes = [
                    _sha256_bytes(json.dumps(dict(r), sort_keys=True, default=str).encode())
                    for r in session.run(
                        f"MATCH (a)-[r]->(b) WHERE a:`{escaped}` OR b:`{escaped}` RETURN elementId(r) AS id, elementId(a) AS source, elementId(b) AS target, type(r) AS type, properties(r) AS properties ORDER BY id"
                    )
                ]
                out["labels"][label] = {
                    "complete_content_scan": True,
                    "node_content_digest": _id_digest(node_hashes),
                    "relationship_content_digest": _id_digest(relation_hashes),
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
    from env_rag_final.access.registry import default_registry_path, load_registry

    snap["namespace_map"] = {"default": {"pg": "default", "vector": "_", "graph": "base"}}
    if default_registry_path().is_file():
        registry = load_registry(default_registry_path())
        snap["namespace_map"].update(
            {
                w.id: {
                    "pg": w.pg_workspace,
                    "vector": w.vector_workspace,
                    "graph": w.graph_workspace,
                }
                for w in registry.workspaces.values()
            }
        )
    return snap


def physical_namespace(snapshot: dict, logical: str, backend: str) -> str:
    fallback = (
        {"pg": "default", "vector": "_", "graph": "base"}
        if logical == "default"
        else {k: logical for k in ("pg", "vector", "graph")}
    )
    return snapshot.get("namespace_map", {}).get(logical, {}).get(backend, fallback[backend])


def compare(before: dict, after: dict, *, protected_workspaces: list[str]) -> dict:
    """Compare two snapshots, ignoring non-protected workspaces."""
    report: dict = {"protected_workspaces": protected_workspaces, "ok": True, "diffs": []}

    def note(path: str, detail) -> None:
        report["ok"] = False
        report["diffs"].append({"path": path, "detail": detail})

    for logical in protected_workspaces:
        for backend in ("pg", "vector", "graph"):
            if physical_namespace(before, logical, backend) != physical_namespace(
                after, logical, backend
            ):
                note(f"proof.namespace_map.{logical}.{backend}", "mapping changed")
    for rel, meta in before["files"].items():
        if after["files"].get(rel) != meta:
            note(f"files.{rel}", {"before": meta, "after": after["files"].get(rel)})

    for table, entry in before["pg"]["tables"].items():
        aft = after["pg"]["tables"].get(table, {})
        for logical in protected_workspaces:
            ws = physical_namespace(before, logical, "pg")
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
            for logical in protected_workspaces:
                ws = physical_namespace(before, logical, "pg")
                if entry.get(ws) != after["pg"]["env_rag"].get(table, {}).get(ws):
                    note(
                        f"env_rag.{table}.{ws}",
                        [entry.get(ws), after["pg"]["env_rag"].get(table, {}).get(ws)],
                    )
            continue
        for logical in protected_workspaces:
            ws = physical_namespace(before, logical, "pg")
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

    # Logical "default" is physically "_" in Qdrant and "base" in Neo4j.
    # Missing content proof is an explicit limitation, never a passing comparison.
    if before.get("format") != SNAPSHOT_FORMAT or after.get("format") != SNAPSHOT_FORMAT:
        note(
            "proof.format",
            "legacy snapshot lacks full content proof; historical non-mutation unverified",
        )
    for snap in (before, after):
        if snap.get("pg", {}).get("complete_content_scan") is not True:
            note("proof.pg", "full row scan missing")
    for family in ("tables", "env_rag"):
        for table in set(before["pg"][family]) | set(after["pg"][family]):
            if table in ("active_catalog", "active_search"):
                continue
            for logical in protected_workspaces:
                ws = physical_namespace(before, logical, "pg")
                b = before["pg"][family].get(table, {}).get("content_digest", {}).get(ws)
                a = after["pg"][family].get(table, {}).get("content_digest", {}).get(ws)
                if b != a:
                    note(f"pg.{family}.{table}.{ws}.content_digest", "content changed")
    for col in set(before["qdrant"]["collections"]) | set(after["qdrant"]["collections"]):
        bcol = before["qdrant"]["collections"].get(col, {})
        acol = after["qdrant"]["collections"].get(col, {})
        if not bcol.get("complete_content_scan") or not acol.get("complete_content_scan"):
            note(f"proof.qdrant.{col}", "full payload/vector scan missing")
        for logical in protected_workspaces:
            physical = physical_namespace(before, logical, "vector")
            b = bcol.get("by_workspace", {}).get(physical)
            a = acol.get("by_workspace", {}).get(physical)
            if b != a:
                note(f"qdrant.{col}.{physical}", [b, a])
    for logical in protected_workspaces:
        physical = physical_namespace(before, logical, "graph")
        b = before["neo4j"]["labels"].get(physical)
        a = after["neo4j"]["labels"].get(physical)
        if b != a:
            note(f"neo4j.{physical}", [b, a])
        if any(entry is not None and not entry.get("complete_content_scan") for entry in (a, b)):
            note(f"proof.neo4j.{physical}", "full node/relationship scan missing")

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
