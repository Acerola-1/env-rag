"""Loopback HTTP transport. No arbitrary paths, no storage initialization."""

from __future__ import annotations

import json
import secrets
from pathlib import Path

from aiohttp import web

from env_rag_final.audit import identity as corpus_identity

from .native import NATIVE_ROOT
from .service import STRATEGIES, ComparisonService

STATIC = Path(__file__).parent / "static"


def resolve_source(record: dict, index: int, kind: str) -> Path | None:
    """Only files derived from a verified record under corpus root can leave."""
    if kind not in ("pdf", "text") or index < 0 or index >= len(record["chunks"]):
        return None
    c = record["chunks"][index]
    if not c.get("verified"):
        return None
    name = Path(c.get("doc_name") or c.get("file_path") or "").name
    return resolve_file(name, kind)


def resolve_file(name: str, kind: str) -> Path | None:
    if not name or name in (".", ".."):
        return None
    root = (NATIVE_ROOT / "inputs").resolve()
    parsed_root = corpus_identity.PARSED_ROOT.resolve()
    if kind == "pdf":
        candidates = [root / name, root / "__parsed__" / name]
    else:
        pdir = corpus_identity.PARSED_ROOT / (name + ".parsed")
        candidates = (
            (sorted(pdir.glob("*.md")) or sorted(pdir.glob("*.blocks.jsonl")))
            if pdir.is_dir()
            else []
        )
    for path in candidates:
        resolved = path.resolve()
        if (
            resolved.is_relative_to(root)
            or (kind == "text" and resolved.is_relative_to(parsed_root))
        ) and resolved.is_file():
            return resolved
    return None


def resolve_document(record, doc_id, kind):
    if kind not in ("pdf", "text"):
        return None
    from .service import canonical_identity

    snapshot = canonical_identity(record["identity_before"])["catalog_active"]["snapshot_id"]
    for item in (record.get("enumeration") or {}).get("answer", {}).get("items", []):
        cit = item.get("citation") or {}
        if (
            item.get("kind") == "document"
            and item.get("doc_id") == doc_id
            and item.get("citation_verified") is True
            and item.get("citation_reverified") is True
            and cit.get("kind") == "catalog_row"
            and cit.get("doc_id") == doc_id
            and cit.get("workspace") == "default"
            and cit.get("snapshot_id") == snapshot
        ):
            return resolve_file(Path(item["doc_name"]).name, kind)
    return None


def create_app(service):
    token = secrets.token_urlsafe(32)

    @web.middleware
    async def trust_boundary(request, handler):
        if request.host.split(":")[0] not in ("localhost", "127.0.0.1"):
            return web.json_response({"error": "仅允许本机访问"}, status=403)
        if request.method == "POST":
            origin = request.headers.get("Origin")
            if origin and origin != f"{request.scheme}://{request.host}":
                return web.json_response({"error": "请求来源不符"}, status=403)
            if request.headers.get("X-RAG-Token") != token:
                return web.json_response({"error": "请从本机页面提交"}, status=403)
        try:
            response = await handler(request)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            # Validation errors are bounded, code-owned labels; provider
            # exceptions never leak text at the HTTP boundary.
            response = web.json_response({"error": str(exc)[:200]}, status=400)
        except web.HTTPException:
            raise
        except Exception as exc:
            response = web.json_response(
                {"error": "请求失败", "error_type": type(exc).__name__}, status=500
            )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        return response

    app = web.Application(middlewares=[trust_boundary], client_max_size=32 * 1024)

    async def index(request):
        return web.FileResponse(STATIC / "index.html")

    async def config(request):
        return web.json_response(
            {"token": token, "strategies": STRATEGIES, "budget": service.ledger.snapshot()}
        )

    async def query(request):
        body = await request.json()
        return web.json_response(
            await service.execute(
                body.get("query"),
                body.get("strategies"),
                generate=body.get("generate", False),
                options=body.get("options"),
                top_k=body.get("top_k", 20),
                submission_id=body.get("submission_id"),
            )
        )

    async def generate(request):
        body = await request.json()
        return web.json_response(
            await service.generate_record(body.get("record_id"), profile=body.get("profile"))
        )

    async def records(request):
        from .service import sanitize

        saved = list(service.records.values())[-100:]
        for rec in saved:
            rec["document_sources"] = [
                {
                    "doc_id": item["doc_id"],
                    "doc_name": item["doc_name"],
                    "pdf_available": resolve_document(rec, item["doc_id"], "pdf") is not None,
                    "text_available": resolve_document(rec, item["doc_id"], "text") is not None,
                }
                for item in (rec.get("enumeration") or {}).get("answer", {}).get("items", [])
                if item.get("kind") == "document"
            ]

        return web.json_response(
            sanitize(
                {
                    "results": saved,
                    "budget": service.ledger.snapshot(),
                    "saved_records_only": True,
                },
                service.values,
            )
        )

    async def export(request):
        rid = request.match_info["rid"]
        if rid not in service.records:
            raise web.HTTPNotFound(text="记录不存在")
        from .service import sanitize

        return web.Response(
            text=json.dumps(
                sanitize(service.records[rid], service.values), ensure_ascii=False, indent=2
            ),
            content_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="' + rid + '.json"'},
        )

    async def source(request):
        rid = request.match_info["rid"]
        rec = service.records.get(rid)
        if rec is None:
            raise web.HTTPNotFound(text="记录不存在")
        path = resolve_source(rec, int(request.match_info["index"]), request.match_info["kind"])
        if path is None:
            raise web.HTTPNotFound(text="此记录的来源文件不可用")
        if request.match_info["kind"] == "text":
            text = path.read_text()
            if path.name.endswith(".blocks.jsonl"):
                blocks = [json.loads(line) for line in text.splitlines()]
                text = "\n\n".join(b.get("content") or b.get("text") or "" for b in blocks)
            return web.Response(text=text, content_type="text/plain")
        return web.FileResponse(path)

    async def document(request):
        rec = service.records.get(request.match_info["rid"])
        if not rec:
            raise web.HTTPNotFound(text="记录不存在")
        path = resolve_document(rec, request.match_info["doc_id"], request.match_info["kind"])
        if path is None:
            raise web.HTTPNotFound(text="核验文档来源不可用")
        if request.match_info["kind"] == "text":
            text = path.read_text()
            if path.name.endswith(".blocks.jsonl"):
                text = "\n\n".join(
                    b.get("content") or b.get("text") or ""
                    for b in (json.loads(line) for line in text.splitlines())
                )
            return web.Response(text=text, content_type="text/plain")
        return web.FileResponse(path)

    app.router.add_get("/", index)
    app.router.add_get("/api/config", config)
    app.router.add_post("/api/query", query)
    app.router.add_post("/api/generate", generate)
    app.router.add_get("/api/records", records)
    app.router.add_get("/api/export/{rid}", export)
    app.router.add_get("/api/source/{rid}/{index}/{kind}", source)
    app.router.add_get("/api/document/{rid}/{doc_id}/{kind}", document)
    app.router.add_static("/static", STATIC, show_index=False)
    return app


def start(port, report_dir, *, interactive=False):
    service = ComparisonService(report_dir, interactive=interactive)
    print(f"RAG 对照页面：http://127.0.0.1:{port}（只读、独立调用账本、不自动重试）")
    web.run_app(create_app(service), host="127.0.0.1", port=port, access_log=None)
