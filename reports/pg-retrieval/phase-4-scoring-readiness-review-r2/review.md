# 评分准备 r2 复审（2026-10-09）

**尚未通过，付费两轮继续暂停。** 上轮17项修复独立复跑17/17，历史35/35、自有21/21，均保持。没有撤回已通过部分；本轮只确认其余调用衔接。

新增10项矩阵：**8失败、2正例通过**，见pytest-independent-r2.txt及test_scoring_review_r2.py。来源全为合成终态/既存工件副本，0真实服务/DB请求、0写库、0生产改动；不重复526工程全套。31份选定保护清单1266条及6项来源锚零漂移，提交before/after登记亦与磁盘一致；不冒充全库1402项独立核验。

## R1 硬失败仍依赖人工PASS分支

`_hard_positive_failure`只在`finalize_positive`的manual.verdict==PASS时被调用。没有记录或人工PENDING时，明确partial的syn-002/pg仍终判PENDING；完整声明但伪quote已被独立拒收，也仍PENDING。它们是已证实FAIL，不是“语义尚未审”。现有提交测试`test_new_output_unaudited_semantic_rows_stay_pending`还把真实partial当待审正例。

修复只需让生成模式的已证实硬失败先于所有人工分支与无记录分支生效。真正complete且引用成立、尚未人工审义的合成仍PENDING（本轮正例通过）；完整且具名语义记录通过仍可PASS。反例按既定行为合同，不能套正例“非complete一律错”的规则；兼容模式历史结论不改。

## R2 typed unit/scope在读取阶段被丢弃

新的匹配器会访问x.unit_id和x.scope_id，但`_fusion_segments`复制typed目标时只留下target_type/doc_id/workspace/discovery。这两字段根本到不了匹配器。正式main模式下，已登记清单的table_unit发现与已映射scope发现都被误记0；这不是缺映射，是读取时丢掉了已有身份。

保持原始typed identity（unit/table/scope及必要的归属证据），全组合键核对，不能只修下游匹配。跨workspace目标不命中是本轮另一正例，修复后须保持；scope也须匹配所属doc/workspace，不能同scope_id跨文档背书。chunk路径、固定分母与pending规则已通过，不返工。

## R3 已有诊断使下一次拒绝失去记录

`_write_rejection_unique`本身能编序号，但owning catch用`if not any(rej_dir.glob("input-rejection*.json"))`决定是否调用。一次坏answer JSON拒绝后，同目录下一次错误记录SHA拒绝不会生成自己的诊断，旧文件不能代表第二次错误。

每次调用都必须独立落本次诊断；如本次前置验证已写过，可用本次局部状态避免重复写，不能检查目录是否曾存在任何诊断来跳过。老诊断不覆盖，新诊断含当前真实原因；所有失败都无裁决。

## R4 必填身份缺失仍被当可选

`_bind_leg_identity`以`got_q is not None`为条件比较，删除实际answer结果的query_id后仍按目录题号评分。锚里删除frozen_identity.eight_table_counts，则`if eight`跳过对锚计数核验，仍出裁决。上轮已验“值错误会拒绝”，本轮确认“删字段也应拒绝”没有完全闭合。

生成模式的真实answer结果须先校验必填题/工作区身份；批准锚冻结计数须结构完整8项，再比实值。合法失败腿无results的情况仍可保持明确failure/absent，不能从错误工件补答案。裸typed API fixture不等同正式答题工件，区别应在owning合同验证，不改冻矩阵伪造字段。

## 范围与下一步

只按handoff-phase-4-scoring-readiness-fixes-r2.md在新scoring-readiness-r3副本闭合R1–R4。源码、真实锚、gold、历史目录和两轮冻结35/17不动；新10项冻结不动。已有待审/召回/诊断设计保持，不能扩大为生产检索改造。6.2–6.5/Gate4/默认路径均不动，不问网络额度或启动任何批次。
