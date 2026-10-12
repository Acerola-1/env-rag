# Workspace Ingestion

## ADDED Requirements

### Requirement: Frozen source classification manifest

导入 SHALL 使用带原始 SHA、逻辑文档身份、分类依据、分片关系和目标 workspace 的冻结清单。无前缀分片 MUST 先证明父文档／领域及覆盖；重复／排除 SHALL 有明确证据，运行后 MUST NOT 为完成率删项缩分母。

#### Scenario: PDF is an unnamed split fragment
- **WHEN** 源 PDF 是无法按 air／water 前缀识别的分片
- **THEN** 导入器根据解析／原始来源证据记录所属文档和目标库，无法证明则报告未解决而不猜测

### Requirement: Complete independent workspace data chain

每个 workspace SHALL 拥有其文档、chunks、有效向量、实体／关系及图谱来源，并发布对应 PG 目录／索引。复用解析或中间结果 SHALL 验证来源、配方和模型身份；MUST 保留表格／sidecar 定位，不得直接复制混合图谱的合并描述造成跨库残留。

#### Scenario: Existing graph merged air and water sources
- **WHEN** 旧图谱实体描述或关系合并了两个领域的文档
- **THEN** 目标库按自身文档证据重建／裁剪并独立验证，不仅改标签就宣称隔离

### Requirement: Cross-workspace duplicates and same-workspace idempotence

相同资料 SHALL 可在不同 workspace 独立存在。同库重复导入 SHALL 使用包含 workspace、源身份、配方及模型的幂等 checkpoint，不重复添加相同数据或执行已成功的模型请求。duplicate 状态 MUST 指向可验证的成功内容。

#### Scenario: Shared source is imported into both libraries
- **WHEN** 一份真实共用资料分别导入 air 和 water
- **THEN** 两库均可独立查询，身份、向量和图谱互不覆盖，同库再次运行新增行和不必要模型请求为零

### Requirement: Resumable bounded ingestion

导入 SHALL 持久记录逐项 processed、duplicate 和失败状态及实发调用，支持中断恢复。执行 SHALL 先通过真实小样本整链验证再继续冻结全量清单；重试和并发 SHALL 有限，不能无界重跑或用旧历史预算假装新任务已完成。

#### Scenario: Import stops after some documents
- **WHEN** 本轮导入进程中断后重新启动
- **THEN** 系统继续未完成项，保留成功 checkpoint，不重复计费已完成请求，失败如实记录

### Requirement: Scoped updates and protected existing data

新增、更新、撤回和回滚 SHALL 只影响明确拥有的目标 workspace，重建其派生索引并使相关缓存失效。已有 default／非本轮空间 MUST 保持数据和 active 身份；禁止全库删除／重建卷。多库副本 SHALL 提供明确同步操作及版本漂移诊断。

#### Scenario: Source is withdrawn from air
- **WHEN** 本轮试验资料从 air 撤回并重建目录／索引
- **THEN** air 的查询与缓存不再使用该资料，water 副本和既有 default 保持原身份
