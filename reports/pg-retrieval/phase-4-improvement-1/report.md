# Phase4 独立改进组1交付：正文范围与完整引用（execution agent，2026-10-08）

范围与守卫：仅本组三个源码文件 + 一个新回归测试文件 + 本目录证据工件；**0 网络/模型/embedding/rerank/PG/Qdrant/Neo4j 请求、0 写库、0 健康探测、0 真实生成**；round-1 运行、评分 r1/r2/r3 目录、两轮冻结矩阵、gold、配置锚、.env 全部逐字节未动（809+9+4+4 清单复算全匹配、gold SHA 匹配）。第一轮已审基线 33/45/15 与 9/14/7 保持原样引用，未重算未补分。

## 变更文件（前/后 SHA 见 sha-after.json）

| 文件 | 前 | 后 |
|---|---|---|
| enumerate_/prose_enum.py | 84c28271… | 28e2b73a… |
| search/expand.py | d3deba9f… | 15422a8d… |
| answer.py | c017606c… | 0cd30bc3… |
| tests/test_phase4_improvement1_prose_integrity.py | （新增） | 14 项 |

直接依赖 enumerate_/__init__、catalog/*、config 未改。修复内容、真实调用路径诊断与边界依据见 `diagnosis.md`；关键三点：条款正文在行首表对象/纯表题/表型单元处硬截止（不再“末条到 EOF”）；跨单元 segments 按装配序声明并显式 `assembly_separator`；生成与独立回读双侧对**完整交付文本**做空白折叠回读，quote-only 模型路径与 C1 合同原样保留。全部一般化，无题号/doc_id/长度硬编码；未删 HTML 泛化（内嵌 `<sub>`/句中“表1”保留）。

## 验收结果

- 本组新测试 14/14（正负例+边界保持+requires_span+预算/空范围语义）；
- `pytest tests` 全套 **468 passed**（454 工程基线含各轮冻结 + 本组 14），一次通过，无删改/xfail/弱化；
- 两轮评审冻结矩阵以正式命令（ENV 指向已验收 r3 评分器）对**新生产代码** **35/35**；评分器历史自测 r1 6/6、r2 10/10；
- r3 自测 12/13：唯一差异为细类标签断言——新独立回读在更早阶段拒收篡改条目，整题 FAIL 判定不变（诊断 §4 如实记录，不返工已验收评分代次，等主 agent 裁决）；
- [离线正式入口回放]（replay-evidence.json）：prose-enum-003 四条 4.3.1–4.3.4 全文对 gold 覆盖、零表尾、独立回读零 problems、coverage complete；prose-002 4.1.2 由 4,008 字（含表2尾）收敛为 128 字正确句；prose-006 由 2,273 收敛为 48；prose-001/004 对照保持全部通过——原始失败与新回放分列，均标注为已存证据离线回放，非现场数据库采集；
- 篡改/错序/重复/漏段/坐标错位构造反例全部拒收且真实正例保持（非全拒）；
- Ruff（4 文件）All checks passed；`openspec validate add-pg-scoped-retrieval --strict` valid；`git diff --check` 干净；敏感扫描：见 manifest 下方说明；
- 跨代保护：已验收 r3 评分 main() 对 live answer.py SHA 漂移将按 A4 合同非零拒绝——**属预期，未给旧锚加豁免、未覆盖历史裁决**；任何真实评测待主 agent 审后另建代码/配置代次。
- 本组未跑 123/246 腿、未改 6.2/6.3/Gate4 状态、未切默认融合、未做任何 schema/目录/索引重建。

## reviewer 勘误（新台账，历史字段不改）

`errata.json`：round-1 历史将 neg-010/pg 记为“HTTP 未发出”；账本凭证实际 answer_llm 对该腿**实发 1 次（HTTP 200）后合同拒收致 model_failure**，整题 FAIL 结论不变。仅登记于此新代次台账。

工件：diagnosis.md、replay-evidence.json、errata.json、baseline-shas.json、sha-after.json、improvement-1-manifest.json（本目录 6 文件 SHA，不含 __pycache__）；凭据模式扫描 0 实质命中——replay-evidence 为 GB 标准条款正文与定位数据，全目录唯一字面命中是本报告中“DSN”一词的自指说明。

**停止点**：提交主 agent 工程复审；不自行扩批、不启动第二轮、不发布两轮增益或新真实质量汇总。
