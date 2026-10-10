## Purpose

建立来源可核验的真实语料评测合同，以固定白名单和审核答案分别检查召回、完整范围、枚举集合与融合收益，保存实际生成上下文及分阶段延迟，避免答案缓存和未经验证的数据造成错误结论。

## ADDED Requirements

### Requirement: Frozen evidence-backed benchmark

评测 SHALL 固定语料、问题、来源快照和审核答案，覆盖 fact、文件枚举、正文枚举、表格枚举、synthesis 及失败反例。未审核或无原文依据的答案 MUST 排除出质量指标，样本替换必须形成新版本。

#### Scenario: Gold list was generated without source review
- **WHEN** 标准清单只有模型输出且未核验原文
- **THEN** 该题不能用于计算集合完全正确率

### Requirement: Cold generation with actual context

对照 SHALL 禁止答案缓存命中和答案文件复用，记录同一次实际生成请求的候选、精排、展开范围、上下文及模型配置。另一次查询的上下文 MUST 不得代替生成时上下文。

#### Scenario: Answer cache hit is detected
- **WHEN** 请求被识别为答案缓存命中
- **THEN** 该请求不计入冷生成质量和延迟对照，报告污染并重新执行

### Requirement: Separated quality and latency evidence

报告 SHALL 分类别列出候选 recall@k、目标范围覆盖、漏项／多项、集合完全正确率、来源／版本错误、降级次数及分阶段 p50／p95，记录分母和两轮结果。质量通过 MUST 依据 design 中冻结的门槛，而非单个成功演示或综合均分。

#### Scenario: Good average hides a failed enumeration category
- **WHEN** 总均分提高但正文枚举未达到门槛
- **THEN** 报告该类别未通过，不能把变更标记验收完成

### Requirement: Evidence-based rollout

系统 SHALL 保留 local、PG 和融合的可复现对照结果。融合未通过冻结质量门槛时 MUST 保留已验证默认基线，公开失败案例，不以小样本结果宣称生产能力。

#### Scenario: Fusion loses a requested version
- **WHEN** 融合在固定对照中遗漏目标版本而 local 正确
- **THEN** 该轮验收失败，融合不得作为通过验证的默认路径
