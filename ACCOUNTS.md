# 演示账号与登录说明

知识库网页（Knowledge API 网关）需要先登录再使用：浏览器打开 **<http://127.0.0.1:8099>**，在登录页输入下面的**主体**和**登录口令**即可。

```bash
# 启动网关（首次使用先按 README 完成 uv sync、.env 配置和容器启动）
.venv/bin/python -m env_rag_final.access --port 8099
```

## 账号一览

下面是内置的演示账号，用于体验“按账号分库授权”的效果。所有服务只绑定本机回环地址，这些口令仅适合本地测试，**请勿用于真实部署**。

| 主体（登录名） | 登录口令 | 能访问的知识库 | 用途 |
| --- | --- | --- | --- |
| `air-reader` | `0Gy9TX27ExBFWWJ8jzqiXmU6` | 仅大气库 air | 体验单库账号：登录后只能看到“大气资料” |
| `water-reader` | `2Ev3yQ1A8QTOaqzQr5Q0B_59` | 仅水库 water | 体验单库账号：登录后只能看到“水资料” |
| `dual-reader` | `6M_Bp4B-RhIggTvPIQwcsCxZ` | air 和 water 都可以 | 体验双库账号：可在两个库之间切换查询 |
| `no-access` | `K77Jt2QUw48GQAsLbKlBNwk6` | 什么都没有 | 对照账号：登录后应提示没有知识库授权 |
| `beta-reader` | `mUECWZa_6M0GL20LypSLhXf0` | 乙企业内的 water | 演示“同名角色在不同企业含义不同” |
| `coastal-reader` | `XTUnupNgSQasfBNyGlSXhgSp` | 第三库 coastal | 扩展库账号（只有启动并入库 coastal 后才可见） |

建议的试用路线：先用 `water-reader` 登录，选 PG 路径问“列出 GB18466-2005 表1的全部项目和限值”，可以看到 31 行完整表格条目；再换 `dual-reader` 体验切库；最后用 `no-access` 确认无权限提示。

## 命令行方式（Bearer Token）

不用浏览器时，可以直接用各账号的 Bearer Token 调接口：

```bash
curl -s -H "Authorization: Bearer 7oVqdt_vGm0QSH5wjFQ1v1lSHDKJyjw1pw5XTUD08-Y" \
  -H 'Content-Type: application/json' \
  -d '{"workspace":"all","question":"空气质量标准与地表水环境质量标准","route":"pg"}' \
  http://127.0.0.1:8099/api/query
```

上面这个 token 属于 `dual-reader`。各账号 token 与口令的对应关系：

| 主体 | Bearer Token |
| --- | --- |
| `air-reader` | `t4zqJhb_1dA25hsE3wgeAC2nhCeDKmmD-T-yy_Xjj7U` |
| `water-reader` | `X2Z3v2LelKs0b80DRR6-RCt0DdI_hKeD0L80cfEJo48` |
| `dual-reader` | `7oVqdt_vGm0QSH5wjFQ1v1lSHDKJyjw1pw5XTUD08-Y` |
| `no-access` | `vlnMElYINuxfz_FY9yf0Fgqmqrn2ngEZ5JRis1l4E2I` |
| `beta-reader` | `mYQbhgErnIGA0Pfzvyn1bAY1zOgVPTajrvx4jcrUMZc` |
| `coastal-reader` | `mSRP4qC6gSr0t7aPMHsiouxmbWffr5lXpQF6MUek1Zk` |

## 这些账号是怎么来的、如何重置

- 账号、角色和授权写在本机注册表 `.local/workspace-access/registry.json`（不进 Git），模板见 `deployment/workspaces.example.json`。
- 口令和 token 的中文清单由引导脚本生成在 `.local/workspace-access/credentials.md`（权限 0600，不进 Git），内容格式与本页一致。
- 重新运行引导脚本会保留已有口令、为新主体补生成随机口令，并重写该清单：

  ```bash
  .venv/bin/python scripts/wa_bootstrap_registry.py
  ```

- 网关校验的是注册表里口令的 PBKDF2-SHA256 哈希和 token 的 SHA-256，不保存明文；明文只存在本机清单中。

## 安全边界

这是应用层的粗粒度知识库授权演示：服务只监听 127.0.0.1，请求里出现未授权的库会整体拒绝，历史记录只对创建者可见。它**不是**数据库级的强租户隔离（未启用 RLS），持有数据库或服务端密钥的环境不在普通读者的威胁模型内。正式部署时请务必替换全部演示口令与 token，并放在反向代理与认证体系之后。更多细节见 [WORKSPACE-ACCESS.md](WORKSPACE-ACCESS.md)。
