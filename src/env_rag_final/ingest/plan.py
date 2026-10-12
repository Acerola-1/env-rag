"""Per-workspace ingestion planning from the frozen corpus manifest."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkItem:
    doc_name: str
    workspace: str
    sha256: str
    doc_id: str
    content_hash: str | None
    parsed_dir: str | None
    classification_basis: str
    duplicate_of: str | None
    duplicate_kind: str | None
    unresolved: tuple[str, ...]

    @property
    def ingesting(self) -> bool:
        return self.duplicate_of is None and not self.unresolved


def load_manifest(path: Path | str) -> list[WorkItem]:
    items: list[WorkItem] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            items.append(
                WorkItem(
                    doc_name=row["file_name"],
                    workspace=row.get("target_workspace") or "",
                    sha256=row["sha256"],
                    doc_id=row["doc_id"],
                    content_hash=row.get("content_hash"),
                    parsed_dir=row.get("parsed_dir"),
                    classification_basis=row.get("classification_basis", ""),
                    duplicate_of=row.get("duplicate_of"),
                    duplicate_kind=row.get("duplicate_kind"),
                    unresolved=tuple(row.get("unresolved") or ()),
                )
            )
    return items


def plan_for_workspace(
    items: list[WorkItem],
    workspace: str,
    *,
    only: list[str] | None = None,
    limit: int | None = None,
    extra_docs: list[str] | None = None,
) -> dict:
    """Split the manifest into what this workspace ingests vs. records as duplicate.

    ``extra_docs`` names real documents this workspace also holds even though the
    manifest files them under another domain.  They are the explicitly
    configured shared copies used to prove that the same material may live in
    two libraries without either overwriting the other.
    """
    ingest: list[WorkItem] = []
    duplicates: list[WorkItem] = []
    excluded: list[WorkItem] = []
    extra = set(extra_docs or ())

    for item in items:
        if item.workspace != workspace and item.doc_name not in extra:
            continue
        if only and item.doc_name not in only:
            continue
        if item.unresolved:
            excluded.append(item)
            continue
        if item.duplicate_of:
            duplicates.append(item)
            continue
        if not item.parsed_dir:
            excluded.append(item)
            continue
        ingest.append(item)

    if limit is not None:
        ingest = ingest[:limit]
    return {
        "workspace": workspace,
        "ingest": ingest,
        "duplicates": duplicates,
        "excluded": excluded,
        "shared": sorted(i.doc_name for i in ingest if i.doc_name in extra),
    }


def duplicate_targets(items: list[WorkItem]) -> dict[str, WorkItem]:
    return {i.doc_name: i for i in items}
