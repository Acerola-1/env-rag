# 下一组仅5.5：精排后完整范围展开与按题型回答

5.4通过主agent最终验收（phase-3-rerank-review-r4/review.md、tasks.md）。只做5.5，完成后停检查点；5.6 Gate3总结与Phase4两轮对照不进入。原319项及所有冻结验收断言保持，原公开失败和gold不改。

## 端到端入口与输入合同

- 最小answer CLI/编排入口连接已验收5.3融合、5.4联合精排、Phase1/2范围读取与引用验证。支持固定已验收候选/精排结果回放用于有界验证，但明确回放来源和代次；不能用人工整理的正确答案代替正式流程。
- 通过真实schema传递query/workspace、source/catalog/search/gold/env身份、typed_targets、每项chunk/doc/SHA/全部paths、原始精排分数与degraded。实际5.3目录快照在pg.catalog_snapshot_id，最终以guard核实的active snapshot为准；输入读取/结构/未知ID/配置/来源拒绝仍有完整零调用终态。
- 原始引用和修复轨迹不得在阶段转换时丢弃。block/source_unit关联不等于table_unit，关联补全不等于请求范围已确认；先确认目标文档/版本和逻辑范围，再读完整证据。
- 真实PG/MinerU/Qdrant/Neo4j/目录/索引只读，不实例化LightRAG初始化，不迁移/重解析/embedding；缓存16,514行既不读取答案也不写入。答案服务复用.env配置，若用release openai_complete_if_cache必须hashing_kv=None；记录0答案缓存读写，不能以函数名字证明。

## 精排选范围，展开不受top-k截断

- 精排只用于发现与范围优先级。选中逻辑表/章节/条款后，通过已验收目录与真实成员链接读取**全部成员**；续表即使分数最低、没有直接进入前k，也必须纳入。范围选择/成员总量/处理量/失败或预算/未读起点分别记录。
- 复用enumerate_与search.expand的正式入口，不重写一套弱化引用/coverage规则。原表2歧义、prose-005歧义、requires_span未定位与空scope均保留ambiguous/partial，不能因为生成成功而升级complete。
- GB8978表1应保留两片13项及表头/单位/注脚；GB18466条款支持requested_clauses，章节标题不当条目，跨chunk不重复、不串下一条。requires_span必须定位正确raw单元跨度，找不到拒绝完整性。
- 文件枚举走完整集合分页，不由精排top-k文件清单冒充完整集合。同内容不同版本仍是独立来源；GB3095-2012/2026对比各自确认、读取范围与适用条件，缺一版本missing/incomplete，不能拿邻近版本替代。

## 按题型输出与生成验证

- fact输出有单位/条件的源事实；file/prose/table枚举优先从已verified条目确定性渲染，不为格式多调答案LLM；synthesis可调用一次答案模型综合，版本标签与引用身份由应用绑定，不让模型自由改写归属。
- 输出拆开discovery、rerank/degraded、scope coverage、generation status与答案项引用。complete须满足全部必要成员已读/处理、无阻断失败、每项引用独立verified；LLM返回正常不等于coverage complete。0项/缺范围/预算不足不得complete。
- 回答每个数值/限制/日期/适用与过渡条件都绑定本次真实上下文的来源。对标准版本比较核查条件性前言/适用条款；缺条件证据就明确incomplete，不用常识或gold补答案。
- 模型路径保留实际messages、冻结参数、原始响应/耗时与净化凭证。结构错误、超时、无引用、编造引句、真实引句支持不了声明（停车场/错误限值/错误年份等）均显式model_failure/partial，禁止编造引用或把全文存在性当位置核验。
- 沿用严格引用坐标合同：表项raw grid片内行，正文raw unit-relative跨度（requires_span偏移与跨unit segments正确换算），完整quote在声明范围内。版本/单位/条件必须与对应来源一致，未知字段不编造。
- 所有前置与工作阶段异常、post drift/采集失败仍有当前题独立账本和部分结果；原错误与后置错误并存，成功/失败全部证据先净化后截断，保留来源与typed目标。

## 集中入口验收矩阵

1. 正式5.3→5.4结果结构进入5.5，真实成员读取；续表片置最低排名、发现top-k=1仍两片13项，原始行引用独立回读正确。
2. GB18466第3章3.1–3.4与4.1六条边界、重复/漏条款；缺9.9.9 partial，不是空列表complete；requires_span选对请求跨度或拒绝。
3. 文件集合跨页、不同版本同内容独立；比较缺一目标missing，不以邻近版本代替，显式自身编号/修改单语义保持。
4. 预算/空scope/源漂移/结构歧义保守；reranker degraded不能伪造精排成功，但允许有完整来源时明确degraded回答。
5. 模型非法JSON/超时/无引句/编造尾句、正确引句配错误声明/数值/年份拒绝；长引句/跨unit/requires_span真实位置正例保持。
6. 适用/过渡条件缺失不完整，所有输出引用对应当前实际上下文；前后守卫/每题凭证/失败终态与净化保持。fixture通过owning入口，不用孤立提取器代替。

## 有界真实验证与交付

- 先完成矩阵。之后固定回放输入，正式只读展开验证GB8978表1低排名续片（13项）与GB18466正文范围；枚举确定性生成，0答案LLM即可。
- 只做**一次必要答案LLM请求**（建议syn-001版本比较），先核实两版本及必要条件范围与引用。沿用已验收精排响应/排序回放，不重复keyword/embedding/local/rerank整轮。报告清楚每个阶段哪些是回放、哪些是本轮真实读取/生成。
- 如果选定问题条件无法完整定位，保留公开失败/incomplete，不改gold或伪造补值来达到指标。此组不跑31题质量指标或正式两轮对照，不宣称Gate3通过。
- 保存范围选择、完整成员清单/预算、上下文（实际送模型那份）、结构化答案/引用、净化原始messages/response、实际服务记录与前后身份；manifest用最终代码/测试/输入/证据SHA。最小CLI和失败回退说明，Ruff/format/OpenSpec strict/diff/凭据扫描，停5.5复审。

冻结source=`95f7791fd84171ab727870fc5810d79b4327b0c4fa547d432951e0499a3808f8`；catalog run/snapshot=`c15c741742394320`/`4919b3938ad93747`；search=`872d689343a9cbb6`；gold=`1bf130077c21583a89c5ca14695694d9552c558a7d8dc5d45ff0d9f72cfd7a5e`。public八表221/5709/279/16514/65527/221/221/119575；唯一已核实映射default↔'_'↔base。
