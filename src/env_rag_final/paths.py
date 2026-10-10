"""Project-owned data locations; no implicit dependency on another checkout."""

from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    if override := os.environ.get("ENV_RAG_PROJECT_ROOT"):
        return Path(override).expanduser().resolve()
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file() and (candidate / "src/env_rag_final").is_dir():
            return candidate
    return Path.cwd().resolve()


PROJECT_ROOT = project_root()
DATASET_ROOT = Path(os.environ.get("ENV_RAG_DATA_DIR", PROJECT_ROOT / "datasets")).expanduser()
if not DATASET_ROOT.is_absolute():
    DATASET_ROOT = PROJECT_ROOT / DATASET_ROOT
PARSED_ROOT = Path(
    os.environ.get("ENV_RAG_PARSED_ROOT", DATASET_ROOT / "corpus/parsed")
).expanduser()
if not PARSED_ROOT.is_absolute():
    PARSED_ROOT = PROJECT_ROOT / PARSED_ROOT
GOLD_PATH = DATASET_ROOT / "evaluation/gold-approved.json"

# Use verified bundled tokenization data before any automatic network download.
_tokenizer_cache = DATASET_ROOT / "runtime/tokenizers"
if _tokenizer_cache.is_dir():
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(_tokenizer_cache))
