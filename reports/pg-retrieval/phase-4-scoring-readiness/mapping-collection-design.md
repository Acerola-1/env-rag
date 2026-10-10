# chunk→unit 映射采集设计（本组仅设计+fixture，未执行任何采集）

**0 真实请求。本节是给未来一次受守卫只读采集的提案，不是授权。**

## 数据依据（主 agent 勘误为准）

- chunk 物理表 = `public.lightrag_doc_chunks`（8 表计数中的 5709 行）——只能另核验来源，
  单独无法给出 unit 对应。
- unit↔chunk 映射必须依据 **`env_rag.unit_chunk_links` JOIN `env_rag.source_units`**，
  组合键 `(workspace, doc_id, snapshot_id, unit_id)`。
- scope 关系另由 **`env_rag.scope_units` JOIN `env_rag.scopes`**（含 parent_scope_id、
  requires_span）建立。
- 存量活跃快照行数证据（phase-1 build-manifest，同一 `c15c741742394320/4919b3938ad93747`）：
  `unit_chunk_links=16783`、`source_units=12269`、`scope_units=14557`、`scopes=1970`。

## 分页、语句与失败语义提案

只读单连接（`default_transaction_read_only=on`、statement_timeout 30s、
`statement_cache_size=0`），身份守卫沿用既有前后采集（**守卫另列不计入数据 SQL**，
与评测账本排除口径一致）：

| 步骤 | SQL | 条数 |
|---|---|---|
| link JOIN unit 分页 | `… JOIN … WHERE snapshot_id=$1 ORDER BY unit_id,chunk_id LIMIT 5000 OFFSET …` | ⌈16783/5000⌉=4 |
| scope_units JOIN scopes 分页 | 同型 | ⌈14557/5000⌉=3 |
| 两表 COUNT 复核（漂移即整采作废） | 2 | 2 |
| chunks 来源核验（可选） | 1 | ≤1 |

数据 SQL 合计 **9–10 ≤ 20**，页数对行数增长留有一页余量即触预算拒绝——**预算不足时
整体失败、不静默截断**；任何一页异常 → 非零终态、已采页只留在诊断不落正式 manifest。

## 完整映射 manifest 格式

```json
{ "schema": "unit-mapping/r1",
  "workspace": "default", "catalog_snapshot_id": "4919b3938ad93747",
  "source_fingerprint": "95f7791f…",
  "captured_at": "…", "guard": {"identity_before": "…", "identity_after": "…", "equal": true},
  "entries": [
    {"workspace": "default", "doc_id": "doc-…", "snapshot_id": "4919b3938ad93747",
     "unit_id": "…", "unit_kind": "block|table", "row_no": null,
     "chunk_ids": ["doc-…-chunk-017", "…"], "content_sha256": "…",
     "scopes": [{"scope_id": "…", "requires_span": false}]}
  ] }
```

规则：跨 workspace/跨 snapshot 条目加载即**拒绝混源**；缺映射的 unit 在评分侧
**显式 pending**（不猜命中也不按不命中杀分）；**空表拒绝当完整**；
`content_sha256` 为该 unit 完整原文 SHA（与展开复读同一合同），manifest 逐文件
独立 SHA 登记。

## 评分侧口径（已在新代实现，见 assess_two_rounds.py `typed_evidence_recall`）

- typed evidence recall **只取展开前 discovery**（typed 目标 + chunk 候选两段的文档
  存在性）与映射条目关联；**展开成功/枚举答案/精排一律不反灌召回**；
  显式零发现对非空期望=**recall 0**，即使枚举答案正确。
- 映射只提供"该发现指向哪个 unit"的关联证据，**不证明范围读取完整**（后者仍归
  答案合同回读）。
- 兼容模式（Round-1）永不读映射；未来正式两轮是否启用由主 agent 随新锚定夺。
- fixture：`fixtures/mapping-fixture.json`（构造样本：一条已映射 + 一条外 workspace
  反例 + 一条缺键反例）与 `fixtures/empty-mapping-fixture.json`（空表=拒绝当完整）；
  测试在 `test_scoring_readiness.py::test_mapping_* / test_typed_recall_*` 以同型
  内存 fixture 覆盖同一规则（文件与测试构造一致，均标注 constructed、非采集）。

## 本组未做

未执行任何采集 SQL（0 请求）；未来采集需主 agent 批准该只读小批（10 语句护栏）
并绑定新配置代次。
