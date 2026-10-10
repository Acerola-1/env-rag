# Phase 3 / 5.2 独立验收：未通过

日期：2026-10-06。**5.2 未通过，只补正 L1–L5；5.3–5.6 / Gate 3 不进入。5.1 已通过与 Gate 2 已通过的结论保持。**

审查实现 `local_adapter.py`、CLI 新分支、8 项提交测试和 phase-3-local 运行交付，并追踪安装发布包实际函数。OCR 只做本地文件预览和规则解析，没有调用外部评审模型。各文件范围/跳过理由见 coverage.json；这不是对整个工作区所有历史变更的再次验收。本轮不修改应用实现、既有断言、冻结 gold 或原始交付。

## 独立验证结果

- 提交的五项文件 SHA 全部匹配。安装 `lightrag-hku==1.5.7` 的 172 项 Python 文件与 RECORD 匹配，0 差异。5.1 的 `compat_runtime.py` 与已接受提交 SHA 相同。
- 新增 `tests/test_local_adapter_review.py`：**9 failed / 1 passed**。完整测试：**229 passed / 9 failed**，原 228 项继续通过。所有新增测试均使用假服务/连接，0 实际模型请求、0 正式后端初始化或写入。详见 acceptance-tests.txt / all-tests.txt。
- Ruff check、format、OpenSpec strict、diff 检查通过；不能替代下面的行为验收。
- 主 agent 独立现场只读盘点：八表计数与内容级 source 指纹、catalog run/snapshot、search active、gold 和 `.env` SHA 前后无漂移，冻结比较无错误。Qdrant 三集合 5709/65526/119574 点、2560d，workspace_id 索引存在；Neo4j base 66069 节点/121819 关系，base RANGE/FULLTEXT 索引 ONLINE。详见 live-inventory.py / live-inventory.json。Qdrant/Neo4j 元数据为本轮读取值，与提交计数一致；不将计数一致解释为没有提交写请求。
- **未独立运行当前 `lightrag-local` 真实生产入口**：L1 已证实其初始化会提交写请求，不能在原后端上用重跑补证。本轮现场检查只使用原生客户端的读取接口，没有调用 LightRAG 存储 initialize，也没有调用 embedding/LLM。

## L1 / P1：幂等初始化仍提交写请求，正式只读合同不成立

位置：`src/env_rag_final/local_adapter.py:338–340`，以及文件开头/运行报告“initialize no-op”的陈述。

安装发布包 `qdrant_impl.py:219–244` 在集合已存在的分支仍**无条件调用 create_payload_index**；`neo4j_impl.py:308` 在成功连接后仍发送 **CREATE INDEX IF NOT EXISTS**。索引已存在只可能使这些请求幂等，并没有消除写请求。initialize 还包含缺集合建表/旧集合迁移、缺数据库 CREATE、缺失或离线 fulltext 索引 DROP/重建路径。当前适配器先执行 initialize，再校验 namespace，没有只读预检拒绝这些分支。

正式 owning-entry 反例调用 `LocalCandidateAdapter.fetch`，使用实际安装的 Qdrant initialize + 假客户端，模拟集合及索引已存在：观察到 entities/chunks 两次 create_payload_index，断言失败。这是写接口调用的证据，不是声称实际语料遭到破坏。

**修复要求**：接入必须 connect/read-only；读取并校验已有集合、索引、label、向量配置。缺失/不兼容明确拒绝或报告不可用，不 ensure/create/migrate/repair。可以复用发布包的读取方法/候选函数，但不能让生产存储 initialize 触及后端。测试覆盖已有资源零写请求，以及缺资源/不兼容零创建请求。纠正代码、报告和 tasks 证据的 no-op/零 DDL 表述。

## L2 / P1：边字段读错，候选和来源路径被覆盖；复制算法不能认定发布包等价

位置：`local_adapter.py:555–561`（边字典）、564–571（计数排序）、599–612（追加/追踪）。

实际发布包 `_find_most_related_edges_from_entities` 在 `operate.py:6123` 输出端点字段 **src_tgt=(src,tgt)**。适配器却读取 source/target，所有边都成为字典键 `"|"`，后续边覆盖此前边。两条真实形状的边反例丢失 edge-first；来源路径反例输出 `edge:|`。提交的四个真实 query 也都存在 `edge:|` 候选，见 static-evidence.json。PG 回读只证明剩余 ID 存在，不能证明召回没有丢边或路径正确。

此外，复制代码在累计后续实体的重复频次之前就排序首个实体，与发布包“全量计数后统一排序”不同；自定义边/总预算也没有落实 chunk_top_k。不能据此称“不复制”“预算一致”或“完整发布包 local 等价”。安装包现有 `_find_related_text_unit_from_entities(node_datas, query_param, text_chunks_db, knowledge_graph_inst, …)` 可直接接收只读存储对象；从函数本体看，不要求完整 LightRAG initialize。报告关于必须完整初始化因而只能复制的理由不成立。

**修复要求**：优先使用实际发布包候选函数和只读存储组合；如有必要的独立扩展，写清边界并验证选择/预算合同，不宣称未经证明的等价。读取真实端点字段，保留全部不同边及同一候选的多个路径，不因字典覆盖丢来源；明确并测试候选预算，区分发现排序与最终精排。两项原反例保持。

