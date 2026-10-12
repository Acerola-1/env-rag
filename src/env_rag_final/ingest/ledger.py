"""Durable, resumable ingestion ledger.

One append-only JSONL event log per run directory.  The current state of a
document is the last event for its idempotency key::

    key = (workspace, doc_name, source_sha256, recipe_id, models_id)

Semantics:

* ``begin``     written **before** the pipeline is touched.  A ``begin`` with
  no terminal event means the process died while work was in flight — the
  document is ``uncertain`` and must be reconciled against the live
  workspace before it is either accepted or retried.  We never claim
  exactly-once for an external model.
* ``done``      the document is processed and verified in the target workspace.
* ``duplicate`` the same content already exists in this workspace; the event
  points at the verified prior success.
* ``skipped``   byte/content duplicate of another manifest entry.
* ``failed``    terminal failure with the real error.

The log is append-only and flushed after every event, so an interrupted run
loses at most the in-flight document.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

LEDGER_FORMAT = "workspace-access/ingest-ledger-r1"

TERMINAL_STATES = {"done", "duplicate", "skipped", "failed"}


def models_id(models: dict) -> str:
    payload = json.dumps(models, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


@dataclass
class DocKey:
    workspace: str
    doc_name: str
    source_sha256: str
    recipe_id: str
    models: str

    @property
    def tuple(self) -> tuple[str, str, str, str, str]:
        return (
            self.workspace,
            self.doc_name,
            self.source_sha256,
            self.recipe_id,
            self.models,
        )

    def as_dict(self) -> dict:
        return {
            "workspace": self.workspace,
            "doc_name": self.doc_name,
            "source_sha256": self.source_sha256,
            "recipe_id": self.recipe_id,
            "models": self.models,
        }


@dataclass
class DocState:
    key: DocKey
    state: str = "new"
    events: list[dict] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    error: str | None = None

    @property
    def settled(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def needs_reconcile(self) -> bool:
        return self.state == "in-flight"


class Ledger:
    """Append-only ingestion event log with a derived current-state view."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._states: dict[tuple, DocState] = {}
        self._replay()

    # ---- persistence --------------------------------------------------
    def _replay(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self._apply(event)

    def _apply(self, event: dict) -> None:
        key = DocKey(
            workspace=event["workspace"],
            doc_name=event["doc_name"],
            source_sha256=event["source_sha256"],
            recipe_id=event["recipe_id"],
            models=event["models"],
        )
        state = self._states.setdefault(key.tuple, DocState(key=key))
        state.events.append(event)
        kind = event.get("event")
        if kind == "begin":
            state.state = "in-flight"
        elif kind in TERMINAL_STATES:
            state.state = kind
            state.evidence = event.get("evidence") or {}
            state.error = event.get("error")
        else:  # pragma: no cover - unknown event types are kept verbatim
            state.state = kind or state.state

    def append(self, key: DocKey, event: str, **payload) -> dict:
        record = {
            "format": LEDGER_FORMAT,
            "event": event,
            "at": round(time.time(), 3),
            "pid": os.getpid(),
            **key.as_dict(),
            **payload,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        self._apply(record)
        return record

    # ---- queries ------------------------------------------------------
    def state(self, key: DocKey) -> DocState | None:
        return self._states.get(key.tuple)

    def events(self, event: str) -> list[dict]:
        return [e for e in self._all_events() if e.get("event") == event]

    def _all_events(self) -> list[dict]:
        out: list[dict] = []
        for state in self._states.values():
            out.extend(state.events)
        out.sort(key=lambda e: e.get("at", 0))
        return out

    def counts(self) -> dict:
        tally: dict[str, int] = {}
        for state in self._states.values():
            tally[state.state] = tally.get(state.state, 0) + 1
        return dict(sorted(tally.items()))

    def model_dispatches(self) -> dict:
        """Aggregate the real (non-cached) model calls recorded per document."""
        totals: dict[str, int] = {}
        for event in self.events("done"):
            for name, value in (event.get("evidence", {}).get("dispatches") or {}).items():
                totals[name] = totals.get(name, 0) + int(value)
        return totals
