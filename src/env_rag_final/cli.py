"""Environmental retrieval, read-only enumeration questions, and audit commands."""

import argparse
import asyncio
import importlib
from importlib.metadata import version
from pathlib import Path

from .config import read_environment

DEPENDENCIES = {
    "lightrag-hku": "lightrag",
    "openai": "openai",
    "asyncpg": "asyncpg",
    "pgvector": "pgvector",
    "qdrant-client": "qdrant_client",
    "neo4j": "neo4j",
    "httpx": "httpx",
    "python-dotenv": "dotenv",
    "lxml": "lxml.etree",
}


async def check_connections(values: dict[str, str]) -> bool:
    import asyncpg
    from neo4j import AsyncGraphDatabase
    from qdrant_client import AsyncQdrantClient

    async def postgres() -> None:
        connection = await asyncpg.connect(
            host=values["POSTGRES_HOST"],
            port=int(values["POSTGRES_PORT"]),
            user=values["POSTGRES_USER"],
            password=values["POSTGRES_PASSWORD"],
            database=values["POSTGRES_DATABASE"],
            timeout=10,
        )
        try:
            await connection.fetchval("SELECT 1")
        finally:
            await connection.close()

    async def qdrant() -> None:
        client = AsyncQdrantClient(
            url=values["QDRANT_URL"],
            api_key=values.get("QDRANT_API_KEY") or None,
            timeout=10,
        )
        try:
            await client.get_collections()
        finally:
            await client.close()

    async def neo4j() -> None:
        driver = AsyncGraphDatabase.driver(
            values["NEO4J_URI"],
            auth=(values["NEO4J_USERNAME"], values["NEO4J_PASSWORD"]),
            connection_timeout=10,
        )
        try:
            await driver.verify_connectivity()
            async with driver.session(database=values.get("NEO4J_DATABASE") or None) as session:
                result = await session.run("RETURN 1 AS ready")
                await result.consume()
        finally:
            await driver.close()

    checks = (("PostgreSQL", postgres), ("Qdrant", qdrant), ("Neo4j", neo4j))
    results = await asyncio.gather(
        *(asyncio.wait_for(check(), timeout=20) for _, check in checks),
        return_exceptions=True,
    )
    okay = True
    for (name, _), result in zip(checks, results, strict=True):
        if isinstance(result, BaseException):
            # Exception messages may contain DSNs or credentials; emit only the type.
            print(f"{name}: FAIL ({type(result).__name__})")
            okay = False
        else:
            print(f"{name}: OK (read-only connectivity)")
    return okay


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "doctor",
            "audit",
            "catalog-migrate",
            "catalog-build",
            "catalog-stale",
            "search-probe",
            "search-build",
            "search-stale",
            "search-query",
            "search-bench",
            "enum-table",
            "enum-prose",
            "enum-docs",
            "lightrag-local",
            "fuse-candidates",
            "rerank-candidates",
            "answer",
            "eval-run",
            "ask",
        ],
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--connections", action="store_true", help="Read-only database checks")
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=None,
        help="Output directory (audit → phase-0; search-probe → phase-2)",
    )
    parser.add_argument(
        "--fingerprint",
        default=None,
        help="Expected source fingerprint (catalog-build; defaults to the Gate 0 frozen value)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even if the same (source, recipe) build is already active",
    )
    parser.add_argument("--doc-id", default=None, help="Document id (enum commands)")
    parser.add_argument(
        "--table-number", default=None, help="Base table number, e.g. 1 (enum-table)"
    )
    parser.add_argument(
        "--chapter-scope", default=None, help="Chapter heading to disambiguate same-number tables"
    )
    parser.add_argument("--scope-id", default=None, help="Catalog scope id (enum-prose)")
    parser.add_argument(
        "--clause-wanted",
        default=None,
        help="Comma-separated clause numbers to extract (enum-prose)",
    )
    parser.add_argument(
        "--predicate", default=None, help="SQL boolean over env_rag.documents columns (enum-docs)"
    )
    parser.add_argument("--page-size", type=int, default=100, help="Page size (enum-docs)")
    parser.add_argument(
        "--with-model",
        action="store_true",
        help="Use the configured LLM for prose item extraction (enum-prose)",
    )
    parser.add_argument("--out", type=Path, default=None, help="Write the EnumResult JSON here")
    parser.add_argument(
        "--query", default=None, help="Natural-language or code query (search-query)"
    )
    parser.add_argument(
        "--kind",
        choices=["auto", "files", "prose", "table"],
        default="auto",
        help="Enumeration question type (ask; auto detects explicit ranges)",
    )
    parser.add_argument("--document", default=None, help="Exact catalog filename or doc_id (ask)")
    parser.add_argument("--version", default=None, help="Standard edition with --code (ask)")
    parser.add_argument("--scope", default=None, help="Range such as 第3章 or 4.1.1 至 4.1.5 (ask)")
    parser.add_argument("--workspace", default="default", help="Verified workspace (ask)")
    parser.add_argument(
        "--format", choices=["text", "json"], default="text", help="ask output format"
    )
    parser.add_argument("--top-k", type=int, default=20, help="Candidate budget (search-query)")
    parser.add_argument(
        "--code",
        default=None,
        help="Explicit standard code for exact lookup, e.g. GB3095-2012 (search-query)",
    )
    parser.add_argument(
        "--strict-code",
        action="store_true",
        help="Require the given code's version to match exactly (no relaxation)",
    )
    parser.add_argument(
        "--expand",
        action="store_true",
        help="After discovery, fully expand the confirmed scope (task 4.4)",
    )
    parser.add_argument(
        "--gold", type=Path, default=None, help="Gold candidates JSON (search-bench)"
    )
    parser.add_argument(
        "--runs", type=Path, default=None, help="Append raw runs JSONL (search-bench)"
    )
    parser.add_argument("--only", default=None, help="Run one gold query id (search-bench)")
    parser.add_argument(
        "--expand-docs",
        action="store_true",
        help="Replace discovery candidates with the full paged document set (task 4.4)",
    )
    parser.add_argument(
        "--query-id",
        default=None,
        help="Frozen gold query id to run (lightrag-local, repeatable via comma)",
    )
    parser.add_argument(
        "--pg-only",
        action="store_true",
        help="Skip the local path entirely (fuse-candidates) — explicit PG-only run",
    )
    parser.add_argument(
        "--fused-report",
        default=None,
        help="Fused runtime JSON to replay (rerank-candidates/answer); defaults to the "
        "phase-3-fusion latest report",
    )
    parser.add_argument(
        "--rerank-report",
        default=None,
        help="Rerank runtime JSON to replay (answer); defaults to the accepted "
        "phase-3-rerank-r2 report",
    )
    parser.add_argument(
        "--allow-model",
        action="store_true",
        help="Authorize the single synthesis answer-model call (answer). Without "
        "it the run verifies scopes/citations read-only and reports synthesis "
        "incomplete with 0 model calls.",
    )
    parser.add_argument(
        "--round",
        type=int,
        default=1,
        help="Evaluation round number (eval-run)",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=None,
        help="Rounds covered by the dry-run execution matrix (eval-run --dry-run)",
    )
    parser.add_argument(
        "--paths",
        default=None,
        help="Comma-separated paths to execute: pg,local,fusion (eval-run)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compile the execution matrix and budget upper bounds offline; "
        "ZERO backend access (eval-run)",
    )
    parser.add_argument(
        "--budgets",
        default=None,
        help="JSON file with configurable budget caps (eval-run)",
    )
    args = parser.parse_args()
    if args.command == "ask":
        _run_ask(args, parser)
        return
    try:
        values = read_environment(args.env_file)
    except ValueError as error:
        parser.exit(1, f"Configuration: FAIL ({error})\n")
    for distribution, module in DEPENDENCIES.items():
        importlib.import_module(module)
        print(f"{distribution}: {version(distribution)}")
    print(f"Configuration: OK ({len(values)} keys; credential values hidden)")
    if args.command == "audit":
        from .audit import run_audit

        report_dir = args.report_dir or Path("reports/pg-retrieval/phase-0")
        try:
            result = run_audit(values, report_dir)
        except Exception as error:  # audit errors are credential-free by construction
            parser.exit(1, f"Audit: FAIL ({error})\n")
        stats = result["stats"]
        print(
            "Audit: OK "
            f"(parsed={stats['parsed_dirs_total']}, doc_full={stats['doc_full_rows']}, "
            f"chunks={stats['chunks_total']}, failed_status={stats['doc_status_failed_rows']}) "
            f"-> {report_dir}"
        )
        print(f"Run ID: {result['manifest']['run_id']}")
        print("Scope: Phase 0 read-only audit only; no schema objects were created.")
        return
    if args.command in ("catalog-migrate", "catalog-build", "catalog-stale"):
        _run_catalog(args, values)
        return
    if args.command in (
        "search-probe",
        "search-build",
        "search-stale",
        "search-query",
        "search-bench",
    ):
        _run_search(args, values)
        return
    if args.command in ("enum-table", "enum-prose", "enum-docs"):
        _run_enum(args, values)
        return
    if args.command == "lightrag-local":
        _run_lightrag_local(args, values)
        return
    if args.command == "fuse-candidates":
        _run_fuse(args, values)
        return
    if args.command == "rerank-candidates":
        _run_rerank(args, values)
        return
    if args.command == "answer":
        _run_answer(args, values)
        return
    if args.command == "eval-run":
        _run_eval(args, values)
        return
    print("Retrieval: scaffold only; two-path fusion is not implemented")
    if args.connections and not asyncio.run(check_connections(values)):
        raise SystemExit(1)


