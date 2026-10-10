# Gate2 第五轮补正：只剩两个阻断

先读gate-2/review-r5/review.md、citation-reread.json、gold-freeze-manifest.json及tests/test_gate2_review_r5.py。原40验收断言保持通过、168既有测试通过；本轮新增2反例失败。4.1–4.3通过保留，**4.5源金标已由主agent审核冻结**，4.4/4.6未完成。

1. **D1类别坐标**：_split_category_sentences当前在去标题body上取坐标，却当完整assembled_text坐标绑定。用body真实起点映射回assembled_text，再绑定到原unit（含span_offset）。正确映射标题与前后空白，不硬编码15字或GB3838 ID。verify最后检查声明span支持quote，不能只查quote在全文。真库prose004五条引句必须在各自raw unit span起点独立回读一致，仍保持五类完整、source OCR号不伪改，规范类别审查映射见审核gold。
2. **D2空发现快照**：明确discovery_candidates=[]不可or回填candidates，即使后者是doc_attribution。若兼容旧fixture/调用，区分未捕获None/缺字段与明确[]；每个真实返回路径捕获预算内发现列表。不能全局禁doc_attribution，真实发现阶段归属候选仍合法。测试应为“枚举答对=true、发现数=0、recall=0”。

保持原40及新2反例的行为强度，不删/skip/降断言。若需要适配旧fake响应的未捕获字段，可显式完善fixture数据并逐项说明，不能改变原预算、工作区、stale或内容要求。

**金标不再等待执行agent自行审核**：指定`--gold reports/pg-retrieval/gate-2/review-r5/gold-approved.json`。主agent批准31正例和10反例期望的数据，不代表实现或指标已通过。该副本、题目、期望、typed来源和SHA保持不变；原提交gold-candidates.json保留历史。源/目录改变须停下记录，不改gold迎合；只改这两处查询/引用实现无需重建索引。

完成后：两个新反例→完整回归→同一审核副本31题benchmark→独立原始网格/引用位置回读→至少8反例完整入口重跑，保存discovery、展开、答案、缺失/多项/来源核验及源/索引身份。prose005/table003可以保留公开失败，按门槛各≥5/6即可；syn001/002召回失败保持，整体recall@20≥0.90即可。不得以标志true代替引用独立回读。

交付phase-2/report-gate2-fixes-r5.md与完整runs/源manifest，停Gate2复审。4.5保持完成；4.6由主agent判定。不得提前进入Phase3，不调用模型、不改public/MinerU或目录确认状态。
