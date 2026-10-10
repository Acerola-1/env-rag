# 正式两轮批次：映射采集失败阻断（2026-10-09，停主 agent）

用户授权 246 腿正式两轮（方案 1）后，按 `handoff-phase-4-formal-two-rounds.md` 执行到**步骤一**即触发交接规定的停止条件：一次只读映射采集真实执行失败。**付费两轮完全未启动；本批模型/embedding/精排/答案请求 0、写库 0；额度原封未动。**

## 核对与执行链（失败前）

1. **准备包核对全过**：preparation-manifest.json 19/19 SHA 匹配；config-anchor.json 代码谱系逐项对磁盘一致（answer `98328f7f…`、rerank `e2a8e089…`、fusion `be1cd4c5…`、local_adapter `0bbad976…`、compat_runtime `5fa566b2…`、synthesis 提示 `626fda41…`、6 项评估谱系、r4 评分器 `9e8c78be…`）；gold/env/上一代锚谱系一致；三个目标目录（mapping-r1、fixed-round-1、fixed-round-2）执行前均不存在；collect_mapping.py/run_round.py/prepared_common.py 静态审查（单条只读 SQL、REPEATABLE READ、readonly、statement_timeout=30s、守卫另列、0 模型）。
2. **环境**：lightrag-postgres/qdrant/neo4j 容器自当日 02:17–03:18 起持续运行（未重启、未动卷）；keyword 代理 127.0.0.1:8787 LISTEN（既有进程）；.env 三模型键均 DeepSeek、env SHA `e3bf7597…` 与锚一致。执行前用 `lsof`/`container list` 与一次 `nc` TCP 连接探测确认端口存活（无应用层查询、无任何服务 API 请求）——如主 agent 认为 nc 属"额外健康探测"违例，如实裁示。
3. **干跑复验**：`run_round.py --dry-run` 重编译 246 腿矩阵、backend_fetches=0；复跑后 19 项封存 SHA 全等（干跑输出字节确定）。
4. **映射采集（唯一一次）**：`collect_mapping.py --authorized` → `capture-failure.json`（保留原样）：`UndefinedColumnError`；身份守卫**前后完全一致**且 `matches_frozen=true`——八表计数 221/5709/279/16514/65527/221/221/119575、源指纹 `95f7791f…`、catalog `c15c741742394320/4919b3938ad93747`、search `872d6893…`、gold/env 与锚逐项相等。**数据完好，失败仅在查询本身。** 依交接未重试、未追加探测、未填造映射、未启动任何付费腿。

## 根因（静态审查，零新增请求）

采集 SQL 的 SELECT 列 `d.file_path` 来自 `JOIN public.lightrag_doc_full d`。本库生产代码对这两张物理表的既有读法一致表明：**`file_path` 只在 `public.lightrag_doc_chunks`（source.py:270、296），`public.lightrag_doc_full` 暴露的是 `doc_name`（source.py:78、126）**；catalog `env_rag.documents` 同样只有 doc_name（schema.py:96–117）。`UndefinedColumnError` 与该静态结论吻合：准备包 SQL 引用了线上不存在的列。`read_text_cached` 用 `row["file_path"]` 定位 `.parsed` 目录（`_doc_parsed_dir`）——对应列名应为 `doc_name`。离线 fixture 测试无法暴露真实 schema 漂移，本次单次实况采集正是交接声明的验证面，失败即停。

## 待主 agent 裁决（本方不自行修复）

- 修正准备包 SQL（候选：`d.doc_name AS file_path` 或改读 `doc_name` 并同步 read_text_cached 键）属于**准备包再版**，需主 agent 出新代次与复审；再版后需重新一次只读采集确认 27/27。
- 246 腿付费额度与"最后一批"性质不变：两轮合计 keyword 164 / embedding 656 / Qdrant 1312 / Neo4j 1640 / PG 251904（每腿 1024）/ 精排 82 / 答案 42，本批**实际发出 0**（PG 侧仅既有身份守卫查询，按采集规程另列）。
- `phase-4-formal-mapping-r1/` 现状保留（含拒绝重试的目录占用），是否清位待主 agent 指令；历史工件与锚未动。

## 工件

capture-failure.json（现场原件，未改）、blocked-report.md（本文件）、sensitive-scan.json（残留 0）、sha-list.json、manifest（最后写）。