def _run_ask(args, parser) -> None:
    """Arbitrary questions; only PG configuration is needed, zero model calls."""
    import json

    from dotenv import dotenv_values

    from .ask import Question, ask_question, format_answer, write_result

    try:
        if args.document and args.doc_id:
            raise ValueError("--document 与 --doc-id 请选择一个")
        request = Question(
            args.query or "",
            kind=args.kind,
            document=args.document or args.doc_id,
            code=args.code,
            version=args.version,
            scope=args.scope,
            scope_id=args.scope_id,
            table_number=args.table_number,
            chapter_scope=args.chapter_scope,
            workspace=args.workspace,
            top_k=args.top_k,
        )
        request.prepare()
        if args.allow_model or args.with_model:
            raise ValueError("ask 不允许模型调用")
        if args.out and args.out.exists():
            raise ValueError("--out 已存在；拒绝覆盖，请使用全新文件名")
        values = {k: v for k, v in dotenv_values(args.env_file).items() if v is not None}
        for k in (
            "POSTGRES_HOST",
            "POSTGRES_PORT",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "POSTGRES_DATABASE",
        ):
            if not values.get(k):
                raise ValueError(f"缺少数据库配置 {k}")
        result = asyncio.run(ask_question(request, values))
        if args.out:
            write_result(args.out, result)
    except ValueError as error:
        parser.exit(1, f"ask: {error}\n")
    except Exception as error:
        parser.exit(1, f"ask: FAIL ({type(error).__name__})\n")
    print(
        json.dumps(result, ensure_ascii=False, indent=2)
        if args.format == "json"
        else format_answer(result)
    )
    if result.get("failure") or result.get("failure_after") or result["coverage_status"] == "stale":
        raise SystemExit(1)


