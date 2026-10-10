"""Phase 1 enumeration: logical tables, table/prose/doc enumeration, contract."""

from .contract import EnumResult, FailStage
from .doc_enum import enumerate_documents
from .prose_enum import (
    extract_clauses_regex,
    extract_items_with_model,
    locate_first_numbered_clause,
    locate_span,
    read_prose_scope,
    verify_citations,
)
from .table_enum import enumerate_table
from .tables import (
    Fragment,
    LogicalTable,
    TableRows,
    enumerate_logical_table,
    link_logical_tables,
    parse_caption,
    read_html_table,
)

__all__ = [
    "EnumResult",
    "FailStage",
    "enumerate_documents",
    "extract_clauses_regex",
    "extract_items_with_model",
    "locate_span",
    "read_prose_scope",
    "locate_first_numbered_clause",
    "verify_citations",
    "enumerate_table",
    "Fragment",
    "LogicalTable",
    "TableRows",
    "enumerate_logical_table",
    "link_logical_tables",
    "parse_caption",
    "read_html_table",
]
