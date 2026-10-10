# 改进组1 最小补正 r3：F3-a 表题衔接 — 执行报告

交接：`handoff-phase-4-improvement-1-fixes-r2.md`。仅修 F3-a 一处归属衔接，F1/F2/F4 与已验收部分零返工。全程 0 网络 / 0 数据库 / 0 模型 / 0 写库 / 0 探测 / 0 真实评测；gold/.env/配置锚/评分 r1-r3/历史代次/全部冻结测试未动。

## 一句话结论

新增冻结验收 3 项从 **2 失败/1 正例 → 3/3**；r2 的 9 项冻结、自有 18 项（+2 新增正负验证）、owning 7 项（+1 新增）全绿；全工程 **479 passed**；35 项评分冻结矩阵对新代码复跑通过；改动只有 `prose_enum.py` 一个边界查询函数与两个自有测试文件（expand/answer SHA 不变）。

## F3-a 根因与修复

**根因**：归属判定只看标记的**上一行**。"本条限值见下表：" → 表题（"表 1" / "## 表 1 限值"）→ `<table>` 表体：表题自己因前导冒号句被正确豁免（attributed），但表体的前一非空行变成了**表题本身**——不以冒号结尾 → 重新判 independent → 硬切。条款体只剩"引言+表题"两行，总汞/0.05/每日监测一次全部丢失，且无 ambiguity note（表题不是冒号句）→ 仍发布 complete。经 run_answer 完整入口复现两种形态。

**修复**（`_intro_line_before`，替代只看上一行的查询）：结构标记的宣告行沿**同一表对象自身的表题行**（`^[ \t]*#{0,4}[ \t]*(?:附\s?表|[表图])[ \t]*[0-9０-９]`：表 N/附图 N/表 N（续）/# 表 N 限值）向上穿透后再判定归属；**有界**：穿透只越过空行与表题行，遇到任何其他行（条款句子、条款头、上一张表的收尾行、页眉、括注副题）立即停止——已确认的归属因此绝不会跨入下一独立条款或后续无关表对象。判定三分（attributed/ambiguous/independent）与 F3 其余语义不动，分隔协议/全文核验/模型声明政策/提示未触碰；无题号、doc_id、"表 1"或固定长度硬编码。

## 正反例矩阵（全部实测）

| 形态 | 入口（run_answer）结果 | 函数级边界 |
|---|---|---|
| 引言+「表 1」+表体+补充要求+4.2 | **complete**，4.1 全文含 总汞/0.05/每日监测一次，`citation_reverified=True`，0 问题 | cuts=[]（表题与表体同一对象豁免） |
| 引言+「## 表 1 限值」同构 | **complete**，同上 | cuts=[] |
| 独立成句+「表 1」+附表（矩阵正例） | **complete**，4.1 恰为短句 "4.1 本条要求已独立成句。"，reverified=True | cuts=[24,28]（表题+表体 clean 切，无 note） |
| 归属不跨界负例（4.1 attributed 表 + 4.2 独立句 + 其后「表 9」附表） | **complete**：4.1 保留自己的表；4.2 止于自身短句，「乙」不出现在任何条款 | cuts=[114,118]（4.2 的表题与表体照旧独立切；穿透在 4.2 句子处停止） |

已确认边界零回退（真实数据 pass-through + 自有回放）：GB8978 4.3.4 **53 字**、GB18466 4.1.2 **128 字**、GB3095 4.2 **48 字** 原句保持、表尾仍排除、五题一对一 missing/extra 全空——`owning-replay`（r2 代）用例与本轮 r3 新用例同绿。

## 验收数字

| 检查面 | 结果 |
|---|---|
| 新冻结 `phase-4-improvement-1-review-r2/`（先复现 2 失败） | **3/3**（零删改/xfail/弱化） |
| 旧冻结 `phase-4-improvement-1-review/` | 9/9 |
| 自有 `test_phase4_improvement1_prose_integrity.py` | 18/18（原 17 语义保持 + 表题穿透正负新增） |
| 自有 `test_phase4_improvement1r2_owning_replay.py` | 7/7（+不跨界 owning 用例） |
| 全工程 `pytest tests` | **479 passed**（一次，最终） |
| 评分冻结矩阵（ENV→r3 评分器） | **35/35** 对新代码 |
| 评分自测 | r1 6/6、r2 10/10、r3 **12/13**（同一细类标签断言，整题 FAIL 不变，非阻断，未返工旧评分目录） |
| 真实数据 owning pass-through（r2 用例复跑） | complete、4 项、4.3.4=53 字、0 模型 |
| Ruff | check 全绿；format 全库 clean（87 文件） |
| OpenSpec strict / `git diff --check` | valid / 干净 |
| 敏感扫描 | 本组文件+r3 目录 0 命中 |
| 历史清单复算 | 全库所有 manifest **零漂移**；gold SHA=1bf130077c21583a… 匹配；锚未动；.env 未读 |

## 源码 SHA（`sha-after-r3.json`）

prose_enum 3d922e20…→**ad98184e…**（本轮唯一源文件改动）；expand d328e76b…、answer fef50024… **不变**；自有测试两文件更新。

## 交付物（`phase-4-improvement-1-r3/`）

`baseline-shas-r3.json`（r2 代次基线）｜`sha-after-r3.json`｜`report-r3.md`｜`f3a-evidence.json`（4 入口案例+函数级边界决策快照）｜`generate_f3a_evidence.py`（离线复算脚本）｜`owning-entry/<case>/answer-runtime-latest.json`（4 份发布态终报，标注 构造读取注入+离线answer入口回放）｜`improvement-1-r3-manifest.json`。r1（`phase-4-improvement-1/`）与 r2（`phase-4-improvement-1-r2/`）提交及两轮 review 目录原样保留。

## 边界与停止点

不启动第二轮；未勾 6.2/6.3/Gate4；未切默认融合；prose-002 旧 trace 漏记仅继续挂账观察。提交后停主 agent：本组通过与否由主 agent 决定下一步安排。
