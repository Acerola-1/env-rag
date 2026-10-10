# 改进组3诊断裁决（2026-10-08）

**诊断通过，允许进入有界文件枚举实现组3。** 生产代码未改，Reviewer0网络/数据库/模型请求/写库，未重复505工程全套。

六腿通过提交驱动器重定向输出到review目录后，与诊断对账JSON逐字段一致：local含修改单1份/增补0，PG同题3份/增补2，多版本2份，年报5份；仅改变local search_id的构造变体3份，page_size=2年报变体5份。两个归属行空citation.snapshot_id且仍verified的问题独立复现。

已核实：完整文件基集合在catalog.documents上分页，而后续归属分支查search_documents并使用local空search_id；候选里已有两份修改单也不进入基集合，最终1/1基集合统计被当作全题complete。基集分页本身不是本例根因；目录/原始产物提供两份相关文件的归属依据。修改单self_code未知，不能伪造成标准本体。

证据边界：EnumConn在有效search_id时提供存量元数据行，实际code/version过滤由生产路由执行；这是构造参数对照，不是现场tsvector/索引查询验证。空键依赖和当前输出问题仍被正式调用参数与产物充分支持。

诊断13项清单、生产2项SHA匹配，另独立复核973条选定核心历史保护清单无失配。发布证据为存量身份+fake只读连接，不冒充现场库；历史清单/冻结/gold/配置不修改。

## 实现裁决

1. 文件枚举的基集与归属必须在同一workspace、active目录snapshot下完整读取与验证；不依赖search_id，不向local回填PG搜索身份。
2. 最终统计、发布、token及coverage以去重并集为准；不得只用基础1/1掩盖未执行/失败/截断的related分支。
3. 所有引用绑定实际目录snapshot/source指纹，不能空串verified。base/related/overlap/union分列，实际归属匹配为0与新增数为0分开：已确认归属项在基集时新增0不应误判失败。
4. 显式含修改单但无可确认相关项须告警并保守非complete，不能把普通标准本体或候选裸标签算作related完成请求；已验证相关项以目录证据为准，不依赖发现是否命中。
5. 多编号/多版本按分支配对确认，保留自身编号/年报/版本枚举及stale/预算合同，发现召回不回填。

见`handoff-phase-4-improvement-3-file-enumeration-implementation.md`。同意直接实施该离线组，不新增真实调用授权；提交后停工程复审。改进组1/2、Gate3/6.1保持，第二轮/6.2/6.3/Gate4仍暂停，不切默认路径。
