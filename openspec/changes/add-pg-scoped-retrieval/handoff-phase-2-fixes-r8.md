# Gate 2 第八轮补正：仅修verify三个边界条件

读 `reports/pg-retrieval/gate-2/review-r8/review.md` 和 `tests/test_gate2_review_r8.py`。174既有通过，原46断言未改，新3反例失败。前60字豁免/裁切offset/旧裸接口原反例已验收，不重新做查询、目录、索引或模型。

## 只修三点

1. **结构有效 ≠ 主owner覆盖quote**：合法跨unit引句被当前`if supported and seg_units`短路。先检查来源及每片区间都有效；有segments时按assembled顺序完整重建并判断whole quote，不以quote必须完全存在于单个owner为前提。无segments时才校验owner单片覆盖。分开变量，不能继续复用已False的单片覆盖标志作为跨片重建条件。
2. **来源缺失统一拒绝**：声明unit_id无论numeric字段齐不齐，都先检查by_id有该unit；缺源False/partial，不能数值分支跳过后仍保持全文存在性True。裸旧接口没有绑定unit时保持全文检查兼容。
3. **空segment拒绝**：owner/segment都使用0≤lo<hi≤len(text)的同一边界规则，offset换算沿用已验收修复；拒绝lo==hi，不能拼接时悄悄忽略空片段。

保留合法quote-only/裁切/跨unit路径；已False不升级、locator错误拒绝；三项新测试及旧46断言不删/skip/降强度。可以增加完整正反对照验证分支，而不是只覆盖本轮三个最小反例。

同一review-r5/gold-approved.json（SHA/题目/期望/分母不变）重跑31题与8真实反例，保存发现/展开/答案/独立raw引用回读；当前指标56/59、23/23、三枚举6/5/5、60正文/241表行均已确认。公开排序/歧义失败继续保留，不要求调召回。

仅修验证器条件和必要回归，不改其他模块，不写public/MinerU、不重建目录/索引、不调用模型、不提前融合。交付补正报告停Gate2复审；4.1–4.3/4.5保持完成，4.4/4.6留主agent。
