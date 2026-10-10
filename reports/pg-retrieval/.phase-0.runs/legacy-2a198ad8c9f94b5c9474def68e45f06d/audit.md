# Phase 0 审计报告（只读）

生成时间：2026-10-04T17:50:37.305866+00:00；run_id：`985f1d0f8653417c`；状态：`ok`。
全部结论由 `uv run env-rag-final audit` 在本次运行中实际采集——凡标注"本次实测/本次复算"的数字都能在
本目录报告文件中复核；首轮历史观察单独标注，不与本次混写。
数据库访问限定为单个 READ ONLY 事务内的 SELECT 与 pg_catalog／ts_debug 探针，无 DDL／DML。

## 1. 已观察事实（本次运行采集）

### 1.1 计数口径（必须区分，不能混用）

| 口径 | 数值 |
|---|---|
| 解析产物目录（`*.pdf.parsed`） | 222 |
| `doc_full` 行数（目录数） | 221 |
| `doc_status` processed 行数 | 221 |
| `doc_status` failed 行数 | 58 |
| 有 chunks 的文档数 | 221 |
| chunks 总数 | 5709 |

- 解析产物 222 份 vs doc_full 221 行；无 doc_full 行的产物：water-58_ca-resolution-96-079-approved-1997.pdf。
- 差异定因（本次复算）：water-58 与 water-44 的**规范化合并正文**（去除文件派生标记后）相等，MD5 相同；原始 merged text 与其 SHA-256 不同，PDF 字节未比较。导入管线按规范化 content_hash 重复拒绝 water-58 入库（doc_status doc-cf323c0335… error_msg）。
- failed 共 58 条（57 条重复文件名＋1 条重复内容），逐条核验其错误信息指向的原始 doc_id 全部存在且 processed（本次运行核验）。
- chunk_order_index 在全部 221 份文档上连续且无重复（本次实测）；processed 行的 chunks_count 与实际 chunk 行数全部一致（221/221，本次实测）。
- doc_full.content 带存储格式前缀 {{LRdoc}}；去除该前缀后与本地合并正文逐字符相等（221/221，本次实测）。Phase 1 比较原文时必须先做该转换。

### 1.2 身份与哈希合同（task 1.4 结论，本次运行复算）

对全部 221 份同时有解析产物与库内记录的文档复算：

| 字段 | 语义（复算公式） | 匹配数 |
|---|---|---|
| `doc_full.id` | `"doc-" + md5(doc_name)`，由**文件名**推导，与内容无关 | 221 |
| `doc_full.content_hash` | `md5(normalize_merged_text_for_hash(blocks 合并正文))`，与 document_hash **不同源** | 221 |
| `blocks.meta.document_hash` | `sha256(blocks 合并正文)`，解析产物完整性指纹 | 221 |
| `mineru_raw/_manifest.source_content_hash` | `sha256(原始 PDF 字节)` | 首轮抽样（air-02）核验；本轮未逐份复算 PDF 字节 |

明确不可比较的哈希对：`document_hash`（解析后正文）≠ `source_content_hash`（原始 PDF 字节）≠
`content_hash`（规范化正文 md5）。三者都可各自复算，但**不能**按字段名互相认定。
doc_full.meta 全部为 NULL（221/221，本次实测），标题等元数据只能从解析产物正文提取。

### 1.3 block/table → chunk 映射（task 1.5 证据，详见 mapping-samples.jsonl）

- sidecar.refs 的 ref 类型本次聚合仅见 block（类型清单见 independent 核验先例与本次聚合）；无 table 类型 ref；
  table 定位靠 chunk 正文内联 `<table id>` 标记与 tables.json 的 blockid 关联。
- GB 8978-1996 表 1 两片同在 chunk-001（片段 caption/dimension 本次从 tables.json 读取，见 mapping-samples）。
- GB 18466-2005 定义 3.1–3.4 与跨 chunk 条款 4.1 的核验结果由本次子串检查产生（见 clause_layout）。
- 反向多对多：本次全库聚合实测：引用数最多的 block 出现在 273 个 chunk 中（chunk_order 231–503）。单 chunk 命中不能认定整个 block 已读。
- 空 sidecar：本次实测 14 个 chunk 的 sidecar 为 {}，无法从 chunk 反查原始 block；正文内联 table id 可作次要依据（fallback，不得自动升级为 confirmed）。
- 全库覆盖：211 份产物 block **ID** 全覆盖、10 份部分覆盖、
  1 份无 chunk。注意：ID 引用覆盖≠block 全部文字覆盖。

### 1.4 中文全文检索现状（task 1.7 观察，详见 search-probes.json）

- 观察事实（本次运行实测）：默认配置把整句中文并成单个 lexeme，子串查询不命中；中文分词必须在应用侧完成（design.md 决策 4）。
- jieba 等分词器未安装，探针只记录"待 Phase 2 安装后验证"的方案，未标成功。

### 1.5 发布包离线接口（task 1.6，详见 compatibility.md 及其探针记录）

- lightrag-hku 1.5.7 导入成功；本次运行实际执行接口存在性、
  docstring 字段、源码副作用扫描等探针（记录嵌在 compatibility.md §3）。
- 初始化副作用已由源码扫描确认：首次建池必然走 initdb/check_tables 路径——本轮审计完全未实例化存储。
- 三库 workspace 现场**取值**属于历史观察（首轮 2026-10-04 只读探针：PG 行 `workspace='default'`、
  Qdrant payload `workspace_id='_'`、Neo4j label `base`）；本轮未重新连接 Qdrant/Neo4j，引用时以上次
  记录为准。发布包常量（`DEFAULT_WORKSPACE="_"` 等）本次已从源码扫描确认，见 compatibility.md §1.3。

## 2. 推断（有依据、未逐条验证）

- `doc_status.content_hash` 与 `doc_full.content_hash` 语义相同。——推断，Phase 1 全量核验。
- 部分覆盖产物中缺引用的 block 属解析端"空块/合并块"处理。——首轮抽样（air-03）核验，未全量。

## 3. 未验证项（Phase 1+ 处理，本阶段不冒充完成）

- 发布包查询链路运行时行为、reranker、llm_response_cache 副作用：需按 tasks 5.1 在隔离环境实测。
- 应用侧分词召回率：jieba 未安装、tsvector/GIN 未建，属 Phase 2。
- Neo4j/Qdrant 本轮未连接；aquery 语义链路未运行。

## 4. 下一步（进入 Gate 0 复审）

1. 主 agent 复审本目录报告与 fixture 测试（tests/），确认身份合同、白名单与排除项、兼容性风险。
2. 通过后进入第 2 组任务：显式辅助 schema 迁移（`env_rag` 占用与权限见 schema.json app_schema_plan）、
   适配器、目录构建。
3. 失败／重复文档的处置单独处理，不阻断有效白名单验证。

## 5. 复跑与来源变化

`run-manifest.json` 记录 run_id、审计代码逐文件 SHA-256 与来源快照指纹。指纹组件覆盖：PG 原文、
chunks（ID／顺序／正文／heading／sidecar）、解析 blocks／tables 字节、分块参数、doc_status。
任一组件变化都会改变 composite 值——这是**观察事实**，不允许为了消除差异写库。
失败运行以 `status=failed_at:<step>` 标记，不会与成功产物混用。报告不含任何凭据（异常只报类型）。
