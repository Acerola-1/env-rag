"""Owning comparison service: one retrieval record, optional later generation."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
import time
import uuid
from pathlib import Path

import asyncpg

from env_rag_final import ask
from env_rag_final.config import read_environment
from env_rag_final.local_adapter import _capture_production_identity, _identity_drift
from env_rag_final.search import tokenizer as tk
from env_rag_final.search.index import check_search_stale
from env_rag_final.search.query import _rank_chunks, _split_codes, _version_matches, run_query

from .budget import BudgetExhausted, InteractiveLedger, Ledger
from .native import MODES, ROOT, NativeBackend, safe_error, sha
from .support import table_summary_problems

STRATEGIES = (*MODES, "pg", *("pg+" + m for m in MODES), "bypass")
GOAL_BUDGET = ROOT / "reports/rag-web-20261010-r1/goal-budget.json"
ANSWER_INSTRUCTION = (
    "依据本次证据用中文回答；引用以 [数字] 标出，仅可引用本次证据。"
    "若有完整枚举，逐项保留，不能只举例；不足或歧义明确说明。"
    "数值、单位、等级、平均时间不得跨行或跨版本替换。"
    "资料性附录必须标为资料性附录，不能说成正文章节要求。\n证据："
)


def bounded_context(rec, limit=40_000):
    """Whole evidence only: preserve ranked order, explicitly expose exclusions."""
    data = {"chunks": [], "entities": [], "relations": []}
    excluded = []
    for kind in data:
        for i, value in enumerate(rec[kind], 1):
            entry = (
                {"id": str(i), "doc_id": value["doc_id"], "content": value["content"]}
                if kind == "chunks"
                else value
            )
            data[kind].append(entry)
            if len(json.dumps(data, ensure_ascii=False)) > limit:
                data[kind].pop()
                excluded.append(
                    {"kind": kind, "index": i - 1, "reason": "whole_evidence_context_budget"}
                )
    rec["generation_exclusions"] = excluded
    rec["used_evidence"] = [
        {"chunk_id": rec["chunks"][int(x["id"]) - 1]["chunk_id"], "doc_id": x["doc_id"]}
        for x in data["chunks"]
    ]
    return json.dumps(data, ensure_ascii=False)


def canonical_identity(value):
    """Normalize the adapter's wrapper before comparing actual fields."""
    if not isinstance(value, dict):
        raise ValueError("身份记录格式错误")
    if "identity" in value:
        if value.get("matches_frozen") is not True or value.get("problems"):
            raise ValueError("现场冻结守卫拒绝")
        value = value["identity"]
    required = (
        "public_counts",
        "catalog_active",
        "source_fingerprint",
        "search_active",
        "gold_sha",
        "env_sha",
    )
    if not isinstance(value, dict) or any(not value.get(k) for k in required):
        raise ValueError("身份记录缺少必要实际字段")
    return value


def sanitize(value, values):
    """Sanitize recursively before any record reaches disk or browser."""
    secrets = sorted(
        {
            v
            for k, v in values.items()
            if v
            and (
                re.search(r"(?:^|_)(?:API_KEY|KEY|PASSWORD|TOKEN|SECRET)$", k.upper())
                or k.upper().endswith(("DSN", "DATABASE_URL"))
            )
        },
        key=len,
        reverse=True,
    )

    def walk(v):
        if isinstance(v, str):
            for secret in secrets:
                v = v.replace(secret, "<redacted>")
            return v
        if isinstance(v, dict):
            result = {k: walk(x) for k, x in v.items()}
            if (
                v.get("chunk_id")
                and isinstance(v.get("content"), str)
                and (
                    result["content"] != v["content"]
                    or v.get("content_sha256") != sha(result["content"])
                )
            ):
                result["content_redacted"] = True
                result["display_content_sha256"] = sha(result["content"])
            return result
        if isinstance(v, list):
            return [walk(x) for x in v]
        return v

    return walk(value)


