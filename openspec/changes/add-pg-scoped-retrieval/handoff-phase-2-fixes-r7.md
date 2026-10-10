# Gate 2 第七轮补正：仅完善F1验证器

读主agent `reports/pg-retrieval/gate-2/review-r7/review.md` 与 `tests/test_gate2_review_r7.py`。普通正文body_start、原空行99反例已验收；D2/类别/金标/索引不重做。171既有通过、新3反例失败；4.4/4.6未完成。

1. **完整quote**：删除prose_enum.py:531前60字放行。完整quote必须受声明区间支持。跨单位quote需要按原始assembled顺序及有效segment完整还原证据，不能只因每个片段在全文存在就通过，也不能只验主owner中的短前缀。
2. **偏移坐标系**：UnitText.text是已裁切片段，unit_rel是raw单元坐标。owner及unit_segments切片都须减span_offset_in_unit，并验证边界及实际可读范围。测试中的合法requires_span正例必须verified；错误跨度必须拒绝。当前WHO范围没有可定位编号结构的保守状态保持，不改Phase1来迎合。
3. **旧接口安全退化**：无units的两参数verify调用仍须检查完整quote确实在全文中，不能只bool(quote)。已False不升级，locator错误拒绝；提供units但缺少声明unit来源时拒绝/降级，不伪造verified。

原43验收断言与新3项保持强度，不删/skip/改期望。完整回归后重跑同一 `reports/pg-retrieval/gate-2/review-r5/gold-approved.json` 的31题和8真实反例；gold SHA/分母/题目不变。独立回读60正文和所有实际表行（本轮241），保留syn001/002排序、prose005/table003公开失败。合法跨unit、requires_span、quote-only与错误位置都须有行为证据，不用固定字数豁免维持指标。

不改查询路由/目录/索引、不重建、不调用模型、不提前融合；仅实现上述验证与必要回归，交付补正报告停Gate2复审。当前31题指标均已复现，不需要再调召回或更改gold。
