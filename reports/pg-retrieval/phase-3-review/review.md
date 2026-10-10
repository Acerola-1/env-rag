# Phase 3 / 5.6 材料审查（2026-10-07）

**材料经主agent直接补正后可用于下一步验证；5.6/Gate3仍未完成，Phase4不进入。** 本轮0真实模型/embedding/rerank/数据库请求、0数据写入；只作离线证据核对、文档补正及一句系统提示一致性调整。不再要求执行agent为这批文档往返返工。

## 三项材料更正

1. **真实证据与fixture分列。** GB8978表1两物理片所有13条引用共享chunk-001；该chunk真实精排第1位、0.999273。最低分续片0.02来自fixture，不能称真实跨chunk低排名实测。完整真实物理片读取与低排名行为fixture各自保持已有验收。
2. **失败状态与退出码分列。** 连接/身份守卫/运行级异常终态后抛出，CLI非零；已经记录的model_failure/partial/ambiguous是业务结果，可正常返回、CLI退出0。历史503记录正是partial/model_failure且无run-level failure。不能以HTTP200、Answer OK或退出码0当答案成功。前份交接的措辞也在本轮更正。
3. **请求材料补全。** 原prep仅有系统提示和messages说明，没有完整请求或8条引用明细。现在syn-prep-syn004.json保存完整拟送messages、1934字user-content、1843字context与摘要；syn004-source-citations.json保存8条来源/完整scope_id/unit-relative跨度/逐字片段及raw摘要。离线重建采用正式提取与绑定函数，每条原始定位切片独立检查，context与历史503的SHA逐字一致。

引用明细来自原始blocks与既有unit_ids/order，不是新的生产运行：未重新查询per-unit chunk映射（仅保留历史scope层chunk集合），也未重新采集活体身份；正式执行仍必须走guard。已有GB3095 7.3原始块附带附录A，已如实标注，不手动剪上下文，不以成员读全证明章范围纯净。

## 提示与声明合同对齐

采用提交中建议的最小句子：正文claim连续逐字，不能改写/拼接/概括；表格按行绑定主体、平均时间、等级、数值、单位。除了该提示字符串，answer.py其余字节保持5.5已验收版本一致（删除新增串可复算回29e0aa29…）。未改变检索、引用、生成预算、覆盖或失败合同。

- 提示调整后回答专属**64 passed**，四份冻结未改；原383项是此前实现验收记录，文档/提示变动不重复全套测试。
- Ruff check/format、OpenSpec strict、diff、凭据扫描通过；旧5.5 manifest和所有历史runtime保留。
- 原51项台账中46项保持，5项是本轮明确修正的answer提示、report、checklist、prep、README；新加原始引用明细后当前52项台账全部重算并核验。阶段代码台账明确区分原实现SHA和本轮提示对齐SHA，不假称全部未变。

## Gate3裁决与下一步

现有阶段证据支持身份/版本合同、真实fact-002联合精排、完整成员读取、失败可见等实现能力；正式命令可复跑目前只完成文档/parser核对。真实成功合成仍未验证，**不勾5.6/Gate3，不进入Phase4**。

syn-004的应用槽是两版本，不能只看每版本有一条就认定问答正确。一次实际验证后必须由主agent检查声明确实回答问题的环境要素、与所选来源和版本一致、引用支持完整声明；HTTP200/coverage complete均不替代此项。

下一步仅执行一次有界syn-004正式answer验证（由主agent另行安排）：复用固定fusion/rerank，先检查最新身份与完整范围/引用和context摘要，再允许至多1次答案LLM；不新跑检索/embedding/rerank，不循环重试。失败照实保留并停止，原503历史不删除。请求材料已具备，但本轮未执行。

文件：phase-3/report.md、gate3-checklist.json、syn-prep-syn004.json、syn004-source-citations.json、phase-3-manifest.json；本目录submission-audit.json、answer-prompt-tests.txt与review-manifest.json。
