# 6.1 rev-2剩余补正：S1 / S2（2026-10-08）

6.1未通过，Gate3保持，6.2不启动。原440通过，冻结r1 20/r2 12全过且字节未变；新冻结 `tests/test_evaluation_review_r3.py` 7项5失败/2正例。Reviewer零真实请求/写库。

## S1 精排HTTP实发对账

移除“进入rerank入口即issued”的推断；请求前reserve保持。成功返回从当前qid的实际call凭证计HTTP；抛错时从本题runtime的已完成/在途call凭证对账，不能借其它题。HTTP前配置/来源/身份拒绝或call=None/skip计0；实际HTTP成功、非2xx、timeout等已进入请求的尝试计1。无法得到凭证时显式unknown，不把未观察推断为已执行或确定0。返回与异常路径均避免双计；保留正例401计1。仅读写假传输工件验证，0新rerank请求。

## S2 完整锚与keyword冻结

验证器先严格校验必填结构/字段/类型，再比较：来源身份、gold内容、实际模型与端点/维度、提示、所需代码SHA、参数预算。code_anchors/frozen_budgets/必需模型任一缺项或空节不能成为可选跳过。keyword实际解析身份（KEYWORD_LLM_MODEL或LLM_MODEL fallback）必须匹配冻结值；增加匹配keyword/fallback正例与漂移负例。保持完整当前tmp新代次正例、缺锚CLI拒绝、dry-run0触碰与已有模型/代码/参数漂移断言。

自己test_evaluation.py的_anchor_values fixture需补充该真实必填模型输入，允许补fixture字段，但不得删除或弱化语义断言。不得凭空填expected或把当前值回写锚去迎合运行；真实锚仍旧，审批后主agent显式新建代码/模型代次。

只改评测验证器、精排账本和必要CLI/自有tests/证据；不动其它通过实现、.env、gold、三版冻结、四轮answer或历史。0真实模型/embedding/rerank/DB请求、0写库。不重构1689行实现；只做上述接缝修复及必要正负例。更新可复算SHA、必要测试、Ruff/strict/diff/敏感值扫描后停6.1主agent复审。
