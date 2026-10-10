# 改进组1工程复审（主 agent，2026-10-08）

**本轮工程验收未通过，仅补正F1–F4；已验收评分r3和历史基线保持。** 已知末条款吞表尾、segments相对坐标排序的问题确已修正，正常跨段正文与quote-only路径正例保持。Reviewer独立工程468项、评分冻结35项通过；提交14项包含在工程回归内。原809/评分9/4/4/本组6项清单均匹配。

新增9项冻结入口/验证测试：**7失败、2正例通过**。0网络、0数据库/模型调用、0写库；未改提交实现、旧工件、金标、锚或既有测试。原r3自测的细类标签变化不是本次阻断项：提前拒绝导致unsupported_declarations分支不触达，整题FAIL仍保持，历史目录应保留。

## F1 分隔符被当成可任意添加的来源（P1）

`prose_enum.verify_citations`和`answer._reverify_prose_items`直接读取citation.assembly_separator并join原文。复制合法跨段条目，把separator改为“停车场允许无条件排放污水。”并按此重建text；原始source没有这句，quote仍是真引句，**两侧都verified=True**。声明本应记录受约束的装配规则，不能给新增内容背书。

separator=7还会抛AttributeError，未按无效引用安全拒绝。应校验类型及来源/允许值，生成侧与实际装配间隙一致，独立侧只接受有依据的协议；不能只限制为任意字符串。

## F2 畸形数值跨度自动降为quote-only（P1）

两侧通过“char_start和char_end都为int”决定是否检查全文，条件不成立就按模型quote-only路径跳过。复制生成的regex条目，追加假尾句，再将char_start置None或字符串，或删除char_end，**两侧仍verified=True**。字段损坏不是模型路径的证据。

应区分真正没有数值跨度的合法模型接口与声明了却不完整/类型错误的数值引用，损坏时拒绝，不允许借类型变化跳过全文核验。新矩阵保留了真实quote-only模型路径正例，不能靠全拒模型过关。

## F3 行首table不必然是独立结构（P1）

新的hard-cut规则把所有行首table都截掉，没有证据区分独立附表与当前条款正文内的规范表。正式_expand_prose入口构造：

```
4.1 本条限值如下，表内规定属于本条：
<table ...>总汞 / 0.05</table>
本条补充要求：每日监测一次。
4.2 下一条要求。
```

当前只交付4.1的冒号前介绍，丢掉数值和补充要求，**coverage=complete**。保留sub标签/句中“表1”不能证明合法内嵌table得到保留。按原交接，结构归属需有依据；无法裁决可partial/ambiguous并显式说明，不能静默丢要求而complete。已确认GB8978的独立表尾应仍排除，不退回吞到EOF。

## F4 回放输入被金标答案筛选，且未验证完整answer入口（P2）

提交测试_replay从gold.expected_items生成requested_clauses，再传给_expand_prose。prose-enum-003的问题请求4.3节，输入却被金标提前限定为4.3.1–4.3.4。这能筛掉本应被发现的多项，不足以证明原请求的集合闭环。

gold.expected_items只用于输出后的判定；输入应来自原问题解析或原始请求trace。已有五题佐证的是expand+独立回读函数，未调用run_answer，因此不能据此证明最终coverage、发布引用和渲染已经闭合。需补零服务的owning answer回放，明确fake连接/身份采集证据，验证partial传播，不mock验证器恒True。

## 保持与交接

保留原已正确收敛的53字4.3.4、128字4.1.2、正常跨段/requires_span、旧冻结语义及模型C1合同。468项通过不是这四个具体反例的反证，也无需重新返工评分器或发付费请求。

交接：`handoff-phase-4-improvement-1-fixes-r1.md`。只修本组实现/必要回放与证据，先新9项冻结和本组相关检查，最后一次全工程回归。第二轮、6.2/6.3/Gate4及默认路径继续保持。
