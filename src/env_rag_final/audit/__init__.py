"""Phase-0 read-only audit: corpus identity, mapping evidence and probe reports.

Entry point: ``uv run python -m env_rag_final.audit`` (or ``env-rag-final audit``).
Writes reports to ``reports/pg-retrieval/phase-0/``. Never writes to the database.
"""

from .pg import run_audit

__all__ = ["run_audit"]
