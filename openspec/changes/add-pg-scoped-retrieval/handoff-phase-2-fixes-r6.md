# Gate 2 第六轮补正：仅修普通正文坐标与位置验证

先读 `reports/pg-retrieval/gate-2/review-r6/review.md` 和 `tests/test_gate2_review_r6.py`。170 既有测试及原 42 验收反例通过，新 1 反例失败。D2 已验收，不重做发现快照；类别分支及当前 60 条正文引用已验收。本轮唯一阻断 F1 是 D1 要求的真实偏移/声明跨度验证遗漏，不新增检索功能。

1. `_expand_prose` 的无子条款 fallback（expand.py:1015 起）不能用 heading_len 推算 `.strip()` 后 body 的位置；使用 body 在未改写 assembled 文本中的真实起点，涵盖标题前空白、标题后空行、正文缩进，并统一与类别分支的映射。缺真实位置则 partial/unverified，不能 fabricated/complete。
2. `verify_citations` 不能只做 quote 全文子串检查：完整 quote 必须受声明的 assembled/raw unit span 支持；边界与归属验证要贯穿 binding 后的真实单位偏移，兼容 requires_span、跨 unit 和模型 quote-only 合法路径。整句存在但声明位置不支持时拒绝 verified/complete。主 agent 新反例的数值末尾丢失必须消除，不以标点、规范化或删 quote 降低断言。

原 42 项和新增 1 项行为断言保持强度。修完先回归完整测试，再使用同一审核副本 `reports/pg-retrieval/gate-2/review-r5/gold-approved.json` 重跑 31 题与 8 项真实反例；保存完整发现/展开/答案与独立 raw 引用回读。不得改题、期望、分母或金标 SHA。真实指标已复现：56/59 证据召回、file/prose/table 6/5/5（各分母 6），60 正文/241 表行当前引用全支持；公开排序/歧义失败可以继续保留。

仅修所属实现及必要回归，不重建目录/索引、不调用模型、不写 public/MinerU、不提前融合。交付补正报告停 Gate 2 复审；4.1–4.3、4.5 保持完成，4.4/4.6 留主 agent 验收。
