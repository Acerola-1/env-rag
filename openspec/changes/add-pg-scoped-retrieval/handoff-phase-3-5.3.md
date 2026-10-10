# 下一组仅 5.3：合并候选，保留身份、路径与版本约束

5.2已通过主agent独立验收，依据phase-3-local-review-r5/review.md/review-manifest.json；tasks.md为当前状态。**只做5.3，完成后停检查点，不做5.4联合rerank、5.5展开/生成、5.6 Gate3或Phase4整轮对照。**

## 接入与结果合同

- 两路用现有实现：local_adapter.LocalCandidateAdapter.fetch（5.2正式只读路径）与search.query.run_query（发现阶段expand=False）。统一请求身份；source/catalog/search/gold/env前后守卫，保留各路trace、状态、配置及实际服务记录。正式PG/Qdrant/Neo4j不初始化、不迁移、不写入；不升级依赖或重建。hashing_kv=None、0答案生成。
- PG用**discovery_candidates**作为发现输入：显式[]就是零发现，不能从枚举答案或其它列表倒灌；只对尚未捕获的None作明确兼容。PG目前有catalog_row、chunk_row、scope/table_unit等类型，不能把doc_id或scope_id当chunk_id。chunk候选按(workspace,chunk_id)合并；文档/范围定位目标保留为有类型的独立目标，或按真实链接及明确发现预算映射，不能猜chunk-000、靠标题/前80字猜ID或把发现当完整枚举。
- 归一化结果至少含workspace/chunk_id/doc归属、源/目录快照、来源校验、各路原始rank/score类型、每条实体/边/PG定位路径、degraded与拒绝原因。两个路径命中同一身份只合并候选，保留全部路径。正文可只读回读完整原文；local.content_head仅展示摘要，不能当全文。冲突的doc归属/原文不得选一个覆盖，明确拒绝或降级。
- 原始分数不可相加。PG ts_rank、local选择序号/方法是不同口径；没有实际scalar score就记unknown，不伪造余弦分数或联合rerank分数。这里只做可审计合并/发现顺序；联合精排归5.4。合并时不得因重复内容或预算静默丢掉不同版本；如有预算截断，记录规则与未保留项，不标complete。

## 强约束与失败合同

- PG既有明确编号/年份条件同时约束local。来源文本提及某编号不等于文档自身编号；复用既有self_code/版本与字段来源。"含修改单/相关文件"沿用既有显式归属路由，不扩成默认同义匹配。
- 缺失GB3095-1996不能被local的2012/2026候选升级为成功；拒绝/旁路理由保留。可先查PG硬约束并省掉不必要的local调用。多编号/版本按分支集合允许各目标，保留跨版本；缺一个目标仍missing/incomplete并保留已找到证据，不替代。暂不生成答案。
- local失败而PG当前可用允许显式PG-only degraded回退，保留真实错误和调用凭证；local返回未verified候选不能直接入可用集合。降级判定同时核对各实际选取阶段的完整性记录，不能仅相信全局排序标签或一个布尔值。PG stale/源身份漂移不能靠local输出升级为可信成功。身份守卫、清理和失败终态沿用已接受合同。

## 一次自查的验收用例

入口级测试至少覆盖：两路同一chunk合并但两路径齐全；不同workspace同chunk_id不混源（fixture，不在生产造数据）；同内容不同版本/不同来源ID保留；明确版本不存在而local有邻近版本仍missing；2012/2026比较保留双版本、缺一个目标不替代；未verified/归属冲突拒绝；local超时的PG-only降级及PG stale拒绝；doc/scope候选不伪装chunk身份、显式空discovery不回填。不要用孤立merge函数通过替代编排入口行为。

通过这些合同后，只做少量必要真实请求（建议fact-002合并、syn-001双版本、neg-001缺失版本；neg可零模型调用），保存两路原始输入、统一候选、合并/拒绝/路径明细、实际调用、只读来源回读与前后身份。无需重复四题local整轮或计算质量指标；不改冻结gold迎合结果。Ruff/OpenSpec strict/diff/凭据扫描后仅5.3提交复审。

交付融合候选实现、最小CLI与PG-only开关/回退说明、fusion-candidates.jsonl、fusion-report.md、manifest及测试证据；5.3待主agent勾选，5.4以后不动。

冻结source=`95f7791fd84171ab727870fc5810d79b4327b0c4fa547d432951e0499a3808f8`；catalog run/snapshot=`c15c741742394320`/`4919b3938ad93747`；search=`872d689343a9cbb6`；gold=`1bf130077c21583a89c5ca14695694d9552c558a7d8dc5d45ff0d9f72cfd7a5e`。八表221/5709/279/16514/65527/221/221/119575；唯一实际映射PG default↔vector '_'↔graph base，其它workspace真实查询拒绝。旧断言与公开失败题保留。
