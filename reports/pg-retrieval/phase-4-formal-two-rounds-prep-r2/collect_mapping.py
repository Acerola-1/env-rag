"""One read-only query for the 27 frozen gold unit keys, for scoring ONLY.

No data from this mapping enters retrieval or answer construction. Guard SQL
uses the accepted identity capture separately. No models/vector/graph calls.
"""

import argparse
import asyncio
import hashlib
import json

import asyncpg
from prepared_common import HERE, ROOT, validate_bundle

from env_rag_final import answer as an
from env_rag_final import evaluation as ev
from env_rag_final.catalog.units import parse_blocks, parse_tables

SQL = """
WITH requested AS (
 SELECT * FROM jsonb_to_recordset($3::jsonb) AS t(doc_id text, unit_id text)
)
SELECT u.workspace,u.doc_id,u.snapshot_id,u.unit_id,u.unit_kind,
       u.requires_span,u.content_length,d.doc_name,
 COALESCE((SELECT jsonb_agg(l.chunk_id ORDER BY l.chunk_order,l.chunk_id)
   FROM env_rag.unit_chunk_links l
   WHERE (l.workspace,l.doc_id,l.snapshot_id,l.unit_id)=
         (u.workspace,u.doc_id,u.snapshot_id,u.unit_id)), '[]'::jsonb) AS chunk_ids,
 COALESCE((SELECT jsonb_agg(DISTINCT jsonb_build_object(
       'scope_id',s.scope_id,'confirm_status',s.confirm_status))
   FROM env_rag.scope_units su JOIN env_rag.scopes s
     USING(workspace,doc_id,snapshot_id,scope_id)
   WHERE (su.workspace,su.doc_id,su.snapshot_id,su.unit_id)=
         (u.workspace,u.doc_id,u.snapshot_id,u.unit_id)), '[]'::jsonb) AS scopes
FROM env_rag.source_units u JOIN requested r USING(doc_id,unit_id)
JOIN public.lightrag_doc_full d ON d.workspace=u.workspace AND d.id=u.doc_id
WHERE u.workspace=$1 AND u.snapshot_id=$2
ORDER BY u.workspace,u.doc_id,u.snapshot_id,u.unit_id LIMIT $4
"""


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def build_entries(rows, targets, workspace, snapshot, text_reader):
    requested = {(t["workspace"], t["doc_id"], t["unit_id"]) for t in targets}
    got, entries = set(), []
    for row in rows:
        key = (row["workspace"], row["doc_id"], row["unit_id"])
        if (
            key not in requested
            or key in got
            or row["snapshot_id"] != snapshot
            or key[0] != workspace
        ):
            raise RuntimeError("missing, repeated, or foreign mapping identity")
        got.add(key)
        text = text_reader(row)
        if not isinstance(text, str) or not text or len(text) != row["content_length"]:
            raise RuntimeError("unit text unavailable or content length differs from catalog")
        chunks, scopes = _json(row["chunk_ids"]), _json(row["scopes"])
        if (
            not isinstance(chunks, list)
            or not chunks
            or any(not isinstance(c, str) or not c for c in chunks)
        ):
            raise RuntimeError("target unit has no confirmed mapping; do not start paid evaluation")
        entries.append(
            {
                "workspace": key[0],
                "doc_id": key[1],
                "snapshot_id": snapshot,
                "unit_id": key[2],
                "unit_kind": row["unit_kind"],
                "requires_span": row["requires_span"],
                "chunk_ids": chunks,
                "scopes": scopes,
                "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
            }
        )
    if got != requested:
        raise RuntimeError("not all frozen target units were captured; no partial mapping publish")
    return entries


