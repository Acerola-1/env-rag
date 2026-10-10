"""Unified enumeration result contract (task 3.5).

One result shape for every enumeration kind. Semantics are strictly separated:

- ``confirmed``   — structure trust in a scope's boundaries (catalog-level)
- ``partial``     — a *link* or relation is incomplete (e.g. continuation
  without its own number)
- ``complete``    — the ANSWER covered exactly the requested target range,
  read all its members (processed == total), and every item carries a
  verifiable citation. complete never means "no parse misses in the original
  PDF" nor "no semantic recall gaps".

Failures (stale, budget exhausted, missing fragment, unresolved span,
ambiguous column, model failure) surface as ``coverage_status`` != complete
with ``fail_stage`` and ``warnings`` filled — never silently truncated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class FailStage:
    NONE = ""
    STALE = "stale"
    BUDGET = "budget_exhausted"
    MISSING_FRAGMENT = "missing_fragment"
    UNRESOLVED_SPAN = "unresolved_span"
    AMBIGUOUS = "ambiguous"
    MODEL = "model_failure"
    SNAPSHOT = "snapshot_mismatch"


VALID_COVERAGE = {"complete", "partial", "ambiguous", "stale"}


@dataclass
class EnumResult:
    query_id: str
    kind: str  # table | prose | document
    workspace: str
    catalog_snapshot_id: str
    source_snapshot_id: str
    scope_ids: list[str] = field(default_factory=list)
    members_total: int = 0
    members_processed: int = 0
    items: list[dict] = field(default_factory=list)
    coverage_status: str = "partial"
    warnings: list[str] = field(default_factory=list)
    fail_stage: str = FailStage.NONE
    predicate: str | None = None  # document enumeration match predicate
    read_token: str | None = None  # doc-set pagination token (content hash)
    model_calls: list[dict] = field(default_factory=list)  # actual LLM requests (prose)
    read_status: str = (
        ""  # reading-layer status (complete/partial/...), separated from answer coverage
    )

    def validate(self) -> None:
        if self.coverage_status not in VALID_COVERAGE:
            raise ValueError(f"invalid coverage_status {self.coverage_status!r}")
        if self.members_processed > self.members_total:
            raise ValueError("members_processed cannot exceed members_total")
        if self.coverage_status == "complete":
            if self.members_processed != self.members_total:
                raise ValueError(
                    "complete requires members_processed == members_total "
                    f"({self.members_processed}/{self.members_total})"
                )
            if self.fail_stage not in (FailStage.NONE, ""):
                raise ValueError("complete cannot carry a fail_stage")
            if self.kind in ("prose", "table") and not self.items and self.members_total > 0:
                # G4: zero items over a non-empty scope is never a complete
                # answer; warning strings cannot authorize it. Only a真正 verified
                # empty set (members_total == 0) may be complete.
                raise ValueError(
                    "complete prose/table with zero items over a non-empty scope is "
                    "not a valid empty set; answer extraction is pending or failed"
                )
            for it in self.items:
                cit = it.get("citation")
                if not isinstance(cit, dict) or not cit:
                    raise ValueError("complete requires every item to carry a citation object")
                if it.get("citation_verified") is not True:
                    # E6: missing/None/other values are NOT accepted as verified
                    raise ValueError(
                        "complete requires every item to have citation_verified explicitly True"
                    )
                for req in ("snapshot_id", "doc_id", "workspace"):
                    if not cit.get(req):
                        # R6: present-but-empty values are as useless as absent ones
                        raise ValueError(
                            f"complete citation must bind a non-empty {req} for independent re-read"
                        )
                if not self.catalog_snapshot_id or not self.workspace:
                    raise ValueError("complete result must identify its snapshots and workspace")
        if self.fail_stage == FailStage.STALE and self.coverage_status != "stale":
            raise ValueError("stale fail_stage must set coverage_status=stale")

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "kind": self.kind,
            "workspace": self.workspace,
            "catalog_snapshot_id": self.catalog_snapshot_id,
            "source_snapshot_id": self.source_snapshot_id,
            "scope_ids": self.scope_ids,
            "members_total": self.members_total,
            "members_processed": self.members_processed,
            "items": self.items,
            "coverage_status": self.coverage_status,
            "warnings": self.warnings,
            "fail_stage": self.fail_stage,
            "predicate": self.predicate,
            "read_token": self.read_token,
            "model_calls": self.model_calls,
            "read_status": self.read_status,
        }
