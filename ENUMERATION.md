# 直接提问：枚举增强入口

在 `/Users/acerola/Dev/Python/RAG/env-rag-final` 中运行。无需固定题号、历史回放报告或答案模型；只连接现有 PostgreSQL，读取已构建目录及原始解析产物。

## 先试这一条

```bash
.venv/bin/env-rag-final ask --query '列出 GB8978-1996 表1的全部项目及限值' --top-k 1
```

预期：`complete`，13行。候选预算1不会截断两片续表的完整读取。

## 三种清单与显式选择

```bash
# 文件：不指定年份，保留所有已登记版本
.venv/bin/env-rag-final ask --query '列出库内 GB3095 标准的全部文档及版本' --kind files

# 原标准＋修改单（归属从同快照目录读取，不伪造修改单自身编号）
.venv/bin/env-rag-final ask --query '库内有哪些 GB18466-2005 的文档（含修改单）？'

# 正文：标准、版本、范围也可以分开选
.venv/bin/env-rag-final ask --query '列出4.2的全部规定' --code GB3095 --version 2012

# 正文：题面无标准号时，用完整文件名明确选择
.venv/bin/env-rag-final ask --query '列出第3章的全部术语和定义' --document 'water-09_生态环境部_医疗机构水污染物排放标准_GB18466-2005.pdf'

# 表格：显式选择表号
.venv/bin/env-rag-final ask --query '列出全部项目及限值' --code GB8978-1996 --table-number 1

# 条款区间：--scope 只接受正文章节或条款范围
.venv/bin/env-rag-final ask --query '逐条列出全部要求' --code GB18466-2005 --scope '4.1.1 至 4.1.5'
```

`--document` 仅接受目录中完整文件名或 doc_id；不做模糊文件选择。`--doc-id` 在 ask 中也可作为这个选择器。题面和显式选择冲突会拒绝，不悄悄覆盖。`--scope-id` 可指定目录范围ID；同号表有多个章节归属时可用 `--table-number 1 --chapter-scope '实际章节标题'` 消歧。

没有标准号且没有明确文件时，章节/表格查询不会把关键词发现提升成目标。自动分类只处理受控的文件/正文/表格枚举；复杂句法请明确给出 `--kind` 和范围，无法确认时保守返回。

## 状态、引用和保存

- `complete`：针对已确认的请求范围，成员全读、条目有核验引用；不表示任意自然语言问题都已理解，也不保证源PDF解析无损。
- `partial`：缺成员、缺条款或引用未通过等；已读条目保留为诊断。
- `ambiguous`：无法确认范围/续片归组，或问题超出枚举意图。
- `missing`：明确文件或标准版本缺失；不拿邻近版本替代。
- `stale`：来源、目录、索引或发布前目录身份变化，拒绝将已有条目作为可信完整答案。

默认打印条目、文件名、来源定位和原因；完整引用（工作区/文档/快照/表片及原始行号，或正文单元跨度）保存在JSON中。原始表格行号包含表头，因此不是最终答案序号。

```bash
.venv/bin/env-rag-final ask --query '列出 GB8978-1996 表1的全部项目' --format json --out /tmp/my-enumeration-new.json
```

`--out` 必须是不存在的新文件；父目录须已存在。基础设施失败/stale退出非零；partial/ambiguous/missing是可检查的业务结果，不能仅凭退出码0判正确。`elapsed_ms` 是本入口从开始到连接回收的耗时，包含守卫、发现、完整展开与回读，不含命令启动和结果打印。

本命令只需要 `.env` 中的五项 POSTGRES 配置，不能使用 `--allow-model` 或 `--with-model`。不会初始化 LightRAG 存储、修改数据库或重建索引。

## 原 LightRAG 的显式可选接入

已有适配函数；以下是调用方接入示例，本次未执行原 LightRAG 模型请求：

```python
from lightrag import QueryParam
from env_rag_final.lightrag_enum_bridge import aquery_with_enumeration
from env_rag_final.ask import format_answer

# 关闭增强：保持原公开 API、参数、返回对象与异常行为。
normal = await aquery_with_enumeration(
    existing_rag, question,
    enumeration=False, param=QueryParam(mode="local"),
)

# 显式启用：返回枚举结果 dict，不调用 existing_rag，也不初始化存储。
listing = await aquery_with_enumeration(
    existing_rag, question,
    enumeration=True,
    enum_options={"kind": "table", "code": "GB8978-1996", "table_number": "1"},
    values=pg_values,
)
print(format_answer(listing))
```

这是 Python 调用方的可选适配器，尚未注册到原项目 HTTP 路由/WebUI。原 LightRAG checkout与本项目发布依赖版本不同；本轮不改它们，不启动原服务。若原应用接入此函数，需要处理开启时的dict与关闭时原返回类型的区别，并在原应用运行环境中提供本包及其依赖。不能把这个适配器或历史评测local当作原系统真实提升的证据。

## 已核验与仍未证明

新入口最终验证：6个完整集合正例（2/3/4/4/13/1项）、1个表格归组歧义（只读PG现场）、1个跨标准判断题（读前拒绝）。预期在运行前由冻结gold及原始blocks/HTML验证，答案生成不读取gold。工程回归550项通过，其中24项是新增入口及适配器验证。

[现场逐例证据与报告](reports/pg-retrieval/enum-entry-20261010-r1/report.md)

原始未改动 LightRAG 的现场对照尚未验证。本轮没有付费模型、embedding或精排请求，也没有重新开启全量评测；此前 Gate4 失败结论保持。
