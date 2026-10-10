# Phase 2 执行交接

Gate1已通过，见reports/pg-retrieval/gate-1/final-review/review.md。执行tasks4.1–4.5，交付后停在Gate2，4.6留主agent验收。先读design决策4/5/7、相关spec及最终Gate1报告。

## 固定输入与边界

- PG workspace=default；221份文档、5709chunks。active run=c15c741742394320，catalog snapshot=4919b3938ad93747，recipe=phase-1-v4-single-active-snapshot-prune。
- source fingerprint=95f7791fd84171ab727870fc5810d79b4327b0c4fa547d432951e0499a3808f8；先只读复核current再构建派生索引。
- 仅在本应用拥有的env_rag中做显式、幂等且有所有权保护的迁移/派生写入；public.lightrag_*与MinerU产物只读。不得重新解析PDF、重新embedding、修failed、初始化LightRAG存储或运行融合。
- 新的索引算法、清洗、分词和词表绑定版本及来源快照，构建前后核验来源；不要覆盖现有目录或错误沿用旧索引。若改目录派生算法，升级recipe并遵守已有构建守卫，不能靠相同来源幂等跳过修改。
- 现有EnumResult/source guard/引用合同必须继续使用；表2缺base与requires_span未定位的保守行为保留。

## 工作顺序与验证

1. **4.1分词探针**：优先验证jieba+受控环保词表，用uv锁定确定版本。PG simple读取应用分词词项；索引与查询同一清洗/编号规范化/分词版本，记录tokens、位置及词表SHA。真实标题、caption、正文及英文例都要验证。编号单独处理Unicode、全角、空格、破折号、版本年份，避免依赖分词。
2. **4.2派生检索索引**：在env_rag构建文档/chunk搜索对象，带权tsvector、GIN及必要B-tree，保留workspace/doc/chunk/snapshot身份。对HTML按文本提取；以真实EXPLAIN与计时核验计划和命中行为。seq scan在小数据上可能合理，如实记录，不能仅凭索引存在声称实际使用。
3. **4.3查询路由**：精确编号/年份优先，元数据限定后进行核心词匹配；保留强版本/身份限制。自然语言停用提问词与受控同义词/OR放宽须有逐次日志；同号多版本不任取首项。参考真实GB3095版本、引用编号与self_code分离等反例。
4. **4.4范围展开**：候选top-k只限制发现阶段。确认scope后读取全部成员并调用已有枚举入口；验证top-k小于表格片数/章节成员数仍不丢续片，长范围预算不足明确partial。文档集合使用分页，不用top-k冒充完整清单。未知范围保持ambiguous。
5. **4.5 gold候选及审核**：从现有35题/10反例提出至少30正例（五类各至少6题）与8反例，逐题补齐原文定位、完整期望集合/事实、目标候选证据单位、限制与允许状态。保留既有难例，缺依据题列缺口，不编造或悄悄替题。先交付gold待审核材料供主agent逐题审核；未审核题不得计入正式recall。实现评测入口与查询原始记录，审核后冻结benchmark版本，再计算指标。

## 交付

reports/pg-retrieval/phase-2/包含report.md、tokenizer-probes.json、index-manifest.json、search-runs.jsonl、gold-candidates.json及失败案例。保存真实命令、配置/代码SHA、source/catalog/index版本、词项、每次候选/限制/放宽路径、scope展开、引用、EXPLAIN和耗时。记录实际执行结果及尚未执行的部分。

Gate2门槛沿用design：已审核题PG recall@20≥0.90、明确编号/版本正例100%；三类enum各≥5/6集合完全正确、引用错误0，反例无false complete。明确定义recall的证据单位和分母，不用最终答案分数替代候选召回，也不使用LightRAG缓存或旧答案文件。未审核gold先交付待审，不填通过指标。

运行受影响行为测试、Ruff、OpenSpec严格校验、diff检查；测试覆盖真实调用路径与上述失败状态。勾选仅限有证据的4.1–4.5，不勾4.6、不进入Phase3。

## 可转交提示

请在/Users/acerola/Dev/Python/RAG/env-rag-final执行OpenSpec add-pg-scoped-retrieval的Phase2 tasks4.1–4.5。先读handoff-phase-2.md和Gate1最终验收，基于v4固定目录实现应用中文分词、env_rag全文索引、编号/版本限定查询、范围完整展开和gold待审核材料。原文库与解析产物只读；不做融合、embedding或修failed。保存真实探针/查询/EXPLAIN/异常日志。gold未审核不计正式指标，交付后停Gate2，4.6留主agent。
