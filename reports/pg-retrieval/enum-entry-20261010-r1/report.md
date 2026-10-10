# 枚举增强入口：本次有界交付

已完成直接自然语言提问入口 `ask` 和原 LightRAG 的显式可选 Python 适配器。本组不重新开启已结案的全量评测，不改变 Gate4 失败结论。

## 实现与使用

- 新增 `src/env_rag_final/ask.py`：受控意图判断、明确文件/代码/版本选择、同快照目录目标确认、全范围读取、独立引用回读、发布前身份及目录内容核对。
- `cli.py` 增加 `ask`：自由问题、`--document`/`--code`/`--version`/`--scope`/`--table-number`；只需要PG配置，默认可读文本，也可输出JSON。既有命令分派保持原样。
- 新增 `lightrag_enum_bridge.py`：关闭增强时原样调用公开 `rag.aquery(query, **kwargs)`；开启时只走新入口，返回dict。无原服务/路由/WebUI修改，不初始化存储。
- 使用指南：项目根 `ENUMERATION.md`。

## 最终案例核验

预期先于生成固定，并对原始blocks/HTML逐项确认。gold与题号只进入独立验收脚本；生产ask不读取gold、历史答案或其他路径输出。下表是有界功能验证，不是31题指标。

| 案例 | 预期 | 实际 | 漏项 | 多项 | 引用问题 | 方式 |
|---|---|---|---|---|---|---|
| versions | complete / 2 | complete / 2 | 0 | 0 | 0 | PG只读现场 |
| amendments | complete / 3 | complete / 3 | 0 | 0 | 0 | PG只读现场 |
| terms | complete / 4 | complete / 4 | 0 | 0 | 0 | PG只读现场 |
| clauses | complete / 4 | complete / 4 | 0 | 0 | 0 | PG只读现场 |
| continued_table | complete / 13 | complete / 13 | 0 | 0 | 0 | PG只读现场 |
| edition | complete / 1 | complete / 1 | 0 | 0 | 0 | PG只读现场 |
| ambiguous_table | ambiguous / 未确认范围 | ambiguous / 0 | 不适用 | 不适用 | 0 | PG只读现场 |
| judgement | ambiguous / 0 | ambiguous / 0 | 0 | 0 | 0 | 前置拒绝，0后端 |

六个正例完整交付2/3/4/4/13/1项；表1续片即使top-k=1仍13行完整。两份修改单自身编号未知如实保留，目录并集为3份。表2缺归组证据不强行完整；“是同一张表吗”不把跨文档清单当判断答案。

## 证据与回归

- 最终字节绑定：`acceptance-sealed/acceptance.json` 的三项代码SHA与磁盘一致；7条PG现场只读问题＋1条前置拒绝。新连接READ ONLY，原文适配器沿用既有只读事务。
- 新增24项（ask19＋bridge5）；工程 `pytest tests` 最终550通过。覆盖多版本、top-k、错文件、无目标、缺条款/不可信引用、发布漂移、约束冲突、版本细化、只需PG配置、不可覆盖输出及关闭适配器的原参数/返回/异常行为。
- 不带目录限定的仓库根pytest会收集同名历史测试文件并报导入冲突。未删除或修改这些封存产物；工程回归以 `pytest tests` 为范围。
- `protected-history-check.json` 复算1670条历史封存清单，0变化。新源码变更不回写旧配置锚；`.env`/gold/历史目录不改。
- 本轮新增模型/embedding/rerank付费调用均0；八表计数前后逐项相同，来源/目录/索引守卫一致。计数不作为0写入的唯一证据，只读连接与读取调用链是权限边界。
- 初次受沙箱限制的命令返回PermissionError，保留在 `table1-live.json`。经只读访问审批后验证成功，不把该记录当数据库或模型服务失败。中间有界验证在独立目录保留；最终证据使用 `acceptance-sealed`。

## 原系统接入与未证明的部分

静态调查确认原 LightRAG REST查询调用aquery_llm/aquery_data，公开Python API为aquery；query/data仍可能抽词调用模型。原checkout与本项目发布依赖版本不同，且原项目存在用户未提交修改，因此本组只提供调用方显式适配器，不编辑或启动它。

关闭增强的透明委托由fixture正负例验证；原始未改动LightRAG的现场对照尚未验证。历史评测local不是原系统基线，本组不声称全系统质量提升、原WebUI已接入或所有自然语言问法均可正确理解。

## 我醒来后怎样测试

在项目目录运行：

```bash
.venv/bin/env-rag-final ask --query '列出 GB8978-1996 表1的全部项目及限值' --top-k 1
.venv/bin/env-rag-final ask --query '库内有哪些 GB18466-2005 的文档（含修改单）？'
.venv/bin/env-rag-final ask --query '列出4.2的全部规定' --code GB3095 --version 2012
```

如需全引用JSON，加 `--format json --out /tmp/一个不存在的新文件.json`。对不确定状态查看flags和范围元信息，不能只看退出码。

本目标的交付边界为可用枚举入口＋明确可选接入＋有界案例证明；此前失败门槛和原系统性能/增益问题均未被覆盖或抹去。
