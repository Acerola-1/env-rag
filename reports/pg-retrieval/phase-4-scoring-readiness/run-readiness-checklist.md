# 付费两轮前的运行准备清单（本组交付后实况）

| 项 | 状态 | 证据 |
|---|---|---|
| 评分器可用（生成绑定模式） | **就绪** | `assess_two_rounds.py`：`--run-dir/--round/--anchor/--manifest/--out` 绑定；兼容默认=r3 原行为；新矩阵 19/19、35 冻结在兼容模式全过、r3 自测 12/13（备案细标签，判罚不变） |
| 人工审查通道 | **就绪（合同见 manual-review-protocol.md）** | 记录必须绑 run/round/qid/path+runtime SHA+响应 SHA/absent+审查人+已核项；错绑=拒绝非静默；PASS 只解已审核语义/载体缺口，不救已证失败、不救 0 交付；`_MANUAL` 兼容限用；本组未预造任何未来结论（测试记录均 fixture 标记） |
| 人工审查人员/流程 | **待主 agent 指定** | 未来两轮的审查由主 agent 侧出记录文件；执行方只消费 |
| 映射采集 | **提案待批准** | `mapping-collection-design.md`（JOIN unit_chunk_links/source_units、组合键、9–10 条数据 SQL≤20、空表/跨源拒绝、缺映射 pending、不反灌）；本组 0 采集 |
| typed evidence recall 评分侧 | **接口已实现（fixture 验证）** | `typed_evidence_recall`：显式零发现=0 不借枚举、缺映射 pending、跨 workspace 条目拒绝；兼容模式不读映射 |
| 新正式配置锚 | **待主 agent 建** | 须绑定改后已验收代码谱系（现行 answer `98328f7f…` 等）+现行预算；旧锚不动；r3 工具对改后源码的拒绝保留为正确行为（`input-rejection.json` 为本组实测演示） |
| 两轮用户额度 | **待用户确认** | 上限提案 kw164/emb656/Qdrant1312/Neo4j1640/PG251904(每腿1024 共用信封)/精排82/答案42（36+6）；1024 为发现+答案共用累计信封，无每阶段另发；实际以账本凭证 |
| 每轮一个独立运行目录 | **合同要求** | `inputs/local` 无轮标识——两轮必须各自 report-dir（评分器按 run_dir+round 绑定，不跨目录借工件） |
| 旧 PENDING 22 条订正口径 | **已引用** | 12 fact + 3 file-enum-004 + 3 neg-002 + 1 neg-005/local + 3 neg-008（主 agent 勘误为准；neg-007 三路原判 FAIL 保持；不改历史终判） |

**本组证据分类**：全部为合成 fixture + 已存真实工件副本（PG 批终端/inputs、round-1 腿）；
**新实际请求 0**、写库 0、生产源码/锚/gold/.env/历史未动（before/after SHA 见
sha-before-after.json）。

## 兼容行为边界（不得视为缺口）

- r3/本副本对改后源码的 SHA 拒绝：正确行为，不加豁免——新代次由主 agent 建新锚绑定。
- 246 腿矩阵与预算由未改 owning 入口 dry-run 编译（收尾组已证 backend_fetches=0）。
