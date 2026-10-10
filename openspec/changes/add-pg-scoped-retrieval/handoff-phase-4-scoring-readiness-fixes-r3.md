# 评分准备：只补严格绑定作用域

r3原27/27、历史35/35、自有22/22独立通过，全部保持。还有一处：main的_STRICT_BIND在_score_legs后关掉，后续recall/typed读正式fusion/local时又进入宽松裸探针状态。

## 只做这一处

在全新 **reports/pg-retrieval/phase-4-scoring-readiness-r4/** 复制评分副本；使严格身份绑定贯穿**完整正式生成模式的工件消费/评分/recall/typed读取**。不要只给被点名的两文件加特殊判定；按owning作用域管理，成功及任何异常finally恢复上一状态，裸接口fixture保留宽松语义。

正式成功的fusion/local结果缺qid或workspace要写本次净化拒绝诊断、非零、无裁决；完整字段、真实零发现仍是合法正例。合法明确failure/no-results/absent腿继续原合同，不强制制造成功元数据。

无需改硬失败、typed匹配、诊断唯一性、锚结构、分母/投影或任何生产代码。0网络/DB/模型/健康探测；gold/.env/真实锚/所有旧目录/冻结不动。before SHA先捕获，PYTHONDONTWRITEBYTECODE=1，新输出固定新目录，manifest最后写。

## 验证

新增冻结 `phase-4-scoring-readiness-review-r3/test_scoring_review_r3.py`：当前2失败/1正确，补后ENV_RAG_SCORING_READINESS_SCRIPT指新副本必须3/3。正例验证入口结束时_STRICT_BIND=False；负例也要求恢复且无裁决。

原review17+review10共27、历史35原样复跑；自有22原语义保持。若非冻结自有typed主入口fixture故意没有qid/workspace，可**只补合法metadata**（必须与其题/工作区一致）并刷新临时manifest，零发现/引用/分母/输出断言不改。原冻结裸接口输入与断言不动。

必要的生命周期正例可补一项：typed/recall读取异常后恢复，随后合法新代可运行。工作面ruff/strict/diff/敏感扫描、历史SHA复核，生产源未改不重复526。

## 停止点

交付作用域修复对照/原始矩阵输出/before-after/manifest，明确所有证据为fixture或既存工件副本、0新请求。停主agent复审，6.2–6.5/Gate4/默认路径不动；不问额度、不建正式锚、不跑123/246腿。此处通过后再准备正式两轮交接；前面已通过部分不再返工。
