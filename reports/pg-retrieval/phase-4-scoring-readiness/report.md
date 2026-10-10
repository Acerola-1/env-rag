# Phase 4 评分准备（零请求）交付（2026-10-09）

按 `handoff-phase-4-scoring-readiness.md` 执行：评分工具适配+测试+说明，
**0 网络/DB/模型/embedding/rerank/健康探测请求、0 写库、0 源码/提示/gold/.env/
配置锚/历史工件/冻结测试改动**（逐文件 before/after 见 `sha-before-after.json`）。
未启动任何轮次运行；6.2–6.5/Gate4/默认融合不动。

## 三个实施面

1. **绑定运行代次**（`generation-input-contract.md`）：`assess_two_rounds.py`
   = r3 只读基线的适配副本。兼容默认 = r3 原行为；生成模式必须显式给
   run-dir/round/anchor/manifest（+可选 records/mapping 附件路径），
   验证顺序全部前置于评分：运行清单 SHA、轮标识与 93+30 分母、批准锚整条
   代码谱系逐项对磁盘（不同谱系=新锚，无豁免、不回写）、固定 gold、pre/post
   身份实值、Gate-0 解析指纹绑定；任何缺/错/异常 → 净化拒绝诊断+非零+无裁决。
   输出必须落空位。r3 工具对改后源码的拒绝保持正确（本目录
   `input-rejection.json` 即兼容模式对现行 answer.py `98328f7f…` 的实测拒绝演示）。
2. **规则与人工结论分离**（`manual-review-protocol.md`）：旧 `_MANUAL` 与
   neg-010"四条真条款不答替代关系"等语义裁决只在兼容模式生效；生成模式零继承
   （同题不同 SHA=不匹配→PENDING，绝不把历史 FAIL/PASS 套新输出）。新记录通道
   绑 round/qid/path+answer-runtime SHA+响应 SHA（公式固定）或显式 absent+审查人+
   已核项；错绑=拒绝非静默；PASS 仅解已审语义/载体缺口，不能救出处/数值/缺项/
   引用/覆盖等已证失败，也不能把"raw 对而 0 交付"算完成；HTTP 三态仍只认账本
   凭证。旧 22 待审清单按主 agent 勘误引用为 **12 fact+3 file-004+3 neg-002+
   1 neg-005/local+3 neg-008**（neg-007 三路原判 FAIL 保持；历史终判不改）。
3. **映射采集设计与接口**（`mapping-collection-design.md`）：本组未执行任何采集。
   依据更正：`unit_chunk_links JOIN source_units` 组合键、scope 走
   scope_units/scopes、`public.lightrag_doc_chunks` 仅来源核验；按存量行数
   （16783/12269/14557/1970）LIMIT 5000 分页 **9–10 条数据 SQL ≤20** 可证
   （守卫另列）；失败=整体作废非截断。评分侧 `typed_evidence_recall` 已实现并
   验证：只取展开前 discovery，零发现对非空期望=recall 0（枚举/精排/展开不反灌），
   缺映射 pending，空表/跨 workspace 拒绝，兼容模式不读。

## 验证结果（原始输出在本目录）

- 自有矩阵 **19/19**（`pytest-own-matrix.txt`）：必验 7 对场景全覆盖——
  新输出不继承旧人工 FAIL/未审 PENDING/绑定记录 PASS 生效；PASS 救不了已证错、
  真实引用仍通过；绑错 runtime SHA/轮/响应均拒绝且无裁决；manifest/gold/锚/
  身份四类输入错误全部诊断落盘非零且无裁决、干净代次可评满 123 行；
  HTTP 实发按凭证 1/0 分列；映射与 typed recall 三态；反例行为优先、分母/决定性/
  掩码规则不变。全部为**合成 fixture+已存真实工件副本**，新实际请求 0。
- **35 项历史冻结矩阵字节未动**，经 `ENV_RAG_ASSESSMENT_SCRIPT` 指向新副本在
  兼容模式复跑 **35/35**（`pytest-frozen35-compat.txt`）。
- r3 自测 13 项对新副本 **12/13**，失败项与已备案细标签同一；对照原 r3 脚本
  本轮同样 12/13（`pytest-r3-selftest-original.txt`）——判罚不变、未改旧目录。
- 生产源码未改 → 按交接不重跑 526 全套。strict/diff/ruff（check+format）净
  （`quality-commands.txt`）。敏感扫描残留 0（`sensitive-scan.json`）。

## 就绪状态与下一组选择

`run-readiness-checklist.md`：评分器就绪；人工审查通道就绪、人员/流程待主 agent
指定；映射采集=提案待批准；**新正式配置锚=待主 agent 建**（绑定已验收改后谱系）；
两轮额度=待用户确认（kw≤164/emb≤656/Qdrant≤1312/Neo4j≤1640/PG 每腿 1024 共用
累计信封·整批≤251904/精排≤82/答案≤36+6；提案非授权、单价未测不填）；每轮必须
独立 report-dir（`inputs/local` 无轮标识，评分器按 run_dir+round 绑定）。
通过后由主 agent 决定：正式两轮评测交接，或低成本失败报告收尾（不强行切融合）。