def merge_chunks(*groups):
    by_id = {}
    for group in groups:
        for c in group:
            key = (c["workspace"], c["chunk_id"])
            if key[0] != "default" or not c.get("verified"):
                raise ValueError("unverified/cross-workspace evidence")
            if key in by_id:
                existing = by_id[key]
                if existing["doc_id"] != c["doc_id"] or existing["content"] != c["content"]:
                    raise ValueError("conflicting source ownership")
                existing["sources"] = list(dict.fromkeys(existing["sources"] + c["sources"]))
                existing.setdefault("paths", []).extend(c.get("paths") or [])
            else:
                by_id[key] = dict(c)
    return list(by_id.values())


def enumeration_intent(query, options):
    if re.search(r"脚注.*(?:分别|适用|含义|意思|解释)", query) and not (
        re.search(r"列出|枚举|清单|全部|所有|逐条", query)
        or any(options.get(k) for k in ("scope", "scope_id", "table_number"))
    ):
        return False
    return bool(
        (
            ask._ENUM.search(query)
            or any(options.get(k) for k in ("scope", "scope_id", "table_number"))
        )
        and not ask._JUDGEMENT.search(query)
    )


class ComparisonService:
    def __init__(
        self, report_dir: Path, *, budget_path: Path | None = None, interactive: bool = False
    ):
        self.directory = report_dir.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.values = read_environment(ROOT / ".env")
        self.env_sha = hashlib.sha256((ROOT / ".env").read_bytes()).hexdigest()
        # New evidence directories do not create new paid allowances. The CLI
        # has no budget-path override; tests use an explicit isolated ledger.
        self.ledger = (
            InteractiveLedger(budget_path or ROOT / "reports/rag-web-interactive/usage.json")
            if interactive
            else Ledger(budget_path or GOAL_BUDGET)
        )
        self.native = NativeBackend(self.values, self.ledger)
        self.lock = asyncio.Lock()
        self.records = {}
        self.native_cache = {}
        self.batch_ids = {}
        self.identity_anchor = (
            canonical_identity(json.loads((self.directory / "identity-anchor.json").read_text()))
            if (self.directory / "identity-anchor.json").exists()
            else None
        )
        self.restore_saved_records()

    def restore_saved_records(self):
        """Only sealed, same-Goal records can survive an intentional restart.

        This never imports historical benchmark answers. A saved retrieval is
        eligible for reuse only with original query-body SHA and goal identity;
        the next execute/generate still performs its live pre/post guard.
        """
        seals = [self.directory / "owned-record-seals.json"] + sorted(
            self.directory.glob("owned-record-seals-*.json")
        )
        seals = [s for s in seals if s.exists()]
        if not seals:
            return
        entries = {}
        for seal in seals:
            entries.update(json.loads(seal.read_text()))
        for name, expected in entries.items():
            if Path(name).name != name or not name.startswith("web-") or not name.endswith(".json"):
                raise ValueError("检索记录封存文件名无效")
            path = self.directory / name
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("检索记录封存字节已改变")
            rec = json.loads(path.read_text())
            rid = rec.get("record_id")
            if not isinstance(rid, str) or rec.get("workspace") != "default":
                raise ValueError("保存的检索身份无效")
            if _identity_drift(canonical_identity(rec["identity_before"]), self.identity_anchor):
                raise ValueError("保存的检索不是本 Goal 身份代次")
            self.records[rid] = rec
            candidate = rec.get("native")
            if candidate:
                from .native import operate

                code = Path(inspect.getfile(operate))
                if candidate["provenance"]["operate_sha256"] != sha(code.read_text()):
                    continue
                key = (rec["query"], candidate["mode"], rec["parameters"]["top_k"])
                self.native_cache[key] = candidate

    def config_check(self):
        if hashlib.sha256((ROOT / ".env").read_bytes()).hexdigest() != self.env_sha:
            raise ValueError("配置文件发生变化；本批停止，不自动接受新配置")

    async def connect(self):
        v = self.values
        return await asyncpg.connect(
            host=v["POSTGRES_HOST"],
            port=int(v["POSTGRES_PORT"]),
            user=v["POSTGRES_USER"],
            password=v["POSTGRES_PASSWORD"],
            database=v["POSTGRES_DATABASE"],
            timeout=15,
            statement_cache_size=0,
            server_settings={"default_transaction_read_only": "on", "statement_timeout": "30000"},
        )

    async def identity(self):
        self.config_check()
        got = canonical_identity(await _capture_production_identity(self.values))
        if self.identity_anchor is not None and _identity_drift(self.identity_anchor, got):
            raise ValueError("生产身份与本次 Goal 配置锚不符，拒绝新增检索/生成")
        if self.identity_anchor is None:
            self.identity_anchor = got
            self.write_new("identity-anchor.json", got)
        return got

    async def hydrate_chunks(self, rec):
        """Redacted display records aren't raw input. Re-read exact source SHA."""
        chunks = rec.get("chunks", [])
        missing = {c["chunk_id"] for c in chunks if sha(c["content"]) != c["content_sha256"]}
        if not missing:
            return
        conn = await self.connect()
        try:
            rows = await conn.fetch(
                """SELECT id,full_doc_id,content FROM public.lightrag_doc_chunks
                WHERE workspace=$1 AND id=ANY($2)""",
                "default",
                sorted(missing),
            )
        finally:
            await conn.close()
        by_id = {r["id"]: r for r in rows}
        replacements = {}
        for c in chunks:
            if c["chunk_id"] not in missing:
                continue
            row = by_id.get(c["chunk_id"])
            if (
                not row
                or row["full_doc_id"] != c["doc_id"]
                or sha(row["content"]) != c["content_sha256"]
            ):
                raise ValueError("保存的展示原文无法重新核对生产来源")
            replacements[c["chunk_id"]] = (c["content"], row["content"])
            c["content"] = row["content"]
            c.pop("content_redacted", None)
            c.pop("display_content_sha256", None)
        native = rec.get("native")
        if native:
            for c in native["chunks"]:
                if c["chunk_id"] in replacements:
                    c["content"] = replacements[c["chunk_id"]][1]
            prompt = native.get("native_prompt") or ""
            for old, new in replacements.values():
                prompt = prompt.replace(
                    json.dumps(old, ensure_ascii=False)[1:-1],
                    json.dumps(new, ensure_ascii=False)[1:-1],
                )
                prompt = prompt.replace(old, new)
            native["native_prompt"] = prompt
            if "<redacted>" in prompt:
                native["prompt_has_unresolved_display_redaction"] = True

    def write_new(self, name, record):
        with (self.directory / name).open("x", encoding="utf-8") as f:
            json.dump(sanitize(record, self.values), f, ensure_ascii=False, indent=2)

    async def pg(self, query, request_id, options, top_k):
        conn = await self.connect()
        try:
            guard = await check_search_stale(conn)
            if guard.get("state") != "current":
                raise ValueError("PG 来源/目录/索引不一致")
            docs = await conn.fetch(
                """SELECT doc_id,doc_name,title,self_code,self_code_version FROM env_rag.documents
                   WHERE workspace=$1 AND snapshot_id=$2 ORDER BY doc_name""",
                "default",
                guard["catalog_snapshot_id"],
            )
            selection_options = dict(options)
            named_title = re.search(r"《([^》]+)》", query)
            title_candidates = []
            if named_title and not options.get("document"):
                title = re.sub(r"\s+", "", named_title.group(1))
                title_candidates = [
                    dict(d) for d in docs if re.sub(r"\s+", "", d.get("title") or "") == title
                ]
                if len(title_candidates) == 1:
                    selection_options["document"] = title_candidates[0]["doc_id"]
            enum = None
            if enumeration_intent(query, options):
                enum = await ask.ask_question(
                    ask.Question(query, top_k=top_k, **selection_options), self.values, conn=conn
                )
                if title_candidates:
                    enum["title_selection"] = {
                        "requested_title": named_title.group(1),
                        "candidates": title_candidates,
                        "basis": "exact_catalog_title",
                    }
                discovered = enum.get("discovery") or {}
            else:
                discovered = (
                    await run_query(conn, query, top_k=top_k, source_values=self.values)
                ).to_dict()
            # Discovery and full-range evidence remain separately typed.
            candidates = discovered.get("discovery_candidates")
            candidates = discovered.get("candidates", []) if candidates is None else candidates
            if enum is None:
                codes, rest = _split_codes(query)
                target_docs = {c["doc_id"] for c in candidates if c.get("doc_id")}
                # A filename match is a discovery clue, never a self-code or a
                # confirmed enumeration target. Exact code/year must coexist.
                if codes and not target_docs:
                    for d in docs:
                        name_codes, _ = _split_codes(d["doc_name"])
                        if any(
                            n["code"] == q["code"]
                            and (
                                not q["version"]
                                or _version_matches(n["version"], q["version"], False)
                            )
                            for n in name_codes
                            for q in codes
                        ):
                            target_docs.add(d["doc_id"])
                    discovered["name_discovery_doc_ids"] = sorted(target_docs)
                    discovered["name_discovery_basis"] = "filename_reference_only_not_self_code"
                tokens = tk.query_terms(rest)
                if target_docs and tokens:
                    for op in (" & ", " | "):
                        expression = op.join(t.to_tsquery() for t in tokens)
                        ranks = await _rank_chunks(
                            conn,
                            guard["search_id"],
                            expression,
                            top_k,
                            "default",
                            sorted(target_docs),
                        )
                        discovered["trace"].append(
                            {
                                "stage": "within_document_lexical",
                                "tsquery": expression,
                                "hits": len(ranks),
                                "doc_ids": sorted(target_docs),
                            }
                        )
                        if ranks:
                            candidates = [
                                *candidates,
                                *[
                                    {
                                        "workspace": "default",
                                        **dict(r),
                                        "target_type": "chunk",
                                        "stage": "within_document_lexical",
                                    }
                                    for r in ranks
                                ],
                            ]
                            discovered["discovery_candidates"] = candidates
                            break
            ids = {c["chunk_id"] for c in candidates if c.get("chunk_id")}
            full_items = (enum or {}).get("answer", {}).get("items", [])
            for item in full_items:
                cit = item.get("citation") or {}
                ids.update(cit.get("chunk_ids") or [])
                for segment in cit.get("unit_segments") or []:
                    ids.update(segment.get("chunk_ids") or [])
            rows = (
                await conn.fetch(
                    """SELECT c.id,c.workspace,c.full_doc_id,c.content,c.heading,c.file_path,d.doc_name
                   FROM public.lightrag_doc_chunks c
                   JOIN public.lightrag_doc_full d ON d.workspace=c.workspace AND d.id=c.full_doc_id
                   WHERE c.workspace=$1 AND c.id=ANY($2)""",
                    "default",
                    sorted(ids),
                )
                if ids
                else []
            )
            if len(rows) != len(ids):
                raise ValueError("PG chunk 回读缺失")
            chunks = [
                {
                    "workspace": r["workspace"],
                    "chunk_id": r["id"],
                    "doc_id": r["full_doc_id"],
                    "doc_name": r["doc_name"],
                    "file_path": r["file_path"],
                    "content": r["content"],
                    "content_sha256": sha(r["content"]),
                    "heading": r["heading"],
                    "verified": True,
                    "sources": ["pg"],
                    "stage": "range_expansion" if enum else "discovery",
                    "paths": [c for c in candidates if c.get("chunk_id") == r["id"]],
                }
                for r in rows
            ]
            # Typed doc candidates are usable document metadata, never disguised
            # as chunks. The UI can clarify against these actual catalog rows.
            choices = [dict(d) for d in docs]
            codes = _split_codes(query)[0]
            if title_candidates:
                choices = title_candidates
            elif codes:
                choices = [
                    d
                    for d in choices
                    if any(
                        d["self_code"] == c["code"]
                        and (
                            not c["version"]
                            or _version_matches(d["self_code_version"], c["version"], False)
                        )
                        for c in codes
                    )
                ]
            return {
                "chunks": chunks,
                "enumeration": enum,
                "discovery": discovered,
                "choices": choices if enum and enum["coverage_status"] == "ambiguous" else [],
                "typed_targets": [c for c in candidates if not c.get("chunk_id")],
                "guard": guard,
                "request_id": request_id,
            }
        finally:
            await conn.close()

    async def execute(
        self, query, strategies, *, generate=False, top_k=20, options=None, submission_id=None
    ):
        if not isinstance(query, str) or not query.strip() or len(query) > 4000:
            raise ValueError("请输入 1–4000 字的问题")
        if not isinstance(strategies, list) or not strategies or len(strategies) > len(STRATEGIES):
            raise ValueError("请选择检索策略")
        if len(set(strategies)) != len(strategies) or any(s not in STRATEGIES for s in strategies):
            raise ValueError("策略无效或重复")
        if type(generate) is not bool or type(top_k) is not int or not 1 <= top_k <= 40:
            raise ValueError("参数无效")
        options = options or {}
        if not isinstance(options, dict) or set(options) - {
            "document",
            "code",
            "version",
            "scope",
            "scope_id",
            "table_number",
            "chapter_scope",
            "kind",
        }:
            raise ValueError("澄清参数无效")
        # Validate chosen fields, but do not force general questions through enum.
        ask.Question(query, top_k=top_k, **options).prepare()
        submission_id = submission_id or uuid.uuid4().hex
        signature = sha(json.dumps([query, strategies, generate, top_k, options], sort_keys=True))
        async with self.lock:
            if submission_id in self.batch_ids:
                old = self.batch_ids[submission_id]
                if old["signature"] != signature:
                    raise ValueError("提交 ID 不可复用于不同问题")
                return old["result"]
            try:
                before = await self.identity()
            except Exception as exc:
                self.write_new(
                    "rejected-" + uuid.uuid4().hex + ".json",
                    {
                        "stage": "identity-before",
                        "query": query,
                        "failure": safe_error(exc, self.values),
                        "budget": self.ledger.snapshot(),
                    },
                )
                raise
            results = []
            pg_record = None
            for strategy in strategies:
                started = time.monotonic()
                rid = "web-" + uuid.uuid4().hex[:16]
                rec = {
                    "record_id": rid,
                    "query": query,
                    "strategy": strategy,
                    "workspace": "default",
                    "parameters": {
                        "top_k": top_k,
                        "rerank": False,
                        "temperature": 0,
                        "options": options,
                    },
                    "status": "retrieved",
                    "chunks": [],
                    "entities": [],
                    "relations": [],
                    "answer": None,
                    "warnings": [],
                    "generation_status": "not_requested",
                    "enumeration": None,
                }
                try:
                    native = None
                    if strategy == "pg" or strategy.startswith("pg+"):
                        if pg_record is None:
                            pg_record = await self.pg(query, rid, options, top_k)
                        rec["pg"] = pg_record
                        rec["enumeration"] = pg_record["enumeration"]
                        rec["status"] = (
                            rec["enumeration"]["coverage_status"]
                            if rec["enumeration"]
                            else pg_record["discovery"].get("status", "retrieved")
                        )
                        rec["chunks"] = pg_record["chunks"]
                        if not rec["enumeration"] and rec["status"] == "missing" and rec["chunks"]:
                            rec["status"] = "retrieved"
                            rec["warnings"].append(
                                "PG 目录未确认编号；发现线索不代表自身编号或全库缺失，保留其他检索证据供核对"
                            )
                    if strategy not in ("pg", "bypass") and rec["status"] not in (
                        "missing",
                        "stale",
                    ):
                        mode = strategy.removeprefix("pg+")
                        key = (query, mode, top_k)
                        native = self.native_cache.get(key)
                        rec["retrieval_reused"] = native is not None
                        if native is None:
                            try:
                                native = await self.native.retrieve(query, mode, rid, top_k=top_k)
                                self.native_cache[key] = native
                            except Exception as exc:
                                if not strategy.startswith("pg+"):
                                    raise
                                rec["degraded"] = "pg-only-degraded"
                                rec["local_failure"] = safe_error(exc, self.values)
                                rec["failure_receipts"] = getattr(exc, "native_receipts", [])
                                rec["status"] = (
                                    "budget_failure"
                                    if isinstance(exc, BudgetExhausted)
                                    else "degraded"
                                )
                        if native:
                            await self.hydrate_chunks(
                                {"chunks": native["chunks"], "native": native}
                            )
                            rec["native"] = native
                            if native.get("degraded"):
                                rec["native_degraded"] = native["degraded"]
                                rec["warnings"].append(
                                    "原生服务发生降级；失败凭证保留，原始模式上下文不伪造为完整"
                                )
                            rec["chunks"] = merge_chunks(rec["chunks"], native["chunks"])
                            rec.update(entities=native["entities"], relations=native["relations"])
                    if strategy.startswith("pg+") and rec["status"] in ("missing", "stale"):
                        rec["native_skipped"] = rec["status"]
                    rec["retrieval_ms"] = round((time.monotonic() - started) * 1000)
                    rec["evidence_sha256"] = sha(
                        json.dumps(
                            [rec["chunks"], rec["entities"], rec["relations"], rec["enumeration"]],
                            ensure_ascii=False,
                            sort_keys=True,
                            default=str,
                        )
                    )
                    self.records[rid] = rec
                    if generate:
                        try:
                            await self._generate(rec)
                        except Exception as exc:
                            rec["generation_status"] = (
                                "budget_exhausted"
                                if isinstance(exc, BudgetExhausted)
                                else "model_failure"
                            )
                            rec["generation_failure"] = safe_error(exc, self.values)
                            rec["answer_call"] = getattr(exc, "web_receipt", None)
                except Exception as exc:
                    rec["status"] = (
                        "budget_failure" if isinstance(exc, BudgetExhausted) else "failure"
                    )
                    rec["failure"] = safe_error(exc, self.values)
                    rec["failure_receipts"] = getattr(exc, "native_receipts", [])
                    if getattr(exc, "web_receipt", None):
                        rec["failure_receipts"].append(exc.web_receipt)
                rec["elapsed_ms"] = round((time.monotonic() - started) * 1000)
                rec["identity_before"] = before
                self.records[rid] = rec
                results.append(rec)
            after = None
            identity_error = None
            try:
                after = await self.identity()
            except Exception as exc:
                identity_error = safe_error(exc, self.values)
            for rec in results:
                rec["identity_after"] = after
                if identity_error or (after and _identity_drift(before, after)):
                    rec["status"] = "stale"
                    rec["warnings"].append("发布后身份核验失败，结果仅供诊断")
                from .server import resolve_document, resolve_source

                for index, c in enumerate(rec["chunks"]):
                    c["pdf_available"] = resolve_source(rec, index, "pdf") is not None
                    c["text_available"] = resolve_source(rec, index, "text") is not None
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
                self.write_new(rec["record_id"] + ".json", rec)
            out = sanitize(
                {
                    "submission_id": submission_id,
                    "results": results,
                    "budget": self.ledger.snapshot(),
                },
                self.values,
            )
            self.batch_ids[submission_id] = {"signature": signature, "result": out}
            return out

    async def _generate(self, rec):
        if rec["generation_status"] != "not_requested":
            return rec
        if rec["status"] in ("missing", "stale", "failure", "budget_failure"):
            rec["generation_status"] = "skipped"
            return rec
        native = rec.get("native")
        strategy = rec["strategy"]
        if strategy in MODES and rec.get("generation_profile") != "uniform_evidence":
            if native and native.get("prompt_has_unresolved_display_redaction"):
                raise ValueError("原生提示仍有展示掩码，未重新读取完整来源；禁止以展示文本生成")
            if not native or not native.get("native_prompt"):
                rec["generation_status"] = "no_context"
                return rec
            # Split only the final delimiter; the user question may contain the
            # same string, so use the known suffix, not an arbitrary first split.
            suffix = "\n\n---User Query---\n\n" + rec["query"]
            prompt = native["native_prompt"]
            if not prompt.endswith(suffix):
                raise ValueError("native prompt shape not recognized")
            system = prompt[: -len(suffix)]
        elif strategy == "bypass":
            system = "你是一个助手。此模式没有知识库检索，请明确区分常识与未经知识库核实的判断。"
        else:
            enum = rec["enumeration"]
            if enum and enum["coverage_status"] == "ambiguous":
                rec["generation_status"] = "needs_clarification"
                return rec
            selected = {d["doc_id"] for d in (enum or {}).get("selected_documents", [])}
            # All discovered noise remains inspectable. For a confirmed enum,
            # only evidence from that range can support the answer; discovery
            # never overrides the directory's scope membership.
            evidence = []
            for i, c in enumerate(rec["chunks"], 1):
                if enum and selected and c["doc_id"] not in selected:
                    c["not_used_reason"] = "outside_confirmed_enumeration_documents"
                    continue
                evidence.append({"id": str(i), "doc_id": c["doc_id"], "content": c["content"]})
            context = json.dumps(
                {
                    "chunks": evidence,
                    "entities": rec["entities"],
                    "relations": rec["relations"],
                    "enumeration": (enum or {}).get("answer"),
                },
                ensure_ascii=False,
            )
            if enum:
                # The range reader already projected exactly the requested
                # rows/clauses from raw chunks. Preserve that complete typed
                # set in the context, instead of sending unrelated tables that
                # happen to share a chunk. Native/PG provenance stays linked
                # by each item's original chunk_ids; all raw/graph discovery
                # remains available in the record.
                projected = []
                rec["generation_reference_map"] = {}
                for i, item in enumerate(enum.get("answer", {}).get("items", []), 1):
                    cit = item.get("citation") or {}
                    projected.append({"id": str(i), "item": item})
                    rec["generation_reference_map"][str(i)] = cit
                context = json.dumps(
                    {"range_status": enum["coverage_status"], "scope_evidence": projected},
                    ensure_ascii=False,
                )
                rec["graph_context_selection"] = "not_used_for_confirmed_enumeration_summary"
                rec["generation_evidence_projection"] = "verified_scope_items_from_merged_sources"
            if not enum:
                context = bounded_context(rec)
            if len(context) > 40_000:
                rec["generation_status"] = "context_budget_exceeded"
                rec["warnings"].append("证据仍完整保留；模型上下文超过 40k 字符，未截断调用")
                return rec
            system = ANSWER_INSTRUCTION + context
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": rec["query"]},
        ]
        rec["generation_context_sha256"] = sha(system)
        rec["generation_messages"] = messages
        if "used_evidence" not in rec:
            rec["used_evidence"] = [
                {"chunk_id": c["chunk_id"], "doc_id": c["doc_id"]}
                for c in rec["chunks"]
                if not c.get("not_used_reason")
            ]
        started = time.monotonic()
        text, receipt = await self.native.completion(
            messages, rec["record_id"], extra=(strategy == "pg" or strategy.startswith("pg+"))
        )
        rec.update(
            answer=text,
            generation_status="generated_pending_semantic_review",
            answer_call=receipt,
            generation_ms=round((time.monotonic() - started) * 1000),
        )
        ids = {str(i) for i in range(1, len(rec["chunks"]) + 1)}
        if strategy in MODES and rec.get("generation_profile") != "uniform_evidence":
            ids = {str(c.get("reference_id")) for c in rec["chunks"]}
        if rec.get("generation_reference_map"):
            ids = set(rec["generation_reference_map"])
        referenced = {
            m.group(1)
            for m in re.finditer(r"\[(?:citation:)?(\d+)\]", text)
            if not (
                re.fullmatch(r"(?:19|20)\d{2}", m.group(1))
                and re.match(r"\d*号", text[m.end() :])
                and "citation:" not in m.group(0)
            )
        }
        unknown = referenced - ids
        rec["citation_check"] = {
            "unknown_reference_ids": sorted(unknown),
            "semantic_support": "unreviewed",
            "table_value_problems": table_summary_problems(
                text, (rec.get("enumeration") or {}).get("answer", {}).get("items", [])
            ),
        }
        if (unknown or rec["citation_check"]["table_value_problems"]) and strategy != "bypass":
            rec["generation_status"] = "citation_failure"
        return rec

    async def generate_record(self, rid, *, profile=None):
        async with self.lock:
            self.config_check()
            if rid not in self.records:
                raise ValueError("检索记录不存在；请先提问")
            rec = self.records[rid]
            if (
                self.ledger.mode == "interactive"
                and profile is None
                and rec.get("generation_status") == "budget_exhausted"
                and not rec.get("answer_call")
            ):
                rec = json.loads(json.dumps(rec))
                rec["previous_generation_failure"] = rec.pop("generation_failure", None)
                rec["generation_status"] = "not_requested"
                rec["generation_retry_basis"] = "previous_app_budget_refusal_no_request"
            if profile is not None:
                if profile != "uniform_evidence" or rec["strategy"] not in MODES:
                    raise ValueError("实验生成口径无效")
                experiment_key = (rid, profile)
                if experiment_key in self.batch_ids:
                    return self.batch_ids[experiment_key]
                rec = json.loads(json.dumps(rec))
                rec.update(
                    record_id="web-" + uuid.uuid4().hex[:16],
                    generation_profile=profile,
                    generation_status="not_requested",
                    answer=None,
                    experiment_retrieval_record_id=rid,
                    answer_call=None,
                )
                rec.pop("used_evidence", None)
                rec.pop("citation_check", None)
                for i, c in enumerate(rec["chunks"], 1):
                    c["native_reference_id"] = c.get("reference_id")
                    c["reference_id"] = str(i)
            before = await self.identity()
            if rec.get("identity_before") and _identity_drift(
                canonical_identity(rec["identity_before"]), before
            ):
                raise ValueError("旧检索记录身份已变化，禁止生成")
            try:
                await self.hydrate_chunks(rec)
                await self._generate(rec)
            except Exception as exc:
                rec["generation_status"] = (
                    "budget_exhausted" if isinstance(exc, BudgetExhausted) else "model_failure"
                )
                rec["generation_failure"] = safe_error(exc, self.values)
                rec["answer_call"] = getattr(exc, "web_receipt", None)
            after = None
            identity_error = None
            try:
                after = await self.identity()
            except Exception as exc:
                identity_error = safe_error(exc, self.values)
            rec["generation_identity_after"] = after
            if identity_error or (after and _identity_drift(before, after)):
                rec["status"] = "stale"
                rec["generation_identity_error"] = identity_error or "identity drift"
                rec["warnings"].append("生成后身份核验失败，回答仅供诊断")
            self.write_new(rid + "-generation-" + uuid.uuid4().hex[:8] + ".json", rec)
            result = sanitize({**rec, "budget": self.ledger.snapshot()}, self.values)
            self.records[rec["record_id"]] = rec
            if profile:
                self.batch_ids[experiment_key] = result
            return result
