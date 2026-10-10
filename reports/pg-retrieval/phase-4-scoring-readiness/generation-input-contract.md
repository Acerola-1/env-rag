# 新代评分输入合同（assess_two_rounds.py 生成绑定模式）

## 命令形状（全部显式，无隐式旧代搜索）

```
uv run python reports/pg-retrieval/phase-4-scoring-readiness/assess_two_rounds.py \
  --run-dir <该轮 report-dir> --round <N> --anchor <该谱系批准锚> \
  --manifest <运行清单文件名> [--records <人工记录>] [--mapping <映射manifest>] \
  --out <新目录内裁决文件（默认 <run-dir>/adjudication-r{N}.json，必须不存在）>
```

不带 `--run-dir` = Round-1 兼容模式（与已验收 r3 行为一致；35 项冻结矩阵经
`ENV_RAG_ASSESSMENT_SCRIPT` 指向本副本复跑全过）。

## 生成前强制核验（任何评分动作之前；任一失败→净化 `input-rejection.json`+非零+无裁决）

| 绑定 | 内容 | 失败语义 |
|---|---|---|
| 运行目录+清单 | `--manifest` 逐条 SHA 复核（缺/错/解析异常全拒） | 拒绝 |
| 轮标识 | 终端 `round==N`；93 正例+30 反例分母核对 | 拒绝 |
| 批准锚 | 该谱系自己的锚（`code_anchors`+`evaluation_code_anchors` 逐项对磁盘）；**不同谱系必须新锚，不加豁免，验证时绝不回写** | 拒绝（兼容模式实测演示：`input-rejection.json`） |
| 固定 gold | SHA `1bf13007…`；锚内 gold 登记一致 | 拒绝 |
| pre/post 身份 | 结构完整+与锚一致+前后相等+matches_frozen+无 failure+finished_at | 拒绝 |
| 解析证据 | Gate-0 `parsed_blocks_tables_bytes` 复算绑定（与 r3 同） | 拒绝 |
| 人工记录/映射 | 显式附件路径；schema/绑定校验（协议文档） | 拒绝 |
| 输出 | 目标文件必须不存在（空位才写） | SystemExit，不覆盖 |

## 规则面（两模式同一份，零改动）

集合投影、条款号+完整 raw 跨度回读、身份/文件名独立证据、反例行为优先、
决定性失败优先于细项 unknown、分母不缩、掩码 pending 细节、expected 仅事后
（从不路由）、统一拒绝边界与净化。兼容路径函数逐一保持 r3 语义（r3 自测
12/13 备案细标签差异不变、判罚不变）。

## 人工结论面（分离）

兼容模式：`_MANUAL`/neg-010 n==4 语义分支按历史原样生效。
生成模式：零继承——无记录=保留 PENDING/机械终判；记录通道与安全性
见 `manual-review-protocol.md`。旧 22 条清单口径按主 agent 勘误订正为
**12 fact + 3 file-enum-004 + 3 neg-002 + 1 neg-005/local + 3 neg-008**
（引用自 `phase-4-finalization-offline-review/review.md` 勘误 2；历史终判不改）。

## 本组场景证据分类

`test_scoring_readiness.py` 19 项全部为**合成 fixture + 已存真实工件副本**
（PG 实况批 terminal/inputs、round-1 腿终态拷贝）；**新真实请求 0**。
