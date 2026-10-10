"""Candidate benchmark sample-set — task 1.8 (corrected per G0-3).

Five question categories (≥6 each) plus ≥8 counter-examples. Every positive
question carries *real* locators: workspace, actual doc_id, full doc_name, and
a validity check (parsed artifact present AND chunks readable) executed at
generation time. Questions whose targets fail the check are moved to
``unresolved_targets`` and do NOT count toward meets_minimum. Gold stays
``unreviewed`` — nothing becomes a metric until the main agent reviews it.
"""

from __future__ import annotations

import asyncpg

from . import identity

_GOLD = "unreviewed"


def _q(qid, category, question, targets, gold, sources, notes=""):
    return {
        "query_id": qid,
        "category": category,
        "question": question,
        "workspace": "default",
        "target_docs": targets,  # list of real locators, see _targets()
        "gold": gold,
        "gold_review_status": _GOLD,
        "gold_sources": sources,
        "notes": notes,
    }


def _targets(rows: list) -> list[dict]:
    return [
        {
            "workspace": r["workspace"],
            "doc_id": r["doc_id"],
            "doc_name": r["doc_name"],
            "chunks_in_db": r["chunks_in_db"],
            "parsed_artifact": r.get("parsed_artifact", False),
            "valid": r.get("valid", False),
        }
        for r in rows
    ]


