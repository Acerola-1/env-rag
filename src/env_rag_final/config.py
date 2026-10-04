"""Load the copied LightRAG environment without exposing credential values."""

from pathlib import Path

from dotenv import dotenv_values

REQUIRED = (
    "LLM_BINDING_HOST",
    "LLM_BINDING_API_KEY",
    "LLM_MODEL",
    "EMBEDDING_BINDING_HOST",
    "EMBEDDING_BINDING_API_KEY",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIM",
    "RERANK_BINDING_HOST",
    "RERANK_BINDING_API_KEY",
    "RERANK_MODEL",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DATABASE",
    "QDRANT_URL",
    "NEO4J_URI",
    "NEO4J_USERNAME",
    "NEO4J_PASSWORD",
)


def read_environment(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise ValueError(f"Environment file not found: {path}")
    values = {key: value for key, value in dotenv_values(path).items() if value is not None}
    missing = [key for key in REQUIRED if not values.get(key)]
    if missing:
        raise ValueError("Missing environment keys: " + ", ".join(missing))
    for key in ("POSTGRES_PORT", "EMBEDDING_DIM"):
        try:
            number = int(values[key])
        except ValueError:
            raise ValueError(f"{key} must be an integer") from None
        if number <= 0:
            raise ValueError(f"{key} must be positive")
    return values
