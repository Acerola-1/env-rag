# 6.1 rev-2 复审（2026-10-08）

**6.1仍未通过；Gate3保持，6.2/网络评测不启动。** 只剩S1精排实发对账与S2完整配置锚两组，不返工已通过的R1/R4及其它R2/R3部分。Reviewer真实模型/embedding/rerank/DB请求0、写库0；未改提交源代码、配置、gold、冻结或历史。新增冻结test_evaluation_review_r3.py。

原 **440项独立通过（12.16s）**；两版冻结r1 20/r2 12字节不变并通过，自有25项通过（合计57项）。新增r3 **7项：5失败/2正例通过**。

## 保持的通过结论

生产async-with图session与直接调用均预算受控；CLI无conn的自建PG、SourceAdapter等连接进入作用域包装并保持所有权恢复。声明的计量覆盖与未计量控制SQL/metadata区分明确，保守多计不当作真实费用。模型预留/实发分账、库吞拒绝的discovery/answer阶段核对、合法配额/schema、AdapterError/OSError后置终态、local完整原始出处、实际资源分类均保持通过。题型/微预算、真实融合精排、选择与逐题工件此前结论也保持。

## S1：精排入口仍不是HTTP凭证

`_fusion_path`在进入`run_rerank`前直接记issued=1。实际精排入口先做gold/config、身份/回放、来源全文与映射检查；这些步骤可能在POST前拒绝。冻结测试两种真实可发生形态——HTTP前AdapterError、返回degraded且call=None——均被记成1。

修复仅需把精排实发账本改为与答案相同的凭证对账：保留请求前reserve；返回与抛错两条路径读取当前qid真实call/终态。未发HTTP=0；已发生成功或失败HTTP=1。缺失凭证保持unknown/unobserved，不凭入口调用猜测，不归零已发生尝试。已发生401仍计1正例通过并必须保持。不要重跑真实精排。

## S2：锚须完整且包含关键词模型

当前函数检查答案/embedding/rerank，却漏keyword；把实际KEYWORD_LLM_MODEL改成另一个值仍通过，而local/fusion由它抽词，两个评测轮会不再可比。

另外code_anchors或frozen_budgets整节清空仍通过，意味着没有代码/提示/参数约束也可启动。这是完整性验证缺口，不是合法新代次。

先定义并验证必填schema（来源、各实际模型/端点类别/维度、提示与所需代码锚、参数预算），缺项/空节/不合法类型零后端拒绝；再比较全部必填值，不只检查出现项。keyword按实际解析的KEYWORD_LLM_MODEL或LLM_MODEL fallback核对。授权换模型需新配置代次；当前DeepSeek阻塞状态不由本次审查改变。完整匹配的临时新代次锚正例通过，证明拒绝不应变成全拒绝。

本次anchor正例仅在tmp副本将源码SHA对齐当前授权兼容缝，用以审查验证器；真实phase-4-config-anchor.json仍原样，无新实弹或未经批准重冻。6.1最终通过后再由主agent建立真实新代码锚，不能提前修改锚遮住不符。

见comments.json/independent-tests.txt/submitted-suite.txt；仅按handoff-phase-4-6.1-fixes-r3.md补正后停6.1，原57项及新增7项断言保持。不修改已验收组件、不增加服务调用。