def _run_eval(args, values: dict[str, str]) -> None:
    """Task 6.1: Phase 4 evaluation owning entry (dry-run or three-path run)."""
    import json as _json

    from . import evaluation as ev

    loads = _json.loads

    report_dir = args.report_dir or Path("reports/pg-retrieval/phase-4")
    paths = args.paths.split(",") if args.paths else ["pg", "local", "fusion"]
    budgets = loads(Path(args.budgets).read_text()) if args.budgets else None
    rounds = list(range(1, (args.rounds or 2) + 1)) if args.dry_run else None
    expected = None
    if not args.dry_run:
        # R3: the real mode requires the COMPLETE frozen Phase 4 anchor —
        # identity, approved model/endpoint class/dimension, prompt SHA, code
        # anchors, parameter budgets, env guards — and refuses BEFORE any
        # dispatch if it is missing, corrupt or mismatched. The anchor is
        # never overridable per run ("expected" is not settable from args).
        # dry-run stays zero-touch and does NOT require the anchor.
        try:
            expected = ev.validate_phase4_anchor(values=values)
        except Exception as error:
            raise SystemExit(f"eval-run: FAIL (anchor: {type(error).__name__}: {error})") from None
    try:
        report = asyncio.run(
            ev.run_evaluation(
                report_dir,
                round_no=args.round,
                rounds=rounds,
                paths=paths,
                query_ids=args.query_id.split(",") if args.query_id else None,
                dry_run=args.dry_run,
                budgets=budgets,
                values=values,
                expected_identity=expected,
                user_allows_answer_model=args.allow_model,
            )
        )
    except Exception as error:
        raise SystemExit(f"eval-run: FAIL ({type(error).__name__}: {error})") from None
    if report.get("mode") == "dry_run":
        print(f"Eval dry-run OK: executions={report['total_executions']} backend_fetches=0")
        print(f"  bounds: {_json.dumps(report['bounds'], ensure_ascii=False)}")
        print(f"  -> {report['matrix_file']}")
    else:
        clean = sum(
            1 for r in report["results"] if "failure" not in r and "budget_failure" not in r
        )
        print(f"Eval OK: round={report['round']} executions={len(report['results'])} clean={clean}")
        print(f"  -> {report_dir / 'eval-runtime-latest.json'}")


