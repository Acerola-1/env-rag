# 固定12道枚举同题裁决

原始产品提示与统一提示实验分列。完整清单与模型摘要分列，少量一般附加解释不算清单条目。

|题目|原local产品|PG+local|统一提示local|决定性差异|
|---|---|---|---|---|
|versions|FAIL|PASS|FAIL|历史1982/1996及GB9137被列成库内文件；库内目标只有2012、2026|
|amendments|FAIL|PASS|PASS|漏独立2026修改单，原生只列2份；增强3份|
|terms|PASS|PASS|PASS|目标条目、版本、数量及实质内容正确；增强保持一致|
|clauses|PASS|PASS|PASS|目标条目、版本、数量及实质内容正确；增强保持一致|
|continued_table|PASS|PASS|PASS|目标条目、版本、数量及实质内容正确；增强保持一致|
|edition|PASS|PASS|PASS|目标条目、版本、数量及实质内容正确；增强保持一致|
|new-prose-GB3838-2002|PASS|PASS|PASS|目标条目、版本、数量及实质内容正确；增强保持一致|
|new-prose-GB5084-2021|PASS_WITH_CONTEXT|PASS|PASS_WITH_CONTEXT|两条目标都正确；原生额外提供父4.1作为上下文，增强只列两条|
|new-prose-GBT14848-2017|FAIL|PASS|FAIL|原生仅拿到目次/前言，四个定义缺失；增强4/4|
|new-prose-GB11607-89|FAIL|PASS|FAIL|原生明确找不到4.1–4.3，增强3/3|
|new-table-HJ2.2-2018|PASS|PASS|PASS|目标条目、版本、数量及实质内容正确；增强保持一致|
|new-table-GB13271-2014|PASS|PASS|PASS_WITH_WARNING|五行限值与监控位置正确；原生附加单位不计集合指标|

产品口径明确纠正4题；统一提示下3个决定性失败仍存在，修改单题转为正确。不能把所有改善归于PG本身。
GB5084原回答包含父4.1背景，不把它算成第三个目标条款；严格只输出请求区间的口径可单独记范围外附加内容。
GB13271统一提示实验表格行正确，但一句概述把所有监控位置都说成烟囱或烟道，和末行烟囱排放口矛盾；保留为附加解释警告，增强没有此句。
现阶段边界：GB8978表2结构仍ambiguous；未审核的一般模型声明仍明确标unreviewed；本题组不代表全库问题成功率。
