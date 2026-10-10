# Phase 4 收尾离线组交付（2026-10-09）

纯离线文档/证据组：**0 网络/DB/模型/embedding/rerank 请求、0 写库、0 源码/
提示/gold/锚/.env 改动**（全部工件 SHA 复算见下）。第二轮、fusion 小批、
答案模型均未启动；6.2/6.3/6.4/6.5 不自行勾选。

## 交付清单

1. **对照账** `remaining-cases.jsonl`（123 行）：r3 已验收评分逐 key 保留
   改前终判与理由；每行新挂 `post_change_evidence`——
   `本路径本题已现场核验` 9 行（PG 批 5 + local 批 4）、`只有构造/离线回放证据`
   9 行（改进组 1/2/3 owning 回放：file-005 双路、file-001/002 local、
   table-001/prose-001/006/neg-004 local、prose-003 pg）、`尚无改后证据`
   111 行。`gate4_attribution` 按合同归因到：发现缺口、范围未确认/读不全、
   归属/版本错误、声明-来源关系不成立、载体/元数据/gold 待人工、数据掩码
   附加缺口、预算观测 3 类等，并逐行标注阻碍 Gate4 哪条门槛或可保留公开
   边界。**真实服务失败 0 行**（round-1 123 行 runtime 全部 ok；neg-008 三行
   runtime=absent 是构造信封在守卫处停止的合法观测，按"预算控制观测但
   未完成本题"归类，不计服务故障），与 HTTP200 后答案拒绝逐行分列。
2. **合成重点解释** `synthesis-explanations.json`（21 行=18 正例+neg-010×3）：
   逐行区分前置条件不足（10 行，HTTP 未发出 0 调用）/改述不满足连续逐字
   合同/引用不逐字/数值对象关系不支持/选错题面范围（syn-003/fusion 交付
   真实 4.1 条款但 gold 问 6.1 采样位置——真实引用不支持替代）；证据指针
   指回 round-1 存量 raw_response/context SHA 与 r3 行，未调模型、未销账。
3. **新代评分/人工审查方案** `scoring-and-review-plan.md` +
   `pending-review-gaps.json`：代次绑定四要素、规则零改动、r3 对改后源码的
   SHA 拒绝属正确行为不加豁免；22 行 PENDING 各列人工动作；typed recall
   映射采集改为提案（只读、PG≤20 语句、本组不采集）；时延字段可用性表
   含 inclusive/exclusive 口径与 untested 项。
4. **两轮计划与预算提案** `two-round-budget-plan.md` +
   `two-round-budget-proposal.json` + `two-round-dry-run/`（owning 入口
   `eval-run --dry-run --rounds 2`，246 行与冻结 6.1 矩阵逐行相等，
   **backend_fetches=0**）：编译上界与交接提案逐项一致（keyword 164/
   embedding 656 批/Qdrant 1312/Neo4j 1640/PG 1024 每腿·两轮 251904/
   精排 82/答案 36+6=42）；对 6.1 冻结上界唯一差为 PG 标定（信封规则
   不变），差异逐项解释；备选低成本收尾路径已写。
5. **finalization-plan.md**：6.2–6.5 结束条件、状态四轴
   （代码完成/有界真实样本完成/全题指标待完成/未覆盖边界清单）、
   下一组只建议一个：固定版本正式评测组（前置=主 agent 新配置代次+
   用户额度授权；替代=失败报告收尾不强行切融合）。

## 边界声明

改前 33/45/15 与 9/14/7 为历史基线，未回写、未据此推算"改后全 31 题
新正确率"；local 3+1 不替代全题集分母。输入 old artifacts 未赋给新轮答案，
仅做对照分析，不冒充冷生成或当前完整质量指标。旧 PG/local 已通过结论保持。

## 验证

- 未改源码：不重跑 526 全套；OpenSpec strict 通过、`git diff --check` 干净
  （见 quality-commands.txt）。
- 敏感扫描：本目录全工件两遍模式+env 密钥值实值比对，命中 0
  （`sensitive-scan.json`）。
- 保护清单复算：全库各代 manifest 逐条比对，0 漂移（见 recheck 记录）；
  r3/历史/改进组/两批复验工件逐字节未动。
