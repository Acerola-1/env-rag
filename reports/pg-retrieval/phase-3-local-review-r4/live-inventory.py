"""Independent read-only inventory. No LightRAG storage initialization/models."""

import asyncio
import json
from pathlib import Path

from dotenv import dotenv_values
from neo4j import READ_ACCESS, AsyncGraphDatabase
from qdrant_client import QdrantClient

from env_rag_final.compat_runtime import (
    _identity_drift,
    _identity_mismatch,
    capture_production_identity,
)

OUT = Path(__file__).parent


async def main():
    values = dict(dotenv_values(".env"))
    result = {"read_only": True, "storage_initialize_calls": 0, "model_calls": 0}
    result["before"] = await capture_production_identity(values, "before")
    result["frozen_problems_before"] = _identity_mismatch(result["before"])
    client = QdrantClient(
        url=values["QDRANT_URL"], api_key=values.get("QDRANT_API_KEY") or None, timeout=15
    )
    try:
        collections = {}
        for item in client.get_collections().collections:
            info = client.get_collection(item.name)
            collections[item.name] = {
                "points_count": info.points_count,
                "vectors": info.config.params.vectors.model_dump(mode="json"),
                "payload_schema": {
                    k: v.model_dump(mode="json") for k, v in info.payload_schema.items()
                },
            }
        result["qdrant"] = collections
    finally:
        client.close()
    driver = AsyncGraphDatabase.driver(
        values["NEO4J_URI"], auth=(values["NEO4J_USERNAME"], values["NEO4J_PASSWORD"])
    )
    try:
        async with driver.session(
            database=values.get("NEO4J_DATABASE") or "neo4j", default_access_mode=READ_ACCESS
        ) as session:
            graph = {}
            for key, query in (
                ("nodes", "MATCH (n:base) RETURN count(n) AS count"),
                ("relationships", "MATCH (:base)-[r]->(:base) RETURN count(r) AS count"),
            ):
                row = await (await session.run(query)).single()
                graph[key] = row["count"]
            graph["indexes"] = await (
                await session.run(
                    "SHOW INDEXES YIELD name, state, type, labelsOrTypes, properties "
                    "RETURN name, state, type, labelsOrTypes, properties"
                )
            ).data()
            result["neo4j"] = graph
    finally:
        await driver.close()
    result["after"] = await capture_production_identity(values, "after")
    result["frozen_problems_after"] = _identity_mismatch(result["after"])
    result["drift"] = _identity_drift(result["before"], result["after"])
    (OUT / "live-inventory.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps({"drift": result["drift"], "frozen_problems": result["frozen_problems_after"]})
    )


if __name__ == "__main__":
    asyncio.run(main())
