# Phase 4 pilot-r2 复审与下一轮裁决（2026-10-08）

**工程试点通过；质量基线存在公开失败。6.1/Gate3保持，6.2未完成。** 本轮Reviewer仅读取工件和离线准备，0新真实请求/写库，不改已验收源码、模型、提示或gold。

## 工程核验

r1 31项、A 28项、B 67项manifest全部匹配。A/B pre/post来源、catalog/search、gold、env、八表计数相同，接受源码SHA一致。A三腿PG累计89/109/144，非PG实发0，到达answer，无失败/拒绝，放行条件满足。

B九腿均到达answer，无budget_failure或腿级/运行级failure；PG累计分别89/77/123、109/142/143、144/45/176，总1048，PG路径与A逐值相同。keyword6、embedding16、Qdrant16、Neo4j30成功凭证吻合。三条fusion精排真实HTTP成功，ordered为10/6/21，分数有限且排序一致；其它路径按策略无精排。

答案预留3、实际HTTP2：pg/fusion syn-004成功接收响应；local因incomplete_conditions不发请求。不是九腿都实际执行精排与模型HTTP，而是各路已走完自己的执行/拒绝策略。1024是有余量的有界护栏；这3题峰值176不足以把它降为全库保证值。

## 独立质量裁决

1. **syn-004交付失败**：pg/fusion原始summary正确识别地表水/环境空气，属于诊断信息；三路交付均0项，不能算合成答案通过。pg输出2项改述，GB3095 claim还添加了绑定quote未陈述的污染物参考限值；pg claim未显式标“附录A”，不能把fusion的附录归属措辞推广到两份输出。fusion原始items实际为**10项**，验证问题为**12条**（不能把12条问题记成12个claims）；8条表格quote不是输入HTML上下文的逐字片段，2条声明改述，标准编号数字3838/3095也触发数值支持检查。fusion明确附录A，未见把它称为第7章强制要求；但引用/声明合同仍未通过。不以raw summary给拒绝交付的答案补分。
2. **prose-enum-001 local明确为集合失败**：问题指定GB18466-2005第3章。pg/fusion为该文档3.1–3.4共4项；local为17项，目标4项存在，但混入另两份标准**13项extra**（还含“1998”条目标记）。这是已观察到的答案范围/相关性失败，不能等31题批次再假定是否失败；app complete只说明它选取的范围处理完，不代表问题集合正确。pg/fusion身份+条款成员集正确，全文/引用细节另按固定评分合同核验。
3. **fact-002边界保留**：partial/ambiguous/partial是实际交付，缺单位和歧义不补造，不为希望得到complete改金标或引用。

## 决定

- **不改提示、合同或批次策略**，把当前model_failure/incomplete/多项作为失败计入基线。当前提示已明确要求连续逐字；不能只针对syn-004不断试模型，把成功样本挑入正式结果。提示调优留待第一轮数据与独立变更审查后另建代次，不能夹在两轮固定配置对照中。
- **维持1024 PG累计信封**；只把第一轮整批PG cap按123腿重新编译为125952，防止旧整批cap变成下一道非必要瓶颈。负例tiny-budget预置保持，不为了消除所有拒绝而取消反例。
- 准备**第一轮41题×3路=123腿**的完整基线交接，31正例93腿与10反例30腿分列，第一轮完成停复审；不自动第二轮、不重用本试点为正式冷生成结果。该轮超出原9腿范围，须由用户将新交接下发执行；本复审不自行发起批次。

第一轮预算与矩阵已通过owning dry-run（backend_fetches=0）。keyword≤82、embedding≤328批、Qdrant≤656、Neo4j≤820、精排≤41、答案≤21（正例18+反例≤3），PG≤125952，均为工程计量上限而非账单价格保证。原两轮门槛保持；完成一轮不能勾6.2或放行Gate4，也不切换默认路径。

下一步：[handoff-phase-4-6.2-round-1.md](/Users/acerola/Dev/Python/RAG/env-rag-final/openspec/changes/add-pg-scoped-retrieval/handoff-phase-4-6.2-round-1.md)。
