"""Review 5.1 in a uniquely owned DB; production connections are SELECT-only."""

import asyncio
import base64
import hashlib
import importlib.metadata
import json
import logging
import os
import tempfile
import uuid
from pathlib import Path

import asyncpg
import numpy as np
from lightrag import LightRAG, QueryParam
from lightrag.kg.pgtable_impl import PGTableGraphStorage
from lightrag.kg.postgres_impl import ClientManager, PGGraphStorage, PostgreSQLDB
from lightrag.utils import EmbeddingFunc

from env_rag_final.catalog.builder import check_stale
from env_rag_final.config import read_environment
from env_rag_final.search.index import check_search_stale

OUT = Path(__file__).parent
logging.getLogger("lightrag").setLevel(logging.CRITICAL)
TABLES = [
    "doc_full",
    "doc_chunks",
    "doc_status",
    "llm_cache",
    "entity_chunks",
    "full_entities",
    "full_relations",
    "relation_chunks",
]


async def connect(values, database, readonly=False):
    return await asyncpg.connect(
        host=values["POSTGRES_HOST"],
        port=int(values["POSTGRES_PORT"]),
        user=values["POSTGRES_USER"],
        password=values["POSTGRES_PASSWORD"],
        database=database,
        statement_cache_size=0,
        timeout=15,
        server_settings={
            "default_transaction_read_only": "on" if readonly else "off",
            "statement_timeout": "30000",
        },
    )


async def metadata(conn):
    tables = await conn.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY 1"
    )
    cols = await conn.fetch(
        "SELECT table_name,column_name,data_type,is_nullable FROM information_schema.columns WHERE table_schema='public' AND table_name LIKE 'lightrag_graph_%' ORDER BY table_name,ordinal_position"
    )
    return {
        "tables": [r[0] for r in tables],
        "graph_columns": [dict(r) for r in cols],
        "extensions": [
            r[0] for r in await conn.fetch("SELECT extname FROM pg_extension ORDER BY 1")
        ],
        "available_vector_age": [
            r[0]
            for r in await conn.fetch(
                "SELECT name FROM pg_available_extensions WHERE name IN ('vector','age') ORDER BY 1"
            )
        ],
        "graph_counts": {
            table: await conn.fetchval(f"SELECT count(*) FROM public.{table}")
            for table in [r[0] for r in tables]
            if table in ("lightrag_graph_nodes", "lightrag_graph_edges")
        },
    }


async def production(values):
    conn = await connect(values, values["POSTGRES_DATABASE"], True)
    try:
        out = {
            "counts": {
                t: await conn.fetchval(f"SELECT count(*) FROM public.lightrag_{t}") for t in TABLES
            },
            "catalog": await check_stale(conn),
            "search": await check_search_stale(conn),
            "schema": await metadata(conn),
        }
        row = await conn.fetchrow(
            "SELECT workspace,namespace,id FROM public.lightrag_graph_nodes LIMIT 1"
        )
        if row:

            class ReadonlyDB:
                async def query(self, sql, params=None, multirows=False):
                    assert sql.lstrip().upper().startswith("SELECT")
                    args = params or []
                    if multirows:
                        return [dict(r) for r in await conn.fetch(sql, *args)]
                    r = await conn.fetchrow(sql, *args)
                    return dict(r) if r else None

                async def execute(self, *a, **kw):
                    raise AssertionError("production graph writes forbidden")

            storage = PGTableGraphStorage(
                namespace=row["namespace"], workspace=row["workspace"], global_config={}
            )
            storage.db = ReadonlyDB()  # No initialize()/ClientManager on production.
            node = await storage.get_node(row["id"])
            out["pgtable_readonly_get_node"] = {
                "success": bool(node) and node.get("entity_id") == row["id"],
                "node_key_sha256": hashlib.sha256(row["id"].encode()).hexdigest(),
                "property_keys": sorted(node or {}),
                "initialization_called": False,
            }
        return out
    finally:
        await conn.close()


