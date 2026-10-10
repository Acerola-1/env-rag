# 离线评分增量补正 R1–R3（主 agent，2026-10-08）

可直接执行，无需新增授权。**0网络/模型/embedding/rerank/数据库请求、0写库、0探测。** 输出新代次`reports/pg-retrieval/phase-4-round-1-assessment-r3/`，原r1/r2评分与所有原运行工件保持字节不变。仅离线脚本、必要测试与报告；不改src/工程tests/.env/gold/锚/历史，不启动第二轮，不勾6.2/6.3/Gate4。

33项旧评分测试独立通过。上轮17项冻结与本轮新增18项冻结不能删改/xfail/弱化；本轮14失败、4正例保持。指定新脚本即可复验：

```bash
ENV_RAG_ASSESSMENT_SCRIPT="$PWD/reports/pg-retrieval/phase-4-round-1-assessment-r3/assess_round1.py" \
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -q \
  reports/pg-retrieval/phase-4-round-1-assessment-review/test_assessment_review_r1.py \
  reports/pg-retrieval/phase-4-round-1-assessment-review-r2/test_assessment_review_r2.py
```

保持现有测试接口，新增`finalize_counter`接口亦供本轮矩阵使用。旧自有测试读取其历史adjudication本身不能证明新版本裁决；新代次的必要测试要调用新代码/新工件。不要重跑454项工程验收。

## R1 完整声明支持与身份

1. 两种prose gold形状统一处理：dict中的clause与字符串开头的编号都要约束item.clause；无编号的名称投影不要硬造编号。正确内容配9.9.9必须FAIL。
2. 对table/prose等有声明doc_id的item，与citation.doc_id及受保护来源核对一致，不允许OR范围条件掩盖冲突。不得改旧工件做修复。
3. 独立核对**所交付text**是否被声明的原始unit跨度/按声明顺序的跨unit segments完整支持，不能只验证短quote。版本装饰、允许的提取结构应有明确可审规则，不能凭gold子串或词集把附加虚假声明放过；不得用第二次LLM验证。
4. 不要求text等于quote（合法真实quote有120字截断，原始声明跨度可能支持全文）。真实prose-enum-001/002正例必须保持；prose-enum-003的4.3.4 20,636字，现有segments顺序无法支持全文，必须记录位置/来源问题，不能保持PASS，也不能自行重排旧citation去掩盖问题。重新审视真实长正文，漏/多项和身份问题照常分列。

## R2 整题行为 vs 局部安全属性

取消`expected in (missing,partial,ambiguous,isolation)`的宽泛放行。先检查运行失败/工件缺失，再按每个冻结行为的具体证据作整题判定。单独记录`no_false_complete`、预算闸门有效、未见外workspace等局部观测，不把它们代替整题通过。

主agent本轮已经作出以下裁决，直接落实到canonical rows和报告（勿改gold）：

- neg-001/006 PG/fusion：显式missing且无版本替代，保持PASS；local仅partial/条件不足，未明确回答missing，整题FAIL，局部无乱答观测保留。
- neg-002：三路PENDING隔离合同（仅本腿观测，无对抗生产证据），观察不升格PASS。
- neg-003及neg-004 PG/fusion：已证真行为保持PASS；neg-004 local、neg-005 PG/fusion保持FAIL；neg-005 local现有待审保持。
- neg-007：三路partial不等于冻结ambiguous，整题FAIL，保守拒绝与未编造表号仍分列。
- neg-008：三路PENDING该成员/字符展开预算反例，PG额度闸门的成功控制独立记录，不能标整题PASS。
- neg-009：三路零交付，未回答内容可检索，整题FAIL；不用这一结果推断内容丢失。
- neg-010：PG/local零交付整题FAIL；fusion四句原标准4.1来源真但不回答替代关系，主agent语义裁决FAIL。写人工理由和四条实际工件位置，不再留疑点待审。
- 任意runtime failure/no_answer_artifact：不能因为零交付被当作missing/ambiguous/isolation成功；错误/证据缺失与实际明确拒绝答复分开。

这一裁决区分行为合同与安全属性，不是退回6.1预算工程验收。保持18正例合成逐行FAIL及原始HTTP账本，分母仍93+30，汇总从新canonical rows生成。

## R3 拒绝边界闭合

- 后置identity必须存在、结构完整、与冻结及before一致；finished_at和matches_frozen布尔不能替代实际字段。缺post在评分前拒绝。
- main的输入验证、读、解析统一捕获普通异常：写净化input-rejection诊断、保留真实类型/原因、非零抛出，无可信adjudication发布。原金标失配、正常完整输入的正负例保持。无需捕获SystemExit/KeyboardInterrupt。
- 本轮不追加服务身份探测；所需核对只使用已冻结文件、原始解析产物和本地代码身份。维持原A4完整性规则，不以“目录存在”冒充内容已绑定。

## 交付

新脚本/必要正负例/新adjudication/报告/SHA manifest/敏感扫描；说明R1真实行变更、R2主agent裁决与局部控制的区别、R3拒绝诊断。复算原809+9+r2的4项清单仍全匹配，生产/冻结/gold/锚未变。旧通过内容不返工，35项冻结及必要自有测试通过后一次提交，停主agent复审。