def _run_catalog(args, values: dict[str, str]) -> None:
    """Catalog commands: migrate/build write ONLY the app schema; stale is read-only."""
    import asyncpg

    from .catalog import applied_names, build_catalog, check_stale, migrate
    from .catalog.builder import FROZEN_SNAPSHOT

    dsn = {
        "host": values["POSTGRES_HOST"],
        "port": int(values["POSTGRES_PORT"]),
        "user": values["POSTGRES_USER"],
        "password": values["POSTGRES_PASSWORD"],
        "database": values["POSTGRES_DATABASE"],
        "statement_cache_size": 0,
        "timeout": 15,
    }

    async def run():
        conn = await asyncpg.connect(**dsn)
        try:
            if args.command == "catalog-migrate":
                applied = await migrate(conn)
                print(f"Migrated: {len(applied)} pending -> {applied or 'none (already applied)'}")
                print(f"Applied objects: {await applied_names(conn)}")
                print("Only the application schema was created; public.lightrag_* untouched.")
            elif args.command == "catalog-build":
                result = await build_catalog(
                    conn,
                    expected_fingerprint=args.fingerprint or FROZEN_SNAPSHOT,
                    force=args.force,
                )
                print(
                    f"Build OK: snapshot={result.snapshot_id} recipe={result.recipe_id} published={result.published}"
                )
                print(
                    f"docs={result.docs} units={result.units} links={result.links} "
                    f"scopes={result.scopes} warnings={len(result.warnings)}"
                )
                for w in result.warnings[:8]:
                    print(f"  warning: {w}")
            else:
                stale = await check_stale(conn)
                print(f"Stale check: {stale}")
        finally:
            await conn.close()

    try:
        asyncio.run(run())
    except Exception as error:
        raise SystemExit(
            f"Catalog {args.command}: FAIL ({type(error).__name__}: {error})"
        ) from None


if __name__ == "__main__":
    main()


