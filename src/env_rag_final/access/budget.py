"""Request-local monotonic deadlines shared by HTTP and database boundaries."""

import time
from contextvars import ContextVar

knowledge_deadline_at: ContextVar[float | None] = ContextVar("knowledge_deadline_at", default=None)


def remaining_seconds() -> float:
    deadline = knowledge_deadline_at.get()
    if deadline is None:
        return 20.0
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("knowledge deadline exceeded")
    return remaining
