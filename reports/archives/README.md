# 历史网页运行记录归档

`rag-web-20261010-r1-runtime.tar.gz` 保存历史网页的原始检索／生成记录、身份锚、封存清单和账本。归档时逐文件对照 SHA-256；具体路径、大小和哈希见同名 `runtime-manifest.json`。

当前本机原目录仍保留，正在使用的网页不受影响。该目录作为本机运行状态不再直接入 Git；新克隆默认不附带展开后的历史记录。需要复现“查看已保存结果”时，在仓库根目录执行：

```sh
# 先检查清单；若已有 runtime 目录，先备份并使用独立工作目录恢复。
tar -tzf reports/archives/rag-web-20261010-r1-runtime.tar.gz
tar -xzf reports/archives/rag-web-20261010-r1-runtime.tar.gz
```

不要覆盖正在运行的记录或账本。历史验收汇总、截图、固定题组和对照证据仍在 `reports/rag-web-20261010-r1/`。日常问答的 `reports/rag-web-interactive/usage.json` 是本机可变计量状态，不进入版本管理，也没有被清空。
