# Phase 0 审计报告（只读）

生成时间：2026-10-04T17:01:59.492737+00:00。全部结论由 `uv run env-rag-final audit` 复跑生成；
数据库访问限定为单个 READ ONLY 事务内的 SELECT 与 pg_catalog／ts_debug 探针，无 DDL／DML。

## 1. 已观察事实（可由报告文件直接复核）

### 1.1 计数口径（必须区分，不能混用）

| 口径 | 数值 |
|---|---|
| 解析产物目录（`*.pdf.parsed`） | 222 |
| `doc_full` 行数（目录数） | 221 |
| `doc_status` processed 行数 | 221 |
| `doc_status` failed 行数 | 58 |
| 有 chunks 的文档数 | 221 |
| chunks 总数 | 5709 |

- 222／221 差异已定因：`water-58_ca-resolution-96-079-approved-1997.pdf` 解析产物存在，但内容与
  `water-44_ca-amend-resolution-92-49.pdf` 完全相同（两者 content_hash `e9dfe2fd…` 由本审计复算相等），
  导入管线按"内容重复"拒绝入库；状态行 `doc-cf323c0335cf0264deca8bd5e400a68f` 记录 failed、chunks_count=0。
- 58 条 failed 的构成：57 条 `File name already exists`（重复文件名）＋
  1 条 `Identical content already exists`（重复内容）。每条的错误信息都指向一个原始 doc_id；
  本审计逐一核验，全部指向的原始文档都存在且为 processed（`failed_originals_all_processed=
  True`）。因此 failed 行不减少有效语料，但也不是可检索文档；
  其身份与依据逐行记录在 inventory.jsonl。
- chunk `chunk_order_index` 在全部 221 份文档上 0..n-1 连续且无重复；processed 文档的
  `doc_status.chunks_count` 与实际 chunk 行数全部一致。**不能**用"最大序号+1"以外的方式推断，
  也不存在因截断产生的尾号缺口。

### 1.2 身份与哈希合同（task 1.4 结论）

对全部 221 份同时有解析产物与库内记录的文档复算：

| 字段 | 语义（已核验公式） | 匹配数 |
|---|---|---|
| `doc_full.id` | `"doc-" + md5(doc_name)`，由**文件名**推导，与内容无关 | 221 |
| `doc_full.content_hash` | `md5(normalize_merged_text_for_hash(blocks 合并正文))`，与 MinerU document_hash **不同源** | 221 |
| `blocks.meta.document_hash` | `sha256(blocks 合并正文)`，解析产物完整性指纹 | 221 |
| `mineru_raw/_manifest.source_content_hash` | `sha256(原始 PDF 字节)`（抽样 air-02 验证） | 抽样核验 |

明确不可比较的哈希对：`document_hash`（解析后正文）≠ `source_content_hash`（原始 PDF 字节）≠
`content_hash`（规范化正文 md5）。三者都可各自复算，但**不能**按字段名互相认定。
`doc_full.meta` 全部为 NULL，标题等元数据只能从解析产物正文提取（design.md 决策 2 的元数据来源约束成立）。

### 1.3 block/table → chunk 映射（task 1.5 证据，详见 mapping-samples.jsonl）

- sidecar.refs 的 ref 类型**只有 block**（全库 5709 个 chunk 聚合），没有 table 类型 ref；
  table 定位要靠 chunk 正文内联的 `<table id="tb-…"…>` 标记与 tables.json 的 blockid 关联，两者都可用。
- GB 8978-1996 表 1 两片（5 行 + `表 1(完)` 10 行）同在 chunk-001，13 项完整；
- GB 18466-2005 3.1–3.4 定义同在 chunk-001；条款 4.1 跨 chunk-001/002（4.1.1–4.1.2 与 4.1.3–4.1.5 分离）；
- 存在一个 block 被 14 个连续 chunk 引用（water-126 Attachment D）的反向多对多案例；
- 14 个 chunk 的 sidecar 为空对象 `{}`，无法反查原始 block，正文内联 table id 可作次要依据（fallback，
  不得自动升级为 confirmed）；