def _run_search(args, values: dict[str, str]) -> None:
    """Search entries (tasks 4.1–4.4). search-build writes only env_rag."""
    import json as _json

    import asyncpg

    if args.command == "search-probe":
        from .search.probe import main_probe

        report_dir = args.report_dir or Path("reports/pg-retrieval/phase-2")
        payload = main_probe(values, report_dir)
        print(
            f"Tokenizer probe OK: version={payload['tokenizer_version']} "
            f"vocab_sha={payload['vocab_sha'][:12]} "
            f"cases={len(payload['real_text_cases'])} "
            f"-> {report_dir / 'tokenizer-probes.json'}"
        )
        return

    read_only = args.command in ("search-stale", "search-query", "search-bench")
    dsn = {
        "host": values["POSTGRES_HOST"],
        "port": int(values["POSTGRES_PORT"]),
        "user": values["POSTGRES_USER"],
        "password": values["POSTGRES_PASSWORD"],
        "database": values["POSTGRES_DATABASE"],
        "statement_cache_size": 0,
        "timeout": 15,
    }
    if read_only:
        dsn["server_settings"] = {"default_transaction_read_only": "on"}

    async def run():
        conn = await asyncpg.connect(**dsn)
        try:
            if args.command == "search-build":
                from .search.index import build_search_index

                return "build", await build_search_index(conn, force=args.force)
            if args.command == "search-stale":
                from .search.index import check_search_stale

                return "stale", await check_search_stale(conn)
            if args.command == "search-bench":
                from .search.eval import load_gold, run_benchmark

                gold_path = args.gold or Path("reports/pg-retrieval/phase-2/gold-candidates.json")
                gold = load_gold(gold_path)
                summary = await run_benchmark(
                    conn,
                    gold,
                    top_k=args.top_k,
                    runs_path=args.runs,
                    values=values,
                    only=args.only,
                    expand=args.expand,
                )
                return "bench", summary
            # search-query
            from .search.query import run_query

            if not args.query and not args.code:
                raise ValueError("search-query requires --query and/or --code")
            return "query", await run_query(
                conn,
                args.query or "",
                code=args.code,
                top_k=args.top_k,
                strict_code=args.strict_code,
                expand=args.expand,
                expand_docs=args.expand_docs,
                scope_id=args.scope_id,
                table_number=args.table_number,
                source_values=values,
            )
        finally:
            await conn.close()

    try:
        kind, result = asyncio.run(run())
    except Exception as error:
        raise SystemExit(f"{args.command}: FAIL ({type(error).__name__}: {error})") from None
    if kind == "build":
        print(
            f"Search build OK: search_id={result.search_id} published={result.published} "
            f"docs={result.docs_indexed} chunks={result.chunks_indexed} "
            f"tokenizer={result.tokenizer_version} vocab={result.vocab_sha[:12]} "
            f"elapsed_ms={result.elapsed_ms}"
        )
        for w in result.warnings[:5]:
            print(f"  warning: {w}")
        return
    if kind == "stale":
        print(f"Search stale check: {result}")
        return
    if kind == "bench":
        print(
            f"Benchmark: {result['questions_total']} questions "
            f"({result['questions_reviewed']} reviewed / "
            f"{result['questions_excluded_not_eligible']} not eligible) "
            f"run_id={result['run_id']}"
        )
        print(
            "  file-list doc recall@k (reviewed only, file_enum) = "
            f"{result['list_doc_recall_at_k_reviewed']}"
        )
        print(
            "  answer-evidence recall@k (reviewed only, typed gold) = "
            f"{result['evidence_recall_at_k_reviewed']}"
        )
        print(f"  raw runs -> {result['runs_path']}")
        payload_path = args.out
        if payload_path:
            payload_path.write_text(
                _json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
            )
            print(f"  summary -> {payload_path}")
        return
    payload = result.to_dict()
    print(_json.dumps(payload, ensure_ascii=False, indent=1))
    if args.out:
        Path(args.out).write_text(_json.dumps(payload, ensure_ascii=False, indent=1) + "\n")


def _run_lightrag_local(args, values: dict[str, str]) -> None:
    """Task 5.2: real local candidate retrieval over production backends."""
    import json as _json

    from .local_adapter import run_frozen

    report_dir = args.report_dir or Path("reports/pg-retrieval/phase-3-local")
    queries = args.query_id.split(",") if args.query_id else None
    try:
        report = asyncio.run(run_frozen(report_dir, queries))
    except Exception as error:
        raise SystemExit(f"lightrag-local: FAIL ({type(error).__name__}: {error})") from None
    total_calls: dict[str, int] = {}
    for r in report["results"]:
        for k, v in (r.get("service_calls") or {}).items():
            if k == "by_service" or not isinstance(v, int):
                continue
            total_calls[k] = total_calls.get(k, 0) + v
    verified = sum(
        1 for r in report["results"] for c in r.get("candidates", []) if c.get("verified")
    )
    total_candidates = sum(len(r.get("candidates", [])) for r in report["results"])
    degraded = sum(len(r.get("degraded", [])) for r in report["results"])
    print(
        f"Local candidates OK: queries={len(report['results'])} "
        f"candidates={total_candidates} (verified={verified}, degraded_notes={degraded})"
    )
    print(f"  service calls: {_json.dumps(total_calls)}")
    print(f"  -> {report_dir / 'local-runtime-latest.json'}")
    print(f"  -> {report_dir / 'local-candidates-latest.jsonl'}")


