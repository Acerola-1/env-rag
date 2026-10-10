# Phase 3 / 5.1 最终独立验收

日期：2026-10-06。**5.1 通过，确认隔离兼容检查点完成。下一组仅安排 5.2；5.3–5.6 / Gate 3 未通过，也未开始本轮验收。** Gate 2 保持通过。

对象为 `compat_runtime.py` rev5 及 `phase-3-r5/` 交付。OCR仅做本地预览/规则解析，主agent审查正式入口、既有拒绝用例与真实运行；范围和前期文件跳过理由见 coverage.json。没有修改应用实现、旧测试断言或执行agent原始交付，未升级依赖。

## 通过依据

1. **代码/版本对应**：提交代码、报告、probes、gold、r5测试五项SHA全部与当前文件匹配。实装发布包1.5.7按安装RECORD核对172个Python文件，0差异；没有引用LightRAG源码工作区。
2. **完整测试**：220/220通过，前轮三失败转为通过、一正例保持，四项r5关键断言未变。历史所有权、实际DROP连接身份变化、env/catalog/source变化、失败回收/终态、后端合同拒绝用例继续通过。Ruff、format（215 files）、OpenSpec strict、diff通过。
3. **最终正式CLI独立运行**：主agent运行最终代码，输出独立目录 formal-cli/。run=`compat-1d137f8354a2`，scratch=`lightrag_probe_23aa53cdb1`，退出0、合同problems=[]、ownership_verified后已清理，正常finished_at。
4. **F1真实故障**：主agent在真实服务器、唯一自有临时库注入首次OID读取OSError。没有UnboundLocalError；终态保留库名、oid=null、oid_known=false、原始故障和acquire-partial阶段。没有初始化任何LightRAG存储或调用模型服务。
5. **F2真实终态及严格拒绝**：同一故障运行实际执行post-guard并保存identity_after、failure.stage=acquire-partial；缺marker/OID的cleanup安全拒绝，cleanup.dropped=false和cleanup-error独立落盘，恢复记录0600，无finished_at。不是把假cleanup成功当成真实回收。
6. **确认归属后的恢复**：审查脚本在CREATE返回时独立保存真实OID并设置仅该新库的审查归属标记；回收前核对创建记录、当前OID与该标记，再用保留材料补marker，经原正式cleanup_scratch三重校验与实际DROP连接自查回收。没有放宽应用的所有权规则；没有使用备用直接DROP路径。详情 partial-live-verification.json，脚本 partial-live-review.py。
7. **正式来源不变**：正常CLI和真实故障/恢复各自前后只读核对，八表计数221/5709/279/16514/65527/221/221/119575、source/catalog/search/gold/原.env字节SHA一致；只读最终库名核查无新probe/reviewer残留，历史固定名库也不存在。0实际LLM/embedding请求，0会话终止，0外来库清理。

独立故障阶段的恢复有明确的额外创建归属证据，不能推广为“保留库名或secret即可给任意库补marker”。身份未知时继续拒绝自动DROP，保留失败/恢复材料。

## 已确认的兼容合同

- 首次ClientManager建池执行initdb/check_tables，属于库级写入；持引用复用与全释放后重建分别记录1/1、1/1、2/2。正式库不得让该初始化路径触及，换workspace不足隔离。
- 发布包原生PGTableGraphStorage可用普通PG表；AGE/PGVector的缺扩展失败仅归属各自后端。不能用8张KV表与10张总表推断旧管线来源。
- 同文件名、不同workspace、不同内容可有相同chunk_id；实际去重身份为(workspace,chunk_id)。公开aquery_data返回可对应物理chunk；同workspace不同版本文件并列与缺失chunk的公开读取合同已实测。
- 实际DROP连接自身核验OID/会话，所有权不符先拒绝；实例在initialize前登记，恢复记录与失败终态独立保存；必验后端、同池、生命周期和cache_type字段有强制门控。
- cache当前证明插入extract阶段，不能当作查询缓存禁用/冷生成已完成。

## 验收边界与下一步

5.1证明接口、身份、初始化副作用、隔离/拒绝/恢复合同及正式只读策略。查询运行使用naive模式和明确本地fixture；**真实LightRAG local语义链路、实际embedding/LLM请求、原Qdrant/Neo4j运行兼容性、融合与rerank质量仍未验证**。没有计算或批准任何新的检索质量指标。

正式.env类名配置为PG KV/Status、Qdrant vector、Neo4J graph。PG两张graph表为空的历史观察不能作为真实local graph替代。下一位agent按 `handoff-phase-3-5.2.md` 先盘点原后端只读身份与公开接入点，再实现实际local候选适配并记录请求/来源映射，完成后停5.2检查点。保留冻结gold、source/catalog/search、公开失败题和前期验收断言。

主agent接受状态、提交SHA、源身份、运行/测试/凭据扫描证据详见 review-manifest.json。所有前轮退回报告保留为历史，以本报告为当前5.1结论。