def read_text_cached():
    cache = {}

    def read(row):
        filename = row["doc_name"]
        if filename not in cache:
            parsed = an._doc_parsed_dir(filename)
            if parsed is None:
                raise RuntimeError("parsed source unavailable")
            _, blocks = parse_blocks(parsed)
            cache[filename] = (
                {b["blockid"]: b.get("content") for b in blocks},
                parse_tables(parsed),
            )
        blocks, tables = cache[filename]
        return (
            blocks.get(row["unit_id"])
            if row["unit_kind"] == "block"
            else (tables.get(row["unit_id"]) or {}).get("content")
        )

    return read


async def collect(destination):
    anchor, values, expected = validate_bundle()
    if destination.exists():
        raise RuntimeError("mapping destination already exists; no automatic retry")
    destination.mkdir(parents=True)
    target_file = json.loads((HERE / "mapping-targets.json").read_text())
    targets = target_file["targets"]
    workspace = "default"
    snapshot = anchor["frozen_identity"]["catalog_run_snapshot"].split("/")[1]
    before = ev._flatten_identity(await ev._capture_identity(values))
    if not before["matches_frozen"] or ev._identity_problems(expected, before):
        raise RuntimeError("mapping source guard rejected before data query")
    conn = None
    entries = None
    error = None
    after = None
    try:
        conn = await asyncpg.connect(
            host=values["POSTGRES_HOST"],
            port=int(values["POSTGRES_PORT"]),
            user=values["POSTGRES_USER"],
            password=values["POSTGRES_PASSWORD"],
            database=values["POSTGRES_DATABASE"],
            timeout=15,
            statement_cache_size=0,
            server_settings={"default_transaction_read_only": "on", "statement_timeout": "30000"},
        )
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            rows = await conn.fetch(SQL, workspace, snapshot, json.dumps(targets), len(targets) + 1)
        entries = build_entries(rows, targets, workspace, snapshot, read_text_cached())
    except Exception as exc:
        error = exc
    finally:
        if conn is not None:
            try:
                await conn.close()
            except Exception as exc:
                error = error or exc
        try:
            after = ev._flatten_identity(await ev._capture_identity(values))
        except Exception as exc:
            error = error or exc
    if error is not None:
        (destination / "capture-failure.json").write_text(
            json.dumps(
                {
                    "error_type": type(error).__name__,
                    "identity_before": before,
                    "identity_after": after,
                    "status": "failed; no mapping publish; stop before paid calls",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        raise RuntimeError("mapping capture or post-guard failed") from error
    if ev._capture_drift(before, after) or ev._identity_problems(expected, after):
        raise RuntimeError("mapping source identity drift; no publication")
    body = {
        "schema": "unit-mapping/r1",
        "scope": "fixed gold target units only; evaluator attachment, never retrieval input",
        "workspace": workspace,
        "catalog_snapshot_id": snapshot,
        "source_fingerprint": before["source_fingerprint"],
        "gold_sha256": target_file["gold_sha256"],
        "guard": {"identity_before": before, "identity_after": after},
        "data_sql_issued": 1,
        "data_sql_cap": 20,
        "guard_sql": "accepted identity capture, separately declared",
        "entries": entries,
        "models_called": 0,
    }
    path = destination / "mapping.json"
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n")
    manifest = {
        "files": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()},
        "data_sql_issued": 1,
    }
    (destination / "capture-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorized", action="store_true")
    args = parser.parse_args(argv)
    if not args.authorized:
        raise SystemExit("mapping collection is proposed only; batch authorization is required")
    destination = ROOT / "reports/pg-retrieval/phase-4-formal-mapping-r2"
    if destination.exists():
        raise SystemExit("mapping destination already exists; preserve it, no retry")
    try:
        asyncio.run(collect(destination))
    except Exception as exc:
        if destination.exists() and not (destination / "capture-failure.json").exists():
            (destination / "capture-failure.json").write_text(
                json.dumps(
                    {"error_type": type(exc).__name__, "status": "failed; stop before paid calls"}
                )
                + "\n"
            )
        raise SystemExit(
            f"mapping failed ({type(exc).__name__}); preserve artifacts, no retry"
        ) from None


if __name__ == "__main__":
    main()
