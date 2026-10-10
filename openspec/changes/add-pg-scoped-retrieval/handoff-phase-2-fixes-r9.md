# Gate 2 第九轮补正：只把类型检查放到减法之前

读 `reports/pg-retrieval/gate-2/review-r9/review.md` 和 `tests/test_gate2_review_r9.py`。177既有/原49验收断言通过，新1调用链反例失败。H1/H2/空segment三原反例已验收，当前31题指标56/59、23/23、三集合6/5/5、60正文/241表行回读和8真实反例都通过；无需再调检索。

唯一问题：verify_citations内部_slice先做rel_lo-off，再检查类型。来自模型JSON额外segments的字符串/null可通过shape/引句验证，binding保留该字段，减法抛TypeError。先对rel_lo/rel_hi原始值检查整数类型（JSON bool不作为整数坐标），非法return None，然后减offset、沿用现有区间规则。只改这一处共同_slice，不改已经通过的分支逻辑。

保留既有False不升级、来源缺失/空span拒绝、合法跨unit/裁切/quote-only路径。新反例应安全上游model_failure或verify=False，不是抛异常；不通过删断言/去掉异常输入/前缀豁免过关。模拟JSON响应即可，不调用真实模型。

修后完整测试；同一review-r5/gold-approved.json的31题与8真实入口反例复跑，独立raw引用回读与来源manifest保存，金标SHA/题目/分母不变。只修上述类型检查及必要回归，不动路由、目录、索引、不写public/MinerU、不重建、不提前融合。交付补正报告停Gate2复审，4.4/4.6仍由主agent判定。
