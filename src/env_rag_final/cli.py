"""Bootstrap verification; retrieval and ingestion are not implemented yet."""

import argparse
import asyncio
import importlib
from importlib.metadata import version
from pathlib import Path

from .config import read_environment

DEPENDENCIES = {
    "lightrag-hku": "lightrag",
    "openai": "openai",
    "asyncpg": "asyncpg",
    "pgvector": "pgvector",
    "qdrant-client": "qdrant_client",
    "neo4j": "neo4j",
    "httpx": "httpx",
    "python-dotenv": "dotenv",
    "lxml": "lxml.etree",
}


async def check_connections(values: dict[str, str]) -> bool:
    import asyncpg
    from neo4j import AsyncGraphDatabase
    from qdrant_client import AsyncQdrantClient

    async def postgres() -> None:
        connection = await asyncpg.connect(
            host=values["POSTGRES_HOST"],
            port=int(values["POSTGRES_PORT"]),
            user=values["POSTGRES_USER"],
            password=values["POSTGRES_PASSWORD"],
            database=values["POSTGRES_DATABASE"],
            timeout=10,
        )
        try:
            await connection.fetchval("SELECT 1")
        finally:
            await connection.close()

    async def qdrant() -> None:
        client = AsyncQdrantClient(
            url=values["QDRANT_URL"],
            api_key=values.get("QDRANT_API_KEY") or None,
            timeout=10,
        )
        try:
            await client.get_collections()
        finally:
            await client.close()

    async def neo4j() -> None:
        driver = AsyncGraphDatabase.driver(
            values["NEO4J_URI"],
            auth=(values["NEO4J_USERNAME"], values["NEO4J_PASSWORD"]),
            connection_timeout=10,
        )
        try:
            await driver.verify_connectivity()
            async with driver.session(database=values.get("NEO4J_DATABASE") or None) as session:
                result = await session.run("RETURN 1 AS ready")
                await result.consume()
        finally:
            await driver.close()

    checks = (("PostgreSQL", postgres), ("Qdrant", qdrant), ("Neo4j", neo4j))
    results = await asyncio.gather(
        *(asyncio.wait_for(check(), timeout=20) for _, check in checks),
        return_exceptions=True,
    )
    okay = True
    for (name, _), result in zip(checks, results, strict=True):
        if isinstance(result, BaseException):
            # Exception messages may contain DSNs or credentials; emit only the type.
            print(f"{name}: FAIL ({type(result).__name__})")
            okay = False
        else:
            print(f"{name}: OK (read-only connectivity)")
    return okay


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["doctor"])
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--connections", action="store_true", help="Read-only database checks")
    args = parser.parse_args()
    try:
        values = read_environment(args.env_file)
    except ValueError as error:
        parser.exit(1, f"Configuration: FAIL ({error})\n")
    for distribution, module in DEPENDENCIES.items():
        importlib.import_module(module)
        print(f"{distribution}: {version(distribution)}")
    print(f"Configuration: OK ({len(values)} keys; credential values hidden)")
    print("Retrieval: scaffold only; two-path fusion is not implemented")
    if args.connections and not asyncio.run(check_connections(values)):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