## L3 / P1：冻结身份只是输出标签，模型和跨后端 workspace 未在调用前门控

位置：`local_adapter.py:82–105`、309–356、622–664。

`run_frozen` 把 FROZEN 写进输出，却不读取/比较实际 source、catalog、search、gold 或 env。expected gold SHA 改为错误值后仍执行 fetch，正式入口反例失败。外部手动盘点不能代替可复跑入口的守卫。

embedding 实际请求使用 values[EMBEDDING_MODEL]，但模型身份 model_name 恒为 Qwen3、维度恒为 2560；配置改为另一模型仍可按旧 Qwen 集合名通过检查。PG workspace 任意可传，但向量 `_`、图 `base` 固定；同 ID 可跨 workspace 同名不同内容（5.1 已实证），按 PG 的 ID 前缀核验不足以证明语义来源属于该 workspace。相应两个 fetch 入口反例均失败。QDRANT_WORKSPACE/NEO4J_WORKSPACE 的环境覆盖也需显式核对，而不是 initialize 后才拒绝。

**修复要求**：在生产连接/服务请求前校验 gold/config/模型/dim/显式 PG↔vector↔graph 映射；只支持已确认的映射，未知值安全拒绝。正式 frozen 入口采集并比较 source/catalog run+snapshot/search/gold/env，finally 做后置漂移核对。失败非零并保存失败报告，不把硬编码 FROZEN 当实测身份；环境覆盖也必须纳入有效配置身份。

## L4 / P1：真实故障被发布包吞掉，降级和调用证据失真

位置：`local_adapter.py:367–380`、457、583–600、622–674，CLI 414–453；安装 `utils.py:6102` 附近 VECTOR helper 的异常兜底。

实际 `pick_by_vector_similarity` 捕获 embedding 异常后返回 chunk ID 简单截断列表。外层 try/except 看不到异常，因此候选继续作为 VECTOR 成功输出、degraded 为空。反例直接调用实际 helper，注入 TimeoutError，稳定复现。向量缺失/读取失败返回空集合再走 WEIGHT 时同样需要明确降级，不能静默视为真实向量排序。

调用计数位于逻辑流程外层：空实体路径未请求 chunks 向量仍加 qdrant_queries；空 selected_ids 不执行 SQL 仍加 pg_readonly_queries。后者 owning-entry 反例失败。服务计数在复用同一 adapter 时累计，也需区分每请求与累计值。提交的 8/4/8/4/4 是代码计数与执行 agent 陈述，本轮没有独立证明为这些数量的实际请求。

异常时 run_frozen 没有统一失败报告/后置守卫出口；未知 query_id 可以只加入 errors 然后 CLI 仍输出 OK。运行日志仅有解析关键词、实体前 8 项、候选前 80 字与计数，没有约定的实际服务请求/响应和明确耗时，也没有可验证失败终态。

**修复要求**：在真实服务适配边界记录尝试/成功/失败，捕获 helper 吞掉的异常或缺向量状态，显式标记排序来源与 degraded；不得以 PG verified 抵消服务失败。计数按实际调用定义，说明查询/批次/HTTP/group 的不同口径，空路径不虚增；请求计数相互隔离。统一失败报告/后置核对/CLI 非零合同，错误 query_id 在任何服务调用前拒绝。保存必要、去凭据的实际请求/响应、模型/config 身份、耗时和失败原因；不调用答案生成、不调整 gold 迎合。

## L5 / P2：创建的 Qdrant/Neo4j 客户端未关闭

位置：`local_adapter.py:306–340`、473–477。

finally 只清理 shared_storage，没有关闭本次创建的两个 Qdrant 客户端和 Neo4j driver。成功 owning-entry 反例中三个实例均未 finalize；initialize/检索失败亦无资源登记和回收路径。真实长驻/连续查询不能依靠进程退出或 GC 回收。

**修复要求**：构造即登记、success/error/cancel 均关闭自有连接，某项关闭失败不跳过其余关闭、报告或 post-guard。注意原生 Qdrant finalize 含 flush pending writes：生产只读适配需要 close-only 或不可写队列保证，不应为补清理引入写副作用。保留现有成功反例并补初始化半途失败路径。

## 保留的有效事实与边界

提交 PG 只读 SELECT、显式拒绝 upsert/delete/drop、缺 chunk/full_doc_id 不匹配拒绝路径仍有价值；新缺 chunk 正例通过。79/79 当前候选 ID 经提交代码 PG 回读，不能升格为“完整语义候选召回/来源链路正确”。本轮 root 没有重新生成这些 79 候选。

neg-001 的 local 发现可以召回 2012/2026 相关证据；仅因此不退回 5.2。保留 missing 期望，后续融合/答案层仍须执行严格版本约束，不能用邻近版本替代不存在的 1996。本轮没有认定任何新增质量指标，也未开启 Gate 3。

下一位 agent 只按 `handoff-phase-3-5.2-fixes.md` 修复 L1–L5，保留十项新验收断言和全部旧断言。安全接入修复后才重跑同一小样本真实链路，提交身份守卫、服务证据、资源回收和来源路径，停 5.2 检查点复审。
