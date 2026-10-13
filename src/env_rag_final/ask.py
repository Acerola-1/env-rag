"""Direct, deterministic enumeration questions. No gold, replay or model calls.

Only explicit catalog identities define document scopes. Keyword discovery is
kept for audit but never promoted into a confirmed target. Existing expansion,
pagination and independent source re-read contracts are reused unchanged.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import asyncpg

from . import answer as an
from .search.expand import _requested_targets, expand_candidates
from .search.index import check_search_stale
from .search.query import _CODE_IN_QUERY, SearchResult, _split_codes, _version_matches, run_query
from .search.tokenizer import normalize_text

_DOCS = """SELECT doc_id, doc_name, title, self_code, self_code_version
 FROM env_rag.documents WHERE workspace=$1 AND snapshot_id=$2 ORDER BY doc_id"""
_JUDGEMENT = re.compile(r"是否|是不是|相同|同一张|区别|差异|比较|对比|为什么|原因|优劣")
_FILES = re.compile(r"文件|文档|年报|公报")
_ENUM = re.compile(
    r"列出|枚举|清单|哪些|哪几|全部|所有|逐条|分类|类别|分级|术语|定义|共有几项|多少项"
)


@dataclass(frozen=True)
class Question:
    text: str
    kind: str = "auto"
    document: str | None = None  # exact catalog doc_name or doc_id, never fuzzy
    code: str | None = None
    version: str | None = None
    scope: str | None = None  # e.g. 第3章 or 4.1.1 至 4.1.5
    scope_id: str | None = None
    table_number: str | None = None
    chapter_scope: str | None = None
    workspace: str = "default"
    top_k: int = 20

    def prepare(self) -> tuple[str, str]:
        if not self.text.strip():
            raise ValueError("问题不能为空")
        if self.kind not in ("auto", "files", "prose", "table"):
            raise ValueError("kind must be auto/files/prose/table")
        # The default-only restriction is replaced by registry validation, not
        # removed: 'default' keeps its historical verified identity and any
        # other value must be a registered, active workspace.
        from env_rag_final.access.registry import resolve_cli_workspace

        resolve_cli_workspace(self.workspace)
        if type(self.top_k) is not int or not 1 <= self.top_k <= 100:
            raise ValueError("top_k must be an integer in 1..100")
        if self.version and not self.code:
            raise ValueError("--version 必须与 --code 一起使用")
        if self.scope_id and (self.scope or self.table_number):
            raise ValueError("--scope-id 不能与 --scope/--table-number 同时指定")
        if self.table_number and not re.fullmatch(r"[A-Z]?\d+(?:\.\d+)?", self.table_number):
            raise ValueError("table_number must be a table identifier such as 1 or A1")
        if self.chapter_scope and not self.table_number:
            raise ValueError("--chapter-scope 需要 --table-number")
        probe = SearchResult("intent", self.workspace)
        probe.query_text = self.text
        named_targets = _requested_targets(probe)
        if self.table_number and any(
            t["kind"] == "table" and t["value"] != self.table_number for t in named_targets
        ):
            raise ValueError("问题中表号与 --table-number 冲突")
        if self.scope:
            probe.query_text = self.scope
            explicit = _requested_targets(probe)
            if not explicit or any(t["kind"] == "table" for t in explicit):
                raise ValueError("--scope 必须是正文章节/条款范围；表格使用 --table-number")
            if named_targets and named_targets != explicit:
                raise ValueError("问题中范围与 --scope 冲突")
        if self.scope_id and named_targets:
            raise ValueError("--scope-id 请配合不含其他范围的提问，以免覆盖题面范围")
        query = self.text.strip()
        if self.code:
            codes, rest = _split_codes(self.code)
            if len(codes) != 1 or rest.strip():
                raise ValueError("--code 必须是一个有效标准号")
            c = codes[0]
            if self.version and not re.fullmatch(r"\d{2}|\d{4}", self.version):
                raise ValueError("--version must be a two- or four-digit year")
            if self.version and c["version"] and c["version"] != self.version:
                raise ValueError("--code 与 --version 冲突")
            edition = self.version or c["version"]
            selected = {"code": c["code"], "version": edition}
            for named in _split_codes(query)[0]:
                if named["code"] != selected["code"] or (
                    named["version"] and edition and named["version"] != edition
                ):
                    raise ValueError("问题中标准号/版本与显式选择冲突")
            canonical = c["code"] + ("-" + edition if edition else "")
            # A user-selected edition refines a bare code in the question.
            # Appending a versioned branch would otherwise UNION all editions
            # from the original bare branch with the selected edition.
            named = bool(_split_codes(query)[0])
            query = normalize_text(query)
            if edition:
                query = _CODE_IN_QUERY.sub(canonical, query)
            if not named:
                query += " " + canonical
        if self.scope:
            query += " " + self.scope
        if self.table_number:
            query += " 表" + self.table_number
        probe = SearchResult("intent", self.workspace)
        probe.query_text = query
        targets = _requested_targets(probe)
        has_table = any(t["kind"] == "table" for t in targets)
        has_prose = bool(self.scope_id) or any(t["kind"] != "table" for t in targets)
        kind = self.kind
        if kind == "auto":
            kind = (
                "table"
                if has_table
                else "prose"
                if has_prose
                else ("files" if _FILES.search(query) else "prose")
            )
        if kind == "files" and (self.document or targets or self.scope_id):
            raise ValueError("文件集合问题请用标准号或名称谓词；不要同时指定章节/单个文件")
        if kind == "prose" and has_table or kind == "table" and has_prose:
            raise ValueError("同时出现正文与表格范围，请拆成两次提问")
        return query, kind


def _identity(guard: dict) -> dict:
    return {
        k: guard.get(k)
        for k in ("search_id", "catalog_snapshot_id", "source_fingerprint", "expected_search_id")
    }


def _coverage(result, expansions, doc_enum, items, problems) -> str:
    states = [result.status] + [
        e.get("status") or e.get("coverage_status") or "partial" for e in expansions
    ]
    if doc_enum:
        states.append(doc_enum.get("coverage_status") or "partial")
    if "stale" in states:
        return "stale"
    if "missing" in states:
        return "missing"
    if "ambiguous" in states:
        return "ambiguous"
    if problems or not items or any(s not in ("ok", "complete") for s in states):
        return "partial"
    for e in expansions + ([doc_enum] if doc_enum else []):
        if e.get("members_total") != e.get("members_processed") or e.get("fail_stage"):
            return "partial"
    for it in items:
        cit = it.get("citation") or {}
        if not (it.get("citation_verified") is True and it.get("citation_reverified") is True):
            return "partial"
        if not all(cit.get(k) for k in ("workspace", "doc_id", "snapshot_id")):
            return "partial"
        if (
            cit.get("workspace") != result.workspace
            or cit.get("snapshot_id") != result.catalog_snapshot_id
            or cit.get("doc_id") != it.get("doc_id")
        ):
            return "partial"
    return "complete"


async def _select_documents(conn, request, result) -> list[dict]:
    """Canonical current catalog, all editions; no discovery/top-k selection."""
    rows = [dict(r) for r in await conn.fetch(_DOCS, request.workspace, result.catalog_snapshot_id)]
    result.catalog_selection_sha = _catalog_sha(rows)
    branches = _split_codes(result.query_text)[0]
    if request.document:
        rows = [r for r in rows if request.document in (r["doc_id"], r["doc_name"])]
        if not rows:
            result.status = "missing"
            result.notes.append("显式指定的文件不在当前目录（只接受完整文件名或 doc_id）")
            return []
    elif not branches:
        result.status = "ambiguous"
        result.notes.append("没有确定目标文件：请指定 --document 或 --code；关键词发现不等于范围")
        return []
    if branches:
        matched = []
        for b in branches:
            found = [
                r
                for r in rows
                if r.get("self_code") == b["code"]
                and (
                    not b["version"]
                    or _version_matches(r.get("self_code_version"), b["version"], False)
                )
            ]
            if not found:
                result.status = "missing" if not request.document else "ambiguous"
                result.notes.append(f"目录未确认请求目标 {b['code']}/{b['version']}，不替代版本")
            for row in found:
                if row not in matched:
                    matched.append(row)
        rows = matched
    return rows


def _catalog_sha(rows) -> str:
    return hashlib.sha256(
        json.dumps([dict(r) for r in rows], ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


async def ask_question(request: Question, values: dict, *, conn=None) -> dict:
    """Owning free-form entry. Owned connections are READ ONLY from connect.

    Unsupported intent is refused before any backend. Result guards are current
    observations, not the historical benchmark's gold/model configuration anchor.
    Infrastructure failures are non-success records; business uncertainty is data.
    """
    query, kind = request.prepare()
    start = time.monotonic()
    out = {
        "query_id": "ask-" + uuid.uuid4().hex[:12],
        "query": request.text,
        "effective_query": query,
        "kind": kind,
        "workspace": request.workspace,
        "coverage_status": "partial",
        "answer": {"items": []},
        "flags": [],
        "model_calls_used": 0,
        "embedding_calls": 0,
        "rerank_calls": 0,
        "original_local_baseline": "unverified",
        "evidence_mode": "caller_supplied_connection"
        if conn is not None
        else "production_readonly",
    }
    if _JUDGEMENT.search(request.text) or not (
        _ENUM.search(request.text) or request.scope or request.scope_id or request.table_number
    ):
        out["coverage_status"] = "ambiguous"
        out["evidence_mode"] = "preflight_no_backend"
        out["flags"].append("此入口只回答枚举清单；判断、对比或开放问答不能用清单代答")
        return out
    owned = conn is None
    before = None
    try:
        if owned:
            conn = await asyncpg.connect(
                host=values["POSTGRES_HOST"],
                port=int(values["POSTGRES_PORT"]),
                user=values["POSTGRES_USER"],
                password=values["POSTGRES_PASSWORD"],
                database=values["POSTGRES_DATABASE"],
                timeout=15,
                statement_cache_size=0,
                server_settings={
                    "default_transaction_read_only": "on",
                    "statement_timeout": "30000",
                },
            )
        before = await check_search_stale(conn, request.workspace)
        out["identity_before"] = before
        if before.get("state") != "current":
            out["coverage_status"] = "stale"
            out["flags"].append("当前来源/目录/搜索索引不一致，拒绝展开；本入口不会自动重建")
        else:
            await _answer_current(conn, request, query, kind, values, before, out)
    except Exception as exc:  # terminal keeps secrets out of printed diagnostics
        out["coverage_status"] = "partial"
        out["failure"] = {"stage": "enumeration", "error_type": type(exc).__name__}
    finally:
        if conn is not None:
            try:
                after = await check_search_stale(conn, request.workspace)
                out["identity_after"] = after
                if after.get("state") != "current" or (
                    before and _identity(before) != _identity(after)
                ):
                    out["coverage_status"] = "stale"
                    out["flags"].append("发布前身份变化，已有条目仅供诊断")
            except Exception as exc:
                out["failure_after"] = {"error_type": type(exc).__name__}
                out["coverage_status"] = "stale"
            if owned:
                try:
                    await conn.close()
                except Exception as exc:
                    out["failure_close"] = {"error_type": type(exc).__name__}
                    out["coverage_status"] = "partial"
        out["elapsed_ms"] = round((time.monotonic() - start) * 1000)
    return out


async def _answer_current(conn, request, query, kind, values, before, out):
    if request.document:
        result = SearchResult(out["query_id"], request.workspace)
        result.query_text = query
        result.search_id = before["search_id"]
        result.catalog_snapshot_id = before["catalog_snapshot_id"]
        result.source_snapshot_id = before["source_fingerprint"]
        result.parsed_codes = _split_codes(query)[0]
        result.parsed_code = result.parsed_codes[0] if result.parsed_codes else None
    else:
        result = await run_query(
            conn, query, top_k=request.top_k, workspace=request.workspace, source_values=values
        )
    out["discovery"] = result.to_dict()
    if result.status in ("stale", "missing"):
        out["coverage_status"] = result.status
        out["flags"].extend(result.notes)
        return
    docs = []
    if kind != "files":
        docs = await _select_documents(conn, request, result)
        out["selected_documents"] = docs
        if result.status in ("missing", "ambiguous"):
            out["coverage_status"] = result.status
            out["flags"].extend(result.notes)
            return
        # Verified metadata defines membership; keyword candidate truncation
        # cannot hide an edition or introduce a noise document.
        result.candidates = [
            dict(
                r,
                workspace=request.workspace,
                discovery="explicit_document" if request.document else "code_exact",
            )
            for r in docs
        ]
        result.status = "ok"
    if request.chapter_scope:
        from .enumerate_.table_enum import enumerate_table

        expansions = []
        for doc in docs:
            r = await enumerate_table(
                conn,
                request.workspace,
                doc["doc_id"],
                request.table_number,
                chapter_scope=request.chapter_scope,
            )
            expansions.append(
                dict(
                    r.to_dict(),
                    kind="table",
                    doc_id=doc["doc_id"],
                    table_number=request.table_number,
                )
            )
        result.trace.append({"stage": "scope_expansion", "expansions": expansions})
    else:
        await expand_candidates(
            conn,
            result,
            request.workspace,
            values,
            scope_id=request.scope_id,
            table_number=request.table_number,
            expand_docs=(kind == "files"),
        )
    expansions, doc_enum = an._expansion_stages(result)
    parsed_dirs, problems = {}, []
    for exp in expansions:
        doc_id = exp["doc_id"]
        name = await conn.fetchval(
            an._DOC_NAME_SQL, request.workspace, result.catalog_snapshot_id, doc_id
        )
        pdir = an._doc_parsed_dir(name)
        parsed_dirs[doc_id] = pdir
        items = exp.get("items") or []
        verify = (
            an._reverify_table_items if exp.get("kind") == "table" else an._reverify_prose_items
        )
        problems.extend(verify(items, pdir))
    rendered = await an._render_with_docs(
        {"files": "file_enum", "prose": "prose_enum", "table": "table_enum"}[kind],
        result,
        expansions,
        doc_enum,
        None,
        {"conn": conn},
        {"workspace": request.workspace, "flags": out["flags"]},
        result.catalog_snapshot_id,
        parsed_dirs,
    )
    out["answer"] = rendered
    out["answer"]["items_count"] = len(rendered["items"])
    doc_names = {d["doc_id"]: d["doc_name"] for d in docs}
    for item in rendered["items"]:
        if item.get("doc_id") in doc_names:
            item["doc_name"] = doc_names[item["doc_id"]]
    out["coverage_status"] = _coverage(result, expansions, doc_enum, rendered["items"], problems)
    out["expansions"] = [{k: v for k, v in e.items() if k != "items"} for e in expansions]
    out["document_enumeration"] = doc_enum
    out["reverification"] = {"items_checked": len(rendered["items"]), "problems": problems}
    out["flags"].extend(result.notes)
    for e in expansions + ([doc_enum] if doc_enum else []):
        out["flags"].extend(str(w) for w in e.get("warnings") or [])
        for key in ("note", "reason"):
            if e.get(key):
                out["flags"].append(str(e[key]))
        if e.get("fail_stage"):
            out["flags"].append("范围读取未完成：" + str(e["fail_stage"]))
    if kind != "files":
        current_rows = await conn.fetch(_DOCS, request.workspace, result.catalog_snapshot_id)
        current_sha = _catalog_sha(current_rows)
        out["catalog_selection"] = {
            "before_sha256": result.catalog_selection_sha,
            "after_sha256": current_sha,
        }
        if current_sha != result.catalog_selection_sha:
            out["coverage_status"] = "stale"
            out["flags"].append("同一快照内目录身份字段发生变化，已读条目仅作诊断")
    if not expansions and not doc_enum:
        out["flags"].append("范围未确认；请给出 --scope、--scope-id 或 --table-number")


def format_answer(result: dict) -> str:
    lines = [
        f"问题：{result['query']}",
        f"状态：{result['coverage_status']}",
        f"交付项目数：{len(result['answer']['items'])}",
    ]
    for i, it in enumerate(result["answer"]["items"], 1):
        text = (
            it.get("doc_name")
            if it.get("kind") == "document"
            else it.get("text") or " | ".join(it.get("cells") or [])
        )
        cit = it.get("citation") or {}
        locator = cit.get("locator") or cit.get("table_id") or "目录行"
        position = f"，原始行 {cit['row_in_fragment']}" if "row_in_fragment" in cit else ""
        source = it.get("doc_name") or it.get("doc_id")
        lines.append(f"{i}. {text}\n   来源：{source} / {locator}{position}")
    for note in result.get("flags") or []:
        lines.append("说明：" + note)
    lines.append("模型/embedding/精排调用：0；原始 local 对照尚未验证。")
    return "\n".join(lines)


def write_result(path: Path, result: dict) -> None:
    """Never overwrite a historical output. JSON retains full citations."""
    with path.open("x", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")
