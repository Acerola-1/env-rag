"""Traceable document metadata extraction (task 2.3, corrected per S3).

Rules (each backed by a behavior test reproducing the review counterexample):

- 自身编号只取**可靠自身声明**：封面独立编号行（前 25 行内、不带"代替/依据/引用/按照/
  执行/参见"等限定词的 GB/HJ-年份行）或显式"标准编号："声明。"依据 GB…"、"部分代替 GB…"、
  "本文件…"、"参照…"永远不赋自身编号。
- 引用编号扫描全文，排除自身编号后进 referenced_codes；引用-only 的文档 self_code 为
  unknown，绝不回填。
- 标题识别并跳过：通用封面行、"部分代替 GB…"、"代替 GB…"、公告／前言、页眉行
  （"GB 18466—2005" 等纯编号行）；取第一个业务标题行，取不到即 unknown。
- 发布／实施日期只在**封面区域**（前 25 行）内分别匹配，不合并、不使用全文首次匹配。
- 每个字段 provenance 携带位置（行号）、原文引句与置信状态；未知与冲突保留。
"""

from __future__ import annotations

import re

from .lexical_norm import extract_codes, normalize_code

# Generic cover lines that must never become a business title.
_GENERIC_TITLES = {
    "中华人民共和国国家标准",
    "中华人民共和国国家环境保护标准",
    "中华人民共和国环境保护标准",
    "中华人民共和国生态环境标准",
    "中 华 人 民 共 和 国 国 家 标 准",
    "国家标准",
    "环境保护标准",
    "生态环境标准",
    "国家环境保护总局",
    "生态环境部",
    "目次",
    "前言",
    "公 告",
    "公告",
    "本文件",
    "本标准",
}

# Lines that disqualify a code from being the *self* code.
_SELF_CODE_DISQUALIFIERS = ("代替", "依据", "引用", "按照", "参照", "执行", "参见", "适用")

_CODE_LINE_RE = re.compile(r"^\s*#?\s*((?:GB|HJ)\s*/?\s*T?\s*[\d.]+\s*[—–-]\s*\d{2,4})\s*$")
_SELF_CODE_DECL_RE = re.compile(
    r"(?:标准编号|本标准编号|代号)\s*[:：]?\s*((?:GB|HJ)[\s/]*T?\s*[\d.]+\s*[—–-]\s*\d{4})", re.I
)
_CODE_ANY_RE = re.compile(r"((?:GB|HJ)\s*/?\s*T?\s*[\d.]+\s*[—–-]\s*\d{4})")
_PARTIAL_REPLACE_RE = re.compile(r"^\s*#?\s*(?:部分\s*)?代替\b")
_DATE_PUB_RE = re.compile(r"(\d{4}[-–—年]\d{1,2}[-–—月]\d{1,2}日?)\s*发布")
_DATE_IMPL_RE = re.compile(r"(\d{4}[-–—年]\d{1,2}[-–—月]\d{1,2}日?)\s*实施")

COVER_LINES = 25  # 封面区域：自身编号与日期只在此窗口内认定


def _new_record() -> dict:
    return {
        "title": None,
        "title_confidence": "unknown",
        "self_code": None,
        "self_code_version": None,
        "referenced_codes": [],
        "doc_type": None,
        "publish_date": None,
        "implement_date": None,
        "stats_period": None,
        "unknown_fields": [],
        "field_provenance": {},
    }


def _mk_prov(line_no: int, quote: str, basis: str, confidence: str) -> dict:
    return {"line": line_no, "quote": quote[:80], "basis": basis, "confidence": confidence}


