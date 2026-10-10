# 新代评分输入合同（r2：assess_two_rounds.py 生成绑定模式）

命令形状不变：

```
uv run python reports/pg-retrieval/phase-4-scoring-readiness-r2/assess_two_rounds.py \
  --run-dir <该轮 report-dir> --round <N> --anchor <该谱系批准锚> \
  --manifest <运行清单> [--records <人工记录>] [--mapping <映射manifest>] --out <空位输出>
```

不带 `--run-dir` = Round-1 兼容模式（与已验收 r3 行为一致；35 项冻结与上一代
兼容路径保持原输入口径）。

## 生成前统一结构/身份核验（任何失败=净化诊断+非零+无裁决）

1. **运行目录与清单**：清单逐条 SHA 对磁盘；**实际消费的每个文件**（terminal、
   每题 answer/fusion 运行时、local 输入、发现回执、inputs 全量）必须被清单绑定——
   清单遍历不等于消费覆盖。
2. **轮与分母**：终端 `round==N`；93+30 且为固定 gold 31×3+10×3 的**唯一键**矩阵，
   category/is_counter 逐行匹配。
3. **批准锚**：该谱系自己的锚。`code_anchors` 六必需键与 `evaluation_code_anchors`
   必需键先结构后 SHA；删键拒绝；锚在运行中绝不回写。兼容旧代字段无豁免。
4. **前后身份**：source/catalog run+snapshot/search/gold/env_sha/counts 逐字段实值；
   counts 对锚冻结八计数；env 前后相等并与锚 env 一致；`matches_frozen` 不替代实值。
5. **题绑**：消费工件的 query_id/workspace 与 key 一致（拿别题首条结果=拒绝）。
6. **附件**：人工记录与映射为显式路径附件；锚/记录/映射自身按 CLI 绑定记录 SHA，
   不参与运行清单覆盖检查。

## 评分面

- 规则（投影/条款号+完整跨度/身份文件名/反例行为/决定性优先/分母/掩码/expected 仅事后）
  与 r3 同源零改动；`_MANUAL` 与历史语义分支**只**在兼容模式生效。
- 生成模式硬失败先于人工层归纳（budget/runtime/覆盖不完/0 交付/集合违规/引用失败），
  PASS 仅解除具名已核的语义/载体缺口；错轮/错 SHA/错响应/冲突键=拒绝+诊断。
- typed evidence recall 按 (workspace,doc,snapshot,unit) 组合身份；未解析存在则指标
  null(pending)，分母不缩；零发现=0 不反灌。
- 唯一拒绝出口覆盖装载→发布全程；输出原子发布、已存在拒覆盖；诊断不重名不覆盖。
