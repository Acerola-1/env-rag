"""Frozen source-classification manifest for workspace ingestion.

Every corpus PDF is inventoried with its byte identity, parsed-artifact
identity, logical-document identity, duplicate relations and the target
workspace the importer must use.  Bare ``分片-*`` shards carry no
air/water prefix, so their workspace is decided from content evidence
(domain terms plus the best-matching parent document by shingle overlap);
unprovable items are reported as ``unresolved`` instead of guessed.

The module is deliberately pure: it reads the corpus and the parsed
sidecars, and optionally a read-only PG snapshot of already-ingested doc
identities.  It never writes to the database.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from env_rag_final.audit import identity

MANIFEST_FORMAT = "workspace-access/corpus-manifest-r1"

# Domain lexicons used only for shard classification evidence.  A shard is
# assigned a workspace only when one side wins clearly; ties stay unresolved.
AIR_TERMS = (
    "环境空气质量",
    "大气污染物",
    "空气质量标准",
    "臭氧",
    "PM2.5",
    "PM10",
    "细颗粒物",
    "氮氧化物",
    "挥发性有机物",
    "空气质量指数",
    "AQI",
    "ambient air",
    "air quality",
    "particulate matter",
    "nonattainment",
    "NAAQS",
    "attainment",
    "GB 3095",
    "GB 18352",
    "GB 4915",
    "GB 13223",
    "轻型汽车污染物排放限值",
    "emission standard",
)
WATER_TERMS = (
    "水污染物",
    "水环境质量",
    "地表水",
    "生活饮用水",
    "污水",
    "废水",
    "排污",
    "水质标准",
    "流域",
    "水功能区",
    "农田灌溉水",
    "地下水",
    "water quality",
    "waste discharge",
    "TMDL",
    "effluent",
    "storm water",
    "stormwater",
    "wastewater",
    "basin plan",
    "regional water quality control board",
    "NPDES",
    "receiving water",
    "drinking water",
    "GB 3838",
    "GB 5084",
    "GB 8978",
    "GB 18466",
)

_PREFIX_RE = re.compile(r"^(air|water)-")
_SHARD_RE = re.compile(r"^分片-(\d+)_(\d+)-(\d+)")
# Standard/regulation identifiers that tie a fragment to its parent document,
# e.g. GB18352.6-2016, HJ 2.2-2018, GB5084-2021, Directive-2008-50-EC.
_CODE_RE = re.compile(r"(?:GB|GBT|HJ|DB|NY|SL|CJ|ISO|EN)\s?/?T?\s?\d+(?:[.\-]\d+)*", re.IGNORECASE)
_CODE_MIN_HITS = 5


def _normalize_code(token: str) -> str:
    return re.sub(r"[\s\-—]", "", token).upper()


def _codes_in_file_name(file_name: str) -> set[str]:
    """Standard codes carried by a corpus file name (``GB18352.6-2016`` -> ``GB18352.6``)."""
    stem = file_name.removesuffix(".pdf")
    stem = re.sub(r"_001$", "", stem)
    codes = set()
    for m in _CODE_RE.finditer(stem):
        raw = _normalize_code(m.group(0))
        # Drop the trailing year so ``GB18352.6-2016`` and ``GB18352.6—2016`` match.
        codes.add(re.sub(r"\d{4}$", "", raw))
    return {c for c in codes if len(c) >= 5}


@dataclass
class DocEntry:
    file_name: str
    relative_path: str
    size_bytes: int
    sha256: str
    has_parsed: bool
    doc_id: str | None = None
    document_hash: str | None = None
    content_hash: str | None = None
    blocks: int = 0
    merged_chars: int = 0
    parsed_dir: str | None = None
    mineru_raw_dir: str | None = None
    parsed_files: list[str] = field(default_factory=list)
    in_default_pg: bool = False
    target_workspace: str | None = None
    classification_basis: str = ""
    classification_evidence: dict = field(default_factory=dict)
    duplicate_of: str | None = None
    duplicate_kind: str | None = None
    unresolved: list[str] = field(default_factory=list)

    def as_row(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _read_blocks(parsed_dir: Path) -> tuple[dict | None, list[str]]:
    candidates = sorted(parsed_dir.glob("*.blocks.jsonl"))
    if not candidates:
        return None, []
    lines = candidates[0].read_text(encoding="utf-8").splitlines()
    if not lines:
        return None, []
    try:
        meta = json.loads(lines[0])
    except json.JSONDecodeError:
        return None, lines
    return meta, lines


def _shingles(text: str, n: int = 12) -> set[str]:
    compact = re.sub(r"\s+", "", text)
    if len(compact) < n:
        return {compact} if compact else set()
    return {compact[i : i + n] for i in range(0, len(compact) - n + 1, 3)}


def _load_domain_text(entry: DocEntry, root: Path) -> str:
    if not entry.parsed_dir:
        return ""
    meta, lines = _read_blocks(root / entry.parsed_dir)
    if not lines:
        return ""
    return identity.merged_blocks_text(lines)


def build_manifest(
    parsed_root: Path,
    *,
    default_pg_doc_ids: set[str] | None = None,
) -> list[DocEntry]:
    """Inventory every PDF under ``parsed_root`` and classify it."""

    pdfs = sorted(p for p in parsed_root.glob("*.pdf"))
    entries: list[DocEntry] = []
    by_sha: dict[str, list[str]] = defaultdict(list)

    for pdf in pdfs:
        rel = pdf.name
        entry = DocEntry(
            file_name=pdf.name,
            relative_path=rel,
            size_bytes=pdf.stat().st_size,
            sha256=_sha256_file(pdf),
            has_parsed=False,
        )
        parsed_dir = parsed_root / f"{pdf.name}.parsed"
        raw_dir = parsed_root / f"{pdf.name}.mineru_raw"
        if parsed_dir.is_dir():
            entry.has_parsed = True
            entry.parsed_dir = parsed_dir.name
            entry.parsed_files = sorted(
                str(p.relative_to(parsed_root)) for p in parsed_dir.rglob("*") if p.is_file()
            )
            meta, lines = _read_blocks(parsed_dir)
            if meta:
                entry.doc_id = meta.get("doc_id")
                entry.document_hash = meta.get("document_hash")
                try:
                    entry.blocks = int(meta.get("blocks") or 0)
                except (TypeError, ValueError):
                    entry.blocks = 0
            if lines:
                entry.content_hash = identity.content_hash(lines)
                entry.merged_chars = len(identity.merged_blocks_text(lines))
        if raw_dir.is_dir():
            entry.mineru_raw_dir = raw_dir.name
        if entry.doc_id is None:
            # Fall back to the path-derived identity used by the pipeline.
            entry.doc_id = identity.doc_id_for(pdf.name)
        entries.append(entry)
        by_sha[entry.sha256].append(entry.file_name)

    index = {e.file_name: e for e in entries}

    # Byte-identical duplicates (the ``_001`` copies) point at the kept original.
    for sha, names in by_sha.items():
        if len(names) < 2:
            continue
        kept = min(names, key=len)
        for name in names:
            if name == kept:
                continue
            e = index[name]
            e.duplicate_of = kept
            e.duplicate_kind = "byte-identical"

    # Content-identical duplicates across different files.
    by_content: dict[str, list[str]] = defaultdict(list)
    for e in entries:
        if e.content_hash and not e.duplicate_of:
            by_content[e.content_hash].append(e.file_name)
    for _hash, names in by_content.items():
        if len(names) < 2:
            continue
        kept = sorted(names, key=len)[0]
        for name in names:
            if name == kept:
                continue
            e = index[name]
            e.duplicate_of = kept
            e.duplicate_kind = "content-identical"

    # Default-workspace membership (frozen audit snapshot).
    if default_pg_doc_ids is not None:
        for e in entries:
            e.in_default_pg = bool(e.doc_id and e.doc_id in default_pg_doc_ids)

    # Domain texts for overlap evidence.
    texts = {e.file_name: _load_domain_text(e, parsed_root) for e in entries}
    air_refs = {n: _shingles(t) for n, t in texts.items() if n.startswith("air-") and t}
    water_refs = {n: _shingles(t) for n, t in texts.items() if n.startswith("water-") and t}

    # Standard-code index over the prefixed (domain-known) documents, so a bare
    # fragment that quotes ``GB18352.6`` can be tied to its parent regulation.
    code_index: dict[str, list[str]] = defaultdict(list)
    for e in entries:
        if not _PREFIX_RE.match(e.file_name):
            continue
        for code in _codes_in_file_name(e.file_name):
            code_index[code].append(e.file_name)

    for e in entries:
        if m := _PREFIX_RE.match(e.file_name):
            e.target_workspace = m.group(1)
            e.classification_basis = "filename-prefix"
            continue
        if not _SHARD_RE.match(e.file_name):
            e.unresolved.append("no air/water prefix and not a recognised shard")
            continue
        text = texts.get(e.file_name) or ""
        e.classification_evidence = _classify_shard(
            e, text, air_refs, water_refs, code_index, index
        )
        decision = e.classification_evidence.get("decision")
        if decision in ("air", "water"):
            e.target_workspace = decision
            e.classification_basis = e.classification_evidence.get("basis", "content-evidence")
        else:
            e.unresolved.append("shard domain not provable from content evidence")

    for e in entries:
        if e.duplicate_of and e.target_workspace is None:
            src = index[e.duplicate_of]
            e.target_workspace = src.target_workspace
            e.classification_basis = f"duplicate-of:{e.duplicate_of}"

    return entries


def _count_code(text_compact: str, code: str) -> int:
    """Occurrences of a standard code, tolerating the ``GB 18352`` short form."""
    hits = text_compact.count(code)
    if "." in code:
        hits = max(hits, text_compact.count(code.split(".", 1)[0]))
    return hits


def _classify_shard(
    entry: DocEntry,
    text: str,
    air_refs: dict[str, set[str]],
    water_refs: dict[str, set[str]],
    code_index: dict[str, list[str]] | None = None,
    index: dict[str, DocEntry] | None = None,
) -> dict:
    compact = re.sub(r"\s+", "", text)
    shingles = _shingles(text)
    term_hits = {
        "air": sum(1 for t in AIR_TERMS if t in text),
        "water": sum(1 for t in WATER_TERMS if t in text),
    }

    # Strongest evidence first: the fragment quotes a regulation code that only
    # one domain-known parent document carries.
    code_evidence: dict = {}
    parent_via_code = None
    if code_index and index:
        best_code, best_hits, best_parents = None, 0, []
        for code, parents in code_index.items():
            hits = _count_code(compact, code)
            if hits >= _CODE_MIN_HITS and hits > best_hits:
                best_code, best_hits, best_parents = code, hits, parents
        if best_code:
            best_parents = sorted(best_parents, key=len)
            parent_via_code = best_parents[0]
            code_evidence = {
                "code": best_code,
                "hits": best_hits,
                "parent_candidates": best_parents,
            }

    def best_overlap(refs: dict[str, set[str]]) -> tuple[str | None, float]:
        best_name, best_ratio = None, 0.0
        for name, ref in refs.items():
            if not ref or not shingles:
                continue
            inter = len(shingles & ref)
            if not inter:
                continue
            ratio = inter / max(1, min(len(shingles), len(ref)))
            if ratio > best_ratio:
                best_name, best_ratio = name, ratio
        return best_name, round(best_ratio, 4)

    air_parent, air_ratio = best_overlap(air_refs)
    water_parent, water_ratio = best_overlap(water_refs)

    decision = "unresolved"
    basis = ""
    reason: list[str] = []
    if parent_via_code and index:
        parent_ws = index[parent_via_code].target_workspace
        if parent_ws in ("air", "water"):
            decision = parent_ws
            basis = "parent-regulation-code"
            reason.append(f"parent-code:{code_evidence['code']}")
    if decision == "unresolved" and (air_ratio >= 0.35 or water_ratio >= 0.35):
        if air_ratio >= water_ratio + 0.05:
            decision, basis = "air", "parent-overlap"
            reason.append("parent-overlap-air")
        elif water_ratio >= air_ratio + 0.05:
            decision, basis = "water", "parent-overlap"
            reason.append("parent-overlap-water")
    if decision == "unresolved":
        # Fall back to domain lexicon only when one side dominates.
        if term_hits["air"] >= 3 and term_hits["air"] >= 2 * max(1, term_hits["water"]):
            decision, basis = "air", "domain-terms"
            reason.append("domain-terms-air")
        elif term_hits["water"] >= 3 and term_hits["water"] >= 2 * max(1, term_hits["air"]):
            decision, basis = "water", "domain-terms"
            reason.append("domain-terms-water")

    return {
        "decision": decision,
        "basis": basis,
        "reason": reason,
        "term_hits": term_hits,
        "code": code_evidence,
        "air_parent": air_parent,
        "air_overlap": air_ratio,
        "water_parent": water_parent,
        "water_overlap": water_ratio,
        "title": _title_of(text),
    }


def _title_of(text: str) -> str:
    for line in text.splitlines():
        stripped = re.sub(r"^#+\s*", "", line).strip()
        if stripped:
            return stripped[:120]
    return ""


def summarize(entries: list[DocEntry]) -> dict:
    by_ws = defaultdict(int)
    logical_by_ws = defaultdict(int)
    for e in entries:
        by_ws[e.target_workspace or "unresolved"] += 1
        if e.duplicate_of is None:
            logical_by_ws[e.target_workspace or "unresolved"] += 1
    duplicates = [e for e in entries if e.duplicate_of]
    return {
        "format": MANIFEST_FORMAT,
        "total_pdfs": len(entries),
        "with_parsed": sum(1 for e in entries if e.has_parsed),
        "in_default_pg": sum(1 for e in entries if e.in_default_pg),
        "by_workspace": dict(sorted(by_ws.items())),
        "logical_docs": sum(logical_by_ws.values()),
        "logical_by_workspace": dict(sorted(logical_by_ws.items())),
        "duplicates": len(duplicates),
        "duplicate_kinds": dict(
            sorted(
                (k, sum(1 for e in duplicates if e.duplicate_kind == k))
                for k in {e.duplicate_kind for e in duplicates}
            )
        ),
        "unresolved": [e.file_name for e in entries if e.unresolved],
        "air": sorted(e.file_name for e in entries if e.target_workspace == "air"),
        "water": sorted(e.file_name for e in entries if e.target_workspace == "water"),
    }
