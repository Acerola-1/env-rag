# Phase 4 pilot-r1 验收（2026-10-08）

**预算保护与已到达的发现链路验收通过；9腿端到端试跑未完成。** 6.1/Gate3保持，6.2未勾选。Reviewer核对工件，0新增真实请求/写库，未重跑已验收代码或测试。

31项manifest全部匹配；pre/post来源、catalog/search、gold、env、八表计数逐字段一致，当前源码与锚一致。9腿每腿PG issued=24，均有budget_failure；15条PG拒绝未越额转发。

实际local凭证：keyword3成功、embedding8成功、Qdrant8成功、Neo4j15成功；3×10候选全文工件的workspace/verified/content SHA核对通过。r1没有精排或答案模型实发，**不能把发现成功称为整个端到端链路成功，也不能核验尚无对象的答案语义**。

根因确认：per_question.pg=24是主agent交接设定偏低。现行ledger在整腿只有一次begin/end，发现和答案累计共享该信封；local还保守双计PG组+SQL。编译材料“two envelopes”文案不会重置运行时额度，432整批上限也无法绕过单腿24。并非执行agent擅自扩批或服务故障。

账本说明更正：r1 reserved_total.answer_llm=1、issued_total.answer_llm=0。报告中“预留==实发”总括不适用于答案；PG/keyword/embedding/Qdrant/Neo4j相等。预算增量捕获工作正常，无失败腿误标complete。原r1报告不改，差异在本复审记录。

决定：配置文件层面标定PG，不重构实现。先PG-only3腿（付费服务cap0、PG每腿1024/总3072），验证全段只读实际量；无预算/入口错误、到达答案阶段且最大PG累计≤512时，执行同范围9腿（PG每腿1024/总9216，其它服务原上限保持）。1024是有限标定护栏，并非测量结论。两阶段不同目录、不同预算文件；A不满足门槛就停，B仅一次。完整246腿不执行。

执行交接：[handoff-phase-4-6.2-pilot-r2.md](/Users/acerola/Dev/Python/RAG/env-rag-final/openspec/changes/add-pg-scoped-retrieval/handoff-phase-4-6.2-pilot-r2.md)。两份预算均经零后端dry-run；源码/config/gold/历史未改。
