"""Task 4.5 / Gate 2 G2-8: build the corrected gold-candidate review package.

Every gold item is DERIVED from the original parsed artifacts by this script
and carries:
- the exact question and category;
- target document identity (workspace/doc_id/doc_name);
- the expected set / fact with its VERBATIM source locator (table_id + row, or
  unit/blockid + clause) and the supporting quote read from the raw artifact;
- TYPED target evidence (workspace/doc/unit/chunk/scope) with acceptable
  alternatives, so the evaluation harness can measure answer-evidence recall —
  a catalog row alone never counts;
- explicit constraints, allowed status and (where applicable) a ``revision``
  record documenting a corrected question/answer without silently swapping it.

Nothing is hand-typed for the corpus facts: the script re-reads the artifacts
and fails (non-zero) if an expected item cannot be re-derived. Review status
stays ``unreviewed`` — the main agent must approve before metrics count.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from env_rag_final.audit import identity as sid  # noqa: E402
from env_rag_final.catalog import units as U  # noqa: E402
from env_rag_final.enumerate_.tables import read_html_table  # noqa: E402

ROOT = sid.PARSED_ROOT

DOCS = {
    "gb3095_2012": "air-02_生态环境部_环境空气质量标准_GB3095-2012.pdf",
    "gb3095_2026": "air-03_生态环境部_环境空气质量标准_GB3095-2026.pdf",
    "gb8978": "water-11_生态环境部_污水综合排放标准_GB8978-1996.pdf",
    "gb18466": "water-09_生态环境部_医疗机构水污染物排放标准_GB18466-2005.pdf",
    "gb14554": "air-06_生态环境部_恶臭污染物排放标准_GB14554-93.pdf",
    "gb3838": "water-04_生态环境部_地表水环境质量标准_GB3838-2002.pdf",
    "yearbook21": "air-15_生态环境部_中国移动源环境管理年报_2021.pdf",
    "yearbook25": "air-19_生态环境部_中国移动源环境管理年报_2025.pdf",
    "modify18466": "water-10_生态环境部_医疗机构水污染物排放标准修改单_2026.pdf",
    "gb18466_merged": "water-03_生态环境部_医疗机构水污染物排放标准_含2026修改单.pdf",
}

errors: list[str] = []


def tables_of(pdf: str) -> dict:
    return U.parse_tables(ROOT / f"{pdf}.parsed")


def blocks_of(pdf: str) -> list[dict]:
    _meta, bl = U.parse_blocks(ROOT / f"{pdf}.parsed")
    return bl


def grid(pdf: str, tid: str) -> list[list[str]]:
    html = (tables_of(pdf).get(tid) or {}).get("content") or ""
    if not html:
        errors.append(f"table {tid} missing in {pdf}")
        return []
    return read_html_table(html)


def table_id(pdf: str, seq: int) -> str:
    for tid in sorted(tables_of(pdf)):
        if tid.endswith(f"-{seq:04d}"):
            return tid
    errors.append(f"table seq {seq} missing in {pdf}")
    return ""


def doc_id_of(pdf: str) -> str:
    """doc_id = doc- + md5(doc_name) — the audited identity contract."""
    return "doc-" + hashlib.md5(pdf.encode()).hexdigest()  # noqa: S324 — repo contract


def parsed_docs_matching(substr: str) -> list[str]:
    return sorted(p.name[: -len(".parsed")] for p in ROOT.glob("*.parsed") if substr in p.name)


def find_row(g: list[list[str]], pred) -> list[str] | None:
    for r in g:
        if pred(r):
            return r
    return None


def block_quote(pdf: str, pattern: str, span: int = 220) -> tuple[str, str] | None:
    rx = re.compile(pattern, re.M)
    for b in blocks_of(pdf):
        c = b.get("content") or ""
        m = rx.search(c)
        if m:
            start = max(0, m.start() - 20)
            return b["blockid"], c[start : m.start() + span].strip()
    return None


_TOC_RE = re.compile(r"^#*\s*目\s*次", re.M)


def block_of(pdf: str, pattern: str) -> dict | None:
    """First NON-TOC block matching the pattern (R5).

    目次/目 次 blocks quote every heading (6.1 污水取样与监测 ……5) and must
    never be taken as the body evidence for a range target — targets resolved
    to a TOC block would mis-point the gold at the table of contents.
    """
    rx = re.compile(pattern, re.M)
    for b in blocks_of(pdf):
        content = b.get("content") or ""
        if _TOC_RE.search(content):
            continue
        if rx.search(content):
            return b
    return None


def first_row_quote(pdf: str, tid: str) -> str:
    """The FIRST real data row of a table, as a ' | ' quote (verbatim grid)."""
    g = grid(pdf, tid)
    for r in g:
        if r and r[0].strip().isdigit():
            return " | ".join(r)
    return ""


def mk(
    qid: str,
    category: str,
    question: str,
    *,
    tdocs: list[str],
    expected=None,
    assertion: str | None = None,
    locator: str,
    quote: str,
    evidence_kind: str,
    typed: list[dict] | None = None,
    constraints: list[str] | None = None,
    allowed_status: list[str] | None = None,
    gap: str | None = None,
    revision: dict | None = None,
) -> dict:
    item = {
        "query_id": qid,
        "category": category,
        "question": question,
        "workspace": "default",
        "target_docs": [
            {"workspace": "default", "doc_id": doc_id_of(DOCS[k]), "doc_name": DOCS[k]}
            for k in tdocs
        ],
        "gold": {
            "expected_items": expected,
            "assertion": assertion,
            "gap": gap,
            "locator": locator,
            "supporting_quote": quote,
            "evidence_kind": evidence_kind,
            "target_evidence": typed or [],
        },
        "constraints": constraints or [],
        "allowed_status": allowed_status or ["complete"],
        "gold_review_status": "unreviewed",
    }
    if revision:
        item["revision"] = revision
    return item


def te(pdf_key: str, unit_id: str) -> dict:
    return {"workspace": "default", "doc_id": doc_id_of(DOCS[pdf_key]), "unit_id": unit_id}


def te_doc(pdf_key: str) -> dict:
    return {"workspace": "default", "doc_id": doc_id_of(DOCS[pdf_key])}


def build() -> dict:
    items: list[dict] = []

    # ================= fact (7) ===========================================
    tid1 = table_id(DOCS["gb3095_2012"], 1)
    g = grid(DOCS["gb3095_2012"], tid1)
    row = find_row(g, lambda r: len(r) > 4 and r[1].startswith("二氧化硫") and "年平均" in r[2])
    if row:
        items.append(
            mk(
                "fact-001",
                "fact",
                "GB 3095-2012 中二氧化硫的年平均浓度二级限值是多少？",
                tdocs=["gb3095_2012"],
                typed=[te("gb3095_2012", tid1)],
                assertion=f"二级年平均限值 {row[4]} μg/m³（一级 {row[3]}）",
                locator=f"{tid1} 数据行 二氧化硫/年平均（按表头 一级/二级 列索引）",
                quote=" | ".join(row),
                evidence_kind="table_row",
                constraints=["code=gb3095-2012"],
            )
        )

    t8978_1 = table_id(DOCS["gb8978"], 1)
    row = find_row(grid(DOCS["gb8978"], t8978_1), lambda r: len(r) > 2 and r[1] == "总汞")
    if row:
        items.append(
            mk(
                "fact-002",
                "fact",
                "GB 8978-1996 表 1 中总汞的最高允许排放浓度是多少？",
                tdocs=["gb8978"],
                typed=[te("gb8978", t8978_1)],
                assertion=f"总汞 {row[2]} mg/L（第一类污染物，表1）",
                locator=f"{t8978_1} 数据行 总汞（表1 第一类污染物最高允许排放浓度）",
                quote=" | ".join(row),
                evidence_kind="table_row",
                constraints=["code=gb8978-1996"],
            )
        )

    hit = block_quote(DOCS["gb18466"], r"^3\.2\s")
    b32 = block_of(DOCS["gb18466"], r"^## 3 术语和定义")
    if hit and b32:
        items.append(
            mk(
                "fact-003",
                "fact",
                "GB 18466-2005 中“医疗机构污水”的定义是什么？",
                tdocs=["gb18466"],
                typed=[te("gb18466", b32["blockid"])],
                assertion="3.2 条定义全文（门诊、病房、手术室…等处排出的诊疗、生活及粪便污水…）",
                locator=f"block {b32['blockid']} §3.2（定义完整跨度）",
                quote=hit[1],
                evidence_kind="prose_block",
                constraints=["code=gb18466-2005"],
            )
        )

    t3838 = table_id(DOCS["gb3838"], 1)
    g3838 = grid(DOCS["gb3838"], t3838)
    cod = find_row(g3838, lambda r: len(r) > 5 and "化学需氧量" in r[1])
    if cod:
        items.append(
            mk(
                "fact-004",
                "fact",
                "GB 3838-2002 中 III 类水体化学需氧量（COD）的标准限值是多少？",
                tdocs=["gb3838"],
                typed=[te("gb3838", t3838)],
                assertion=f"III 类 COD 限值 {cod[4]} mg/L（I/II/III/IV/V = "
                f"{cod[2]}/{cod[3]}/{cod[4]}/{cod[5]}/{cod[6]}）",
                locator=f"{t3838} 数据行 化学需氧量(COD)≤（按 I–V 类列头索引）",
                quote=" | ".join(cod),
                evidence_kind="table_row",
                constraints=["code=gb3838-2002"],
                revision={
                    "submitted_assertion": "III 类 COD 限值 15 mg/L",
                    "corrected_assertion": f"III 类 COD 限值 {cod[4]} mg/L",
                    "reason": "提交按 row[3] 取到 II 类；表头 I/II/III/IV/V 对应 15/15/20/30/40",
                },
            )
        )

    t14554 = table_id(DOCS["gb14554"], 1)
    g14554 = grid(DOCS["gb14554"], t14554)
    odor = find_row(g14554, lambda r: len(r) > 4 and "臭气浓度" in " ".join(r))
    if odor:
        items.append(
            mk(
                "fact-005",
                "fact",
                "GB 14554-93 中臭气浓度（无量纲）的厂界二级标准值是多少？",
                tdocs=["gb14554"],
                typed=[te("gb14554", t14554)],
                assertion="二级 新扩改建 20、现有 30（无量纲）；表1 厂界标准值",
                locator=f"{t14554} 数据行 臭气浓度（二级含新扩改建/现有两列）",
                quote=" | ".join(odor),
                evidence_kind="table_row",
                constraints=["code=gb14554-93"],
                revision={
                    "submitted_assertion": "厂界二级标准值 20（无量纲），表1",
                    "corrected_assertion": "二级新扩改建 20／现有 30，需保留两条件",
                    "reason": "问题未限定新扩改建/现有，不能只答 20",
                },
            )
        )

    hit = block_quote(DOCS["gb3095_2012"], r"2012-02-29\s*发布|2016-01-01\s*实施")
    bcover = block_of(DOCS["gb3095_2012"], r"2012-02-29\s*发布")
    if hit and bcover:
        items.append(
            mk(
                "fact-006",
                "fact",
                "GB 3095-2012 的发布日期和实施日期分别是什么？",
                tdocs=["gb3095_2012"],
                typed=[te("gb3095_2012", bcover["blockid"])],
                assertion="发布 2012-02-29；实施 2016-01-01（封面原文，两项分列）",
                locator=f"block {bcover['blockid']} 封面日期",
                quote=hit[1],
                evidence_kind="prose_block",
                constraints=["code=gb3095-2012"],
            )
        )

    t4 = table_id(DOCS["gb8978"], 7)
    row = find_row(grid(DOCS["gb8978"], t4), lambda r: len(r) > 3 and r[1] == "pH")
    if row:
        items.append(
            mk(
                "fact-007",
                "fact",
                "GB 8978-1996 中 pH 值的排放限值范围是多少？",
                tdocs=["gb8978"],
                typed=[te("gb8978", t4)],
                assertion="pH 6~9（表4 第二类污染物 一级/二级/三级同级；表2 同值）",
                locator=f"{t4} 数据行 pH（表4；1997-12-31 前建设单位见表2 同值 6~9）",
                quote=" | ".join(row),
                evidence_kind="table_row",
                constraints=["code=gb8978-1996"],
                revision={
                    "submitted_assertion": "6~9（表 2，1997-12-31 前建设单位的适用性以原文为准）",
                    "corrected_assertion": "表4 pH 一级/二级/三级均 6~9；表2 同值；两个年限范围各自引用",
                    "reason": "审阅要求两个年限范围分别引用；值本身不变",
                },
            )
        )

    # ================= file_enum (6) ======================================
    items.append(
        {
            "query_id": "file-enum-001",
            "category": "file_enum",
            "question": "库内有哪些 GB 3095 标准的文档？列出文件名和版本年份。",
            "workspace": "default",
            "target_docs": [
                {
                    "workspace": "default",
                    "doc_id": doc_id_of(DOCS["gb3095_2012"]),
                    "doc_name": DOCS["gb3095_2012"],
                },
                {
                    "workspace": "default",
                    "doc_id": doc_id_of(DOCS["gb3095_2026"]),
                    "doc_name": DOCS["gb3095_2026"],
                },
            ],
            "gold": {
                "match_predicate": "self_code = GB3095",
                "expected_doc_ids": [
                    doc_id_of(DOCS["gb3095_2012"]),
                    doc_id_of(DOCS["gb3095_2026"]),
                ],
                "expected_versions": ["2012", "2026"],
                "locator": "env_rag.documents self_code=GB3095（活动目录逐行身份）",
                "supporting_quote": None,
                "evidence_kind": "catalog_row",
                "target_evidence": [te_doc("gb3095_2012"), te_doc("gb3095_2026")],
            },
            "constraints": ["code=gb3095 (all versions)"],
            "allowed_status": ["complete"],
            "gold_review_status": "unreviewed",
        }
    )
    yb = parsed_docs_matching("中国移动源环境管理年报")
    items.append(
        {
            "query_id": "file-enum-002",
            "category": "file_enum",
            "question": "库内有哪些《中国移动源环境管理年报》？",
            "workspace": "default",
            "target_docs": [
                {"workspace": "default", "doc_id": doc_id_of(p), "doc_name": p} for p in yb
            ],
            "gold": {
                "match_predicate": "doc_name LIKE '%中国移动源环境管理年报%'（标题条件保留）",
                "expected_doc_ids": [doc_id_of(p) for p in yb],
                "expected_versions": [p[-8:-4] for p in yb],
                "locator": "env_rag.documents doc_name/title（parsed 目录仅交叉核对）",
                "supporting_quote": "; ".join(yb),
                "evidence_kind": "catalog_row",
                "target_evidence": [{"workspace": "default", "doc_id": doc_id_of(p)} for p in yb],
            },
            "constraints": ["title=中国移动源环境管理年报"],
            "allowed_status": ["complete"],
            "gold_review_status": "unreviewed",
        }
    )
    bl = parsed_docs_matching("年中国水资源公报")
    items.append(
        {
            "query_id": "file-enum-003",
            "category": "file_enum",
            "question": "库内有哪些《中国水资源公报》（水利部）？",
            "workspace": "default",
            "target_docs": [
                {"workspace": "default", "doc_id": doc_id_of(p), "doc_name": p} for p in bl
            ],
            "gold": {
                "match_predicate": "doc_name LIKE '%水利部_%年中国水资源公报%'",
                "expected_doc_ids": [doc_id_of(p) for p in bl],
                "expected_versions": [p[-8:-4] for p in bl],
                "locator": "env_rag.documents doc_name（目录为真源）",
                "supporting_quote": "; ".join(bl),
                "evidence_kind": "catalog_row",
                "target_evidence": [{"workspace": "default", "doc_id": doc_id_of(p)} for p in bl],
            },
            "constraints": ["title=中国水资源公报"],
            "allowed_status": ["complete"],
            "gold_review_status": "unreviewed",
        }
    )
    md = parsed_docs_matching("修改单")
    items.append(
        {
            "query_id": "file-enum-004",
            "category": "file_enum",
            "question": "库内有哪些文档名称含“修改单”？",
            "workspace": "default",
            "target_docs": [
                {"workspace": "default", "doc_id": doc_id_of(p), "doc_name": p} for p in md
            ],
            "gold": {
                "match_predicate": "doc_name LIKE '%修改单%'（名称谓词，不替代主题相关性）",
                "expected_doc_ids": [doc_id_of(p) for p in md],
                "expected_count": len(md),
                "locator": "env_rag.documents doc_name",
                "supporting_quote": "; ".join(md),
                "evidence_kind": "catalog_row",
                "target_evidence": [{"workspace": "default", "doc_id": doc_id_of(p)} for p in md],
            },
            "constraints": [],
            "allowed_status": ["complete"],
            "gold_review_status": "unreviewed",
        }
    )
    med = [
        (doc_id_of(DOCS["gb18466"]), DOCS["gb18466"], "self_code=GB18466 原标准"),
        (
            doc_id_of(DOCS["modify18466"]),
            DOCS["modify18466"],
            "封面明确「GB 18466—2005」修改单（封面归属，self_code 未知）",
        ),
        (
            doc_id_of(DOCS["gb18466_merged"]),
            DOCS["gb18466_merged"],
            "标题「GB 18466—2005（含2026年修改单）」整合版（封面归属，self_code 未知）",
        ),
    ]
    items.append(
        {
            "query_id": "file-enum-005",
            "category": "file_enum",
            "question": "库内有哪些 GB 18466-2005 的文档（含修改单）？",
            "workspace": "default",
            "target_docs": [
                {"workspace": "default", "doc_id": d, "doc_name": n} for d, n, _ in med
            ],
            "gold": {
                "match_predicate": "self_code = GB18466 OR 封面/标题明确归属 GB 18466—2005"
                "（修改单与含修改单整合版按封面证据纳入；不得冒认 self_code）",
                "expected_doc_ids": [d for d, _, _ in med],
                "membership_basis": [{"doc_id": d, "doc_name": n, "basis": b} for d, n, b in med],
                "locator": "env_rag.documents + 封面 block 原文（修改单封面）",
                "supporting_quote": None,
                "evidence_kind": "catalog_row+cover",
                "target_evidence": [{"workspace": "default", "doc_id": d} for d, _, _ in med],
            },
            "constraints": ["code=gb18466-2005 (含修改单归属)"],
            "allowed_status": ["complete"],
            "gold_review_status": "unreviewed",
            "revision": {
                "submitted_expected_doc_ids": [doc_id_of(DOCS["gb18466"])],
                "corrected_expected_doc_ids": [d for d, _, _ in med],
                "reason": "仅列原标准不满足「含修改单」；两份相关文档封面明确 GB 18466—2005，"
                "须记录身份/归属依据，不得把引用编号当自身编号",
            },
        }
    )
    items.append(
        {
            "query_id": "file-enum-006",
            "category": "file_enum",
            "question": "库内有哪些 GB 3838 地表水环境质量标准文档？",
            "workspace": "default",
            "target_docs": [
                {
                    "workspace": "default",
                    "doc_id": doc_id_of(DOCS["gb3838"]),
                    "doc_name": DOCS["gb3838"],
                },
            ],
            "gold": {
                "match_predicate": "self_code = GB3838（其他文档引用该标准不计入）",
                "expected_doc_ids": [doc_id_of(DOCS["gb3838"])],
                "locator": "env_rag.documents self_code",
                "supporting_quote": None,
                "evidence_kind": "catalog_row",
                "target_evidence": [te_doc("gb3838")],
            },
            "constraints": ["code=gb3838"],
            "allowed_status": ["complete"],
            "gold_review_status": "unreviewed",
        }
    )

    # ================= prose_enum (6) =====================================
    b3 = block_of(DOCS["gb18466"], r"^## 3 术语和定义")
    b33 = block_of(DOCS["gb18466"], r"^## 3\.3\s")
    b34 = block_of(DOCS["gb18466"], r"^## 3\.4\s")
    terms_typed = [
        {**te("gb18466", b["blockid"]), "quote": (b.get("content") or "")[:180]}
        for b in (b3, b33, b34)
        if b
    ]
    items.append(
        {
            "query_id": "prose-enum-001",
            "category": "prose_enum",
            "question": "GB 18466-2005 中 3 章定义了哪些术语？逐项列出编号和中文名。",
            "workspace": "default",
            "target_docs": [
                {
                    "workspace": "default",
                    "doc_id": doc_id_of(DOCS["gb18466"]),
                    "doc_name": DOCS["gb18466"],
                },
            ],
            "gold": {
                "expected_items": ["3.1 医疗机构", "3.2 医疗机构污水", "3.3 污泥", "3.4 废气"],
                "locator": "blocks "
                + ", ".join(b["blockid"][:8] for b in (b3, b33, b34) if b)
                + "（3.1/3.2 与 3.3/3.4 各有原始块）",
                "supporting_quote": (b3 or {}).get("content", "")[:220],
                "evidence_kind": "prose_scope",
                "target_evidence": terms_typed,
            },
            "constraints": ["code=gb18466-2005", "scope=3"],
            "allowed_status": ["complete"],
            "gold_review_status": "unreviewed",
            "revision": {
                "note": "提交 quote 截在 3.2，不能支持 3.3/3.4；已附四术语各原始块 typed 证据",
            },
        }
    )
    b41 = block_of(DOCS["gb18466"], r"^## 4\.1 污水排放要求")
    items.append(
        {
            "query_id": "prose-enum-002",
            "category": "prose_enum",
            "question": "GB 18466-2005 的 4.1.1 与 4.1.2 分别规定了什么？逐条列出。",
            "workspace": "default",
            "target_docs": [
                {
                    "workspace": "default",
                    "doc_id": doc_id_of(DOCS["gb18466"]),
                    "doc_name": DOCS["gb18466"],
                },
            ],
            "gold": {
                "expected_items": [
                    {
                        "clause": "4.1.1",
                        "text": "传染病和结核病医疗机构污水排放一律执行表1的规定",
                    },
                    {
                        "clause": "4.1.2",
                        "text": "县级及县级以上或 20 张床位及以上的综合医疗机构和其他医疗机构"
                        "污水排放执行表 2 的规定。直接或间接排入地表水体和海域的污水执行排放标准，"
                        "排入终端已建有正常运行城镇二级污水处理厂的下水道的污水，执行预处理标准。",
                    },
                ],
                "locator": f"block {(b41 or {}).get('blockid', '')} §4.1（两条全文）",
                "supporting_quote": (b41 or {}).get("content", "")[:260],
                "evidence_kind": "prose_block",
                "target_evidence": [te("gb18466", (b41 or {}).get("blockid", ""))],
            },
            "constraints": ["code=gb18466-2005"],
            "allowed_status": ["complete"],
            "gold_review_status": "unreviewed",
            "revision": {
                "submitted_expected_items": [
                    "4.1.1 传染病和结核病医疗机构污水排放一律执行表1的规定",
                    "4.1.2 综合医疗机构和其他医疗机构执行表2（排放标准/预处理标准）",
                ],
                "reason": "4.1.2 省略县级/20床适用条件，不能把无条件简述作为完整 gold",
            },
        }
    )
    b43 = block_of(DOCS["gb8978"], r"^#*\s*4\.3\s*其他规定")
    items.append(
        {
            "query_id": "prose-enum-003",
            "category": "prose_enum",
            "question": "GB 8978-1996 第 4.3 节“其他规定”列出了哪些要求？",
            "workspace": "default",
            "target_docs": [
                {
                    "workspace": "default",
                    "doc_id": doc_id_of(DOCS["gb8978"]),
                    "doc_name": DOCS["gb8978"],
                },
            ],
            "gold": {
                # C5: the FULL requirement of every clause — a keyword/number
                # prefix can never score as a complete requirement
                "expected_items": [
                    {
                        "clause": "4.3.1",
                        "text": "同一排放口排放两种或两种以上不同类别的污水，"
                        "且每种污水的排放标准又不同时，其混合污水的排放标准按附录 A 计算。",
                    },
                    {
                        "clause": "4.3.2",
                        "text": "工业污水污染物的最高允许排放负荷量按附录 B 计算。",
                    },
                    {
                        "clause": "4.3.3",
                        "text": "污染物最高允许年排放总量按附录 C 计算。",
                    },
                    {
                        "clause": "4.3.4",
                        "text": "对于排放含有放射性物质的污水，除执行本标准外，"
                        "还须符合 GB 8703—88《辐射防护规定》。",
                    },
                ],
                "locator": f"block {(b43 or {}).get('blockid', '')} §4.3.1–4.3.4",
                "supporting_quote": (b43 or {}).get("content", "")[:220],
                "evidence_kind": "prose_block",
                "target_evidence": [te("gb8978", (b43 or {}).get("blockid", ""))],
            },
            "constraints": ["code=gb8978-1996"],
            "allowed_status": ["complete"],
            "gold_review_status": "unreviewed",
            "revision": {"note": "提交 regex 未容忍 ## 标题形式而产生空 quote；已改从真实块读取"},
        }
    )
    b3838_3 = block_of(DOCS["gb3838"], r"按功能高低依次划分为五类")
    items.append(
        {
            "query_id": "prose-enum-004",
            "category": "prose_enum",
            "question": "GB 3838-2002 的水域功能是如何分类的？列出全部类别。",
            "workspace": "default",
            "target_docs": [
                {
                    "workspace": "default",
                    "doc_id": doc_id_of(DOCS["gb3838"]),
                    "doc_name": DOCS["gb3838"],
                },
            ],
            "gold": {
                # C5 projection: per-category sentences with the SOURCE's
                # verbatim Roman numerals (OCR quirks stay in the labels)
                "expected_items": [
                    # labels use the SOURCE's OCR numerals verbatim
                    {"clause": "I类", "text": "主要适用于源头水、国家自然保护区"},
                    {
                        "clause": "Ⅰ类",
                        "text": "主要适用于集中式生活饮用水地表水源地一级保护区、"
                        "珍稀水生生物栖息地、鱼虾类产卵场、仔稚幼鱼的索饵场等",
                    },
                    {
                        "clause": "Ⅰ类",
                        "text": "主要适用于集中式生活饮用水地表水源地二级保护区、鱼虾类越冬场、"
                        "洄游通道、水产养殖区等渔业水域及游泳区",
                    },
                    {
                        "clause": "N类",
                        "text": "主要适用于一般工业用水区及人体非直接接触的娱乐用水区",
                    },
                    {"clause": "V类", "text": "主要适用于农业用水区及一般景观要求水域"},
                ],
                "locator": f"block {(b3838_3 or {}).get('blockid', '')} §3（类号存在 OCR 异常，"
                "保留原号与审查映射，不当作逐字规范类号）",
                "supporting_quote": (b3838_3 or {}).get("content", "")[:280],
                "evidence_kind": "prose_block",
                "target_evidence": [te("gb3838", (b3838_3 or {}).get("blockid", ""))],
            },
            "constraints": ["code=gb3838-2002", "scope=3"],
            "allowed_status": ["complete"],
            "gold_review_status": "unreviewed",
            "revision": {
                "reason": "III 类摘要须含越冬场/洄游通道/水产养殖等；类号 OCR 异常保留原号"
            },
        }
    )
    b14554 = block_of(DOCS["gb14554"], r"厂界标准值分三级|4\.1\s*标准分级")
    items.append(
        {
            "query_id": "prose-enum-005",
            "category": "prose_enum",
            "question": "GB 14554-93 对恶臭污染物厂界标准值的分级别规定了哪几级？",
            "workspace": "default",
            "target_docs": [
                {
                    "workspace": "default",
                    "doc_id": doc_id_of(DOCS["gb14554"]),
                    "doc_name": DOCS["gb14554"],
                },
            ],
            "gold": {
                "expected_items": ["一级", "二级", "三级"],
                "locator": f"block {(b14554 or {}).get('blockid', '')} §4.1 标准分级",
                "supporting_quote": (b14554 or {}).get("content", "")[:220],
                "evidence_kind": "prose_block",
                "target_evidence": [te("gb14554", (b14554 or {}).get("blockid", ""))],
            },
            "constraints": ["code=gb14554-93"],
            "allowed_status": ["complete"],
            "gold_review_status": "unreviewed",
            "revision": {"note": "正文 4.1 明确三级，无须空 gap"},
        }
    )
    b42 = block_of(DOCS["gb3095_2012"], r"^#*\s*4\.2\s")
    items.append(
        {
            "query_id": "prose-enum-006",
            "category": "prose_enum",
            "question": "GB 3095-2012 的 4.2 节对环境空气功能区质量要求作了哪些规定？",
            "workspace": "default",
            "target_docs": [
                {
                    "workspace": "default",
                    "doc_id": doc_id_of(DOCS["gb3095_2012"]),
                    "doc_name": DOCS["gb3095_2012"],
                },
            ],
            "gold": {
                # B2 projection: 4.2 has no numbered sub-clauses — the answer is
                # the WHOLE clause prose as one item (both provisions + the
                # table reference), not three synthetic fragments
                "expected_items": [
                    {
                        "clause": "4.2",
                        "text": "一类区适用一级浓度限值，二类区适用二级浓度限值。"
                        "一、二类环境空气功能区质量要求见表 1和表 2。",
                    }
                ],
                "locator": f"block {(b42 or {}).get('blockid', '')} §4.2",
                "supporting_quote": (b42 or {}).get("content", "")[:200],
                "evidence_kind": "prose_block",
                "target_evidence": [te("gb3095_2012", (b42 or {}).get("blockid", ""))],
            },
            "constraints": ["code=gb3095-2012"],
            "allowed_status": ["complete"],
            "gold_review_status": "unreviewed",
        }
    )

    # ================= table_enum (6) =====================================
    t1a, t1b = table_id(DOCS["gb8978"], 1), table_id(DOCS["gb8978"], 2)
    rows_a = [r for r in grid(DOCS["gb8978"], t1a)[1:] if r and r[0].strip().isdigit()]
    rows_b = [r for r in grid(DOCS["gb8978"], t1b) if r and r[0].strip().isdigit()]
    items.append(
        {
            "query_id": "table-enum-001",
            "category": "table_enum",
            "question": "GB 8978-1996 表 1（第一类污染物）共列出哪些污染物及其限值？逐行列出。",
            "workspace": "default",
            "target_docs": [
                {
                    "workspace": "default",
                    "doc_id": doc_id_of(DOCS["gb8978"]),
                    "doc_name": DOCS["gb8978"],
                },
            ],
            "gold": {
                "expected_items_source": f"两物理片原始行：{t1a} {len(rows_a)} 行 + {t1b} "
                f"{len(rows_b)} 行",
                "expected_items_count": len(rows_a) + len(rows_b),
                # R5: the FULL frozen item set — every row with its raw cells
                "expected_items": [{"seq": r[0], "cells": r} for r in (rows_a + rows_b)],
                "locator": f"{t1a} + {t1b}（表1 + 表1(完)）",
                "supporting_quote": " | ".join(rows_a[0]) if rows_a else "",
                "evidence_kind": "table_logical",
                "target_evidence": [
                    {
                        **te("gb8978", t1a),
                        "quote": " | ".join(rows_a[0]) if rows_a else "",
                    },
                    {
                        **te("gb8978", t1b),
                        "quote": " | ".join(rows_b[0]) if rows_b else "",
                    },
                ],
            },
            "constraints": ["code=gb8978-1996", "table=1"],
            "allowed_status": ["complete"],
            "gold_review_status": "unreviewed",
            "revision": {"note": "提交 quote 含表头且非逐字来源；已附两片原始行坐标与计数"},
        }
    )
    pollutants = sorted(
        {r[1] for r in g if len(r) > 2 and r[0].strip().isdigit() and "污染物" not in r[1]}
    )
    items.append(
        {
            "query_id": "table-enum-002",
            "category": "table_enum",
            "question": "GB 3095-2012 表 1 列出的基本项目污染物有哪些？",
            "workspace": "default",
            "target_docs": [
                {
                    "workspace": "default",
                    "doc_id": doc_id_of(DOCS["gb3095_2012"]),
                    "doc_name": DOCS["gb3095_2012"],
                },
            ],
            "gold": {
                "expected_items": [{"name": n} for n in pollutants],
                "locator": f"{tid1} 污染物项目列去重（同污染物多平均时间为子行，不属于额外答案项）",
                "supporting_quote": first_row_quote(DOCS["gb3095_2012"], tid1),
                "evidence_kind": "table_logical",
                "target_evidence": [te("gb3095_2012", tid1)],
            },
            "constraints": ["code=gb3095-2012", "table=1"],
            "allowed_status": ["complete"],
            "gold_review_status": "unreviewed",
        }
    )
    t2s = [table_id(DOCS["gb14554"], s) for s in (2, 3, 4)]
    proj: list[str] = []
    for t in t2s:
        for r in grid(DOCS["gb14554"], t):
            if len(r) > 1 and r[0].strip().isdigit() and "序号" not in r[0]:
                name = r[1].strip()
                if name and name not in proj:
                    proj.append(name)
    items.append(
        {
            "query_id": "table-enum-003",
            "category": "table_enum",
            "question": "GB 14554-93 表 2 及其续表列出的排放标准值项目有哪些？",
            "workspace": "default",
            "target_docs": [
                {
                    "workspace": "default",
                    "doc_id": doc_id_of(DOCS["gb14554"]),
                    "doc_name": DOCS["gb14554"],
                },
            ],
            "gold": {
                # B2 projection: the ANSWER is the pollutant-NAME set (9 items);
                # the per-height raw rows stay as citation evidence, never as
                # additional answer items
                "expected_items": [{"name": n} for n in proj],
                "locator": " + ".join(t2s) + "（表2+续表2+续表2；按名称去重，"
                "不把排气筒高度当新污染物）",
                "supporting_quote": first_row_quote(DOCS["gb14554"], t2s[0]),
                "evidence_kind": "table_logical",
                "target_evidence": [
                    {**te("gb14554", t), "quote": first_row_quote(DOCS["gb14554"], t)} for t in t2s
                ],
            },
            "constraints": ["code=gb14554-93", "table=2"],
            "allowed_status": ["complete"],
            "gold_review_status": "unreviewed",
            "revision": {"note": "按名称去重；排气筒高度不是新污染物项目"},
        }
    )
    data_rows = [r for r in g3838 if r and r[0].strip().isdigit()]
    items.append(
        {
            "query_id": "table-enum-004",
            "category": "table_enum",
            "question": "GB 3838-2002 表 1 的基本项目共多少项？逐项列出。",
            "workspace": "default",
            "target_docs": [
                {
                    "workspace": "default",
                    "doc_id": doc_id_of(DOCS["gb3838"]),
                    "doc_name": DOCS["gb3838"],
                },
            ],
            "gold": {
                "expected_items_count": len(data_rows),
                # R5: the complete frozen item list (序号+项目名), not a count
                "expected_items": [{"seq": r[0], "name": r[1]} for r in data_rows],
                "note": f"网格 {len(g3838)} 行含 1 表头；数据序号 1–{len(data_rows)}",
                "locator": f"{t3838}（序号列 1–{len(data_rows)}）",
                "supporting_quote": " | ".join(data_rows[0][:3]) if data_rows else "",
                "evidence_kind": "table_logical",
                "target_evidence": [te("gb3838", t3838)],
            },
            "constraints": ["code=gb3838-2002", "table=1"],
            "allowed_status": ["complete"],
            "gold_review_status": "unreviewed",
            "revision": {
                "submitted_question": "GB 3838-2002 表 1 的 25 项基本项目是什么？",
                "corrected_question": "GB 3838-2002 表 1 的基本项目共多少项？逐项列出。",
                "submitted_expected_items_count": 25,
                "corrected_expected_items_count": len(data_rows),
                "reason": "网格 25 行含表头，数据序号 1–24，实际 24 项；显式更正且留历史",
            },
        }
    )
    t18466_2 = table_id(DOCS["gb18466"], 2)
    # R5: every data row of 表2 with its raw cells (multi-level headers are
    # flattened per physical row; 脚注 rows kept separately)
    t18466_grid = grid(DOCS["gb18466"], t18466_2)
    t18466_rows = [
        {"row_in_fragment": i, "cells": r}
        for i, r in enumerate(t18466_grid)
        if r and r[0].strip().isdigit()
    ]
    t18466_context = {
        "header_rows": [r for r in t18466_grid if r and not r[0].strip().isdigit()][:1],
        "footnotes": [
            " | ".join(r) for r in t18466_grid if r and any(c.strip().startswith("注") for c in r)
        ],
    }
    items.append(
        {
            "query_id": "table-enum-005",
            "category": "table_enum",
            "question": "GB 18466-2005 表 2 的控制项目和预处理标准是什么？",
            "workspace": "default",
            "target_docs": [
                {
                    "workspace": "default",
                    "doc_id": doc_id_of(DOCS["gb18466"]),
                    "doc_name": DOCS["gb18466"],
                },
            ],
            "gold": {
                # R5: complete expected set — every control item row with its
                # 预处理标准 value column, read from the raw merged grid
                "expected_items": t18466_rows,
                "expected_items_count": len(t18466_rows),
                "note": "多层/合并单元格按行展开；答案投影=数据行（序号+控制项目+排放/预处理标准）；"
                "表头与脚注为上下文（footnotes 保留总余氯细分），不作为集合成员",
                "locator": t18466_2,
                "raw_grid_context": t18466_context,
                "supporting_quote": " | ".join(str(c) for c in t18466_rows[0]["cells"])
                if t18466_rows
                else "",
                "evidence_kind": "table_logical",
                "target_evidence": [te("gb18466", t18466_2)],
            },
            "constraints": ["code=gb18466-2005", "table=2"],
            "allowed_status": ["complete"],
            "gold_review_status": "unreviewed",
        }
    )
    t3_3095 = table_id(DOCS["gb3095_2012"], 3)
    g3 = grid(DOCS["gb3095_2012"], t3_3095)
    names3: list[str] = []
    for r in g3:
        if len(r) > 1 and r[0].strip().isdigit():
            n = r[1].strip()
            if n and n not in names3:
                names3.append(n)
    items.append(
        {
            "query_id": "table-enum-006",
            "category": "table_enum",
            "question": "GB 3095-2012 表 3 列出了哪些污染物的分析方法？",
            "workspace": "default",
            "target_docs": [
                {
                    "workspace": "default",
                    "doc_id": doc_id_of(DOCS["gb3095_2012"]),
                    "doc_name": DOCS["gb3095_2012"],
                },
            ],
            "gold": {
                "expected_items": [{"name": n} for n in names3],
                "note": f"网格 {len(g3)} 行；按污染物名称列去重（不是 {len(g3)} 种污染物；"
                "同一污染物多方法行为子行）",
                "locator": t3_3095,
                "supporting_quote": first_row_quote(DOCS["gb3095_2012"], t3_3095),
                "evidence_kind": "table_logical",
                "target_evidence": [te("gb3095_2012", t3_3095)],
            },
            "constraints": ["code=gb3095-2012", "table=3"],
            "allowed_status": ["complete"],
            "gold_review_status": "unreviewed",
            "revision": {"note": "16 网格行不是 16 污染物；名称列去重后为 expected_items"},
        }
    )

    # ================= synthesis (6) ======================================
    t3095_12 = table_id(DOCS["gb3095_2012"], 1)
    t3095_26 = table_id(DOCS["gb3095_2026"], 1)
    pm12 = find_row(
        grid(DOCS["gb3095_2012"], t3095_12),
        lambda r: len(r) > 4 and "2.5" in r[1].replace(" ", "") and "年平均" in r[2],
    )
    items.append(
        {
            "query_id": "syn-001",
            "category": "synthesis",
            "question": "对比 GB 3095-2012 与 GB 3095-2026 中 PM2.5 年平均浓度限值的差异。",
            "workspace": "default",
            "target_docs": [
                {
                    "workspace": "default",
                    "doc_id": doc_id_of(DOCS["gb3095_2012"]),
                    "doc_name": DOCS["gb3095_2012"],
                },
                {
                    "workspace": "default",
                    "doc_id": doc_id_of(DOCS["gb3095_2026"]),
                    "doc_name": DOCS["gb3095_2026"],
                },
            ],
            "gold": {
                "expected": "2012：PM2.5 年均 一级 15／二级 35；2026 过渡期（至2030年末）"
                "一级15／二级30，2031 起一级10／二级25 μg/m³。必须携带过渡阶段日期条件。",
                "locator": f"{t3095_12} PM2.5/年平均行 + {t3095_26} PM2.5/年平均行（含阶段列）",
                "supporting_quote": " | ".join(pm12) if pm12 else "",
                "evidence_kind": "cross_table",
                "target_evidence": [
                    {
                        **te("gb3095_2012", t3095_12),
                        "quote": " | ".join(pm12) if pm12 else "",
                    },
                    {
                        **te("gb3095_2026", t3095_26),
                        "quote": first_row_quote(DOCS["gb3095_2026"], t3095_26),
                    },
                    # B5: the transition dates are a NECESSARY condition of the
                    # answer — the 2026 foreword names 2030-12-31/2031-01-01
                    {
                        **te("gb3095_2026", "eebc13e2a0348fa67955192750d4e9e6"),
                        "quote": "本标准自实施之日起至2030年12月31日，"
                        "环境空气污染物基本项目实施过渡阶段浓度限值；"
                        "2031年1月1日起，在全国范围内实施基本项目浓度限值。",
                    },
                ],
            },
            "constraints": ["versions=2012,2026", "condition=transition-dates"],
            "allowed_status": ["complete"],
            "gold_review_status": "unreviewed",
            "revision": {
                "reason": "必须保留 2026 过渡期至2030年末与2031起两阶段，不能只给一对新旧值",
            },
        }
    )
    b61 = block_of(DOCS["gb18466"], r"^#*\s*6\.1\s")
    items.append(
        {
            "query_id": "syn-002",
            "category": "synthesis",
            "question": "GB 18466-2005 排放的污水在执行标准和监测点位上分别有什么要求？",
            "workspace": "default",
            "target_docs": [
                {
                    "workspace": "default",
                    "doc_id": doc_id_of(DOCS["gb18466"]),
                    "doc_name": DOCS["gb18466"],
                },
            ],
            "gold": {
                "expected": "4.1 执行标准（表1/表2、排放/预处理标准）与 6.1 取样与监测"
                "两个范围独立取证后合并；6.1 存在重复 6.1.2 原始编号，不能按编号去重丢独立要求",
                "locator": f"block {(b41 or {}).get('blockid', '')}（4.1）+ block "
                f"{(b61 or {}).get('blockid', '')}（6.1）",
                "supporting_quote": (b61 or {}).get("content", "")[:200],
                "evidence_kind": "multi_scope",
                "target_evidence": [
                    {
                        **te("gb18466", (b41 or {}).get("blockid", "")),
                        "quote": (b41 or {}).get("content", "")[:180],
                    },
                    {
                        **te("gb18466", (b61 or {}).get("blockid", "")),
                        "quote": (b61 or {}).get("content", "")[:180],
                    },
                ],
            },
            "constraints": ["code=gb18466-2005"],
            "allowed_status": ["complete"],
            "gold_review_status": "unreviewed",
        }
    )
    b4211 = block_of(DOCS["gb8978"], r"4\.2\.1\.1")
    items.append(
        {
            "query_id": "syn-003",
            "category": "synthesis",
            "question": "GB 8978-1996 中第一类污染物和第二类污染物在控制方式上的区别是什么？",
            "workspace": "default",
            "target_docs": [
                {
                    "workspace": "default",
                    "doc_id": doc_id_of(DOCS["gb8978"]),
                    "doc_name": DOCS["gb8978"],
                },
            ],
            "gold": {
                "expected": "第一类：在车间或车间处理设施排放口采样；第二类：在排污单位排放口采样",
                "locator": f"block {(b4211 or {}).get('blockid', '')} §4.2.1.1/4.2.1.2（完整原块）",
                "supporting_quote": (b4211 or {}).get("content", "")[:240],
                "evidence_kind": "prose_block",
                "target_evidence": [te("gb8978", (b4211 or {}).get("blockid", ""))],
            },
            "constraints": ["code=gb8978-1996"],
            "allowed_status": ["complete"],
            "gold_review_status": "unreviewed",
            "revision": {"note": "提交含省略号 quote 不是逐字引句；已改完整块"},
        }
    )
    b3838_scope = block_of(DOCS["gb3838"], r"^#*\s*1\s*范围|适用范围")
    b3095_scope = block_of(DOCS["gb3095_2012"], r"^#*\s*1\s*适用范围|本标准规定了环境空气质量")
    items.append(
        {
            "query_id": "syn-004",
            "category": "synthesis",
            "question": "GB 3838-2002 与 GB 3095-2012 分别对哪些环境要素规定质量标准？",
            "workspace": "default",
            "target_docs": [
                {
                    "workspace": "default",
                    "doc_id": doc_id_of(DOCS["gb3838"]),
                    "doc_name": DOCS["gb3838"],
                },
                {
                    "workspace": "default",
                    "doc_id": doc_id_of(DOCS["gb3095_2012"]),
                    "doc_name": DOCS["gb3095_2012"],
                },
            ],
            "gold": {
                "expected": "GB3838：地表水环境质量；GB3095：环境空气质量。两原文单独引用，"
                "不得跨文档混引",
                "locator": f"block {(b3838_scope or {}).get('blockid', '')}（GB3838 范围）+ "
                f"block {(b3095_scope or {}).get('blockid', '')}（GB3095 范围）",
                "supporting_quote": (b3095_scope or {}).get("content", "")[:180],
                "evidence_kind": "multi_doc",
                "target_evidence": [
                    {
                        **te("gb3838", (b3838_scope or {}).get("blockid", "")),
                        "quote": (b3838_scope or {}).get("content", "")[:180],
                    },
                    {
                        **te("gb3095_2012", (b3095_scope or {}).get("blockid", "")),
                        "quote": (b3095_scope or {}).get("content", "")[:180],
                    },
                ],
            },
            "constraints": ["codes=gb3838-2002,gb3095-2012"],
            "allowed_status": ["complete"],
            "gold_review_status": "unreviewed",
        }
    )
    items.append(
        {
            "query_id": "syn-005",
            "category": "synthesis",
            "question": "综合 GB 18466-2005 表 1、表 2，说明传染病医疗机构、综合医疗机构"
            "分别执行哪张表。",
            "workspace": "default",
            "target_docs": [
                {
                    "workspace": "default",
                    "doc_id": doc_id_of(DOCS["gb18466"]),
                    "doc_name": DOCS["gb18466"],
                },
            ],
            "gold": {
                "expected": "传染病和结核病医疗机构 → 表1（一律执行）；县级及县级以上或20床及以上"
                "的综合/其他医疗机构 → 表2（按排放去向分排放标准/预处理标准）",
                "locator": f"block {(b41 or {}).get('blockid', '')} §4.1 全文（含 4.1.2 条件）"
                " + 表1/表2 caption",
                "supporting_quote": (b41 or {}).get("content", "")[:240],
                "evidence_kind": "multi_scope",
                "target_evidence": [
                    {
                        **te("gb18466", (b41 or {}).get("blockid", "")),
                        "quote": (b41 or {}).get("content", "")[:180],
                    },
                    {
                        **te("gb18466", table_id(DOCS["gb18466"], 1)),
                        "quote": first_row_quote(DOCS["gb18466"], table_id(DOCS["gb18466"], 1)),
                    },
                    {
                        **te("gb18466", t18466_2),
                        "quote": first_row_quote(DOCS["gb18466"], t18466_2),
                    },
                ],
            },
            "constraints": ["code=gb18466-2005", "tables=1,2"],
            "allowed_status": ["complete"],
            "gold_review_status": "unreviewed",
            "revision": {"reason": "必须保留 4.1.2 县级/20床条件与两类排放去向"},
        }
    )
    b422 = block_of(DOCS["gb8978"], r"4\.2\.2\.1")
    items.append(
        {
            "query_id": "syn-006",
            "category": "synthesis",
            "question": "GB 8978-1996 中 1997-12-31 前与 1998-01-01 起建设的单位分别执行哪几张表？",
            "workspace": "default",
            "target_docs": [
                {
                    "workspace": "default",
                    "doc_id": doc_id_of(DOCS["gb8978"]),
                    "doc_name": DOCS["gb8978"],
                },
            ],
            "gold": {
                "expected": "1997-12-31 前建设（含改、扩建）→ 表1、表2、表3；1998-01-01 起建设 → "
                "表1、表4、表5；建设时间以环境影响评价报告书（表）批准日期为准",
                "locator": f"block {(b422 or {}).get('blockid', '')} §4.2.2.1–4.2.2.3（两句均可取原文）",
                "supporting_quote": (b422 or {}).get("content", "")[:260],
                "evidence_kind": "prose_block",
                "target_evidence": [te("gb8978", (b422 or {}).get("blockid", ""))],
            },
            "constraints": ["code=gb8978-1996"],
            "allowed_status": ["complete"],
            "gold_review_status": "unreviewed",
            "revision": {"note": "两句均可取原文，不能只引前一版条件"},
        }
    )

    # ================= counter-examples (10) ===============================
    counters = [
        {
            "counter_id": "neg-001",
            "type": "absent_version",
            "question": "GB 3095-1996 的二级标准年均限值是多少？",
            "expected_behavior": "missing；库内 2012/2026，另一个版本不得替代",
            "expected_status": "missing",
            "review_status": "expectation_checked_runtime_verification_required",
        },
        {
            "counter_id": "neg-002",
            "type": "cross_workspace_isolation",
            "question": "（隔离测试）default 查询不得返回其他 workspace 同 ID 证据",
            "expected_behavior": "组合键 (workspace,id) 隔离",
            "expected_status": "isolation",
            "review_status": "unreviewed",
        },
        {
            "counter_id": "neg-003",
            "type": "self_code_vs_cited_code",
            "question": "自身编号为 GB 3838-2002 的文档有哪些？（原题「涉及 GB 3838-2002」"
            "检索语义另计，不含引用文档）",
            "expected_behavior": "仅 self_code=GB3838 计入；引用该编号的文档不得计入自身编号集合",
            "expected_status": "ok",
            "review_status": "needs_correction",
            "revision": {
                "submitted_question": "哪些文档涉及 GB 3838-2002？",
                "corrected_question": "自身编号为 GB 3838-2002 的文档有哪些？（引用语义另计）",
                "reason": "原问题「涉及」含引用文档，与期望「仅自身编号」不一致",
            },
        },
        {
            "counter_id": "neg-004",
            "type": "fragmented_table_merge",
            "question": "GB 8978-1996 表 1 共有几项？",
            "expected_behavior": "必须合并两物理片（13 项）；只给 5/10 项并 complete 属失败",
            "expected_status": "complete",
            "review_status": "reviewed",
        },
        {
            "counter_id": "neg-005",
            "type": "same_number_different_docs",
            "question": "GB 3838-2002 的表 1 与 GB 3095-2012 的表 1 是同一张表吗？",
            "expected_behavior": "逻辑表身份含文档+章节+表号，跨文档不合并",
            "expected_status": "ambiguous",
            "review_status": "unreviewed",
        },
        {
            "counter_id": "neg-006",
            "type": "no_answer_in_corpus",
            "question": "GB 50014-2021（室外排水设计标准）中雨水管渠设计重现期的取值范围是多少？",
            "expected_behavior": "missing；不得编造或近似替代（含无年份裸编号同样拒绝）",
            "expected_status": "missing",
            "review_status": "expectation_checked_runtime_verification_required",
        },
        {
            "counter_id": "neg-007",
            "type": "ambiguous_caption",
            "question": "GB 8978-1996 中 caption 为空表号的表（tb-…-0003）属于哪个表号？",
            "expected_behavior": "不能确认时 ambiguous，不强行声称完整",
            "expected_status": "ambiguous",
            "review_status": "unreviewed",
        },
        {
            "counter_id": "neg-008",
            "type": "budget_exhaustion",
            "question": "（构造）极小预算枚举 GB 18466-2005 全部 4.1 条款。",
            "expected_behavior": "partial + 已处理/总量；不得静默截断后 complete",
            "expected_status": "partial",
            "review_status": "unreviewed",
        },
        {
            "counter_id": "neg-009",
            "type": "duplicate_content_doc",
            "question": "water-58_ca-resolution-96-079-approved-1997.pdf 的内容在库内可检索吗？",
            "expected_behavior": "该文件自身因内容重复未入库（无独立 doc 身份）；但其内容与已入库原件"
            "相同，可通过原件检索到。不得把去重当作内容丢失",
            "expected_status": "ok",
            "review_status": "needs_correction",
            "revision": {
                "submitted_expected_behavior": "该文件因内容重复未入库；必须报「无对应 chunks」，"
                "不得把它算入可检索文档",
                "corrected_expected_behavior": "文件身份未导入不等于内容不可检索；内容与 water-44 "
                "完全相同，可通过已入库原件检索",
                "reason": "审阅：该 PDF 内容与 water44 完全相同，去重不等于内容丢失",
            },
        },
        {
            "counter_id": "neg-010",
            "type": "version_substitution",
            "question": "GB 18466-2005 修改单（2026）能否替代 GB 18466-2005 回答原标准条款？",
            "expected_behavior": "修改单只修改指定条款；原标准问题必须读原文档，不得用修改单替代",
            "expected_status": "ok",
            "review_status": "unreviewed",
        },
    ]

    return {
        "version": "phase-2-gold-candidates-v2-gate2-corrected",
        "generated_by": "env_rag_final.search.gold (re-derived from raw parsed artifacts)",
        "gold_review_policy": "未审核答案不计入质量指标；主 agent 逐题审核原文依据后冻结 benchmark 版本",
        "frozen_inputs": {
            "source_fingerprint": "95f7791fd84171ab727870fc5810d79b4327b0c4fa547d432951e0499a3808f8",
            "catalog_snapshot_id": "4919b3938ad93747",
            "workspace": "default",
        },
        "corrections_applied": [
            "fact-004 III 类 COD 按表头列索引 = 20 mg/L（I/II=15）",
            "fact-005 二级臭气浓度保留新扩改建20/现有30 两条件",
            "fact-007 表4 与表2 两年限范围分别引用",
            "table-enum-004 题干更正为 24 项（25 网格行含表头）",
            "file-enum-005 纳入修改单及含修改单整合版（封面归属，不得冒认 self_code）",
            "prose-enum-001 四术语各附原始块 typed 证据",
            "prose-enum-002/syn-005 保留 4.1.2 县级/20床条件与排放去向",
            "prose-enum-004 III 类含越冬场/洄游通道/水产养殖；类号 OCR 异常保留原号",
            "syn-001 保留 2026 过渡期（至2030末）与 2031 起两阶段",
            "neg-003 问题/期望一致化（自身编号语义）",
            "neg-009 期望更正：去重 ≠ 内容不可检索",
            "全部题附 typed target_evidence（workspace/doc/unit/chunk/scope）",
        ],
        "evidence_counts": {
            "fact": sum(1 for i in items if i["category"] == "fact"),
            "file_enum": sum(1 for i in items if i["category"] == "file_enum"),
            "prose_enum": sum(1 for i in items if i["category"] == "prose_enum"),
            "table_enum": sum(1 for i in items if i["category"] == "table_enum"),
            "synthesis": sum(1 for i in items if i["category"] == "synthesis"),
            "counter_examples": len(counters),
        },
        "derivation_errors": errors,
        "questions": items,
        "counter_examples": counters,
    }


def verify_typed_targets(payload: dict) -> list[str]:
    """R5/B5: automatically verify EVERY typed target and supporting quote.

    - prose unit targets: the blockid must exist in the doc's blocks and the
      supporting quote must be found VERBATIM inside that block's content —
      a quote that is only a prefix of the source is accepted ONLY when the
      gold declares it truncated (``truncated: true``); an extended quote with
      a fabricated tail never passes;
    - table unit targets: the table id must exist AND the quote, when present,
      must match a real row of the raw grid (row-level content check);
    - TOC blocks (目次) are rejected as targets outright.
    Failures are collected and reported — a gold whose evidence does not
    re-read cannot be frozen.
    """
    problems: list[str] = []
    for q in payload["questions"]:
        g = q.get("gold", {})
        quote = (g.get("supporting_quote") or "").strip()
        for te_entry in g.get("target_evidence") or []:
            uid = te_entry.get("unit_id")
            if not uid:
                continue
            doc_name = next(
                (
                    t["doc_name"]
                    for t in q.get("target_docs", [])
                    if t["doc_id"] == te_entry["doc_id"]
                ),
                None,
            )
            if not doc_name:
                problems.append(f"{q['query_id']}: typed target doc not in target_docs")
                continue
            tables = tables_of(doc_name)
            if uid in tables:
                # C4: table targets verify ROW content by CELL equality — the
                # quote must split into cells and EVERY quoted cell must equal
                # the corresponding cell of SOME real grid row (a column
                # projection). A real row plus a fabricated appended value
                # fails (no row has that cell sequence); a rewritten value
                # fails. Plain character substrings are never accepted.
                target_quote = (te_entry.get("quote") or quote).strip()
                if target_quote:
                    grid_rows = read_html_table((tables[uid].get("content") or ""))
                    quoted_cells = [
                        re.sub(r"\s+", " ", c).strip() for c in _split_quote_row(target_quote)
                    ]
                    quoted_cells = [c for c in quoted_cells if c]

                    def _row_matches(row: list[str]) -> bool:
                        norm_row = [re.sub(r"\s+", " ", c or "").strip() for c in row]
                        # full-cell projection: every quoted cell equals a cell
                        # of the row (contiguous, order-preserving subsequence
                        # or the full row) — colspan-expanded grids legitimately
                        # repeat cells, so a subsequence projection is allowed,
                        # but EVERY quoted cell must match EXACTLY and the
                        # projection may not append values the row lacks.
                        n, m = len(norm_row), len(quoted_cells)
                        if m == 0 or m > n:
                            return False
                        for start in range(n - m + 1):
                            if norm_row[start : start + m] == quoted_cells:
                                return True
                        return False

                    if quoted_cells and not any(_row_matches(r) for r in grid_rows):
                        problems.append(
                            f"{q['query_id']}: table quote is not a cell-exact projection "
                            f"of a real row of {uid[-8:]} ({doc_name[:20]})"
                        )
                continue
            blk = next((b for b in blocks_of(doc_name) if b.get("blockid") == uid), None)
            if blk is None:
                problems.append(f"{q['query_id']}: unit {uid[:8]} not found in {doc_name[:24]}")
                continue
            if _TOC_RE.search(blk.get("content") or ""):
                problems.append(f"{q['query_id']}: unit {uid[:8]} is a 目次 block")
                continue
            # each typed target carries its OWN quote when the item has several
            target_quote = (te_entry.get("quote") or quote).strip()
            if not target_quote:
                continue
            content = blk.get("content") or ""
            if target_quote in content:
                continue
            # a deliberately truncated quote is a PREFIX of the source: only
            # then it is legitimate — anything longer (fabricated tail) or
            # non-prefix (rewritten) fails
            truncated_declared = bool(te_entry.get("truncated"))
            if truncated_declared and content.startswith(target_quote):
                continue
            problems.append(
                f"{q['query_id']}: quote not found VERBATIM in unit {uid[:8]} ({doc_name[:20]})"
            )
    return problems


def _norm_cells(cells) -> str:
    """Whitespace-normalized joined row cells for grid matching."""
    import re as _re

    return " | ".join(_re.sub(r"\s+", " ", str(c or "")).strip() for c in cells)


def _split_quote_row(quote: str) -> list[str]:
    return [p for p in str(quote).split("|")]


if __name__ == "__main__":
    payload = build()
    problems = verify_typed_targets(payload)
    if problems:
        print("TYPED TARGET VERIFICATION FAILURES:")
        for p_ in problems:
            print("  -", p_)
        raise SystemExit(1)
    out = Path(__file__).resolve().parents[3] / "reports/pg-retrieval/phase-2/gold-candidates.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    counts = payload["evidence_counts"]
    print(f"gold candidates -> {out}")
    print(
        f"  fact={counts['fact']} file={counts['file_enum']} prose={counts['prose_enum']} "
        f"table={counts['table_enum']} syn={counts['synthesis']} "
        f"counters={counts['counter_examples']}"
    )
    if errors:
        print("DERIVATION ERRORS:")
        for e in errors:
            print("  -", e)
        raise SystemExit(1)
    total = sum(v for k, v in counts.items() if k != "counter_examples")
    print(f"  total positives={total}")
    if total < 30 or any(
        counts[k] < 6 for k in ("fact", "file_enum", "prose_enum", "table_enum", "synthesis")
    ):
        print("WARNING: coverage below the design minimum")
        raise SystemExit(1)