async def build_sample_set(conn: asyncpg.Connection) -> dict:
    ws = "default"

    # Fetch real identities + validity (parsed artifact AND chunks) for targets.
    async def locate(doc_name: str) -> dict | None:
        r = await conn.fetchrow(
            """SELECT f.id AS doc_id, f.doc_name, f.workspace,
                      (SELECT count(*) FROM public.lightrag_doc_chunks c
                       WHERE c.workspace=f.workspace AND c.full_doc_id=f.id) AS chunks,
                      f.sidecar_location
               FROM public.lightrag_doc_full f
               WHERE f.workspace=$1 AND f.doc_name=$2""",
            ws,
            doc_name,
        )
        if r is None:
            return None
        parsed_ok = identity.blocks_lines_for(doc_name, r["sidecar_location"]) is not None
        return {
            "workspace": r["workspace"],
            "doc_id": r["doc_id"],
            "doc_name": r["doc_name"],
            "chunks_in_db": r["chunks"],
            "parsed_artifact": parsed_ok,
            "valid": r["chunks"] > 0 and parsed_ok,
        }

    names = {
        "gb3095_2012": "air-02_生态环境部_环境空气质量标准_GB3095-2012.pdf",
        "gb3095_2026": "air-03_生态环境部_环境空气质量标准_GB3095-2026.pdf",
        "gb8978": "water-11_生态环境部_污水综合排放标准_GB8978-1996.pdf",
        "gb18466": "water-09_生态环境部_医疗机构水污染物排放标准_GB18466-2005.pdf",
        "gb3838": "water-04_生态环境部_地表水环境质量标准_GB3838-2002.pdf",
        "gb14554": "air-06_生态环境部_恶臭污染物排放标准_GB14554-93.pdf",
    }
    located = {}
    unresolved: list[dict] = []
    for key, name in names.items():
        loc = await locate(name)
        if loc is None:
            unresolved.append({"doc_name": name, "reason": "not in doc_full"})
            continue
        located[key] = loc

    # Whole-corpus sets resolved by explicit predicates (no ellipsis IDs).
    async def names_by(pattern: str) -> list[dict]:
        rows = await conn.fetch(
            """SELECT f.id AS doc_id, f.doc_name, f.workspace,
                      (SELECT count(*) FROM public.lightrag_doc_chunks c
                       WHERE c.workspace=f.workspace AND c.full_doc_id=f.id) AS chunks
               FROM public.lightrag_doc_full f
               WHERE f.workspace=$1 AND f.doc_name LIKE $2 ORDER BY f.doc_name""",
            ws,
            pattern,
        )
        return [
            {
                "workspace": r["workspace"],
                "doc_id": r["doc_id"],
                "doc_name": r["doc_name"],
                "chunks_in_db": r["chunks"],
                "parsed_artifact": identity.blocks_lines_for(r["doc_name"], None) is not None,
                "valid": (
                    r["chunks"] > 0 and identity.blocks_lines_for(r["doc_name"], None) is not None
                ),
            }
            for r in rows
        ]

    nianbao = await names_by("%中国移动源环境管理年报%")
    gongbao_water = await names_by("%水利部_%年中国水资源公报%")
    hj_docs = await names_by("%HJ%-%")
    gaiidan = await names_by("%修改单%")
    for label, rows in (
        ("file-enum-002", nianbao),
        ("file-enum-003", gongbao_water),
        ("file-enum-004", hj_docs),
        ("file-enum-005", gaiidan),
    ):
        if not rows:
            unresolved.append({"query_id": label, "reason": "predicate matched 0 docs"})

    T = {k: _targets([v]) for k, v in located.items()}
    TL = lambda *keys: _targets([located[k] for k in keys])  # noqa: E731

    facts = [
        _q(
            "fact-001",
            "fact",
            "GB 3095-2012 中二氧化硫的年平均浓度二级限值是多少？",
            T["gb3095_2012"],
            {"assertion": "二级限值 60 μg/m³（以表1原文为准）"},
            [
                "表1 环境空气污染物基本项目浓度限值（tb-257d8cf3fdf90e76c31908c4f92fc1a1-0001，GB3095-2012 chunk-002 内联）"
            ],
        ),
        _q(
            "fact-002",
            "fact",
            "GB 8978-1996 表 1 中总汞的最高允许排放浓度是多少？",
            T["gb8978"],
            {"assertion": "0.05 mg/L（以表1原文为准）"},
            [
                "表 1 第一类污染物最高允许排放浓度（tb-b45c510232ed4d2452b0f5b2a13434e4-0001，chunk-001）"
            ],
        ),
        _q(
            "fact-003",
            "fact",
            "GB 18466-2005 中“医疗机构污水”的定义是什么？",
            T["gb18466"],
            {"assertion": "3.2 条定义原文（以 chunk-001 正文为准）"},
            ["3 术语和定义（chunk-001；blocks 385d9e8e…/ad9d292d… 在该 chunk sidecar.refs 内）"],
        ),
        _q(
            "fact-004",
            "fact",
            "GB 3838-2002 中 III 类水体化学需氧量（COD）的标准限值是多少？",
            T["gb3838"],
            {"assertion": None, "gap": "gold 数值需人工对照表 1 原文补齐，不得编造"},
            ["表 1 地表水环境质量标准基本项目标准限值（tb-9390ecf1…-0001）"],
        ),
        _q(
            "fact-005",
            "fact",
            "GB 14554-93 中臭气浓度（无量纲）的厂界二级标准值是多少？",
            T["gb14554"],
            {"assertion": None, "gap": "gold 数值需人工对照表 1 原文补齐，不得编造"},
            ["表 1 恶臭污染物厂界标准值"],
        ),
        _q(
            "fact-006",
            "fact",
            "GB 3095-2012 的发布日期和实施日期分别是什么？",
            T["gb3095_2012"],
            {"assertion": "2012-02-29 发布；实施日期以封面原文为准（2016-01-01，待审核）"},
            [
                "封面 content_list（“2012-02-29 发布 2016-01-01 实施”）",
                "注意：发布／实施必须分开记录（specs 元数据要求）",
            ],
        ),
        _q(
            "fact-007",
            "fact",
            "GB 8978-1996 中 pH 值的排放限值范围是多少？",
            T["gb8978"],
            {"assertion": "6~9（表 2，1997-12-31 前建设单位的适用性以原文为准）"},
            ["表 2（tb-b45c510232ed4d2452b0f5b2a13434e4-0003）"],
        ),
    ]

    def _enum_q(qid, question, rows, predicate, expected_count=None):
        gold = {"match_predicate": predicate, "expected_doc_ids": [r["doc_id"] for r in rows]}
        if expected_count is not None:
            gold["expected_count"] = expected_count
        return _q(
            qid,
            "file_enum",
            question,
            _targets(rows),
            gold,
            ["匹配谓词对 doc_full.doc_name 全量执行（本文件生成时已解析出上方 expected_doc_ids）"],
        )

    file_enums = [
        _enum_q(
            "file-enum-001",
            "库内有哪些 GB 3095 标准的文档？列出文件名和版本年份。",
            await names_by("%GB3095-%"),
            "doc_name LIKE '%GB3095-%'",
        ),
        _enum_q(
            "file-enum-002",
            "库内有哪些《中国移动源环境管理年报》？",
            nianbao,
            "doc_name LIKE '%中国移动源环境管理年报%'",
            expected_count=5,
        ),
        _enum_q(
            "file-enum-003",
            "库内有哪些《中国水资源公报》（水利部）？",
            gongbao_water,
            "doc_name LIKE '%水利部_%年中国水资源公报%'",
            expected_count=5,
        ),
        _enum_q(
            "file-enum-004",
            "库内有哪些 HJ 系列的生态环境标准文件？",
            hj_docs,
            "doc_name LIKE '%HJ%-%'（HJ 编号模式，需主 agent 复核谓词是否混入非 HJ 编号）",
        ),
        _enum_q(
            "file-enum-005",
            "库内有哪些文档名称含“修改单”？",
            gaiidan,
            "doc_name LIKE '%修改单%'",
            expected_count=7,
        ),
        _q(
            "file-enum-006",
            "file_enum",
            "库内《地表水环境质量标准》相关的文档有哪些？",
            T["gb3838"],
            {
                "match_predicate": "doc_name LIKE '%地表水环境质量标准%'",
                "expected_doc_ids": [located["gb3838"]["doc_id"]],
                "notes": "引用该编号的其他文档不得计入（自身编号 vs 引用编号）",
            },
            ["specs：引用编号不能使文档匹配自身编号查询"],
        ),
        _enum_q(
            "file-enum-007",
            "列出库内全部恶臭污染物相关标准文件。",
            await names_by("%恶臭%"),
            "doc_name LIKE '%恶臭%'",
        ),
    ]

    prose_enums = [
        _q(
            "prose-enum-001",
            "prose_enum",
            "GB 18466-2005 中 3 章定义了哪些术语？逐项列出编号、中文名和英文对照。",
            T["gb18466"],
            {
                "expected_items": [
                    "3.1 医疗机构 medical organization",
                    "3.2 医疗机构污水",
                    "3.3 污泥 sludge",
                    "3.4 废气 waste gas",
                ],
                "coverage": "chunk-001 全文；跨 chunk 边界以原始 block 为准",
            },
            ["3 术语和定义（chunk-001）"],
        ),
        _q(
            "prose-enum-002",
            "prose_enum",
            "GB 18466-2005 的 4.1.1 至 4.1.5 分别规定了什么？逐条列出。",
            T["gb18466"],
            {
                "expected_items": ["4.1.1", "4.1.2", "4.1.3", "4.1.4", "4.1.5"],
                "coverage": "条款跨 chunk-001/002，需完整范围读取",
            },
            ["4.1 污水排放要求（chunk-001 4.1.1–4.1.2；chunk-002 4.1.3–4.1.5）"],
        ),
        _q(
            "prose-enum-003",
            "prose_enum",
            "GB 8978-1996 第 4.3 节“其他规定”列出了哪些要求？",
            T["gb8978"],
            {"expected_items": None, "gap": "以 chunk-001 正文 4.3 条款原文为准，待审核"},
            ["4.3 其他规定（chunk-001，block a00e1705… 在 refs 内）"],
        ),
        _q(
            "prose-enum-004",
            "prose_enum",
            "GB 3838-2002 的水域功能是如何分类的？列出全部类别。",
            T["gb3838"],
            {"expected_items": None, "gap": "分类条款原文待审核补齐"},
            ["正文 3.1（blocks 待定位）"],
        ),
        _q(
            "prose-enum-005",
            "prose_enum",
            "GB 14554-93 对恶臭污染物厂界标准值的分级别规定了哪几级？",
            T["gb14554"],
            {"expected_items": None, "gap": "以表 1 行列原文为准，待审核"},
            ["表 1 恶臭污染物厂界标准值"],
        ),
        _q(
            "prose-enum-006",
            "prose_enum",
            "GB 3095-2012 的 4.2 节对环境空气功能区质量要求作了哪些规定？",
            T["gb3095_2012"],
            {"expected_items": None, "gap": "4.2 条款正文 + 引用表 1/表 2，待审核"},
            ["4.2（block 7f9dddaf02f372cc7d329f4678c46fbc，chunk-002）"],
        ),
        _q(
            "prose-enum-007",
            "prose_enum",
            "GB 18466-2005 第 5 章“处理工艺与消毒要求”包含哪些条款？",
            T["gb18466"],
            {"expected_items": None, "gap": "5.1–5.x 范围以原始 block 边界为准，待审核"},
            ["5 处理工艺与消毒要求（block bbaab527… 所在 chunk 待映射核验）"],
        ),
    ]

    table_enums = [
        _q(
            "table-enum-001",
            "table_enum",
            "GB 8978-1996 表 1（第一类污染物）共列出哪些污染物及其限值？逐行列出。",
            T["gb8978"],
            {"expected_items_count": 13, "note": "两物理片段 5+10 行，逻辑续表必须合并后枚举"},
            ["tb-b45c510232ed4d2452b0f5b2a13434e4-0001（表 1）+ -0002（表 1(完)），同 chunk-001"],
        ),
        _q(
            "table-enum-002",
            "table_enum",
            "GB 3095-2012 表 1 列出的基本项目污染物有哪些？",
            T["gb3095_2012"],
            {
                "expected_items_count": 6,
                "note": "二氧化硫、二氧化氮、一氧化碳、臭氧、PM10、PM2.5（以原文为准）",
            },
            ["tb-257d8cf3fdf90e76c31908c4f92fc1a1-0001（chunk-002 内联）"],
        ),
        _q(
            "table-enum-003",
            "table_enum",
            "GB 3838-2002 表 1 的 25 项基本项目是什么？",
            T["gb3838"],
            {"expected_items_count": 25, "note": "单表 25 行；gold 清单需逐项审核，当前未审核"},
            ["tb-9390ecf1…-0001"],
        ),
        _q(
            "table-enum-004",
            "table_enum",
            "GB 18466-2005 表 2 的控制项目和预处理标准是什么？",
            T["gb18466"],
            {
                "expected_items": None,
                "gap": "以 tb-68a03b50e1ba1ffc6a0116529f694fe1-0002 行列原文为准，待审核",
            },
            ["tb-…-0002（chunk-002）"],
        ),
        _q(
            "table-enum-005",
            "table_enum",
            "GB 14554-93 表 2 及其续表列出的排放标准值项目有哪些？",
            T["gb14554"],
            {
                "expected_items": None,
                "gap": "表 2 + 续表 2 ×2 逻辑合并，待审核",
                "note": "续表关联需要 caption「续表 2」+ 表头/序号核验",
            },
            ["tables.json：0002「表 2 恶臭污染物排放标准值」、0003/0004「续表 2」"],
        ),
        _q(
            "table-enum-006",
            "table_enum",
            "GB 3095-2012 表 3 列出了哪些污染物的分析方法？",
            T["gb3095_2012"],
            {"expected_items_count": 16, "note": "dim [16,5]；chunk-003 区域"},
            ["tb-257d8cf3fdf90e76c31908c4f92fc1a1-0003（chunk-003 refs 437f7c19…）"],
        ),
        _q(
            "table-enum-007",
            "table_enum",
            "GB 8978-1996 表 6（测定方法）包含哪些行？",
            T["gb8978"],
            {
                "expected_items": None,
                "gap": "表 6 + 表 6(续) + 表 6(完) 三片段合并，待审核",
                "note": "跨 chunk（2c9867c4… 与 7b834077…）",
            },
            ["tables.json：tb-…-0013/0014/0015"],
        ),
    ]

    synthesis = [
        _q(
            "syn-001",
            "synthesis",
            "对比 GB 3095-2012 与 GB 3095-2026 中 PM2.5 年平均浓度限值的差异。",
            TL("gb3095_2012", "gb3095_2026"),
            {
                "expected": "两版本分别读取表 1 后对比；2012 年 15 μg/m³（一级，待审核）、2026 值待审核补齐"
            },
            ["GB 3095-2012 表1", "GB 3095-2026 表1（tb-4c883d21… 内联）"],
        ),
        _q(
            "syn-002",
            "synthesis",
            "GB 18466-2005 排放的污水在执行标准和监测点位上分别有什么要求？",
            T["gb18466"],
            {"expected": "4.1（排放要求）+ 6.1（取样与监测）合并；两范围独立取证（待审核）"},
            ["4.1（chunk-001/002）", "6.1（block e0dae056…）"],
        ),
        _q(
            "syn-003",
            "synthesis",
            "GB 8978-1996 中第一类污染物和第二类污染物在控制方式上的区别是什么？",
            T["gb8978"],
            {"expected": "表 1（第一类，不分时段）与表 2/4（第二类，分级分期）对照（待审核）"},
            ["表 1（chunk-001）", "表 4 第二类污染物（tb-…-0007）"],
        ),
        _q(
            "syn-004",
            "synthesis",
            "GB 3838-2002 与 GB 3095-2012 分别对哪些环境要素规定质量标准？",
            TL("gb3838", "gb3095_2012"),
            {"expected": "两文档各自独立覆盖后合并（地表水 vs 环境空气）；不得跨文档混引"},
            ["GB 3838-2002 范围/功能分类", "GB 3095-2012 1 适用范围"],
        ),
        _q(
            "syn-005",
            "synthesis",
            "综合 GB 18466-2005 的表 1、表 2、表 3，说明传染病医疗机构、综合医疗机构分别执行哪些表。",
            T["gb18466"],
            {"expected": "4.1.1–4.1.2 与三张表的对应关系（待审核）"},
            ["4.1.1/4.1.2（chunk-001）", "表 1（chunk-001）/表 2（chunk-002）/表 3"],
        ),
        _q(
            "syn-006",
            "synthesis",
            "GB 14554-93 中恶臭污染物排放限值与测定方法之间是什么对应关系？",
            T["gb14554"],
            {"expected": "表 2 排放标准值 + 表 3 测定方法（待审核）"},
            ["表 2/续表 2", "表 3（tb-…-0005）"],
        ),
        _q(
            "syn-007",
            "synthesis",
            "中国移动源环境管理年报 2021 年和 2025 年两份报告中机动车保有量分别是多少？",
            _targets([r for r in nianbao if ("2021" in r["doc_name"] or "2025" in r["doc_name"])]),
            {
                "expected": "各文档独立定位后比较；缺一年则报 incomplete，不得用近似文档替代（待审核补值）"
            },
            ["年报 2021（air-15…）", "年报 2025（air-19…）", "specs 跨文档枚举要求"],
        ),
    ]

    counter = [
        {
            "counter_id": "neg-001",
            "type": "absent_version",
            "question": "GB 3095-1996 的二级标准年均限值是多少？",
            "expected_behavior": "库内只有 2012/2026 版；必须报“目标版本未入库”，不得用 2012 版回答",
            "evidence": "inventory.jsonl 无 GB3095-1996",
            "review_status": _GOLD,
        },
        {
            "counter_id": "neg-002",
            "type": "cross_workspace_isolation",
            "question": "（测试 workspace 注入后的隔离查询）",
            "expected_behavior": "查询 default workspace 时不得返回其他 workspace 的同 ID 证据；Phase 1 适配器测试用",
            "evidence": "design.md 身份约束",
            "review_status": _GOLD,
            "note": "执行方式：隔离测试注入，不依赖真实第二 workspace",
        },
        {
            "counter_id": "neg-003",
            "type": "self_code_vs_cited_code",
            "question": "哪些文档涉及 GB 3838-2002？",
            "expected_behavior": "引用该编号的文档（如 GB 18466 前言）不得计入“文档自身编号”匹配结果",
            "evidence": "specs：引用编号不能匹配自身编号查询",
            "review_status": _GOLD,
        },
        {
            "counter_id": "neg-004",
            "type": "fragmented_table_merge",
            "question": "GB 8978-1996 表 1 共有几项？（续表识别失败反例）",
            "expected_behavior": "只返回第一片段 5 项而宣称 complete 属失败；缺第二片段时必须 partial",
            "evidence": "mapping-samples gb8978-table1-two-fragments-one-chunk",
            "review_status": _GOLD,
        },
        {
            "counter_id": "neg-005",
            "type": "same_number_different_sections",
            "question": "GB 3838-2002 的“表 3”和 GB 3095-2012 的“表 3”是同一张表吗？",
            "expected_behavior": "同表号跨文档不得合并；逻辑表身份含文档＋章节＋表号",
            "evidence": "design.md 决策 2",
            "review_status": _GOLD,
        },
        {
            "counter_id": "neg-006",
            "type": "missing_sidecar_refs",
            "question": "（构造）仅凭 sidecar 反查 air-03 chunk-002 的原始 block。",
            "expected_behavior": "sidecar={} 时必须以正文内联 table id 为 fallback 并标 partial，不得宣称 confirmed",
            "evidence": "mapping-samples empty-sidecar-chunks",
            "review_status": _GOLD,
        },
        {
            "counter_id": "neg-007",
            "type": "no_answer_in_corpus",
            "question": "GB 50014-2021（室外排水设计标准）中雨水管渠设计重现期的取值范围是多少？",
            "expected_behavior": "库内无该标准；必须明确“语料中无答案”，不得编造或近似替代",
            "evidence": "inventory.jsonl 无 GB50014",
            "review_status": _GOLD,
        },
        {
            "counter_id": "neg-008",
            "type": "ambiguous_caption",
            "question": "GB 8978-1996 中 caption 为“(1997年12月31日之前建设的单位)”的表属于哪个表号？",
            "expected_behavior": "caption 不含表号（tb-…-0003），需按序号/上下文核验；不能确认时返回 ambiguous",
            "evidence": "tables.json：tb-…-0003 caption 为空表号",
            "review_status": _GOLD,
        },
        {
            "counter_id": "neg-009",
            "type": "duplicate_content_doc",
            "question": "water-58_ca-resolution-96-079-approved-1997.pdf 的内容在库内可检索吗？",
            "expected_behavior": "该文件因内容重复未入库；必须报“无对应 chunks”，不得把它算入可检索文档",
            "evidence": "inventory.jsonl gap_222_vs_221",
            "review_status": _GOLD,
        },
        {
            "counter_id": "neg-010",
            "type": "budget_exhaustion",
            "question": "（构造）给定极小预算枚举 GB 18466-2005 全部 4.1 条款。",
            "expected_behavior": "预算耗尽必须返回 partial＋已处理/总量，不得静默截断后宣称 complete",
            "evidence": "specs Complete bounded reading",
            "review_status": _GOLD,
        },
    ]

    excluded = await conn.fetch(
        """SELECT s.id, s.file_path, s.status FROM public.lightrag_doc_status s
           WHERE s.workspace=$1 AND s.status='failed' ORDER BY s.file_path""",
        ws,
    )
    doc_full_rows = await conn.fetchval(
        "SELECT count(*) FROM public.lightrag_doc_full WHERE workspace=$1", ws
    )

    categories = {
        "fact": facts,
        "file_enum": file_enums,
        "prose_enum": prose_enums,
        "table_enum": table_enums,
        "synthesis": synthesis,
    }

    # G0-3: a question counts only if every target resolves to a doc with
    # parsed artifact AND chunks. Unresolved ones are moved out and listed.
    valid_categories = {}
    displaced = []
    for cat, qs in categories.items():
        keep = []
        for q in qs:
            bad = [t for t in q["target_docs"] if not t.get("valid", False)]
            if not q["target_docs"]:
                bad = [{"reason": "predicate matched no readable target"}]
            if bad:
                displaced.append({"query_id": q["query_id"], "unresolved_targets": bad})
            else:
                keep.append(q)
        valid_categories[cat] = keep

    whitelist = {
        "workspace": ws,
        "doc_full_rows": doc_full_rows,
        "all_doc_ids": [
            r["doc_id"]
            for r in await conn.fetch(
                "SELECT id AS doc_id FROM public.lightrag_doc_full WHERE workspace=$1 ORDER BY id",
                ws,
            )
        ],
        "excluded_from_searchable": [
            {
                "doc_id": r["id"],
                "doc_name": r["file_path"],
                "reason": f"doc_status={r['status']}（重复文件名/重复内容被拒），无 chunks",
            }
            for r in excluded
        ],
        "selection_basis": "只从 parsed↔doc_full↔chunks 三方对应的文档出题；每题 target_docs 为真实身份",
        "review_note": "全部 gold 未审核（unreviewed）；gold.assertion 为 null 的题需主 agent 对照原文补齐后方可计入指标",
    }

    return {
        "version": "phase-0-candidate-v2",
        "gold_review_policy": "未审核答案不计入质量指标（specs retrieval-evaluation）",
        "coverage_check": {
            "required": {
                "fact": 6,
                "file_enum": 6,
                "prose_enum": 6,
                "table_enum": 6,
                "synthesis": 6,
            },
            "actual": {k: len(v) for k, v in valid_categories.items()},
            "counter_examples": len(counter),
            "counter_examples_required": 8,
            "displaced_unresolved_targets": displaced,
            "meets_minimum": (
                all(len(v) >= 6 for v in valid_categories.values())
                and len(counter) >= 8
                and not displaced
            ),
        },
        "whitelist": whitelist,
        "questions": valid_categories,
        "counter_examples": counter,
    }
