"""Hierarchical chapter / clause scopes (task 2.5, corrected per S2).

Model:
- 叶范围（leaf scope）= 一个编号标题（或附录）起的连续 block 序列，边界由下一个
  同级/更高级标题确定——局部边界保持精确。
- 父范围（parent scope）= 聚合其全部后代叶范围的成员（按源顺序、去重），因此
  "GB 3095 第 4 章" 同时包含 4.1／4.2 的 blocks，且不混入第 5 章。
- 大 block 中的内嵌条款（无独立标题 block）持久化为 requires_span：scope 状态为
  requires_span，note 记录 block 与 chunk 引用跨度；读取层按字符跨度提取，跨度
  无法满足时显式拒绝，整个 block 的引用跨度不等同于完整条款。
- front-matter／空成员标 ambiguous。

confirm_status:
- confirmed      — 叶范围有成员（含单 block 跨 chunk，如 GB18466 4.1）
- ambiguous      — front-matter 或无成员
- requires_span  — 内容位于被大量 chunk 引用的大 block 中，需要 span 提取
"""

from __future__ import annotations

import re

_CLAUSE_NUM_RE = re.compile(r"^(\d+(?:\.\d+)*)\s")
_APPENDIX_RE = re.compile(
    r"^(?:附录\s*[A-Z]|Annex\s+\d+|Appendix\s+[A-Z]|\bAttachment\s+[A-Z])", re.I
)
_BIG_BLOCK_MIN_REFS = 10
_BIG_BLOCK_MIN_CHARS = 50_000


def _heading_number(heading: str | None) -> str | None:
    if not heading:
        return None
    m = _CLAUSE_NUM_RE.match(heading.strip())
    return m.group(1) if m else None


def _mk(
    workspace, doc_id, snapshot_id, scope_id, kind, title, number, status, note=None, parent=None
):
    return {
        "workspace": workspace,
        "doc_id": doc_id,
        "snapshot_id": snapshot_id,
        "scope_id": scope_id,
        "scope_kind": kind,
        "parent_scope_id": parent,
        "title": title,
        "number": number,
        "confirm_status": status,
        "note": note,
    }


def build_scopes(
    doc_id: str, snapshot_id: str, blocks: list[dict], workspace: str = "default"
) -> list[dict]:
    """Build leaf + parent scopes from ordered raw content blocks.

    Each scope dict carries ``_members`` (leaf: own blocks; parent: aggregated
    descendant members in source order).
    """
    ws = workspace
    leaf: list[tuple[dict, list[str]]] = []
    open_scope: dict | None = None
    open_members: list[str] = []
    front_members: list[str] = []
    block_order: dict[str, int] = {}

    for idx, b in enumerate(blocks):
        bid = b["blockid"]
        block_order[bid] = idx
        heading = (b.get("heading") or "").strip()
        number = _heading_number(heading)
        is_appendix = bool(_APPENDIX_RE.match(heading))

        if number or is_appendix:
            if open_scope is not None:
                leaf.append((open_scope, open_members))
            open_scope = _mk(
                ws,
                doc_id,
                snapshot_id,
                f"{doc_id}:scope:{number or heading}",
                "clause" if number else "chapter",
                heading,
                number,
                "confirmed",
            )
            open_members = [bid]
            continue

        if open_scope is not None:
            open_members.append(bid)
        else:
            front_members.append(bid)

    if open_scope is not None:
        leaf.append((open_scope, open_members))

    scopes: list[dict] = []
    if front_members:
        sc = _mk(
            ws,
            doc_id,
            snapshot_id,
            f"{doc_id}:scope:front-matter",
            "chapter",
            "front-matter",
            None,
            "ambiguous",
            "封面/公告/前言等未编号区块，边界以 block 顺序为准",
        )
        sc["_members"] = front_members
        scopes.append(sc)

    for sc, members in leaf:
        sc["_members"] = members
        if not members:
            sc["confirm_status"] = "ambiguous"
            sc["note"] = "scope has no member units"
        scopes.append(sc)

    # ---- parents: aggregate descendants (S2) --------------------------------
    # Iteratively materialize any missing ancestor ("4.2.1.1" without a "4.2"
    # heading block) so every sub-scope has a resolvable parent chain.
    by_number = {sc["number"]: sc for sc in scopes if sc["number"]}

    def ensure_chain(num: str):
        """Create ancestor scopes down to `num` when their headings are absent."""
        parts = num.split(".")
        for depth in range(1, len(parts)):
            ancestor = ".".join(parts[:depth])
            if ancestor in by_number:
                continue
            anc = _mk(
                ws,
                doc_id,
                snapshot_id,
                f"{doc_id}:scope:{ancestor}",
                "clause",
                ancestor,
                ancestor,
                "confirmed",
                note="父标题无独立 block；成员由子范围聚合（源顺序）",
            )
            anc["_members"] = []
            scopes.append(anc)
            by_number[ancestor] = anc

    for sc in list(scopes):
        num = sc["number"]
        if not num:
            continue
        if "." in num:
            ensure_chain(num)
        parent_num = num.rsplit(".", 1)[0] if "." in num else None
        if parent_num:
            sc["parent_scope_id"] = by_number[parent_num]["scope_id"]

    # aggregate members bottom-up so grand-parents inherit transitively
    for depth in sorted({s["number"].count(".") for s in scopes if s["number"]}, reverse=True):
        for sc in scopes:
            num = sc["number"]
            if not num or num.count(".") != depth:
                continue
            parent = by_number[num.rsplit(".", 1)[0]]
            merged = sorted(
                set(parent.get("_members", [])) | set(sc["_members"]),
                key=lambda bid: block_order.get(bid, 1 << 30),
            )
            parent["_members"] = merged

    order = {sc["scope_id"]: i for i, sc in enumerate(scopes)}
    scopes.sort(key=lambda sc: order[sc["scope_id"]])
    return scopes


