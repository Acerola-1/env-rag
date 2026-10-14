# workspace 权限独立验收

## Verdict

**整体验收不通过，基础部署、正文迁移和已抽查授权路径通过。** 三次本地提交确实存在，审查范围为 `1c73eec3..af29ae36`。未修改实现、原始验收报告、授权配置或知识库数据；本轮仅增加此独立报告。正常浏览器查询新增了一条当前示例用户的私有检索记录。

本报告区分真实接口／数据库读取、实际浏览器操作和离线反例。离线反例证明实现的确定性错误，不当作真实服务成功验收。未新增答案 LLM、embedding 或 rerank 请求，也未重跑入库、重启或撤回操作。

## Verified

- Knowledge API 8099、air 9622、water 9623 在运行；coastal 实例也存在。air／water 的三个后端有效命名空间均与实例 workspace 一致，当前两实例镜像 digest 相同。digest 见 live-readonly.json。
- 现场 8 个未认证／无权／未知库反例、3 个他人记录访问和 4 个直接实例查询／管理访问均按预期拒绝。此抽查支持基础授权有效，不证明所有未覆盖路径都安全。
- 真实 PG：default 221 文档／5709 chunks；air 63 文档／1949 chunks；water **159** 文档／3765 chunks（158 领域文档加 1 共用样本）。air／water 的 processed 分别为 63／159，无 failed 状态。
- 对目标两库全部 5714 个 chunk 与 default 同 ID 行联合比较：不存在 default 中缺失的 ID，正文、tokens、heading、sidecar 差异均为 0；去重后 5709 个 chunk。这比原报告只复现一份文件的 4 个 chunk 更广，但只证明这些字段的当前相等，不证明旧库从未被改写。
- 旧 default、air、water、coastal 均有 active 目录／搜索构建；已在真实网页以 dual-reader 登录并执行水资料查询。
- Python 612 项在普通沙箱通过，唯一失败是既有本机端口监听测试；该项在允许监听环境补验通过，合计 613 项。前端选择测试 6 项通过；Ruff／116 文件格式检查、Git diff 和本变更 OpenSpec strict 通过。
- UI 静态审计 0 findings，但现有 premium-ui 配置只覆盖旧 web/static，因此不把它作为新 access/static 无缺陷的证据。

## Findings

### F1 — P1: 第三库的有效凭据已经写进提交代码

位置：`scripts/wa_third_workspace.py:79-80`。

第三库 bootstrap 使用固定明文默认口令／bearer，而不是随机生成。独立请求直接使用**代码里的默认值**（不从本机凭据文件取该 token）访问 `/api/me`，返回 HTTP 200、身份为 coastal-reader；本机配置也仍使用该值。知道仓库代码的人即可获取第三库身份。这不符合凭据仅保存在本机忽略目录的合同。

修复：随机生成新凭据，并撤销／轮换已经公开的旧值；补验旧值 401、合法新值可用、无权主体不能读 coastal。仅改源码的 fallback 不会使现有凭据失效。本轮审查未执行凭据修改。

证据：extra-live.json。

### F2 — P1: 新网关丢掉已定位范围的 chunk，仍报告 complete

位置：`src/env_rag_final/access/gateway.py:276` 及 `merge_evidence()`。

现场请求：water-reader，PG 路线，`top_k=1`，问题“列出 GB18466-2005 表1的全部项目和限值”。响应 HTTP 200、status=complete；raw 候选已定位表1并给出 `chunk_ids=[...chunk-001]`，网关却只回读单数 `chunk_id`。最终证据仅有空的文档项和封面／前言 `chunk-000`，没有表1正文。显式 top-k 不得限制确认范围的合同在网关处失效。

无 chunk_id 的文档／表格候选还统一按 `(workspace, None)` 合并，多个文档／目标会互相折叠，并以空正文进入生成证据。网页默认 top-k=20 时可能碰巧召回表正文，不能掩盖此确定性丢失。

修复：传递并独立核验完整展开结果，读取所有范围成员及 chunk_ids；保留文档／条款／表格类型身份和结构化清单，按类型使用复合去重键；完成状态依据实际交付范围核对。用 top-k=1 的真实表／正文／多文档反例复验。

证据：water-query-top1.json、live-readonly.json；浏览器页面截图也显示文档空项。

### F3 — P1: 生成未校验当前来源，静默截断且错误升级完整性

位置：`src/env_rag_final/access/server.py:250-253`；`access/gateway.py:489-540`。

读取旧记录后仅校验用户／权限代次，不重查 source/catalog/search 是否仍 current；生成不检查 retrieval 的 stale／partial／ambiguous。每个 chunk 无条件截前 4000 字符，无完整证据预算或截断标记；graph 实体／关系也不进入生成上下文。引用验证只是回答包含 `[编号]` 且原始正文非空，不能证明回答有来源支持，甚至不能证明被引用的末尾已发送。

离线反例：输入 stale 的检索记录仍尝试一次模型请求；一份 4025 字符证据的末尾成员不在请求中，响应只要出现 `[0]` 就被标 complete。真实历史记录和 browser/operations 也有 ambiguous 检索被标成 complete 的生成。

修复：生成前后核验来源／权限与记录代次；stale 禁止生成；完整清单独立交付，整块／结构化投影预算与遗漏显式记录；按实际发送证据验证引用。模型生成成功状态与范围覆盖分开，不升级 coverage。

证据：offline-counterexamples.json。此反例使用离线 fake client，0 真实模型调用。

### F4 — P1: 切库后的旧生成响应可以覆盖新库界面

位置：`src/env_rag_final/access/static/app.js:245-265`。

