# 仅补正5.4 R1–R4，集中验证后停检查点

主agent首轮未通过，报告phase-3-rerank-review/review.md。原295项通过，独立tests/test_rerank_review_r1.py的14反例失败。5.3与以前Gate结论保持，不进入5.5/5.6，不重跑检索/keyword/embedding/local整轮。

## R1 输入可验证且集合完整

- 当前生产身份与回放输入来源身份必须一致；核验source/catalog/search/workspace/query_id/question。拒绝不符/缺失或损坏的回放，不能仅“当前库冻结”就相信任意文件。
- 本次候选以(workspace,chunk_id)只读回读正式PG原文/full_doc_id，逐条核实verified、请求workspace、doc归属、原文SHA/长度和来源约束。记录回放字节指纹与真实回读证据，不能仅重新算一个SHA就信任篡改后的文本；新测试也覆盖“篡改正文并更新SHA”仍不等于真实来源。
- 缺正文/缺源/归属冲突不得静默过滤余下集合后status=ok；显式拒绝或degraded，保存全部候选及未发送集合。发送完整保留合并集合，候选数/字符或token预算与接口限制均记清，任何限制不得静默截断再称完整成功。
- 所有条目仍经过同一个联合请求，不分两路精排拼接。真实请求配置不换端点/模型，不修改.env/gold/目录/索引。

## R2 成功与回退同一份完整来源

- 输出独立保留typed doc/scope/table目标与原citation、snapshot、成员/归属依据。它们不作为伪chunk送给rerank。
- ordered无论success/HTTP失败/响应非法等路径均保留workspace/chunk/doc/SHA、全部paths与表片/scope/版本关联；失败仅分数为None、顺序为原融合顺序，不能丢来源。
- 使用首次历史回放时，要按现有已验收目录与rev4融合映射补齐真实表片路径（原fact-002的两片ID不同）。源正文回读正确不等于历史路径元数据齐全。保存补全依据，不猜ID/locator。

## R3 完整失败边界与实际每题凭证

- 继承5.3最终统一前置出口：gold/fused读取、JSON/结构、unknown id、配置、SHA与输入合同拒绝均有原类型/原因、明确零服务调用、无finished_at。所有普通Exception都不能漏出无报告路径；不捕获BaseException。检查请求配置也包含rerank API key是否配置，不发Bearer None。
- 一旦工作窗口开始，读取/处理/回读等失败均执行post身份核验，保留当前题部分结果/真正发生的SQL与服务调用、原错误和后置失败/漂移。新题先重置账本；HTTP返回就发布当前题凭证，不等成功返回out才保留。
- 超大整数/异常结构等分数验证安全降级，禁止math.isfinite数值转换溢出逃出响应验证；保留实际HTTP凭证、验证拒绝原因、无伪分数的完整原序回退。

## R4 原始证据与净化

- 保存足够复验的实际请求（query/model/有序documents或不可变正文引用与逐项SHA）和净化后的原始响应index/score/meta，独立重推排序和身份映射；id+count不能替代实际响应分数。
- HTTP错误正文、非JSON正文、异常消息与任意响应字段均经过凭据净化再落盘。已配置API key/password/token与Authorization等敏感字段绝不进入公开报告，失败证据依然保留状态/错误类型与非敏感原因。
- 每题模型参数、真实payload预算、字符数/输入条数、调用耗时与skip/degraded/验证状态明确。HTTP200只代表传输成功，非法响应不能标精排成功。
- 修复CLI格式，两次运行200/404历史保留；manifest在最终修改后生成，检查结论与checkout一致。

## 一次完整自查与必要实证

1. 先复现冻结14反例，一次集中修复四组；保留原16项矩阵语义与所有旧Gate断言。旧测试用sha-0等占位SHA而新合同要真实SHA，可把fixture改为可复算正文SHA与明确的fake只读来源校验，并把断言改为比较该真实fixture SHA；这是补全输入，不得删掉顺序/来源保留断言或绕开正式校验路径。
2. 补上同内容两版本、两路重复路径、篡改正文且更新SHA、每题post失败/工作错误并存的入口测试；来源回读应有fake明确PG行，不能因测试网络连接被拒而“碰巧”通过污染输入零调用反例。
3. 全套/独立反例/Ruff/format/OpenSpec strict/diff/凭据扫描通过后，只做一次必要真实reranker调用（fact-002固定10候选），此前只读核实当前源身份/全文/路径，保存净化原始请求/响应与独立index/score核验。不再运行keyword/embedding/local。
4. 历史成功响应已未落盘，不能事后伪造或用ordered冒充原响应。新调用单独记录为修复后的新代次；若真实调用失败，保留诚实失败并停检查点，不通过换密钥/模型迎合。
5. 交付report、manifest、输入/原始响应/排序与失败终态证据；停5.4待主agent，不进入展开/生成/Gate3。
