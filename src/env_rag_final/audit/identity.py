"""Hash and identity semantics for the audited corpus.

All formulas below were verified against the live database and installed
lightrag-hku 1.5.7 source; see audit.md identity-contract section. The audit
re-derives each hash from the local parsed artifacts on every run.
"""

from __future__ import annotations

import hashlib
import json
import urllib.parse
from pathlib import Path

from env_rag_final.paths import PARSED_ROOT


def doc_id_for(file_name: str) -> str:
    """doc_full.id == "doc-" + md5(file_path). file_path equals doc_name here."""
    return "doc-" + hashlib.md5(file_name.encode()).hexdigest()


def merged_blocks_text(blocks_lines: list[str]) -> str:
    """Reproduce lightrag sidecar writer merge: rendered blocks joined by blank line."""
    parts = []
    for line in blocks_lines:
        b = json.loads(line)
        if b.get("type") == "content":
            parts.append(b.get("content") or "")
    return "\n\n".join(p for p in parts if p.strip())


def document_hash(blocks_lines: list[str]) -> str:
    """blocks meta.document_hash == "sha256:" + sha256(merged rendered text)."""
    return "sha256:" + hashlib.sha256(merged_blocks_text(blocks_lines).encode()).hexdigest()


def normalize_merged_text_for_hash(text: str) -> str:
    """Mirror lightrag.utils_pipeline.normalize_merged_text_for_hash (1.5.7).

    Reimplemented locally (no LightRAG storage instantiation); exact regexes
    copied from the installed wheel so hashes match stored values. The
    normalization replaces filename-derived id prefixes with ``-<DOC>-`` and
    asset paths with ``<ASSETS>/`` so sidecar-rendered bodies dedupe.
    """
    import re

    text = re.sub(r"\b(tb|im|eq)-[0-9a-f]{32}-(\d{4})\b", r"\1-<DOC>-\2", text)
    text = re.sub(r'(?<=path=")[^"]*\.blocks\.assets/', "<ASSETS>/", text)
    return text


def content_hash(blocks_lines: list[str]) -> str:
    """doc_full.content_hash == md5(normalize_merged_text_for_hash(merged text))."""
    return hashlib.md5(
        normalize_merged_text_for_hash(merged_blocks_text(blocks_lines)).encode()
    ).hexdigest()


def sidecar_path_to_dir(sidecar_location: str | None) -> Path | None:
    """doc_full.sidecar_location is a file:// URL percent-encoding the parsed dir."""
    if not sidecar_location or not sidecar_location.startswith("file://"):
        return None
    raw = urllib.parse.unquote(sidecar_location.removeprefix("file://"))
    path = Path(raw)
    if path.suffix == ".jsonl":  # direct blocks file
        return path.parent
    return path


def blocks_lines_for(doc_name: str, sidecar_location: str | None) -> list[str] | None:
    """Read *.blocks.jsonl lines from the parsed dir; None when unavailable."""
    # Snapshot URIs may retain the old export host's absolute path. Resolve
    # by stable document filename INSIDE this project's corpus, never by
    # following that external path or falling back to a sibling checkout.
    directory = PARSED_ROOT / f"{doc_name}.parsed"
    if not directory.exists():
        return None
    candidates = sorted(directory.glob("*.blocks.jsonl"))
    if not candidates:
        return None
    return candidates[0].read_text().splitlines()
