# chunk→unit 映射采集设计（r2 订正版；本组仍 0 采集、fixture 只证接口）

## 数据依据（按主 agent 勘误与源定义核对）

- chunk 物理表 = `public.lightrag_doc_chunks`（5709）——仅来源核验，单独不能给 unit 对应。
- unit↔chunk 依据 **`env_rag.unit_chunk_links` JOIN `env_rag.source_units`**，组合键
  (workspace, doc_id, snapshot_id, unit_id)。
- scope 关系 = **`env_rag.scope_units` JOIN `env_rag.scopes`**。
- `requires_span` 的实际位置（已对照源定义 `catalog/builder.py`）：
  **`source_units.requires_span` 列**（unit 级），并且 `scopes.confirm_status` 可取
  `'requires_span'`（scope 级，builder 由 scope 标记其成员 unit）——两处语义不同，
  采集时按各自字段取，不混写。上一版把 scopes 的"requires_span 状态"写成含糊位置，
  此版为准；旧文件保留不改。
- 存量行数（活跃快照 build-manifest 实测）：unit_chunk_links=16783、source_units=12269、
  scope_units=14557、scopes=1970。

## 分页/语句/失败语义提案（待批准，本组不执行）

单只读连接（read-only、statement_timeout、cache_size=0），守卫前后身份另列：

| 步骤 | SQL | 条数 |
|---|---|---|
| links⋈units 分页 ORDER BY (unit 组合键排序) LIMIT 5000 | ⌈16783/5000⌉ | 4 |
| scope_units⋈scopes 分页 | ⌈14557/5000⌉ | 3 |
| 两端 COUNT 漂移复核（与活跃锚对账） | 2 |
| chunks 来源核验（可选） | ≤1 |

合计 **9–10 ≤20**；任一页异常/COUNT 漂移=整体作废、非零终态，已采页只进诊断不进
正式 manifest（不静默截断）。完整采集必须：同一只读快照内完成、排序组合键、
完整性/终态与内容清单守卫、缺映射显式 pending、空表拒绝。

## manifest 格式与规则

`unit-mapping/r1`：顶层 workspace/snapshot/source_fingerprint + 逐条组合键
`{workspace, doc_id, snapshot_id, unit_id, chunk_ids, content_sha256, scopes[]}`。
评分加载规则（r2 已实现）：组合索引、同 unit_id 跨文档不覆盖、冲突重复条目拒绝、
跨 workspace/snapshot 条目拒绝、空表拒绝；未映射 unit 保留在期望分母、指标置
null(pending)；typed-doc 发现不算 unit 命中；枚举/精排/展开不反灌；零发现保持 0。

## fixture 与本组边界

`fixtures/mapping-fixture.json`、`fixtures/empty-mapping-fixture.json` 为**构造样本**
（非采集）；行为由自有矩阵 `test_typed_recall_*`、评审矩阵 S3 三对场景覆盖。
本组 0 数据 SQL、0 请求；正式采集待主 agent 批准只读小批。
