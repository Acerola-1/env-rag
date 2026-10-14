"""Demo credential sheet as a Chinese Markdown document.

Human-facing documentation lives in the committed ``ACCOUNTS.md`` at the
repository root.  The local machine sheet written by the bootstrap script is
``.local/workspace-access/credentials.md`` (git-ignored, 0600) and uses the
same table layout, so these helpers can read either file.  The prose around
the table is for people; only the table rows are parsed.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local/workspace-access"
CREDENTIALS_MD = LOCAL / "credentials.md"

# Accounts are shown in a fixed explanatory order; unknown extras go last.
PREFERRED_ORDER = (
    "air-reader",
    "water-reader",
    "dual-reader",
    "no-access",
    "beta-reader",
    "coastal-reader",
)

_DISPLAY = {
    "air-reader": "大气读者（仅 air）",
    "water-reader": "水资料读者（仅 water）",
    "dual-reader": "双库读者（air + water）",
    "no-access": "无授权对照账号",
    "beta-reader": "乙企业账号（角色名同企业内解释）",
    "coastal-reader": "沿海资料读者（第三库 coastal）",
}


def parse_credentials_md(text: str) -> dict:
    """Extract ``{user_id: {password, bearer, enterprise}}`` from the table."""
    creds: dict = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 4:
            continue
        user, password, bearer, enterprise = cells
        if user == "主体" or not password or set(user) <= set(":- "):
            continue
        creds[user] = {"password": password, "bearer": bearer, "enterprise": enterprise}
    return creds


def load_credentials(path: Path = CREDENTIALS_MD) -> dict:
    return parse_credentials_md(path.read_text(encoding="utf-8"))


def render_credentials_md(creds: dict) -> str:
    """Render the credential sheet as natural-language Chinese Markdown."""
    ordered = [u for u in PREFERRED_ORDER if u in creds]
    ordered += sorted(u for u in creds if u not in PREFERRED_ORDER)
    lines = [
        "# 演示账号与登录凭据（本机）",
        "",
        "本文件由 `scripts/wa_bootstrap_registry.py` 生成，只保存在本机",
        "（`.local/` 不进入 Git，权限 0600）。开源仓库中的可读说明是根目录 `ACCOUNTS.md`；",
        "两者账号表格式一致。重新运行引导脚本会重新生成口令，本表随之重写。",
        "",
        "登录方式：浏览器打开 http://127.0.0.1:8099 ，在登录页输入“主体”和“登录口令”。",
        "命令行调用接口时使用 Bearer Token。服务只绑定 127.0.0.1，这些账号的",
        "适用范围是本机测试；真实部署使用另外签发的账号。",
        "",
        "| 主体 | 登录口令 | Bearer Token | 所属企业 |",
        "| --- | --- | --- | --- |",
    ]
    for user in ordered:
        entry = creds[user]
        lines.append(
            f"| {user} | {entry['password']} | {entry['bearer']} | {entry['enterprise']} |"
        )
    lines += [
        "",
        "账号含义：",
        "",
    ]
    for user in ordered:
        lines.append(f"- `{user}`：{_DISPLAY.get(user, user)}")
    lines += [
        "- `no-access` 没有任何知识库授权，对应页面上的“无权限”提示；登录后知识库列表为空。",
        "- `beta-reader` 属于乙企业：同名角色在不同企业授予不同知识库，",
        "  它在 beta-env 被授予 water。",
        "",
    ]
    return "\n".join(lines)