def extract_document_metadata(doc_name: str, content: str) -> dict:
    """Extract catalog metadata with line-level provenance."""
    rec = _new_record()
    prov: dict = {}

    body = content or ""
    if body.startswith("{{LRdoc}}"):
        body = body.removeprefix("{{LRdoc}}")
        prov["content_source"] = {
            "basis": "doc_full.content minus explicit {{LRdoc}} storage marker",
            "confidence": "extracted",
        }
    lines = body.splitlines()

    # ---------------- title -------------------------------------------------
    title = None
    title_attempts = []
    for i, ln in enumerate(lines[:60]):
        stripped = ln.strip().lstrip("# ").strip()
        if not stripped:
            continue
        # space-normalized compare: cover lines often space out every glyph
        condensed = re.sub(r"\s+", "", stripped)
        if stripped in _GENERIC_TITLES or condensed in {
            _GENERIC_TITLES and re.sub(r"\s+", "", g) for g in _GENERIC_TITLES
        }:
            title_attempts.append(f"skip generic line {i}: {stripped[:30]!r}")
            continue
        if _PARTIAL_REPLACE_RE.match(stripped) or "代替" in stripped:
            # "部分代替 GB 8978—1996" / "代替 GB 4287—2012、…" — not a title
            title_attempts.append(f"skip replacement line {i}: {stripped[:40]!r}")
            continue
        if _CODE_LINE_RE.match(ln):
            title_attempts.append(f"skip pure code line {i}: {stripped[:40]!r}")
            continue
        title = stripped
        rec["title"] = title
        rec["title_confidence"] = "extracted"
        prov["title"] = _mk_prov(
            i, stripped, "; ".join(title_attempts) or "first heading line", "extracted"
        )
        break
    if title is None:
        rec["unknown_fields"].append("title")
        prov["title"] = {
            "attempts": title_attempts,
            "basis": "no business title in first 60 lines",
            "confidence": "unknown",
        }

    # ---------------- self code: cover lines only, strict qualifiers --------
    self_code = None
    for i, ln in enumerate(lines[:COVER_LINES]):
        decl = _SELF_CODE_DECL_RE.search(ln)
        if decl:
            self_code = decl.group(1)
            prov["self_code"] = _mk_prov(
                i, ln.strip(), "explicit 标准编号 declaration", "extracted"
            )
            break
        bare = _CODE_LINE_RE.match(ln)
        if bare and not any(q in ln for q in _SELF_CODE_DISQUALIFIERS):
            self_code = bare.group(1)
            prov["self_code"] = _mk_prov(
                i,
                ln.strip(),
                "standalone code line on cover (no 代替/依据/… qualifier)",
                "extracted",
            )
            break
        # any qualified occurrence inside the cover disqualifies that line but
        # we keep scanning: a real cover also has the standalone code line.
    if self_code:
        norm = normalize_code(self_code)
        code, _, year = norm.rpartition("-")
        rec["self_code"] = code
        rec["self_code_version"] = year
    else:
        rec["unknown_fields"].append("self_code")
        prov["self_code"] = {
            "basis": f"no unqualified standalone code line within first {COVER_LINES} lines "
            "(依据/代替/引用 lines are never self codes)",
            "confidence": "unknown",
        }

    # ---------------- referenced codes: full body, exclude self --------------
    all_codes = extract_codes(body)
    self_norm = normalize_code(self_code) if self_code else None
    rec["referenced_codes"] = sorted({c for c in all_codes if c != self_norm})
    prov["referenced_codes"] = {
        "basis": "regex scan of full body; self code excluded; 依据/引用 lines stay references",
        "confidence": "extracted",
    }
    # explicit provenance entry when a doc references codes but has no self code
    if rec["referenced_codes"] and not self_code:
        prov["self_code"]["note"] = (
            "document cites other standards (referenced_codes) but declares none of its own"
        )

    # ---------------- doc type ----------------------------------------------
    if "标准" in doc_name or "标准" in (title or ""):
        rec["doc_type"] = "standard"
        prov["doc_type"] = _mk_prov(0, doc_name, "name/title contains 标准", "extracted")
    elif "公报" in doc_name:
        rec["doc_type"] = "bulletin"
        prov["doc_type"] = _mk_prov(0, doc_name, "name contains 公报", "extracted")
    elif "年报" in doc_name:
        rec["doc_type"] = "yearbook"
        prov["doc_type"] = _mk_prov(0, doc_name, "name contains 年报", "extracted")
    elif "报告" in doc_name:
        rec["doc_type"] = "report"
        prov["doc_type"] = _mk_prov(0, doc_name, "name contains 报告", "extracted")
    elif "方案" in doc_name:
        rec["doc_type"] = "action_plan"
        prov["doc_type"] = _mk_prov(0, doc_name, "name contains 方案", "extracted")
    else:
        rec["doc_type"] = None
        rec["unknown_fields"].append("doc_type")
        prov["doc_type"] = {"basis": "no type keyword in file name", "confidence": "unknown"}

    # ---------------- dates: cover window only, separate fields --------------
    cover = "\n".join(lines[:COVER_LINES])
    pub = _DATE_PUB_RE.search(cover)
    if pub:
        rec["publish_date"] = pub.group(1)
        prov["publish_date"] = _mk_prov(
            cover[: pub.start()].count("\n"), pub.group(0), "'…发布' in cover region", "extracted"
        )
    else:
        rec["unknown_fields"].append("publish_date")
        prov["publish_date"] = {"basis": "no 发布 date in cover region", "confidence": "unknown"}
    impl = _DATE_IMPL_RE.search(cover)
    if impl:
        rec["implement_date"] = impl.group(1)
        prov["implement_date"] = _mk_prov(
            cover[: impl.start()].count("\n"), impl.group(0), "'…实施' in cover region", "extracted"
        )
    else:
        rec["unknown_fields"].append("implement_date")
        prov["implement_date"] = {"basis": "no 实施 date in cover region", "confidence": "unknown"}
    rec["unknown_fields"].append("stats_period")
    prov["stats_period"] = {
        "basis": "not extracted in Phase 1; kept unknown",
        "confidence": "unknown",
    }

    prov["dates_scope"] = {
        "basis": f"cover region = first {COVER_LINES} lines only; "
        "body-wide first match intentionally not used",
        "confidence": "extracted",
    }
    rec["field_provenance"] = prov
    return rec