def _run_fuse(args, values: dict[str, str]) -> None:
    """Task 5.3: fuse the PG discovery path and the local semantic path."""
    import json as _json

    from .fusion import run_fusion

    report_dir = args.report_dir or Path("reports/pg-retrieval/phase-3-fusion")
    queries = args.query_id.split(",") if args.query_id else None
    try:
        report = asyncio.run(run_fusion(report_dir, queries, pg_only=args.pg_only))
    except Exception as error:
        raise SystemExit(f"fuse-candidates: FAIL ({type(error).__name__}: {error})") from None
    usable = sum(len(r.get("usable", [])) for r in report["results"])
    rejected = sum(len(r.get("rejected", [])) for r in report["results"])
    statuses = {r["query_id"]: r["status"] for r in report["results"]}
    print(f"Fusion OK: queries={len(report['results'])} usable={usable} rejected={rejected}")
    print(f"  status: {_json.dumps(statuses)}")
    print(f"  -> {report_dir / 'fusion-runtime-latest.json'}")
    print(f"  -> {report_dir / 'fusion-candidates.jsonl'}")


def _run_rerank(args, values: dict[str, str]) -> None:
    """Task 5.4: one joint rerank over the fused usable candidate set."""
    import json as _json

    from .rerank import run_rerank

    report_dir = args.report_dir or Path("reports/pg-retrieval/phase-3-rerank")
    queries = args.query_id.split(",") if args.query_id else None
    fused_path = Path(args.fused_report) if args.fused_report else None
    try:
        report = asyncio.run(run_rerank(report_dir, queries, fused_report_path=fused_path))
    except Exception as error:
        raise SystemExit(f"rerank-candidates: FAIL ({type(error).__name__}: {error})") from None
    ordered = sum(len(r.get("ordered", [])) for r in report["results"])
    degraded = sum(1 for r in report["results"] if r.get("status") == "degraded")
    skipped = sum(1 for r in report["results"] if r.get("status") == "skipped")
    statuses = {r["query_id"]: r["status"] for r in report["results"]}
    print(
        f"Rerank OK: queries={len(report['results'])} ordered={ordered} "
        f"degraded={degraded} skipped={skipped}"
    )
    print(f"  status: {_json.dumps(statuses)}")
    print(f"  -> {report_dir / 'rerank-runtime-latest.json'}")


def _run_answer(args, values: dict[str, str]) -> None:
    """Task 5.5: full scope expansion over replayed 5.3/5.4 + per-type answers."""
    import json as _json

    from .answer import run_answer

    report_dir = args.report_dir or Path("reports/pg-retrieval/phase-3-answer")
    queries = args.query_id.split(",") if args.query_id else None
    rerank_path = Path(args.rerank_report) if args.rerank_report else None
    fused_path = Path(args.fused_report) if args.fused_report else None
    try:
        report = asyncio.run(
            run_answer(
                report_dir,
                queries,
                rerank_report_path=rerank_path,
                fused_report_path=fused_path,
                allow_model=args.allow_model,
            )
        )
    except Exception as error:
        raise SystemExit(f"answer: FAIL ({type(error).__name__}: {error})") from None
    complete = sum(1 for r in report["results"] if r.get("coverage_status") == "complete")
    items = sum(len((r.get("answer") or {}).get("items") or []) for r in report["results"])
    print(
        f"Answer OK: queries={len(report['results'])} complete={complete} "
        f"answer_items={items} model_calls={report.get('model_calls_used')}"
    )
    print(
        f"  coverage: {_json.dumps({r['query_id']: r['coverage_status'] for r in report['results']})}"
    )
    print(f"  -> {report_dir / 'answer-runtime-latest.json'}")