def persist_span_requirements(
    doc_id: str,
    snapshot_id: str,
    blocks: list[dict],
    scopes: list[dict],
    chunk_link_counts: dict[str, int],
) -> list[dict]:
    """Mark scopes whose content lives inside oversized multi-chunk blocks.

    Any scope whose members are exclusively big blocks (referenced by many
    chunks) is persisted with ``requires_span``: the reference span proves
    neither sub-clause location nor per-fragment coverage, so reading must
    extract verified character spans (or per-table locators) and refuse
    otherwise. Embedded clause numbers, when present, are listed in the note.
    """
    big_blocks = [
        b
        for b in blocks
        if len(b.get("content") or "") >= _BIG_BLOCK_MIN_CHARS
        and chunk_link_counts.get(b["blockid"], 0) >= _BIG_BLOCK_MIN_REFS
    ]
    if not big_blocks:
        return []
    big_ids = {b["blockid"] for b in big_blocks}
    all_numbers = {s["number"] for s in scopes if s.get("number")}
    updated: list[dict] = []
    for sc in scopes:
        if sc["confirm_status"] == "ambiguous" or not sc.get("_members"):
            continue
        if not set(sc["_members"]) <= big_ids:
            continue  # scope has small dedicated blocks → normal reading works
        members_big = [b for b in big_blocks if b["blockid"] in sc["_members"]]
        embedded: set[str] = set()
        for b in members_big:
            for m in re.finditer(r"^(\d+(?:\.\d+)*)\s", b.get("content") or "", re.M):
                embedded.add(m.group(1))
        embedded -= {sc["number"]}
        embedded -= all_numbers
        max_refs = max(chunk_link_counts.get(b["blockid"], 0) for b in members_big)
        chars = sum(len(b.get("content") or "") for b in members_big)
        sc["confirm_status"] = "requires_span"
        span_hint = (
            f"内嵌条款 {sorted(embedded)[:6]} 需按字符跨度定位；"
            if embedded
            else "子片段（表格/段落）需按 locator 逐片段定位；"
        )
        sc["note"] = (
            f"内容位于大 block（{members_big[0]['blockid'][:12]}…，共 {chars} 字符，"
            f"被最多 {max_refs} 个 chunk 引用）；{span_hint}"
            "不得把整个 block 引用跨度当作完整范围"
        )
        updated.append(sc)
    return updated
