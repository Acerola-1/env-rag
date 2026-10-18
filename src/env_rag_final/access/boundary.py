"""Request-local live authorization, kept outside serializable identities.

Only the HTTP server (or an explicitly scoped trusted caller) binds this
guard. ContextVar isolates concurrent requests and never stores credentials
on a service singleton, in a record, or in the public AuthContext.
"""

from contextvars import ContextVar

from env_rag_final.access.auth import NotAvailable

live_guard = ContextVar("knowledge_live_guard", default=None)


async def require_live(ctx=None):
    """Recheck the original request context before another data operation."""
    binding = live_guard.get()
    if binding is None:
        if ctx is not None and ctx.mode == "remote":
            raise NotAvailable("remote operation requires a live request scope")
        return
    original, check = binding
    if ctx is not None:
        if ctx.auth_binding() != original.auth_binding() or not set(ctx.workspaces) <= set(
            original.workspaces
        ):
            raise NotAvailable("request context changed")
    await check()
