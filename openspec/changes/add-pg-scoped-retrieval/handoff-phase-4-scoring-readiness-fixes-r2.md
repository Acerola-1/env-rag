# 评分准备 r2 剩余 R1–R4 衔接

上一轮17/17、35/35、自有21/21通过保持。不是返工四组主体，也不是生产改进；只修主agent review-r2指出的调用衔接。新副本放 **reports/pg-retrieval/phase-4-scoring-readiness-r3/**。0网络/DB/模型/探测；源码/gold/.env/真实锚/所有旧目录/冻结字节不动；before SHA先捕获，PYTHONDONTWRITEBYTECODE=1，输出固定新目录不回写。

先确认红相：`phase-4-scoring-readiness-review-r2/test_scoring_review_r2.py` 10项（8F/2P）。补后ENV_RAG_SCORING_READINESS_SCRIPT指新副本，矩阵不能改；上轮17与历史35也必须原样通过。

## R1 硬失败先于“任何”人工状态（最小接缝）

生成模式下，将已证实的正例硬失败归纳置于所有manual分支及无record分支之前，不能仅在PASS时调用。partial/伪引用等即便没记录或记录PENDING，也要FAIL；保留真实片段、诊断和人工记录，不以未审身份软化。

真正完整且独立引用成立但语义未审的合成仍PENDING；完整、具名审义通过才可PASS。正例硬失败规则不套到反例，各反例继续行为合同；Round1兼容历史不变。

自有非冻结`test_new_output_unaudited_semantic_rows_stay_pending`使用实际partial作为PENDING正例，允许**强化**该行断言为FAIL，另保留/新增真正complete而未审的PENDING正例。不是改gold、不是削弱断言；本轮reviewer正例已覆盖后者。已通过的人工PASS硬失败拒绝、载体五项、零交付、错绑定等不动。

## R2 保留typed identity直到评分入口

`_fusion_segments`不能只复制doc字段后要求下游访问被丢掉的unit_id/scope_id。保留上游真实发布的unit_id/table_id/scope_id与归属依据、citation/status等需要的原始字段；不从名称猜ID，不将doc目标升格unit。

typed命中用workspace/doc/snapshot/unit组合归属；table按真实table↔unit身份，scope按映射成员且匹配所属doc/workspace，不因同名scope或另一workspace命中。本轮fixture均标constructed，不冒充现场。

真实chunk映射/固定分母/未映射null及零发现不反灌保持，禁止为了让测试通过把所有typed目标视为命中。正式main两类正例（table_unit/scope）必须能被读入且命中，外workspace负例保持0或明确拒绝混源。

## R3 每次失败独立诊断

owning catch不能因目录里有上一条input-rejection就跳过本次写盘。用本次调用局部状态/返回的诊断路径去重，或只在catch统一写一次。第二次失败必须有第二份包含其真实原因的新诊断，第一份字节不变。

仍保持全流程普通异常净化/非零/无裁决、成功原子发布、拒绝覆盖旧输出。目标父目录的创建/诊断存放由本次输出合同明确处理，不为失败无诊断提供理由；不改历史文件。

## R4 真工件/批准锚先验必填再比值

生成模式实际answer结果必须有合法qid/workspace并与本题/锚相符；只有明确failure/无results腿可以按既有失败/absent语义处理。不要用“字段不存在就不比较”给成功结果豁免。

frozen_identity.eight_table_counts必须是完整八表对应结构（8项合法计数），空/缺/畸形即输入拒绝，再比真实pre/post计数。其它已验的身份与谱系检验保持。

裸typed接口测试的最小数据不是正式answer工件：可在owning新代合同校验时区分，不为此修改17项冻结输入/断言。需要补充合法metadata的非冻结fixture可补字段，不能把缺字段负例改成正例。

## 验证与交付

10新冻结+17旧评审+35历史冻结；自有矩阵只做上述明确强化/合法fixture补充，不删弱断言。备案r3自测12/13细标签保持，不改旧目录，不重复526。

交付新副本/四处衔接对照/原始测试结果/工作面ruff-format/strict/diff/敏感扫描/before-after/保护清单复核，manifest最后写。保持上一代scorer等SHA，声明所有证据为fixture或既存工件副本、0新请求。

停止点仍是主agent评分准备复审。不要建立真实正式锚、问额度、执行123/246腿或改变默认融合；6.2–6.5/Gate4不勾。完整衔接通过后才安排正式两轮。