查询处理有 `state.generation` 校验，但生成和历史记录加载没有。离线确定性复现：air 开始生成 → 切 water → water 开始生成 → air 的旧请求先返回。当前选择是 water、新生成仍 pending，页面可见区域却显示旧 air 回答。同类问题可影响退出／身份切换后的结果与记录展示。

修复：每个异步流程绑定用户、workspace、record ID 和请求代次；切换／退出取消或忽略旧响应，success／error 分支都核验。增加慢请求、切库、退出／重新登录的浏览器测试。

证据：ui-race.json。它是离线应用代码时序反例，不冒充浏览器现场测试。

### F5 — P2: 合法 PDF 下载未实现成功链路

位置：`src/env_rag_final/access/server.py:317-324`；`access/static/app.js:227-233`。

网页证据只有“解析正文”链接，没有 PDF 入口。本人真实水资料记录的 chunk 文本返回 200；相同记录索引的 PDF 两次都返回 404。下载依赖 evidence.path，但 PG 接入没有保留 doc_name/file_path，LightRAG 接入同样没有补齐路径；即使 path 已含 `.pdf`，再次拼接后缀也可能无效。

原 browser/operations 没有成功 PDF 下载／哈希核对记录，权限矩阵里的 PDF 404 是对他人记录的负例，不能证明合法下载可用。

修复：从已授权 workspace 的真实文档行解析文件身份，验证白名单及文件 SHA，提供网页入口；分别验证正例下载 200／实际 PDF 字节和反例 404。

证据：extra-live.json、browser.png。

### F6 — P1: 旧数据保护比较漏掉实际向量／图谱命名空间

位置：`src/env_rag_final/access/snapshot.py:284-296`；`scripts/wa_report.py:241` 附近。

保护比较只传 `['default']`，但旧向量实际 workspace 为 `_`，旧 Neo4j label 为 `base`。比较会跳过 base，并在向量 default 键上比较两个 None。因此 JSON 离线反例把 base 节点数和三集合 `_` 点数全部改动后，compare 仍返回 ok=true、diffs=[]。

另外快照仅比较数量／少数 ID 摘要，没有正文、缓存返回值、向量值、完整 payload、实体属性和关系来源的内容哈希；env_rag 历史行只有计数，不能证明逐字段恢复。原 summary／tasks 已披露误删 default 的 5 条 corpus_runs 和 7 条 search_builds 历史行，因此“旧数据从未被碰过”与仓库报告冲突。不能据此推断当前旧数据一定损坏；但 0 差异结论的证明力不足。

修复：按真实后端映射比较，加入完整内容／属性哈希及分页结束核验；对已恢复历史行提交独立原值证据和逐字段差异。缺失的初始完整快照不能靠事后补造，相关历史不变性必须明确标为未证明。

证据：offline-counterexamples.json、原 summary.md 最后“已披露的操作事故”。

### F7 — P2: 通用新增库启动仍要求改脚本

位置：`scripts/wa_instances.sh:17`；`scripts/wa_instance_env.py` 的 PORTS。

启动端口只硬编码 air／water／coastal，其它注册库返回空端口，无法通过同一命令启动。第三库证明使用预先写在脚本里的 coastal，core SHA 列表又不包含启动脚本，因此只能证明这个预设名字无需改检索代码，不能证明任意新增库仅配置可达成。

修复：从注册表读取内部地址／发布端口、命名空间和运行目录；用未预置的新 ID 做配置扩展验收。启动前校验并固定镜像 digest；当前重建默认仍用 latest，与 design 的固定来源要求不符。

## Missing or overstated acceptance evidence

- “51 条越权用例全部被拒”不准确：矩阵共 51 条，含 16 个 200 和 1 个内部接口 405，拒绝为 34 条；这是含正例的混合矩阵。
- `_ok()` 对伪造角色接受 200，对未知 expected 默认返回 true，多个 expected 不校验 body。因此应强化验收脚本的失败判定，不能以退出码零直接勾全部条件。
- 6 个 CLI PG 任务报告当前确为 complete，但不能代替 Knowledge API／网页的范围传递验收（F2）。检索 sweep 判断 HTTP 200＋有证据，也不验证真实完整范围／独立原文支持。
- 当前持久记录和浏览器操作中只有 air 的真实答案生成。water、双库各一次来源独立核验的真实生成、实际一次融合生成、缓存命中及撤回后旧记录失效证据未找到。不能因为入库做了大量 merge-summary LLM 请求就算用户问答生成验收完成。
- 副本当前按数据库可以证明全量 chunk 字段相等；“同版本重跑能逐字节复现全部 chunk”的原 chunk-identity-proof 仅实测一份文件 4 个 chunk，应区分此实验与本轮广泛 SQL 核对。
- 17 个分片中 8 个按领域词规则分类，属于可解释的推断，并非逐个父文档关系已证明；现有清单可保留分类，但报告需标明证据类型与限度。
- Docker Compose 已披露未运行；静态模板还缺 `.env`／语料可用挂载、记录目录写权限、容器内实例地址和可发布的监听地址等，不能视为可直接运行的部署方案。

## Review coverage and boundaries

OCR 确定性工具列出 55 个 reviewable 文件，全部按 source/diff／证据内容审查，0 skipped；文件清单在 review-coverage.json。另人工核对被 OCR 默认排除的测试、Dockerfile、说明文档、JSONL 和真实网页。100% 仅指这 55 个文件的静态审查覆盖，不是全仓／全接口／全数据安全认证。

正式验收建议：先修 F1，再修完整证据与生成合同、切库响应、合法下载和保护比较；收紧验收脚本，补齐缺失现场证据后重新验收受影响项。现有部署和数据复用成果可以保留，无需为此重跑全量入库或全部模型请求。