async def main():
    values = read_environment(Path(".env"))
    env_sha = hashlib.sha256(Path(".env").read_bytes()).hexdigest()
    out = {
        "readonly_production": True,
        "real_model_calls": 0,
        "real_embedding_calls": 0,
        "release": importlib.metadata.version("lightrag-hku"),
    }
    dist = importlib.metadata.distribution("lightrag-hku")
    mismatches = []
    checked = 0
    for f in dist.files or []:
        if f.hash and str(f).startswith("lightrag/") and str(f).endswith(".py"):
            checked += 1
            actual = (
                base64.urlsafe_b64encode(hashlib.sha256(dist.locate_file(f).read_bytes()).digest())
                .rstrip(b"=")
                .decode()
            )
            if actual != f.hash.value:
                mismatches.append(str(f))
    out["wheel_record"] = {"python_files_checked": checked, "mismatches": mismatches}
    assert not mismatches
    out["production_before"] = await production(values)
    dbname = "env_rag_compat_review_" + uuid.uuid4().hex[:8]
    marker = "codex-owned-5.1-review-" + uuid.uuid4().hex
    assert dbname != values["POSTGRES_DATABASE"]
    admin = await connect(values, "postgres")
    created = False
    oid = None
    objects = []
    mutable = [
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DATABASE",
        "POSTGRES_WORKSPACE",
        "POSTGRES_MAX_CONNECTIONS",
        "POSTGRES_CONNECTION_RETRIES",
        "POSTGRES_CONNECTION_RETRY_BACKOFF",
        "POSTGRES_CONNECTION_RETRY_BACKOFF_MAX",
    ]
    saved = {k: os.environ.get(k) for k in mutable}
    old_init, old_check = PostgreSQLDB.initdb, PostgreSQLDB.check_tables
    calls = {"initdb": 0, "check_tables": 0}

    async def guarded_init(db):
        assert db.database == dbname, "LightRAG target escaped owned scratch DB"
        calls["initdb"] += 1
        await old_init(db)

    async def counted_check(db):
        assert db.database == dbname
        calls["check_tables"] += 1
        await old_check(db)

    try:
        assert not await admin.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", dbname)
        await admin.execute(f'CREATE DATABASE "{dbname}"')
        created = True
        oid = await admin.fetchval("SELECT oid FROM pg_database WHERE datname=$1", dbname)
        await admin.execute(f"COMMENT ON DATABASE \"{dbname}\" IS '{marker}'")
        out["owned_scratch"] = {"database": dbname, "oid": oid, "ownership_marker": marker}
        for k in mutable[:4]:
            os.environ[k] = values[k]
        os.environ.update(
            {
                "POSTGRES_DATABASE": dbname,
                "POSTGRES_WORKSPACE": "",
                "POSTGRES_MAX_CONNECTIONS": "4",
                "POSTGRES_CONNECTION_RETRIES": "1",
                "POSTGRES_CONNECTION_RETRY_BACKOFF": "0",
                "POSTGRES_CONNECTION_RETRY_BACKOFF_MAX": "0",
            }
        )
        PostgreSQLDB.initdb = guarded_init
        PostgreSQLDB.check_tables = counted_check
        assert ClientManager._instances["db"] is None
        out["vector_flags"] = {
            str(v): ClientManager.get_config(v)["enable_vector"]
            for v in [None, "NanoVectorDBStorage", "QdrantVectorDBStorage", "PGVectorStorage"]
        }
        first = await ClientManager.get_client(None)
        second = await ClientManager.get_client(None)
        out["pool_retained_second_call"] = {"same_object": first is second, "calls": dict(calls)}
        await ClientManager.release_client(second)
        await ClientManager.release_client(first)
        third = await ClientManager.get_client(None)
        out["pool_after_final_release"] = {
            "calls": dict(calls),
            "reinitialized": calls["initdb"] == 2,
        }
        await ClientManager.release_client(third)
        tempconn = await connect(values, dbname)
        out["scratch_after_pool"] = await metadata(tempconn)
        await tempconn.close()
        fixture_calls = {"llm": 0, "embedding": 0}

        async def embed(texts):
            fixture_calls["embedding"] += 1
            return np.array([[0.5] * 4 for _t in texts], dtype=np.float32)

        async def llm(*a, **kw):
            fixture_calls["llm"] += 1
            return "deterministic fixture response"

        with tempfile.TemporaryDirectory(prefix="env-rag-compat-review-") as folder:
            for ws, content in [
                ("review_a", "Review fixture first content; concentration 60."),
                ("review_b", "Review fixture alternate version; concentration 99."),
            ]:
                rag = LightRAG(
                    workspace=ws,
                    working_dir=str(Path(folder) / ws),
                    kv_storage="PGKVStorage",
                    doc_status_storage="PGDocStatusStorage",
                    graph_storage="PGTableGraphStorage",
                    vector_storage="NanoVectorDBStorage",
                    embedding_func=EmbeddingFunc(embedding_dim=4, max_token_size=512, func=embed),
                    llm_model_func=llm,
                )
                objects.append(rag)
                await rag.initialize_storages()
                await rag.ainsert(content, file_paths=["doc-a"])
            results = []
            for rag in objects:
                result = await rag.aquery_data(
                    "concentration",
                    param=QueryParam(mode="naive", top_k=5, chunk_top_k=5, enable_rerank=False),
                )
                results.append(
                    {
                        "workspace": rag.workspace,
                        "chunks": (result.get("data") or {}).get("chunks", []),
                        "status": result.get("status"),
                    }
                )
            tc = await connect(values, dbname)
            rows = [
                dict(r)
                for r in await tc.fetch(
                    "SELECT workspace,id,full_doc_id,content FROM lightrag_doc_chunks ORDER BY workspace,id"
                )
            ]
            graph = objects[0].chunk_entity_relation_graph
            await graph.upsert_node(
                "review-node", {"entity_id": "review-node", "description": "fixture graph node"}
            )
            graph_node = await graph.get_node("review-node")
            out["plain_graph_fixture_get_node"] = graph_node.get("entity_id") == "review-node"
            statuses = [
                dict(r)
                for r in await tc.fetch(
                    "SELECT workspace,id,status FROM lightrag_doc_status ORDER BY workspace,id"
                )
            ]
            out["scratch_with_plain_graph"] = await metadata(tc)
            out["sample"] = {
                "rows": rows,
                "statuses": statuses,
                "queries": results,
                "cache_columns": [
                    r[0]
                    for r in await tc.fetch(
                        "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='lightrag_llm_cache' ORDER BY ordinal_position"
                    )
                ],
                "cache_types": [
                    dict(r)
                    for r in await tc.fetch(
                        "SELECT workspace,cache_type,count(*) AS n FROM lightrag_llm_cache GROUP BY workspace,cache_type ORDER BY workspace,cache_type"
                    )
                ],
                "missing_chunk": [await objects[0].text_chunks.get_by_id("missing-review-chunk")],
                "effective_workspaces": [r.text_chunks.workspace for r in objects],
            }
            await tc.close()
            assert len(rows) == 2 and {r["workspace"] for r in rows} == {"review_a", "review_b"}
            assert all(s["status"] == "processed" for s in statuses)
            out["sample"]["same_filename_same_chunk_id"] = rows[0]["id"] == rows[1]["id"]
            out["sample"]["different_content"] = rows[0]["content"] != rows[1]["content"]
            for r in results:
                assert r["chunks"] and all(
                    any(
                        x["workspace"] == r["workspace"]
                        and x["id"] == c["chunk_id"]
                        and x["content"] == c["content"]
                        for x in rows
                    )
                    for c in r["chunks"]
                )
            for rag in reversed(objects):
                await rag.finalize_storages()
            objects.clear()
        out["fixture_calls"] = fixture_calls
        assert ClientManager._instances["db"] is None
        age = PGGraphStorage(
            namespace="chunk_entity_relation",
            workspace="review_a",
            global_config={"vector_storage": "NanoVectorDBStorage"},
            embedding_func=None,
        )
        try:
            await asyncio.wait_for(age.initialize(), 10)
            out["age_probe"] = {"unexpected_success": True}
        except Exception as exc:
            out["age_probe"] = {"error_type": type(exc).__name__, "error": str(exc)[:600]}
        finally:
            if age.db is not None:
                await ClientManager.release_client(age.db)
                age.db = None
        try:
            vector = await asyncio.wait_for(ClientManager.get_client("PGVectorStorage"), 10)
            out["pgvector_probe"] = {"unexpected_success": True}
            await ClientManager.release_client(vector)
        except Exception as exc:
            out["pgvector_probe"] = {"error_type": type(exc).__name__, "error": str(exc)[:600]}
    finally:
        for rag in reversed(objects):
            await rag.finalize_storages()
        PostgreSQLDB.initdb = old_init
        PostgreSQLDB.check_tables = old_check
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if created:
            current = await admin.fetchrow(
                "SELECT oid,shobj_description(oid,'pg_database') AS marker FROM pg_database WHERE datname=$1",
                dbname,
            )
            assert current and current["oid"] == oid and current["marker"] == marker, (
                "scratch ownership changed; refusing cleanup"
            )
            active = await admin.fetchval(
                "SELECT count(*) FROM pg_stat_activity WHERE datname=$1", dbname
            )
            if active:
                out["cleanup"] = {
                    "dropped": False,
                    "reason": "active sessions remain; retained rather than terminating foreign sessions",
                    "sessions": active,
                }
            else:
                await admin.execute(f'DROP DATABASE "{dbname}"')
                out["cleanup"] = {"dropped": True, "ownership_verified": True}
        await admin.close()
        out["production_after"] = await production(values)
        out["production_unchanged"] = out["production_before"] == out["production_after"]
        out["env_file_unchanged"] = hashlib.sha256(Path(".env").read_bytes()).hexdigest() == env_sha
        (OUT / "independent-runtime.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2, default=str) + "\n"
        )
    assert out["production_unchanged"] and out["env_file_unchanged"]
    print(
        {
            k: out[k]
            for k in [
                "wheel_record",
                "vector_flags",
                "pool_retained_second_call",
                "pool_after_final_release",
                "cleanup",
                "production_unchanged",
                "env_file_unchanged",
            ]
        }
    )


asyncio.run(main())
