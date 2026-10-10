# 5.1 第四轮补正：只处理 F1–F2

正常正式CLI已由主agent独立复跑成功；5.1尚未放行仅因部分创建失败路径的两处缺口。详见 `reports/pg-retrieval/phase-3-review-r4/review.md`。**只修 F1–F2，仍停5.1；不进入5.2–5.6/Gate3。**

1. **F1**：_acquire_scratch 的 OID读取 await 前初始化 row/部分创建状态。查询抛错也须携带已知的 partial_scratch，不能用 UnboundLocalError 覆盖原故障或丢掉已创建库名。未知OID标unknown，不放宽所有权校验。
2. **F2**：部分创建失败走统一后置身份采集、安全回收、失败报告终态出口。报告最后落盘必须有库身份、恢复路径或恢复失败、cleanup成功/拒绝及阶段，不停留在scratch加入前的初始快照；后置采集失败也独立记录。不要为部分失败再新增一个提前raise的平行分支。marker/OID不完整时继续安全拒绝自动DROP，记录retained及可验证恢复步骤；人工处理不算正式自动清理成功。

保留原216项及新增4项（3失败/1正例），修复3失败且1正例保持；保留前轮6项拒绝和2正例，不弱化/删减/xfail。新增必要的 OID读取失败、partial清理成功/拒绝与后置采集失败入口证据即可，不扩展检索业务。

从最终代码生成独立新代次报告/JSON/manifest，完整正式CLI正常路径仍须成功、fixture服务请求0、临时库只清理已确认归属对象。source/catalog/search/gold/.env只读前后不变，原Qdrant/Neo4j不初始化。不升级依赖、不迁移原库或重建索引。Ruff/OpenSpec strict/diff及全套通过后提交，仍由主agent复审5.1。