- 全库覆盖：211 份产物 block 全覆盖、10 份部分覆盖、1 份无 chunk（water-58，见 1.1）。

### 1.4 中文全文检索现状（task 1.7 观察，详见 search-probes.json）

- 已安装扩展只有 plpgsql；无自定义文本搜索配置；`default_text_search_config=english`。
- `ts_debug` 实测：整句中文并成单个 lexeme（如 `医疗机构水污染物排放标准`），子串 tsquery 不命中
  （`substr_match=false`）。design.md 决策 4（应用侧分词 + simple 配置）的前提在当前库上成立。
- jieba 等分词器**未安装**，探针只记录"待 Phase 2 安装后验证"的方案，未标成功。

### 1.5 发布包离线接口（task 1.6，详见 compatibility.md）

- lightrag-hku 1.5.7 导入成功；`aquery_data` 文档声明返回
  chunks[].chunk_id；`PGKVStorage.get_by_ids` 的 SQL 返回 id/tokens/content/chunk_order_index/full_doc_id/
  heading/sidecar 等完整证据字段。
- `ClientManager.get_client` 首次创建连接池时会执行 `initdb()` + `check_tables()`（建表/建索引/迁移），
  因此**任何**用发布包连接现有库的尝试都会先执行 DDL——本轮审计完全未实例化存储，保持只读。
- workspace 现状：PG 表内全部数据 `workspace='default'`（PG_WORKSPACE／WORKSPACE 未在 .env 设置）；
  Qdrant payload `workspace_id='_'`（发布包 DEFAULT_WORKSPACE 常量）也是 default；
  Neo4j label `base`（空 workspace 的落名）。三存储命名不同但指向同一逻辑 workspace。

## 2. 推断（有依据、未逐条验证）

- `LIGHTRAG_DOC_STATUS` 的 `content_hash` 列与 `doc_full.content_hash` 语义相同（重复检测在
  pipeline.py 内用同一函数计算），inventory 中两列值一致的行可互认。——推断，Phase 1 目录构建时全量核验。
- 10 份部分覆盖产物中缺引用的 block 属解析端"空块/合并块"处理，不构成内容缺失（air-03 缺引用的 5 块
  内容完整出现在 chunk-002 正文但 refs 为空）。——抽样核验，未全量。
- 大 token chunk（1958–1889 tokens）的空 refs 与段落语义分块的合并路径相关。——推断。

## 3. 未验证项（Phase 1+ 处理，本阶段不冒充完成）

- 发布包 `aquery_data` 实际运行返回、reranker 行为、llm_response_cache 的读写副作用：需按 tasks 5.1 在
  隔离临时库／测试 workspace 实测；本库 `lightrag_llm_cache` 已有 16,514 行，评测必须绕开。
- 应用侧分词的召回率：jieba 未安装、tsvector/GIN 未建，属 Phase 2。
- Neo4j 图谱只做了只读 labels/keys 探针；`aquery` 语义链路未运行。

## 4. 下一步（进入 Gate 0 审查）

1. 主 agent 审查本目录报告，确认身份合同（1.2 表）、白名单与排除项（sample-set.json 的 unreviewed 状态）、
   兼容性风险（compatibility.md 的 check_tables 边界）。
2. 通过后进入第 2 组任务：显式辅助 schema 迁移（`env_rag` 名称当前未被占用且当前用户有 CREATE 权限，
   已在 schema.json 记录）、适配器、目录构建。
3. 失败／重复文档的处置（58 条 failed、water-58 缺失）单独处理，不阻断有效白名单验证。

## 5. 复跑与来源变化

`run-manifest.json` 记录了代码版本、输入指纹、每一步状态。语料目录或数据库行数变化会使
corpus_fingerprint 与若干计数字段变化——这是**观察事实**，不允许为了消除差异写库；
复跑后请对比 manifest 的 fingerprint 字段解释差异。报告不含任何凭据（异常一律只报类型）。