def _run_enum(args, values: dict[str, str]) -> None:
    """Enumeration entries (3.1–3.5). Read-only against the live catalog."""
    import json as _json

    import asyncpg

    from .catalog.builder import check_stale

    dsn = {
        "host": values["POSTGRES_HOST"],
        "port": int(values["POSTGRES_PORT"]),
        "user": values["POSTGRES_USER"],
        "password": values["POSTGRES_PASSWORD"],
        "database": values["POSTGRES_DATABASE"],
        "statement_cache_size": 0,
        "timeout": 15,
        "server_settings": {"default_transaction_read_only": "on"},
    }

    async def run():
        conn = await asyncpg.connect(**dsn)
        adapter = None
        try:
            if args.command == "enum-table":
                from .enumerate_.table_enum import enumerate_table

                if not args.doc_id or not args.table_number:
                    raise ValueError("enum-table requires --doc-id and --table-number")
                return await enumerate_table(
                    conn,
                    "default",
                    args.doc_id,
                    args.table_number,
                    chapter_scope=args.chapter_scope,
                )
            if args.command == "enum-prose":
                from .enumerate_.prose_enum import (
                    bind_citations,
                    extract_clauses_regex,
                    extract_items_with_model,
                    read_prose_scope,
                    verify_citations,
                )

                if not args.doc_id or not args.scope_id:
                    raise ValueError("enum-prose requires --doc-id and --scope-id")
                snap = (await check_stale(conn)).get("active_snapshot_id")
                if adapter is None:
                    from .catalog.source import SourceAdapter

                    adapter = SourceAdapter(
                        {
                            "host": values["POSTGRES_HOST"],
                            "port": int(values["POSTGRES_PORT"]),
                            "user": values["POSTGRES_USER"],
                            "password": values["POSTGRES_PASSWORD"],
                            "database": values["POSTGRES_DATABASE"],
                        }
                    )
                wanted = args.clause_wanted.split(",") if args.clause_wanted else None
                units, result = await read_prose_scope(
                    adapter,
                    conn,
                    "default",
                    args.doc_id,
                    snap,
                    scope_id=args.scope_id,
                    requested_clauses=wanted,
                )
                text = "\n\n".join(u.text for u in units)
                model_failed = None
                if args.with_model:
                    items, logs, err = await extract_items_with_model(
                        text,
                        args.predicate or "列出该范围内的全部条目，附逐字引句。",
                        values,
                    )
                    result.model_calls = [
                        {
                            "model": lg.model,
                            "latency_ms": lg.latency_ms,
                            "ok": lg.ok,
                            "error": lg.error,
                            "request_messages": lg.request_messages,
                            "raw_response": lg.response_text,
                        }
                        for lg in logs
                    ]
                    model_failed = err
                else:
                    items = extract_clauses_regex(text, wanted)

                # G1: bind every item's source; model quotes get located spans
                items = bind_citations(items, "default", args.doc_id, snap, units)
                items = verify_citations(items, text, units)
                result.items = items

                # G2: re-check the source AFTER extraction/model before deciding
                # the final coverage — a change during extraction is stale
                stale_after = await check_stale(conn)
                if (
                    stale_after.get("state") != "current"
                    or stale_after.get("active_snapshot_id") != snap
                ):
                    result.coverage_status = "stale"
                    result.fail_stage = "stale"
                    result.warnings.append(
                        "catalog/source changed during/after extraction; result is stale"
                    )
                    result.validate()
                    return result

                # G4: answer-level coverage decided here, not by the reader.
                missing = []
                if wanted:
                    got = {it.get("clause") or it.get("place") for it in items}
                    missing = [w for w in wanted if w not in got]
                    if missing:
                        result.warnings.append(f"requested clauses missing: {missing}")
                unverified = [it for it in items if it.get("citation_verified") is not True]
                if model_failed:
                    result.coverage_status = "partial"
                    result.fail_stage = model_failed
                    result.warnings.append(f"model extraction failed: {model_failed}")
                    result.items = []
                elif result.read_status != "complete":
                    result.coverage_status = "partial"
                elif missing or unverified or not items:
                    result.coverage_status = "partial"
                    if unverified:
                        result.warnings.append(
                            f"{len(unverified)} items carry unverified citations"
                        )
                else:
                    result.coverage_status = "complete"
                result.validate()
                return result
            # enum-docs
            from .enumerate_.doc_enum import enumerate_documents

            if not args.predicate:
                raise ValueError("enum-docs requires --predicate (boolean over env_rag.documents)")
            return await enumerate_documents(
                conn,
                args.predicate,
                predicate_text=args.predicate,
                page_size=args.page_size,
            )
        finally:
            await conn.close()

    try:
        result = asyncio.run(run())
    except Exception as error:
        raise SystemExit(f"{args.command}: FAIL ({type(error).__name__}: {error})") from None
    payload = result.to_dict()
    print(_json.dumps(payload, ensure_ascii=False, indent=1))
    if args.out:
        Path(args.out).write_text(_json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
