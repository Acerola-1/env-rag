"""Phase 4 evaluation entry (task 6.1): fixed-sample cold-generation comparison.

One owning entry drives local / PG-only / fusion paths over the frozen
41-question set (31 positives + 10 counters) and records, per question per
path, the actual candidates, rerank stage, scope expansion, the SAME
downstream generation contract (accepted ``answer`` entry), timings and a
per-service call ledger.

Budgets are enforced at the REAL I/O boundary BEFORE requests:

* ``BudgetedServiceBoundary`` subclasses the documented ``ServiceBoundary``
  and reserves every ``boundary.call`` (embedding batch texts/chars included,
  positional OR keyword);
* ``BudgetedQdrantClient`` / ``BudgetedNeo4jDriver`` subclass the native
  recording wrappers, which otherwise execute I/O and only record afterwards
  — reservation happens before the inner call, refusal issues ZERO calls;
  the Neo4j gate covers BOTH production forms: the direct
  ``driver.session().run(...)`` proxy session AND the session object yielded
  by ``async with driver.session()`` (entered-session runs go through the
  same gate exactly once; ``__aenter__``/``__aexit__`` ownership is kept);
* ``_BudgetedConnection`` wraps EVERY PG connection used inside a leg — the
  one handed to the answer entry AND self-made ones. ``asyncpg.connect`` is
  patched for the duration of each budgeted scope, so the answer entry's own
  connection (the real CLI form: no conn is passed), SourceAdapter full-text
  read-back, and the fusion/rerank source+guard reads all count their data
  SQL. Establishment/close and transaction-control statements
  (BEGIN/COMMIT via ``conn.transaction``, ``SET LOCAL`` via ``conn.execute``)
  are not billed — audited: no data SQL flows through ``execute`` in the
  read-only eval code paths. ``local_adapter._fetch`` reads are intentionally
  DOUBLE-counted (its ``boundary.call("pg")`` group reservation plus the
  per-statement wrapper) — conservative over-accounting, never under;
* reservations are NOT the bill. ``issued`` advances only at the real I/O
  attempt (right before the inner call runs, so an executed-then-failed call
  still counts) — a model answer that skips HTTP on incomplete conditions
  reports zero issued; ``answer_llm`` issuance is reconciled from the entry's
  REAL receipt (``model_calls_used``, read from the answer runtime even on
  the exception path);
* refusals cannot be swallowed into a clean complete: the orchestration
  checks this question's refusal-event DELTA after every stage — discovery
  and answer — so a release helper that catches ``BudgetExhausted`` and
  falls back (the VECTOR→WEIGHT path) still marks the leg
  ``budget_failure`` / partial instead of consuming further quota.

The three path runners use the ACTUAL adapter objects: local candidates are
full-text read back through the production ``SourceAdapter`` (a content head
is never treated as the content), and the fusion path really runs one joint
rerank and feeds its fresh report forward. ``expected_status`` from gold is
recorded for post-hoc scoring only and NEVER decides routing; counter
questions reach the same answer contract through the evaluation adapter
(``category_overrides`` / ``expand_budgets`` seams, default-None preserved).

Failures terminate honestly: run-level drift, capture errors (ANY exception
from the post capture included — terminal written before re-raising, with
results, the live ledger snapshot, the original error and the post error
side by side) and pre-guard refusals write a sanitized failure terminal
(results kept, no ``finished_at``) and then raise; a source/config refusal
is run-level — it terminates the evaluation instead of consuming later
questions' quotas — and the CLI exits non-zero. Offline dry-run compiles the
selected-set execution matrix and code-derived budget upper bounds with zero
backend access; the CLI's real mode requires the COMPLETE frozen Phase 4
anchor (``validate_phase4_anchor``: identity, approved model/endpoint class/
dimension, prompt SHA, code anchors, parameter budgets, env guards) BEFORE
any dispatch — a missing or corrupt anchor never reaches the entry.
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .answer import AdapterError
from .answer import run_answer as _run_answer
from .catalog import source as _source_module
from .fusion import run_fusion as _run_fusion
from .local_adapter import (
    LocalCandidateAdapter,
    ServiceBoundary,
    _RecordingNeo4jDriver,
    _RecordingQdrantClient,
)
from .rerank import _sanitize_evidence
from .rerank import run_rerank as _run_rerank

GOLD_PATH = Path("reports/pg-retrieval/gate-2/review-r5/gold-approved.json")
CONFIG_ANCHOR = Path("reports/pg-retrieval/phase-4/phase-4-config-anchor.json")
PATHS = ("pg", "local", "fusion")

# Routing categories for counter examples: the gold counter entries carry no
# category field, but the answer contract needs one. Fed to the accepted
# answer entry through the category_overrides seam (E4) so the REAL entry
# renders by type — never a label that bypasses the contract.
COUNTER_CATEGORIES = {
    "neg-001": "fact",
    "neg-002": "fact",
    "neg-003": "file_enum",
    "neg-004": "table_enum",
    "neg-005": "table_enum",
    "neg-006": "fact",
    "neg-007": "table_enum",
    "neg-008": "prose_enum",
    "neg-009": "file_enum",
    "neg-010": "synthesis",
}

# Explicit per-counter preconditions. A natural-language problem statement is
# NOT a precondition. neg-008's constructed micro budget really reaches the
# prose reader through expand_budgets -> prose_budget -> read_prose_scope
# (max_members / max_chars); neg-002's isolation is evidenced from the ACTUAL
# workspace values observed on the produced candidates, not asserted.
# Attribution labels reflect the ACTUAL resources of a leg (see
# ``_leg_attribution``): the formal source access of a production run stays
# the production read-only entry — a constructed budget on the question does
# NOT turn it into an isolated fixture. Only legs whose discovery source/entry
# really is a test-injected fake are labelled ``isolated_fixture``.
COUNTER_PRECONDITIONS = {
    "neg-008": {
        "kind": "enum_member_budget",
        "execution_attribution": "production_readonly_with_constructed_budget",
        "attribution_note": "constructed micro budget (max_members=1/max_chars=120) "
        "reaches the real prose reader via expand_budgets -> prose_budget -> "
        "read_prose_scope; source access itself remains the production read-only "
        "entry. Legs that run on an injected fake discovery source are separately "
        "labelled isolated_fixture.",
        "expand_budget": {"max_members": 1, "max_chars": 120},
    },
    "neg-002": {
        "kind": "cross_workspace_isolation",
        "execution_attribution": "real_entry",
        "attribution_note": "this leg OBSERVES the workspaces of the candidates it "
        "actually produced; observing no foreign workspace is NOT an adversarial "
        "same-id cross-workspace proof — that rejection is unit-verified with a "
        "fixture source in tests/test_evaluation.py "
        "(test_local_rejects_foreign_workspace_and_unverified).",
    },
}


class BudgetExhausted(AdapterError):
    """Raised BEFORE a request would exceed a configured budget cap."""


_SPEC_KEYS = {
    "max_texts_per_embed_call",
    "max_chars_per_embed_call",
    "per_question",
    "round_caps",
    "total_caps",
}

# R3 (schema BEFORE any identity/backend contact): every cap must be a
# non-negative int (0 legally forbids issuing; None would silently UNBIND the
# dimension and is refused; bool is not an int here), and every service name
# must be one the ledger actually gates.
_SERVICES = ("llm", "embedding", "qdrant", "neo4j", "pg", "rerank", "answer_llm")
_ENVELOPE_SERVICES = ("llm", "embedding", "qdrant", "neo4j", "pg")


def _check_cap(where: str, value) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AdapterError(
            f"invalid budget cap {where}={value!r}: must be a non-negative integer "
            "(None/unbounded and bool are refused)"
        )
    if value < 0:
        raise AdapterError(f"invalid budget cap {where}={value!r}: negative values refused")


def _check_cap_dict(name: str, value) -> None:
    if not isinstance(value, dict):
        raise AdapterError(f"budget section {name} must be an object of service -> int cap")
    for service, cap in value.items():
        if service not in _SERVICES:
            raise AdapterError(
                f"unknown service {service!r} in budget section {name} "
                f"(gated services: {list(_SERVICES)})"
            )
        _check_cap(f"{name}.{service}", cap)


def _check_scalar(name: str, value) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AdapterError(
            f"invalid budget limit {name}={value!r}: must be a positive integer "
            "(batch limits of 0 would make every embedding call unissuable)"
        )


@dataclass
class BudgetSpec:
    """Configurable, pre-call enforced caps. ``per_question`` envelopes bound
    one question-path execution; ``round_caps`` / ``total_caps`` bound a round
    / the whole evaluation; the embed per-call limits bound a SINGLE batch by
    texts and chars. Enforced in code before the request, never extrapolated
    from historical samples."""

    max_texts_per_embed_call: int = 32
    max_chars_per_embed_call: int = 64_000
    per_question: dict = field(
        default_factory=lambda: {
            "llm": 1,
            "embedding": 4,
            "qdrant": 8,
            "neo4j": 10,
            "pg": 24,
        }
    )
    round_caps: dict = field(
        default_factory=lambda: {
            "llm": 82,
            "embedding": 328,
            "qdrant": 656,
            "neo4j": 820,
            "pg": 1968,
            "rerank": 41,
            "answer_llm": 21,
        }
    )
    total_caps: dict = field(
        default_factory=lambda: {
            "llm": 164,
            "embedding": 656,
            "qdrant": 1312,
            "neo4j": 1640,
            "pg": 3936,
            "rerank": 82,
            "answer_llm": 42,
        }
    )

    @classmethod
    def from_dict(cls, data: dict | None) -> "BudgetSpec":
        """Strict pre-request schema: refused BEFORE any identity capture or
        backend contact — an invalid/None/negative/bool cap or an unknown
        service never reaches the ledger (R3)."""
        if data is None:
            return cls()
        if not isinstance(data, dict):
            raise AdapterError("budget configuration must be a JSON object")
        for key, value in data.items():
            if key not in _SPEC_KEYS:
                raise AdapterError(
                    f"unknown budget key {key!r} (schema validation before any call)"
                )
            if key in ("max_texts_per_embed_call", "max_chars_per_embed_call"):
                _check_scalar(key, value)
            else:
                _check_cap_dict(key, value)
        spec = cls()
        for key, value in data.items():
            current = getattr(spec, key)
            if isinstance(current, dict) and isinstance(value, dict):
                setattr(spec, key, {**current, **value})
            else:
                setattr(spec, key, value)
        missing = [s for s in _ENVELOPE_SERVICES if s not in spec.per_question]
        if missing:
            raise AdapterError(
                f"per_question envelope must cover every gated discovery service; missing {missing}"
            )
        return spec


class BudgetLedger:
    """RESERVATIONS and ACTUAL ISSUED calls are two separate accounts.

    ``reserve`` runs BEFORE the request (caps enforced pre-request, envelopes
    consumed conservatively); a refusal issues zero calls. ``issued`` is only
    advanced by ``mark_issued`` at the moment the wrapper REALLY enters the
    inner I/O call — so a call that executed and then failed still counts,
    while a model answer that skipped HTTP on incomplete conditions reports
    zero issued (R2). Reservations may conservatively occupy an envelope but
    are never the bill."""

    def __init__(self, spec: BudgetSpec, round_no: int = 1):
        self.spec = spec
        self.round_no = round_no
        self.reserved_total: dict[str, int] = {}
        self.reserved_round: dict[str, int] = {}
        self.issued_total: dict[str, int] = {}
        self.question_used: dict[str, dict[str, int]] = {}
        # per-leg state that must survive an exception (e.g. rerank issuance
        # reconciliation published by _fusion_path before re-raising)
        self.annotations: dict[str, dict] = {}
        self.events: list[dict] = []

    def begin_question(self, where: str) -> None:
        self.question_used[where] = {}

    def end_question(self, where: str) -> None:
        self.question_used.pop(where, None)

    def check_question_envelope(self, service: str, amount: int, where: str) -> None:
        cap = self.spec.per_question.get(service)
        if cap is None:
            return
        used = 0
        for entry in self.question_used.values():
            used = max(used, entry.get(service, 0))
        if used + amount > cap:
            self._refuse(service, amount, where, f"per-question envelope {cap} reached ({used})")

    def reserve(self, service: str, amount: int, where: str) -> None:
        cap_t = self.spec.total_caps.get(service)
        cap_r = self.spec.round_caps.get(service)
        used_t = self.reserved_total.get(service, 0)
        used_r = self.reserved_round.get(service, 0)
        if cap_t is not None and used_t + amount > cap_t:
            self._refuse(service, amount, where, f"total cap {cap_t} reached ({used_t})")
        if cap_r is not None and used_r + amount > cap_r:
            self._refuse(service, amount, where, f"round cap {cap_r} reached ({used_r})")
        self.reserved_total[service] = used_t + amount
        self.reserved_round[service] = used_r + amount
        for entry in self.question_used.values():
            entry[service] = entry.get(service, 0) + amount
        self.events.append(
            {
                "kind": "reserved",
                "service": service,
                "amount": amount,
                "where": where,
            }
        )

    def mark_issued(self, service: str, amount: int, where: str) -> None:
        """The real-call receipt: called by the wrappers at the moment the
        inner I/O is entered (an executed-then-failed call still counts)."""
        self.issued_total[service] = self.issued_total.get(service, 0) + amount
        self.events.append(
            {
                "kind": "issued",
                "service": service,
                "amount": amount,
                "where": where,
            }
        )

    def annotate(self, where: str, key: str, value) -> None:
        """Per-leg state an inner seam must publish even when the exception
        path swallows its return value (e.g. the rerank issuance status of a
        FAILED fusion leg)."""
        self.annotations.setdefault(where, {})[key] = value

    def take_annotations(self, where: str) -> dict:
        return self.annotations.pop(where, {})

    def question_refusals(self, where: str) -> int:
        return sum(
            1
            for e in self.events
            if e["kind"] == "budget_refusal"
            and (e["where"] == where or str(e["where"]).startswith(f"{where}:"))
        )

    def last_refusal(self, where: str) -> dict | None:
        for e in reversed(self.events):
            if e["kind"] == "budget_refusal" and (
                e["where"] == where or str(e["where"]).startswith(f"{where}:")
            ):
                return e
        return None

    def override_question_envelope(self, service: str, cap: int) -> None:
        self.spec.per_question = {**self.spec.per_question, service: cap}

    def restore_envelope(self, per_question: dict) -> None:
        self.spec.per_question = dict(per_question)

    def _refuse(self, service: str, amount: int, where: str, reason: str) -> None:
        self.events.append(
            {
                "kind": "budget_refusal",
                "service": service,
                "amount": amount,
                "where": where,
                "reason": reason,
                "issued": 0,
            }
        )
        raise BudgetExhausted(
            f"budget refused {service} x{amount} at {where}: {reason} (zero calls issued)"
        )

    def snapshot(self) -> dict:
        return {
            "reserved_total": dict(self.reserved_total),
            "issued_total": dict(self.issued_total),
            "reserved_round": dict(self.reserved_round),
            "refusal_count": sum(1 for e in self.events if e["kind"] == "budget_refusal"),
            "events": self.events,
            "caps": {
                "round": dict(self.spec.round_caps),
                "total": dict(self.spec.total_caps),
                "per_question": dict(self.spec.per_question),
                "max_texts_per_embed_call": self.spec.max_texts_per_embed_call,
                "max_chars_per_embed_call": self.spec.max_chars_per_embed_call,
            },
        }


_ACTIVE_BUDGET: contextvars.ContextVar[tuple[BudgetLedger, str] | None] = contextvars.ContextVar(
    "eval_active_budget", default=None
)


def _embed_texts(args: tuple, kwargs: dict) -> list:
    """Batch content of an embedding call, positional OR keyword — the
    release openai_embed accepts both shapes."""
    for arg in args:
        if isinstance(arg, list) and arg and all(isinstance(t, str) for t in arg):
            return arg
    value = kwargs.get("texts")
    if isinstance(value, list) and value and all(isinstance(t, str) for t in value):
        return value
    return []


class BudgetedServiceBoundary(ServiceBoundary):
    """Reserves from the active ledger before every ``call``; embedding batch
    caps (texts/chars) are checked against the ACTUAL request shape."""

    def __init__(self) -> None:
        super().__init__()
        active = _ACTIVE_BUDGET.get()
        self._ledger: BudgetLedger | None = active[0] if active else None
        self._where = active[1] if active else "unscoped"

    async def call(self, service: str, operation: str, fn, *args, **kwargs):
        ledger = self._ledger
        if ledger is None:
            return await super().call(service, operation, fn, *args, **kwargs)
        where = f"{self._where}:{operation}"
        if service == "embedding":
            texts = _embed_texts(args, kwargs)
            if len(texts) > ledger.spec.max_texts_per_embed_call:
                ledger._refuse(
                    service,
                    len(texts),
                    where,
                    f"single batch of {len(texts)} texts exceeds per-call cap "
                    f"{ledger.spec.max_texts_per_embed_call}",
                )
            total_chars = sum(len(t) for t in texts)
            if total_chars > ledger.spec.max_chars_per_embed_call:
                ledger._refuse(
                    service,
                    len(texts),
                    where,
                    f"single batch of {total_chars} chars exceeds per-call cap "
                    f"{ledger.spec.max_chars_per_embed_call}",
                )
        ledger.check_question_envelope(service, 1, where)
        ledger.reserve(service, 1, where)
        # the reservation passed: the real call is entered now. ``ServiceBoundary.call``
        # invokes fn immediately; an fn that then fails still counts as issued.
        ledger.mark_issued(service, 1, where)
        return await super().call(service, operation, fn, *args, **kwargs)


class BudgetedQdrantClient(_RecordingQdrantClient):
    """The native wrapper records AFTER the real call — reserve BEFORE it, and
    issue only when the native call is actually entered."""

    def _reserve(self, operation: str) -> str | None:
        ledger = getattr(self._boundary, "_ledger", None)
        if ledger is None:
            return None
        where = f"{getattr(self._boundary, '_where', 'unscoped')}:{operation}"
        ledger.check_question_envelope("qdrant", 1, where)
        ledger.reserve("qdrant", 1, where)
        return where

    def _recorded(self, operation: str, fn):
        base = super()._recorded(operation, fn)

        def guarded(*args, **kwargs):
            where = self._reserve(operation)  # raises BudgetExhausted on refusal
            if where is not None:
                # passing the gate means the native call runs NOW (a failure
                # inside it is an executed call, still issued)
                self._boundary._ledger.mark_issued("qdrant", 1, where)
            return base(*args, **kwargs)

        return guarded


class _BudgetedNeo4jSession:
    """Budget gate for BOTH production forms of the recording session: the
    direct ``driver.session().run(...)`` and the ``async with`` path, whose
    entered session object (returned by ``__aenter__``) previously bypassed
    any patch applied to the outer proxy. ``__aenter__``/``__aexit__`` and all
    other attributes delegate to the native recording session — close
    ownership and recording receipts are untouched, each real run gets exactly
    one budget gate + one issued mark."""

    def __init__(self, inner, ledger: BudgetLedger, where: str):
        self._inner = inner
        self._ledger = ledger
        self._where = where

    def _reserve(self) -> None:
        self._ledger.check_question_envelope("neo4j", 1, self._where)
        self._ledger.reserve("neo4j", 1, self._where)

    def run(self, *args, **kwargs):
        self._reserve()
        return self._attempt(*args, **kwargs)

    async def _attempt(self, *args, **kwargs):
        # issued at await time, when the native session.run really executes
        self._ledger.mark_issued("neo4j", 1, self._where)
        return await self._inner.run(*args, **kwargs)

    async def __aenter__(self):
        entered = await self._inner.__aenter__()
        return _BudgetedNeo4jSession(entered, self._ledger, self._where)

    async def __aexit__(self, *exc):
        return await self._inner.__aexit__(*exc)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class BudgetedNeo4jDriver(_RecordingNeo4jDriver):
    """Same gate for the async Neo4j driver — covering the entered session."""

    def session(self, *args, **kwargs):
        raw = super().session(*args, **kwargs)
        ledger = getattr(self._boundary, "_ledger", None)
        if ledger is None:
            return raw
        where = f"{getattr(self._boundary, '_where', 'unscoped')}:session.run"
        return _BudgetedNeo4jSession(raw, ledger, where)


@contextlib.contextmanager
def budgeted_local_boundary(ledger: BudgetLedger, where: str):
    """Scoped installation of the budgeted boundary, the budgeted native
    wrappers AND the budgeted PG connection seam for one question-path
    execution. ``LocalCandidateAdapter.fetch`` constructs a fresh
    ``ServiceBoundary`` per fetch, so replacing the module attributes for the
    duration of the leg is the injection point that does not modify accepted
    source.

    ``asyncpg.connect`` is wrapped for the same duration: every SELF-MADE
    connection opened inside the leg — the answer entry's own connection (the
    real CLI form never passes one), the SourceAdapter full-text read-back,
    the fusion/rerank source+guard reads, local_adapter's provenance reads —
    is returned as a ``_BudgetedConnection`` whose data SQL is reserved
    before it runs. Connection establishment itself stays unbilled; the
    wrapper passes ``close``/timeout/transaction/readonly semantics through
    to the code path that owns the connection. Restored in ``finally``."""
    import asyncpg as _asyncpg

    import env_rag_final.local_adapter as la_module

    token = _ACTIVE_BUDGET.set((ledger, where))
    originals = (
        la_module.ServiceBoundary,
        la_module._RecordingQdrantClient,
        la_module._RecordingNeo4jDriver,
    )
    orig_connect = _asyncpg.connect

    async def _budgeted_connect(*args, **kwargs):
        conn = await orig_connect(*args, **kwargs)
        active = _ACTIVE_BUDGET.get()
        if active is None:
            return conn
        leg_ledger, leg_where = active
        return _BudgetedConnection(conn, leg_ledger, leg_where)

    la_module.ServiceBoundary = BudgetedServiceBoundary
    la_module._RecordingQdrantClient = BudgetedQdrantClient
    la_module._RecordingNeo4jDriver = BudgetedNeo4jDriver
    _asyncpg.connect = _budgeted_connect
    try:
        yield
    finally:
        _asyncpg.connect = orig_connect
        (
            la_module.ServiceBoundary,
            la_module._RecordingQdrantClient,
            la_module._RecordingNeo4jDriver,
        ) = originals
        _ACTIVE_BUDGET.reset(token)


class _BudgetedConnection:
    """Wraps EVERY PG connection used inside a leg — the one handed to the
    answer entry AND self-made ones opened through the leg-scoped
    ``asyncpg.connect`` seam (E2: PG statements inside the accepted answer
    entry are budgeted too; so are fusion/rerank/SourceAdapter/local_adapter
    reads).

    Billing contract, stated as the code actually behaves: data SQL is
    reserved+issued at the ``fetch``/``fetchrow``/``fetchval`` seam.
    ``execute`` passes through UNbilled — audited, the read-only evaluation
    code paths use it only for ``SET LOCAL statement_timeout`` (catalog
    source guard) and transaction control; build/migrate/index paths that
    could smuggle data through ``execute`` are outside the Phase 4 read-only
    boundary and never run here. ``conn.transaction(...)`` likewise yields
    the inner transaction (BEGIN/COMMIT unbilled); ``close`` and every other
    attribute delegate to the owner. local_adapter._fetch reads land in both
    accounts (its boundary group call AND this wrapper) — deliberate
    conservative double-counting, declared in the run report."""

    def __init__(self, inner, ledger: BudgetLedger, where: str):
        self._inner = inner
        self._ledger = ledger
        self._where = where

    async def _guard(self) -> None:
        where = f"{self._where}:pg"
        self._ledger.check_question_envelope("pg", 1, where)
        self._ledger.reserve("pg", 1, where)
        # the gate passed: the statement executes now (an error inside it is
        # an executed call, still issued — never rewritten to zero)
        self._ledger.mark_issued("pg", 1, where)

    async def fetch(self, *args, **kwargs):
        await self._guard()
        return await self._inner.fetch(*args, **kwargs)

    async def fetchrow(self, *args, **kwargs):
        await self._guard()
        return await self._inner.fetchrow(*args, **kwargs)

    async def fetchval(self, *args, **kwargs):
        await self._guard()
        return await self._inner.fetchval(*args, **kwargs)

    async def close(self):
        return await self._inner.close()

    def __getattr__(self, name):
        return getattr(self._inner, name)


# ---------------------------------------------------------------------------
# Gold loading, selection validation and the execution matrix
# ---------------------------------------------------------------------------


def _file_sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_gold_set(gold_path: Path = GOLD_PATH) -> dict:
    data = json.loads(Path(gold_path).read_text(encoding="utf-8"))
    positives = [
        {
            "query_id": q["query_id"],
            "category": q["category"],
            "question": q["question"],
            "workspace": q.get("workspace") or "default",
            "is_counter": False,
            "expected_status": None,
            "precondition": {},
        }
        for q in data["questions"]
    ]
    counters = [
        {
            "query_id": c["counter_id"],
            "category": COUNTER_CATEGORIES[c["counter_id"]],
            "question": c["question"],
            "workspace": "default",
            "is_counter": True,
            "expected_status": c.get("expected_status"),
            "precondition": COUNTER_PRECONDITIONS.get(c["counter_id"], {}),
        }
        for c in data.get("counter_examples", [])
    ]
    return {"positives": positives, "counters": counters, "sha256": _file_sha(gold_path)}


def validate_selection(
    questions: list[dict], query_ids: list[str] | None, paths: list[str]
) -> list[dict]:
    """ZERO-touch input validation BEFORE any backend contact (E6): unknown
    query ids or unknown paths fail with no identity capture."""
    for p in paths:
        if p not in PATHS:
            raise AdapterError(f"unknown evaluation path {p!r} (allowed: {list(PATHS)})")
    if not paths:
        raise AdapterError("evaluation needs at least one path")
    if query_ids is None:
        return questions
    known = {q["query_id"] for q in questions}
    unknown = [q for q in query_ids if q not in known]
    if unknown:
        raise AdapterError(f"unknown-query-id (rejected before any backend read): {unknown}")
    wanted = set(query_ids)
    return [q for q in questions if q["query_id"] in wanted]


def build_execution_matrix(
    gold_sha: str, questions: list[dict], rounds: list[int], paths: list[str]
) -> dict:
    rows = []
    for round_no in rounds:
        for q in questions:
            for path in paths:
                rows.append(
                    {
                        "round": round_no,
                        "path": path,
                        "query_id": q["query_id"],
                        "category": q["category"],
                        "is_counter": q["is_counter"],
                        # recorded for POST-HOC scoring only — never routing
                        "expected_status": q["expected_status"],
                        "answer_model_budget": 1 if q["category"] == "synthesis" else 0,
                    }
                )
    return {
        "gold_sha256": gold_sha,
        "rounds": rounds,
        "paths": paths,
        "rows": rows,
        "total_executions": len(rows),
        "denominators": {
            "positive_executions": sum(1 for r in rows if not r["is_counter"]),
            "counter_executions": sum(1 for r in rows if r["is_counter"]),
            "note": "positive quality and counter behaviour are reported SEPARATELY; "
            "never merged into one recall/exact score",
        },
    }


def derive_budget_bounds(matrix: dict, spec: BudgetSpec) -> dict:
    """Upper bounds compiled from the ACTUAL selected matrix rows and the
    configured envelopes/caps — per-row, not history-extrapolated; the final
    number is the real constraint (min of envelope sum and total cap)."""
    rows = matrix["rows"]
    local_legs = sum(1 for r in rows if r["path"] in ("local", "fusion"))
    fusion_legs = sum(1 for r in rows if r["path"] == "fusion")
    all_legs = len(rows)
    synth = sum(1 for r in rows if r["answer_model_budget"] == 1 and not r["is_counter"])
    synth_counter = sum(1 for r in rows if r["answer_model_budget"] == 1 and r["is_counter"])

    def _bounded(service: str, envelope_sum: int) -> dict:
        cap = spec.total_caps.get(service)
        return {
            "envelope_bound": envelope_sum,
            "total_cap": cap,
            "effective_bound": envelope_sum if cap is None else min(envelope_sum, cap),
        }

    return {
        "note": "compiled from the frozen matrix rows x configured envelopes; "
        "enforced pre-request by the budget ledger (refusal issues zero calls). "
        "REAL-boundary compilation: the per-question pg envelope now spans every "
        "guarded data SQL inside the leg — discovery helpers, the answer entry "
        "AND its self-made connection, SourceAdapter full-text read-back, "
        "fusion/rerank guard reads (two envelopes per row: discovery + answer); "
        "establishment/close and transaction-control statements are declared "
        "unbilled in the run report's budget_coverage_declaration; reservations "
        "are the pre-request gate, issued_total is the real-call bill",
        "path_executions": all_legs,
        "local_or_fusion_legs": local_legs,
        "services": {
            "llm": _bounded("llm", local_legs * spec.per_question.get("llm", 0)),
            "embedding": _bounded("embedding", local_legs * spec.per_question.get("embedding", 0)),
            "qdrant": _bounded("qdrant", local_legs * spec.per_question.get("qdrant", 0)),
            "neo4j": _bounded("neo4j", local_legs * spec.per_question.get("neo4j", 0)),
            # pg covers EVERY leg's discovery AND the answer entry's
            # guard/scope/source-read statements: two envelopes per row
            "pg": _bounded("pg", all_legs * spec.per_question.get("pg", 0) * 2),
            "rerank": _bounded("rerank", fusion_legs),
            "answer_llm": _bounded("answer_llm", synth + synth_counter),
        },
        "embedding_max_texts_per_call": spec.max_texts_per_embed_call,
        "embedding_max_chars_per_call": spec.max_chars_per_embed_call,
        "answer_llm_calls_positives": synth,
        "answer_llm_calls_counter_cap": synth_counter,
        "answer_llm_note": "reserved ONLY for synthesis-category rows and only "
        "with explicit authorization; refusal means the answer entry runs "
        "read-only (allow_model=False), never a hidden call",
    }


# ---------------------------------------------------------------------------
# Path runners — actual adapters over the accepted entries
# ---------------------------------------------------------------------------


def _fused_result_from_report(report: dict, qid: str) -> dict:
    return next(r for r in report.get("results") or [] if r.get("query_id") == qid)


async def _pg_path(q, values, conn, ledger, qdir, local_adapter_factory=None) -> dict:
    """PG-only discovery via the accepted fusion entry (0 model calls), its
    OWN runtime directory per question (E5: no shared-path overwrite)."""
    started = time.monotonic()
    report = await _run_fusion(
        qdir / "fusion",
        [q["query_id"]],
        pg_only=True,
    )
    result = _fused_result_from_report(report, q["query_id"])
    return {
        "fused_result": result,
        "rerank_report": None,
        "discovery_status": result.get("status"),
        "usable": len(result.get("usable") or []),
        "latency_ms": int((time.monotonic() - started) * 1000),
        "receipts": {},
    }


def _candidate_fields(cand) -> dict:
    """ALL actual provenance of a candidate (R4): every source path it was
    really reached through, its selection order and source type are carried
    over as-is — never discarded, never replaced by a guessed vector score."""
    if isinstance(cand, dict):
        return dict(cand)
    return {
        "chunk_id": getattr(cand, "chunk_id", None),
        "workspace": getattr(cand, "workspace", None),
        "doc_id": getattr(cand, "full_doc_id", None),
        "file_path": getattr(cand, "file_path", None),
        "verified": getattr(cand, "verified", False),
        "verify_error": getattr(cand, "verify_error", None),
        "content_head": getattr(cand, "content_head", None),
        "content_len": getattr(cand, "content_len", None),
        "reached_via": list(getattr(cand, "reached_via", None) or []),
        "similarity_order": getattr(cand, "similarity_order", None),
        "source_type": getattr(cand, "source_type", None),
    }


def _dsn_from(values: dict) -> dict:
    return {
        "host": values["POSTGRES_HOST"],
        "port": int(values["POSTGRES_PORT"]),
        "user": values["POSTGRES_USER"],
        "password": values["POSTGRES_PASSWORD"],
        "database": values["POSTGRES_DATABASE"],
    }


async def _read_back_full_content(values: dict, workspace: str, chunk_id: str) -> str | None:
    """FULL production text via the accepted read-only source adapter — a
    content head is never treated as the content (E1)."""
    adapter = _source_module.SourceAdapter(_dsn_from(values))
    row = await adapter.get_chunk(workspace, chunk_id)
    return (row or {}).get("content")


async def _local_path(q, values, conn, ledger, qdir, local_adapter_factory=None) -> dict:
    """Real local candidates via the accepted adapter under the budgeted
    boundary; each candidate is full-text read back through the production
    SourceAdapter. Candidates are NEVER filled from PG discovery or gold;
    unverified or foreign-workspace candidates are refused and recorded."""
    factory = local_adapter_factory or (lambda v, ws, led: LocalCandidateAdapter(v, ws))
    adapter = factory(values, q["workspace"], ledger)
    started = time.monotonic()
    local_result = await adapter.fetch(
        q["question"],
        query_id=q["query_id"],
        frozen_gold_sha=None,
    )
    usable: list[dict] = []
    refused: list[dict] = []
    for cand in getattr(local_result, "candidates", None) or []:
        f = _candidate_fields(cand)
        if f.get("workspace") != q["workspace"]:
            refused.append(
                {
                    "chunk_id": f.get("chunk_id"),
                    "reason": "workspace does not match the question workspace "
                    "(cross-workspace evidence rejected)",
                }
            )
            continue
        if not f.get("verified"):
            refused.append(
                {"chunk_id": f.get("chunk_id"), "reason": "candidate not source-verified"}
            )
            continue
        full = await _read_back_full_content(values, f["workspace"], f["chunk_id"])
        if full is None:
            refused.append(
                {
                    "chunk_id": f.get("chunk_id"),
                    "reason": "production read-back returned no content",
                }
            )
            continue
        usable.append(
            {
                "workspace": f["workspace"],
                "chunk_id": f["chunk_id"],
                "doc_id": f.get("doc_id"),
                "file_path": f.get("file_path"),
                "verified": True,
                "content_sha256": hashlib.sha256(full.encode("utf-8")).hexdigest(),
                "content_len": len(full),
                "content": full,
                "paths": [
                    {
                        # R4: ACTUAL provenance, not a label — the candidate's
                        # own source type, every source path it was reached
                        # through and its real selection order. ``score``
                        # stays None: the candidate contract carries no float
                        # vector score, and none is fabricated here (PG-side
                        # score semantics are that path's own, not unified).
                        "path": "local",
                        "workspace": f["workspace"],
                        "chunk_id": f["chunk_id"],
                        "doc_id": f.get("doc_id"),
                        "file_path": f.get("file_path"),
                        "discovery": f.get("source_type") or "unspecified",
                        "score": None,
                        "similarity_order": f.get("similarity_order"),
                        "reached_via": list(f.get("reached_via") or []),
                    }
                ],
            }
        )
    fused = _synthesized_fused_result(q, usable, path_label="local")
    return {
        "fused_result": fused,
        "rerank_report": None,
        "discovery_status": fused["status"],
        "usable": len(usable),
        "latency_ms": int((time.monotonic() - started) * 1000),
        "receipts": {
            "call_records": list(getattr(local_result, "call_records", None) or []),
            "service_calls": dict(getattr(local_result, "service_calls", None) or {}),
            "degraded": list(getattr(local_result, "degraded", None) or []),
            # actual selection-basis markers (e.g. chunk_pick weight-fallback /
            # truncation-fallback / vector-similarity), carried verbatim
            "sorting_sources": dict(getattr(local_result, "sorting_sources", None) or {}),
            "refused_candidates": refused,
        },
    }


def _synthesized_fused_result(q, usable: list[dict], path_label: str) -> dict:
    """Fused-replay shape for the local path (improvement-2, discovery isolation).

    Discovery NEVER promotes to targets: every usable candidate, its own path
    provenance, service receipts and the full discovery document list are kept
    for audit, but ``typed_targets``/``targets_resolved`` stay EMPTY — this
    layer has only DISCOVERED documents. Target identity is confirmed later by
    the answer-layer canonical-code gate against the catalog's documents rows.
    An empty discovery only proves THIS path found nothing (status=missing with
    discovery_only provenance), never a verified absence from the whole corpus
    — that distinction is recorded, not papered over.
    """
    docs: list[str] = []
    for u in usable:
        if u["doc_id"] and u["doc_id"] not in docs:
            docs.append(u["doc_id"])
    return {
        "query_id": q["query_id"],
        "query": q["question"],
        "workspace": q["workspace"],
        "pg": {
            "status": "ok" if usable else "missing",
            "search_id": "",
            "catalog_snapshot_id": "",
            "source_snapshot_id": "",
            "discovery_total": len(usable),
        },
        "targets_resolved": [],
        "typed_targets": [],
        "discovery_docs": docs,
        "targets_confirmed": False,
        "path_provenance": {
            "path": path_label,
            "discovery_only": True,
            "note": "this layer performs discovery only; target identity is "
            "confirmed by the answer-layer canonical-code gate against catalog "
            "documents rows — not a 5.3 code resolution and never a corpus-wide verdict",
        },
        "usable": usable,
        "status": "ok" if usable else "missing",
        "degraded": [],
        "budget": {"limit": 40, "kept": len(usable), "truncated": []},
    }


def _rerank_http_entry(item) -> bool | None:
    """Rerank call receipt of one result entry (S1): a ``call`` dict means an
    HTTP request was entered (success, non-2xx or timeout alike — executed
    failures are never zeroed); ``call: None`` with the key present is the
    entry's own proof of a BEFORE-HTTP skip/refusal (bills 0); a missing
    receipt is unknown — never guessed either way."""
    if not isinstance(item, dict) or "call" not in item:
        return None
    return isinstance(item.get("call"), dict)


# Guard stages the rerank entry runs BEFORE any per-question HTTP: a failure
# recorded there is an explicit pre-request refusal for the whole run (zero
# for this question too). Any OTHER failure without a receipt for THIS
# question proves nothing about this question — explicitly unknown.
# (names taken verbatim from run_rerank's failure terminals: the unified
# zero-contact pre-flight boundary, the identity guards before any per-query
# HTTP, and the unknown-query-id rejection — all provably call-zero)
_RERANK_PRE_HTTP_STAGES = frozenset(
    {
        "pre-flight",
        "pre-flight-parse",
        "pre-flight-read",
        "identity-capture",
        "identity-before",
        "unknown-query-id",
    }
)


def _rerank_exception_issuance(qdir: Path, qid: str) -> str:
    """Exception path (S1 r4): reconcile from THIS question's own receipt
    only, returning ``executed`` / ``before-http-zero`` / ``unknown-no-receipt``.

    The in-flight ``failure_service_records`` block is attributed ONLY when
    its ``query_id`` IS this question — a foreign question's call never
    counts here; and the runtime merely existing with some failure is NOT
    proof this question stopped before HTTP (that stays unknown, never a
    claimed zero). No readable runtime at all is also unknown."""
    runtime_path = qdir / "rerank" / "rerank-runtime-latest.json"
    try:
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — no readable receipt: unknown, never a claim
        return "unknown-no-receipt"
    for entry in runtime.get("results") or []:
        if entry.get("query_id") == qid:
            verdict = _rerank_http_entry(entry)
            if verdict is True:
                return "executed"
            if verdict is False:
                return "before-http-zero"
    records = runtime.get("failure_service_records") or {}
    if records.get("query_id") == qid:
        for record in records.get("call_records") or []:
            if isinstance(record, dict) and record.get("service") == "rerank":
                return "executed"
    stage = (runtime.get("failure") or {}).get("stage")
    if isinstance(stage, str) and stage in _RERANK_PRE_HTTP_STAGES:
        return "before-http-zero"
    return "unknown-no-receipt"


async def _fusion_path(q, values, conn, ledger, qdir, local_adapter_factory=None) -> dict:
    """Accepted two-path fusion AND the ACTUAL joint rerank stage (E1): one
    rerank call reserved before the accepted entry runs, its fresh report
    taken from the returned runtime and fed into the answer stage.

    Issuance (S1) is the REAL HTTP receipt, never the entry run: the reserve
    keeps the pre-request gate, but ``mark_issued`` fires only when the
    entry's call receipt shows a request actually entered — an executed
    401/5xx/timeout still counts; a pre-HTTP gold/config/identity/source
    refusal or skip bills zero; an unreadable receipt stays explicitly
    unknown (no mark, no assumption). On the exception path the three-state
    result is published to the owning entry through the ledger, so the
    FAILED leg record and terminal still carry ``rerank_issuance`` while the
    original error propagates unchanged."""
    started = time.monotonic()
    report = await _run_fusion(
        qdir / "fusion",
        [q["query_id"]],
        pg_only=False,
    )
    result = _fused_result_from_report(report, q["query_id"])
    rerank_return = None
    rerank_latency = None
    rerank_issuance = None
    if (result.get("usable") or []) and (result.get("status") or "") not in ("missing", "stale"):
        # the event location keeps the LEG's where prefix so the per-stage
        # refusal-delta check in run_evaluation sees a rerank refusal too
        active = _ACTIVE_BUDGET.get()
        where = f"{active[1]}:rerank" if active else f"{q['query_id']}:rerank"
        ledger.check_question_envelope("rerank", 1, where)
        ledger.reserve("rerank", 1, where)
        t0 = time.monotonic()
        try:
            rerank_return = await _run_rerank(
                qdir / "rerank",
                [q["query_id"]],
                fused_report_path=qdir / "fusion" / "fusion-runtime-latest.json",
            )
        except Exception:
            # reconcile issuance from this qid's OWN receipt, publish the
            # state to the owning entry (the failed leg must carry
            # rerank_issuance in the terminal too), then re-raise the
            # ORIGINAL error unchanged
            status = _rerank_exception_issuance(qdir, q["query_id"])
            if status == "executed":
                ledger.mark_issued("rerank", 1, where)
            if active is not None:
                ledger.annotate(active[1], "rerank_issuance", status)
            raise
        rerank_latency = int((time.monotonic() - t0) * 1000)
        verdict = _rerank_http_entry(
            next(
                (
                    e
                    for e in (rerank_return.get("results") or [])
                    if e.get("query_id") == q["query_id"]
                ),
                None,
            )
        )
        if verdict is True:
            ledger.mark_issued("rerank", 1, where)
            rerank_issuance = "executed"
        elif verdict is False:
            rerank_issuance = "before-http-zero"
        else:
            rerank_issuance = "unknown-no-receipt"
    return {
        "fused_result": result,
        "rerank_report": rerank_return,
        "rerank_latency_ms": rerank_latency,
        "rerank_issuance": rerank_issuance,
        "discovery_status": result.get("status"),
        "usable": len(result.get("usable") or []),
        "latency_ms": int((time.monotonic() - started) * 1000),
        "receipts": {},
    }


PATH_RUNNERS = {"pg": _pg_path, "local": _local_path, "fusion": _fusion_path}
# snapshot of the REAL path implementations at import time: a leg whose
# runner object was replaced (test seam) is honestly classified below — the
# classification follows the ACTUAL resources, never a declared label.
_ORIGINAL_PATH_RUNNERS = dict(PATH_RUNNERS)


def _leg_attribution(q: dict, precondition: dict, runner, path: str, local_adapter_factory):
    """Evidence class of one leg from what it ACTUALLY ran on (R4 evidence
    limit): an injected fake source/runner is a fixture; a production leg of
    a constructed-budget counter stays production_readonly_with_constructed_budget."""
    if local_adapter_factory is not None or runner is not _ORIGINAL_PATH_RUNNERS.get(path):
        return (
            "isolated_fixture",
            "this leg ran on an injected fake discovery source/runner (test seam); "
            "it is NOT evidence about production access",
        )
    if q["is_counter"]:
        note = precondition.get("attribution_note")
        return precondition.get("execution_attribution", "real_entry"), note
    return "real_entry", None


# ---------------------------------------------------------------------------
# Identity plumbing
# ---------------------------------------------------------------------------


async def _capture_identity(values: dict) -> dict:
    """Live read-only identity capture resolved THROUGH the answer module at
    call time: one guard implementation, one patch point (tests), one real
    capture in production."""
    from . import answer as answer_module

    return await answer_module._capture_identity(values)


def _flatten_identity(pre: dict) -> dict:
    """One canonical shape (the accepted answer entry's report identity)."""
    inner = pre.get("identity") or pre
    return {
        "matches_frozen": pre.get("matches_frozen", True),
        "problems": pre.get("problems", []),
        "counts": inner.get("public_counts"),
        "source_fingerprint": inner.get("source_fingerprint"),
        "catalog_active": inner.get("catalog_active"),
        "search_active": inner.get("search_active"),
        "gold_sha": inner.get("gold_sha"),
        "env_sha": inner.get("env_sha"),
    }


_IDENTITY_KEYS = (
    "source_fingerprint",
    "catalog_active",
    "search_active",
    "gold_sha",
    "env_sha",
    "counts",
)


def _identity_problems(expected: dict, live: dict) -> list[str]:
    """Anchor expectation vs live capture. ``expected`` uses the anchor key
    names (env_sha included — config changes count as drift)."""
    problems: list[str] = []
    catalog = live.get("catalog_active") or {}
    live_view = {
        "source_fingerprint": live.get("source_fingerprint"),
        "catalog_run_snapshot": f"{catalog.get('run_id')}/{catalog.get('snapshot_id')}",
        "search_active": live.get("search_active"),
        "gold_sha256": live.get("gold_sha"),
        "env_sha": live.get("env_sha"),
    }
    for key in (
        "source_fingerprint",
        "catalog_run_snapshot",
        "search_active",
        "gold_sha256",
        "env_sha",
    ):
        if key in expected and expected[key] != live_view[key]:
            problems.append(f"{key}: expected {expected[key]!r} != live {live_view[key]!r}")
    return problems


def _capture_drift(before: dict, after: dict) -> list[str]:
    problems: list[str] = []
    for key in _IDENTITY_KEYS:
        if before.get(key) != after.get(key):
            problems.append(
                f"{key} changed between pre and post capture: {before.get(key)!r} -> {after.get(key)!r}"
            )
    if not after.get("matches_frozen", True):
        problems.append(f"post capture reports frozen-contract mismatch: {after.get('problems')}")
    return problems


def _clean_error(exc: Exception, values: dict) -> str:
    """E5: sanitize the FULL message first, truncate after — a truncated
    prefix must never survive as a credential fragment."""
    text = f"{type(exc).__name__}: {exc}"
    safe = _sanitize_evidence(text, values)
    return str(safe)[:400]


# ---------------------------------------------------------------------------
# The complete frozen Phase 4 configuration anchor (CLI real mode, R3)
# ---------------------------------------------------------------------------

_ANCHOR_REQUIRED_IDENTITY = (
    "source_fingerprint",
    "catalog_run_snapshot",
    "search_active",
    "gold_sha256",
)

# S2 completeness schema. These sections/subsections/keys are REQUIRED with
# the right types: an empty or absent section is a completeness violation —
# never an optional skip that would let a run start without code/prompt/
# parameter constraints — and every required value is COMPARED, not only the
# ones that happen to be present. The keyword identity is compared using the
# ACTUAL production resolution (``KEYWORD_LLM_MODEL`` falling back to
# ``LLM_MODEL`` — same expression local_adapter uses): both evaluation rounds
# extract terms with the same model or the comparison is not comparable.
_ANCHOR_REQUIRED_SECTIONS = ("frozen_identity", "model_config", "code_anchors", "frozen_budgets")
_MODEL_REQUIRED_SUBSECTIONS = {
    "answer_query_llm": ("value", "endpoint_class"),
    "keyword_llm": ("value",),
    "embedding": ("value", "dim", "endpoint_class"),
    "rerank": ("value", "endpoint_class"),
}
_REQUIRED_CODE_ANCHORS = (
    "answer.py",
    "rerank.py",
    "fusion.py",
    "local_adapter.py",
    "compat_runtime.py",
    "synthesis_system_prompt_sha256",
)
_REQUIRED_PARAMS = (
    "discovery_top_k",
    "fusion_usable_cap_per_query",
    "rerank_max_inputs",
    "max_answer_model_context_chars",
    "max_answer_model_calls_per_run",
    "answer_temperature",
)
_LIVE_REQUIRED_KEYS = (
    "QUERY_LLM_MODEL",
    "LLM_BINDING_HOST",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIM",
    "EMBEDDING_BINDING_HOST",
    "RERANK_MODEL",
    "RERANK_BINDING_HOST",
)
_SHA64 = re.compile(r"[0-9a-f]{64}")


def _nonempty_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _resolve_keyword_identity(values: dict) -> str | None:
    """Exactly the production resolution order (local_adapter's keyword LLM):
    KEYWORD_LLM_MODEL first, falling back to LLM_MODEL."""
    for key in ("KEYWORD_LLM_MODEL", "LLM_MODEL"):
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _endpoint_host(endpoint_class: str | None) -> str:
    match = re.search(r"://([^/\s),]+)", endpoint_class or "")
    return match.group(1) if match else ""


def validate_phase4_anchor(
    anchor_path: Path | None = None,
    values: dict | None = None,
    gold_path: Path | None = None,
) -> dict:
    """ZERO-backend completeness + fidelity check of the WHOLE approved
    Phase 4 configuration before the CLI dispatches a real evaluation.
    Structure FIRST (sections, model subsections, required code anchors and
    prompt SHA, required parameter budgets, identity fields, types), then
    EVERY required value compared: identity/gold content, the four model
    identities incl. the keyword fallback, endpoint classes, embedding
    dimension, env guards, prompt SHA, code-anchor byte SHAs and parameter
    constants. Missing/corrupt anchor or ANY violation refuses listing all
    problems at once (no silent model switching, no accepted-component edits
    to fit results; empty sections are violations, not opt-outs). ``env_sha``
    drift itself is enforced at run time by the identity capture
    (``matches_frozen`` + post-run re-check). Returns the COMPLETE expected
    identity subset the run must satisfy afterwards."""
    anchor_path = Path(anchor_path or CONFIG_ANCHOR)
    gold_path = Path(gold_path or GOLD_PATH)
    if not anchor_path.exists():
        raise AdapterError(
            f"Phase 4 config anchor missing: {anchor_path} — refusing before any backend contact"
        )
    try:
        anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise AdapterError(f"Phase 4 anchor unreadable/corrupt: {type(exc).__name__}") from exc

    problems: list[str] = []

    # ---- 1. completeness schema (empty/absent sections are violations) ----
    for section in _ANCHOR_REQUIRED_SECTIONS:
        node = anchor.get(section)
        if not isinstance(node, dict) or not node:
            problems.append(
                f"anchor section {section!r} missing/empty — a complete anchor is required"
            )

    frozen = anchor.get("frozen_identity")
    if isinstance(frozen, dict) and frozen:
        for key in _ANCHOR_REQUIRED_IDENTITY + ("gold_file",):
            if not _nonempty_str(frozen.get(key)):
                problems.append(f"anchor.frozen_identity.{key} missing/empty")

    model_cfg = anchor.get("model_config")
    if isinstance(model_cfg, dict) and model_cfg:
        for sub, fields in _MODEL_REQUIRED_SUBSECTIONS.items():
            node = model_cfg.get(sub)
            if not isinstance(node, dict) or not node:
                problems.append(f"anchor.model_config.{sub} missing/empty")
                continue
            for field in fields:
                if field == "dim":
                    dim = node.get("dim")
                    if isinstance(dim, bool) or not isinstance(dim, int) or dim < 1:
                        problems.append(f"anchor.model_config.{sub}.dim must be a positive int")
                elif not _nonempty_str(node.get(field)):
                    problems.append(f"anchor.model_config.{sub}.{field} missing/empty")

    code_anchors = anchor.get("code_anchors")
    if isinstance(code_anchors, dict) and code_anchors:
        for name in _REQUIRED_CODE_ANCHORS:
            value = code_anchors.get(name)
            if not _nonempty_str(value) or not _SHA64.fullmatch(value):
                problems.append(f"anchor.code_anchors.{name} missing/empty/not a sha256 hex")

    params = anchor.get("frozen_budgets")
    if isinstance(params, dict) and params:
        for name in _REQUIRED_PARAMS:
            value = params.get(name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                problems.append(
                    f"anchor.frozen_budgets.{name} missing/invalid (non-negative int required)"
                )

    # ---- 2. gold identity (path + content hash) ----
    if isinstance(frozen, dict):
        declared_gold = frozen.get("gold_file")
        if _nonempty_str(declared_gold) and Path(declared_gold) != gold_path:
            problems.append(
                f"anchor gold_file {declared_gold!r} != evaluated gold path {str(gold_path)!r}"
            )
        if _nonempty_str(frozen.get("gold_sha256")):
            if _file_sha(gold_path) != frozen["gold_sha256"]:
                problems.append(
                    "gold content hash drift: evaluated gold file is not the frozen approved one"
                )

    # ---- 3. live config: required keys present, then compared ----
    if not isinstance(values, dict):
        problems.append("real evaluation needs loaded values for the frozen config check")
    else:
        for key in _LIVE_REQUIRED_KEYS:
            if not _nonempty_str(values.get(key)):
                problems.append(
                    f"live config {key} missing/empty — required for the frozen comparison"
                )
        keyword_resolved = _resolve_keyword_identity(values)
        if keyword_resolved is None:
            problems.append(
                "keyword LLM identity absent (KEYWORD_LLM_MODEL nor LLM_MODEL fallback set): "
                "local/fusion term extraction would run unbound to the frozen configuration"
            )
        mc = model_cfg if isinstance(model_cfg, dict) else {}

        def _compare(label: str, expected, actual) -> None:
            # only compare when the anchor side is valid (already flagged
            # otherwise) and the live side is present (already flagged
            # otherwise) — REQUIRED values are compared, never skipped silently
            if not _nonempty_str(expected) or not _nonempty_str(actual):
                return
            if actual.strip() != expected.strip():
                problems.append(
                    f"{label} drift: live {actual!r} != frozen {expected!r} (no silent switching)"
                )

        answer_cfg = mc.get("answer_query_llm") or {}
        _compare("QUERY_LLM_MODEL", answer_cfg.get("value"), values.get("QUERY_LLM_MODEL"))
        _compare(
            "keyword LLM (KEYWORD_LLM_MODEL/LLM_MODEL fallback)",
            (mc.get("keyword_llm") or {}).get("value"),
            keyword_resolved,
        )
        emb = mc.get("embedding") or {}
        _compare("EMBEDDING_MODEL", emb.get("value"), values.get("EMBEDDING_MODEL"))
        dim = emb.get("dim")
        live_dim = values.get("EMBEDDING_DIM")
        if (
            isinstance(dim, int)
            and not isinstance(dim, bool)
            and _nonempty_str(live_dim)
            and str(live_dim).strip() != str(dim)
        ):
            problems.append(f"EMBEDDING_DIM {live_dim!r} != frozen {dim!r}")
        rk = mc.get("rerank") or {}
        _compare("RERANK_MODEL", rk.get("value"), values.get("RERANK_MODEL"))
        for label, cfg, live_key in (
            ("answer endpoint", answer_cfg, "LLM_BINDING_HOST"),
            ("embedding endpoint", emb, "EMBEDDING_BINDING_HOST"),
            ("rerank endpoint", rk, "RERANK_BINDING_HOST"),
        ):
            host = _endpoint_host(cfg.get("endpoint_class"))
            if host and _nonempty_str(values.get(live_key)) and host not in values[live_key]:
                problems.append(f"{label} class drift: {live_key} lacks {host}")
        # L3 env guards: the forbidden workspace overrides must be unset
        for key in ("QDRANT_WORKSPACE", "NEO4J_WORKSPACE", "POSTGRES_WORKSPACE"):
            if os.environ.get(key, "").strip():
                problems.append(
                    f"env override {key} is set; the production mapping must not be overridden"
                )

    # ---- 4. prompt and code SHAs ----
    if isinstance(code_anchors, dict) and code_anchors:
        expected_prompt_sha = code_anchors.get("synthesis_system_prompt_sha256")
        if _nonempty_str(expected_prompt_sha):
            from .answer import _SYNTH_SYSTEM

            got_prompt_sha = hashlib.sha256(_SYNTH_SYSTEM.encode("utf-8")).hexdigest()
            if got_prompt_sha != expected_prompt_sha:
                problems.append("synthesis prompt sha drift vs the frozen anchor")
        src_root = Path(__file__).parent
        for fname in _REQUIRED_CODE_ANCHORS:
            if not fname.endswith(".py"):
                continue
            sha = code_anchors.get(fname)
            if not _nonempty_str(sha):
                continue  # schema already flagged the missing/invalid entry
            target = src_root / fname
            if not target.exists():
                problems.append(f"code anchor target {fname} missing")
            elif hashlib.sha256(target.read_bytes()).hexdigest() != sha:
                problems.append(
                    f"code anchor drift: {fname} — accepted components must not change for "
                    "evaluation convenience; an approved seam change starts a NEW anchor "
                    "generation explicitly (after 6.1 acceptance), never silently"
                )

    # ---- 5. parameter budgets against the code constants ----
    if isinstance(params, dict) and params:
        from . import answer as answer_module
        from .fusion import FUSION_BUDGET
        from .rerank import RERANK_INPUT_BUDGET
        from .search.query import DEFAULT_TOP_K

        param_checks = (
            ("discovery_top_k", DEFAULT_TOP_K),
            ("fusion_usable_cap_per_query", FUSION_BUDGET),
            ("rerank_max_inputs", RERANK_INPUT_BUDGET),
            ("max_answer_model_context_chars", answer_module.MAX_MODEL_CONTEXT_CHARS),
            ("max_answer_model_calls_per_run", answer_module.MAX_ANSWER_MODEL_CALLS),
        )
        for name, actual in param_checks:
            anchored = params.get(name)
            if isinstance(anchored, int) and not isinstance(anchored, bool) and anchored != actual:
                problems.append(f"parameter drift: {name} anchored {anchored!r} != code {actual!r}")
        # S2 (r4): the anchored ANSWER TEMPERATURE must equal the value the
        # generation payload actually sends. The code-SHA pin alone lets an
        # anchor declare 1 while the frozen literal is 0 — declared vs actual
        # is compared here, at zero backend contact.
        anchored_temp = params.get("answer_temperature")
        if isinstance(anchored_temp, int) and not isinstance(anchored_temp, bool):
            answer_src = (Path(__file__).parent / "answer.py").read_text(encoding="utf-8")
            literals = re.findall(r'"temperature"\s*:\s*([0-9]+)', answer_src)
            if not literals:
                problems.append(
                    "answer_temperature unverifiable: no temperature literal found in the "
                    "synthesis generation payload"
                )
            else:
                actual_temps = sorted({int(value) for value in literals})
                if actual_temps != [anchored_temp]:
                    problems.append(
                        f"answer_temperature drift: anchored {anchored_temp} != actual "
                        f"generation payload temperature {actual_temps}"
                    )

    if problems:
        raise AdapterError(
            "Phase 4 anchor validation failed (zero backend contact): " + "; ".join(problems)
        )
    return {k: frozen[k] for k in _ANCHOR_REQUIRED_IDENTITY if _nonempty_str(frozen.get(k))}


# ---------------------------------------------------------------------------
# The owning entry
# ---------------------------------------------------------------------------


async def run_evaluation(
    report_dir: Path,
    *,
    round_no: int = 1,
    rounds: list[int] | None = None,
    paths: list[str] | None = None,
    query_ids: list[str] | None = None,
    dry_run: bool = False,
    budgets: dict | None = None,
    gold_path: Path = GOLD_PATH,
    conn=None,
    values: dict | None = None,
    transport=None,
    local_adapter_factory: Callable | None = None,
    expected_identity: dict | None = None,
    user_allows_answer_model: bool = False,
) -> dict:
    """Phase 4 owning entry. ``dry_run=True`` compiles the SELECTED-set
    execution matrix and budget upper bounds with zero backend access; the
    real mode runs the three paths per question under pre-call enforced
    budgets with per-question unique artifacts."""
    report_dir = Path(report_dir)
    paths = list(paths) if paths else list(PATHS)
    spec = BudgetSpec.from_dict(budgets)
    if not isinstance(round_no, int) or round_no < 1:
        raise AdapterError(f"invalid round {round_no!r}")
    if rounds is not None and (not rounds or any(not isinstance(r, int) or r < 1 for r in rounds)):
        raise AdapterError(f"invalid rounds {rounds!r}")

    gold_set = load_gold_set(gold_path)
    all_questions = [*gold_set["positives"], *gold_set["counters"]]
    # ZERO-touch validation BEFORE any capture/backend (E6)
    questions = validate_selection(all_questions, query_ids, paths)

    if dry_run:
        matrix_rounds = rounds or [round_no]
        matrix = build_execution_matrix(gold_set["sha256"], questions, matrix_rounds, paths)
        bounds = derive_budget_bounds(matrix, spec)
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "execution-matrix.json").write_text(
            json.dumps(matrix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (report_dir / "budget-upper-bounds.json").write_text(
            json.dumps(bounds, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return {
            "mode": "dry_run",
            "backend_fetches": 0,
            "total_executions": matrix["total_executions"],
            "bounds": bounds,
            "matrix_file": str(report_dir / "execution-matrix.json"),
        }

    if values is None:
        raise AdapterError("evaluation run mode requires values (real orchestration)")
    if (report_dir / "eval-runtime-latest.json").exists():
        raise AdapterError(
            f"{report_dir} already holds a completed evaluation runtime — recovery or "
            "re-runs MUST start a new generation directory with a fresh explicit budget "
            "(cold generation can never replay completed answers)"
        )

    ledger = BudgetLedger(spec, round_no)
    out: dict = {
        "task": f"Phase 4 evaluation round {round_no} (6.1 owning entry)",
        "round": round_no,
        "paths": paths,
        "gold_sha256": gold_set["sha256"],
        "budget_snapshot_start": ledger.snapshot(),
        "results": [],
        "cold_generation_contract": "no old runtime answers read; every answer uses the "
        "context/messages of THIS round's own generation",
        "budget_coverage_declaration": {
            "enforced_pre_request": {
                "service_boundary": "every ServiceBoundary.call (embedding/llm/pg groups, "
                "including local_adapter readonly_select_chunks); embedding batch texts/chars "
                "caps judged on the ACTUAL positional-or-keyword shape",
                "qdrant_native_wrapper": "query_points/retrieve via BudgetedQdrantClient — "
                "reserve before the native call, issued only when it is entered",
                "neo4j_native_wrapper": "BOTH driver.session().run(...) and the async-with "
                "entered session run through _BudgetedNeo4jSession (one gate + one issued mark "
                "per real run; __aenter__/__aexit__ and close ownership delegate unchanged)",
                "pg_data_sql": "fetch/fetchrow/fetchval on the explicit AND on every "
                "self-made connection (asyncpg.connect is scoped-patched per leg: answer's own "
                "connection, SourceAdapter read-back, fusion/rerank guard reads, local_adapter "
                "provenance reads)",
                "rerank_and_answer_model": "reserved before the accepted entries run; "
                "issuance reconciled ONLY from the entries' real HTTP receipts — "
                "answer_llm from model_calls_used (runtime included on the exception "
                "path), rerank from the call receipt of THIS question's result entry "
                "or failure_service_records whose query_id IS this question (a foreign "
                "question's in-flight call never counts; the mere existence of some "
                "failure never proves this question stopped before HTTP; only a named "
                "pre-flight/identity guard stage is an explicit before-http zero; "
                "otherwise unknown) — executed 401/timeout counts, skip/refusal 0, "
                "unknown is explicit and unbilled; the three-state status is published "
                "onto the leg record and terminal even when the leg raises",
            },
            "not_billed": [
                "connection establishment and close (readonly/timeout/server_settings pass "
                "through to the owning code path)",
                "transaction control: BEGIN/COMMIT via conn.transaction and SET LOCAL via "
                "conn.execute — audited to carry no data SQL in the read-only evaluation paths",
                "run-level pre/post identity capture (guard reads outside per-question envelopes)",
                "native client methods not recorded by the accepted wrappers (identical coverage "
                "to the accepted recording contract — declared, not hidden)",
            ],
            "artifact_counts_note": "per-leg pg numbers are envelope usage on the WRAPPED seams "
            "(local_adapter._fetch is deliberately double-accounted: group reservation AND "
            "statement gate — conservative over-accounting, never under); they are NOT a claim "
            "of exhaustive coverage of every historical PG read",
        },
    }

    def _write_terminal() -> None:
        """Single write boundary: the WHOLE report sanitized, then persisted."""
        report_dir.mkdir(parents=True, exist_ok=True)
        safe = _sanitize_evidence(out, values)
        body = json.dumps(safe, ensure_ascii=False, indent=2) + "\n"
        stamp = time.strftime("%Y%m%dT%H%M%S")
        (report_dir / f"eval-runtime-{stamp}.json").write_text(body, encoding="utf-8")
        (report_dir / "eval-runtime-latest.json").write_text(body, encoding="utf-8")

    def _fail_terminal(stage: str, detail) -> None:
        out["failure"] = {"stage": stage, "detail": detail}
        # failures carry the LIVE ledger — the actual budget state at the
        # terminal moment, not a later extrapolation
        out["budget_snapshot_end"] = ledger.snapshot()
        _write_terminal()

    # ---- pre identity guard: capture, frozen flag, expected config ---------
    try:
        pre = _flatten_identity(await _capture_identity(values))
    except AdapterError:
        _fail_terminal("identity-before", "pre-flight identity capture reported refusal")
        raise
    except Exception as exc:  # noqa: BLE001
        _fail_terminal("identity-capture", _clean_error(exc, values))
        raise AdapterError("pre-flight identity capture failed") from exc
    out["identity_before"] = pre
    if not pre["matches_frozen"]:
        _fail_terminal("identity-before", pre["problems"] or "matches_frozen false")
        raise AdapterError(
            "pre-flight identity mismatch (rejected before any question): "
            + "; ".join(pre["problems"] or ["matches_frozen false"])
        )
    if expected_identity:
        problems = _identity_problems(expected_identity, pre)
        if problems:
            _fail_terminal("config-drift", problems)
            raise AdapterError(
                "Phase 4 config drift — refusing before any question: " + "; ".join(problems)
            )

    def _reconcile_answer_issuance(reserved_answer: bool, qdir: Path, where: str) -> int | None:
        """Issuance is the entry's REAL receipt. On the exception path the
        answer entry still wrote its runtime (model_calls_used is set in the
        unified finally, including executed-then-failed calls) — read it so a
        failed actual call is never rewritten to zero. Returns the reconciled
        count, or None when no receipt exists (the reservation stays a
        conservative occupancy, unbilled)."""
        if not reserved_answer:
            return None
        runtime = qdir / "answer" / "answer-runtime-latest.json"
        try:
            calls = int(
                json.loads(runtime.read_text(encoding="utf-8")).get("model_calls_used") or 0
            )
        except Exception:  # noqa: BLE001 — no trustworthy receipt
            return None
        if calls > 0:
            ledger.mark_issued("answer_llm", calls, where)
        return calls

    for q in questions:
        precondition = q.get("precondition") or {}
        for path in paths:
            where = f"r{round_no}/{path}/{q['query_id']}"
            original_envelope: dict | None = None
            runner = PATH_RUNNERS[path]
            attribution, attribution_note = _leg_attribution(
                q, precondition, runner, path, local_adapter_factory
            )
            record: dict = {
                "round": round_no,
                "path": path,
                "query_id": q["query_id"],
                "category": q["category"],
                "is_counter": q["is_counter"],
                # post-hoc scoring only — NEVER routing (E4)
                "expected_status": q["expected_status"],
                # classified from the ACTUAL resources of the leg (R4)
                "execution_attribution": attribution,
                "timings": {},
            }
            if attribution_note:
                record["attribution_note"] = attribution_note
            ledger.begin_question(where)
            qdir = report_dir / "legs" / f"r{round_no}" / path / q["query_id"]
            refusal_base = ledger.question_refusals(where)
            reserved_answer = False
            try:
                t0 = time.monotonic()
                with budgeted_local_boundary(ledger, where):
                    if precondition.get("kind") == "enum_member_budget":
                        cap = (precondition.get("expand_budget") or {}).get("max_members")
                        if cap is not None:
                            original_envelope = dict(spec.per_question)
                            ledger.override_question_envelope("pg", int(cap) * 4)
                    stage = await runner(
                        q,
                        values,
                        conn,
                        ledger,
                        qdir,
                        local_adapter_factory=local_adapter_factory,
                    )
                    record["timings"]["discovery_ms"] = int((time.monotonic() - t0) * 1000)
                    record["discovery"] = {
                        "status": stage["discovery_status"],
                        "usable": stage["usable"],
                        "latency_ms": stage["latency_ms"],
                    }
                    if stage.get("receipts"):
                        record["receipts"] = stage["receipts"]
                    if precondition.get("kind") == "cross_workspace_isolation":
                        workspaces = sorted(
                            {
                                u.get("workspace")
                                for u in (stage["fused_result"].get("usable") or [])
                            }
                        )
                        foreign = any(w != q["workspace"] for w in workspaces)
                        record["isolation_evidence"] = {
                            "observed_candidate_workspaces": workspaces,
                            "question_workspace": q["workspace"],
                            "foreign_workspace_present": foreign,
                            "evidence_class": (
                                "a foreign-workspace candidate was OBSERVED among this leg's "
                                "candidates and rejected by the workspace check — an honest "
                                "observation, not a constructed proof"
                                if foreign
                                else "observation only: no foreign workspace appeared among "
                                "THIS leg's candidates. NOT an adversarial same-id cross-workspace "
                                "verification — that rejection is unit-verified against a fixture "
                                "source in tests/test_evaluation.py "
                                "(test_local_rejects_foreign_workspace_and_unverified)"
                            ),
                        }

                    if ledger.question_refusals(where) > refusal_base:
                        # R2: a release helper may catch BudgetExhausted and
                        # fall back (VECTOR -> WEIGHT). The refusal stays in
                        # the ledger — it is checked per STAGE, so a swallowed
                        # refusal can never surface as a clean complete, and
                        # the leg consumes no further quota.
                        event = ledger.last_refusal(where) or {}
                        record["budget_failure"] = {
                            "stage": "discovery",
                            "reason": str(event.get("reason") or "budget refusal during discovery"),
                            "calls_issued": 0,
                            "coverage_status": "partial",
                            "note": "refusal recorded in the ledger even though discovery "
                            "returned; answer stage not entered",
                        }
                    else:
                        fp = report_dir / "inputs" / path / f"{q['query_id']}-fusion.json"
                        fp.parent.mkdir(parents=True, exist_ok=True)
                        fp.write_text(
                            json.dumps(
                                {
                                    "task": f"Phase 4 round {round_no} evaluation input "
                                    f"(path={path})",
                                    "identity_before": pre,
                                    "results": [stage["fused_result"]],
                                },
                                ensure_ascii=False,
                            ),
                            encoding="utf-8",
                        )

                        rerank_report = stage.get("rerank_report")
                        if rerank_report is None:
                            rerank_report = {
                                "query_id": q["query_id"],
                                "status": "absent",
                                "ordered": [],
                                "degraded": [],
                                "typed_targets": [],
                                "identity_before": pre,
                                "note": "declared rerank strategy for this path is none "
                                "(raw path order) — explicit absent, never a claimed "
                                "rerank success",
                            }
                        rp = report_dir / "inputs" / path / f"{q['query_id']}-rerank.json"
                        rp.write_text(
                            json.dumps(rerank_report, ensure_ascii=False), encoding="utf-8"
                        )
                        if stage.get("rerank_latency_ms") is not None:
                            record["timings"]["rerank_ms"] = stage["rerank_latency_ms"]
                        if stage.get("rerank_issuance") is not None:
                            # S1: how the rerank bill was decided from the REAL
                            # receipt — executed / before-http-zero / unknown
                            record["rerank_issuance"] = stage["rerank_issuance"]

                        # ANSWER stage runs INSIDE the same budget scope: when
                        # no conn is supplied (the real CLI form) the entry's
                        # self-made asyncpg connection is wrapped and counted.
                        allow_model = False
                        if q["category"] == "synthesis" and user_allows_answer_model:
                            ledger.reserve("answer_llm", 1, where)
                            reserved_answer = True
                            allow_model = True
                        bconn = (
                            _BudgetedConnection(conn, ledger, where) if conn is not None else None
                        )
                        t1 = time.monotonic()
                        answer_kwargs: dict = {
                            "fused_report_path": fp,
                            "rerank_report_path": rp,
                            "values": values,
                            "transport": transport,
                            "allow_model": allow_model,
                            "category_overrides": {q["query_id"]: q["category"]},
                        }
                        if bconn is not None:
                            answer_kwargs["conn"] = bconn
                        if precondition.get("expand_budget"):
                            answer_kwargs["expand_budgets"] = {
                                q["query_id"]: precondition["expand_budget"]
                            }
                        answer_report = await _run_answer(
                            qdir / "answer",
                            [q["query_id"]],
                            **answer_kwargs,
                        )
                        res = answer_report["results"][0]
                        model_calls = int(answer_report.get("model_calls_used") or 0)
                        if model_calls > 0:
                            # issued from the REAL receipt, never from the
                            # reservation: an answer that skipped HTTP on
                            # incomplete conditions bills zero
                            ledger.mark_issued("answer_llm", model_calls, where)
                        record["answer"] = {
                            "coverage_status": res.get("coverage_status"),
                            "model_status": (res.get("model") or {}).get("status"),
                            "model_calls": model_calls,
                            "items": len((res.get("answer") or {}).get("items") or []),
                            "latency_ms": int((time.monotonic() - t1) * 1000),
                        }
                        if res.get("reverification"):
                            record["reverification"] = {
                                "items_checked": res["reverification"].get("items_checked"),
                                "problems": len(res["reverification"].get("problems") or []),
                            }
                        record["timings"]["total_ms"] = (
                            record["timings"].get("discovery_ms", 0)
                            + record["answer"]["latency_ms"]
                        )
                        if ledger.question_refusals(where) > refusal_base:
                            event = ledger.last_refusal(where) or {}
                            record["budget_failure"] = {
                                "stage": "answer",
                                "reason": str(
                                    event.get("reason") or "budget refusal during answer"
                                ),
                                "calls_issued": 0,
                                "coverage_status": "partial",
                                "note": "the answer entry returned after a recorded refusal — "
                                "this leg is a budget failure, never an unmarked complete",
                            }
            except BudgetExhausted as exc:
                record["budget_failure"] = {
                    "reason": _clean_error(exc, values),
                    "calls_issued": 0,
                    "coverage_status": "partial",
                    "stage": "budget",
                }
                _reconcile_answer_issuance(reserved_answer, qdir, where)
            except Exception as exc:  # noqa: BLE001 — isolated per-question terminal
                if ledger.question_refusals(where) > refusal_base:
                    # the entry/library caught the refusal and surfaced a
                    # generic error — the LEDGER is the account, not the
                    # exception type
                    event = ledger.last_refusal(where) or {}
                    record["budget_failure"] = {
                        "stage": "swallowed-refusal",
                        "reason": str(
                            event.get("reason") or "budget refusal recorded in the ledger"
                        ),
                        "calls_issued": 0,
                        "coverage_status": "partial",
                        "underlying_error": _clean_error(exc, values),
                        "note": "a recorded budget refusal made this leg fail inside the entry; "
                        "reported as budget failure, not a clean run",
                    }
                    _reconcile_answer_issuance(reserved_answer, qdir, where)
                else:
                    record["failure"] = {
                        "stage": "evaluation",
                        "error": _clean_error(exc, values),
                    }
                    # an answer that really attempted its model call and then
                    # failed still bills that attempt (R2: executed failures
                    # are never rewritten to zero)
                    _reconcile_answer_issuance(reserved_answer, qdir, where)
            finally:
                # states an inner seam published before re-raising (e.g. the
                # three-state rerank reconciliation of a FAILED fusion leg)
                # must land on the leg record and the terminal (S1 r4)
                for key, value in ledger.take_annotations(where).items():
                    record.setdefault(key, value)
                ledger.end_question(where)
                if original_envelope is not None:
                    ledger.restore_envelope(original_envelope)
            out["results"].append(record)

    # ---- post identity guard: observed after, never copied from before -----
    # ANY failure of the post capture itself (AdapterError from the guard OR
    # another exception) writes the terminal first — results, live ledger,
    # original + post error coexist — then raises run-level (R3).
    try:
        post = _flatten_identity(await _capture_identity(values))
    except Exception as exc:  # noqa: BLE001
        out["identity_after_error"] = _clean_error(exc, values)
        _fail_terminal("identity-after-capture", f"{type(exc).__name__}: post capture failed")
        raise AdapterError(
            f"post identity capture failed ({type(exc).__name__}); "
            "evaluation results preserved in terminal"
        ) from exc
    out["identity_after"] = post
    drift = _capture_drift(pre, post)
    if expected_identity:
        drift = drift + _identity_problems(expected_identity, post)
    if drift:
        _fail_terminal("identity-after-drift", drift)
        raise AdapterError(
            "post-run identity drift (terminal written, results kept): " + "; ".join(drift)
        )

    out["budget_snapshot_end"] = ledger.snapshot()
    out["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    _write_terminal()
    return out
