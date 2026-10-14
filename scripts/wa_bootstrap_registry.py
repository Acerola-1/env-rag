#!/usr/bin/env python
"""Bootstrap the workspace registry and sample credentials (local, ignored).

Writes:

* ``.local/workspace-access/registry.json``  — workspaces, principals, grants
* ``.local/workspace-access/credentials.md`` — Chinese human-readable sheet
  with generated passwords + bearer tokens (0600, never committed). The
  committed companion document for open-source readers is ``ACCOUNTS.md``.
* ``deployment/workspaces.example.json``     — committed template, no secrets

Adding a library is a registry edit plus ingestion; no retrieval code changes.
"""

from __future__ import annotations

import json
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from wa_credentials import (  # noqa: E402
    CREDENTIALS_MD,
    parse_credentials_md,
    render_credentials_md,
)

from env_rag_final.access.registry import (  # noqa: E402
    REGISTRY_FORMAT,
    hash_password,
    hash_token,
)

REVISION = "wa-20261012-r1"
LOCAL = ROOT / ".local/workspace-access"

WORKSPACES = {
    "air": {
        "name": "大气资料",
        "pg_workspace": "air",
        "vector_workspace": "air",
        "graph_workspace": "air",
        "status": "active",
        "instance_url": "http://127.0.0.1:9622",
        "instance_key_ref": "air",
        "parsed_root": "datasets/corpus/parsed",
        "embedding_model": "Qwen/Qwen3-Embedding-4B",
        "embedding_dim": 2560,
        "code_identity": "lightrag-hku==1.5.7 / ghcr.io/hkuds/lightrag:latest",
        "corpus_manifest": "reports/workspace-access/wa-20261012-r1/corpus-manifest.jsonl",
        "notes": "大气环境资料；解析产物复用仓库 MinerU sidecar",
    },
    "water": {
        "name": "水资料",
        "pg_workspace": "water",
        "vector_workspace": "water",
        "graph_workspace": "water",
        "status": "active",
        "instance_url": "http://127.0.0.1:9623",
        "instance_key_ref": "water",
        "parsed_root": "datasets/corpus/parsed",
        "embedding_model": "Qwen/Qwen3-Embedding-4B",
        "embedding_dim": 2560,
        "code_identity": "lightrag-hku==1.5.7 / ghcr.io/hkuds/lightrag:latest",
        "corpus_manifest": "reports/workspace-access/wa-20261012-r1/corpus-manifest.jsonl",
        "notes": "水环境资料；含显式共用样本",
    },
}

# enterprise -> role -> workspaces.  Role names are interpreted inside their
# enterprise, so `beta-env`'s `air-reader` grants a different library.
GRANTS = {
    "alpha-env:air-reader": ["air"],
    "alpha-env:water-reader": ["water"],
    "alpha-env:environment-reader": ["air", "water"],
    "alpha-env:guest": [],
    "beta-env:air-reader": ["water"],
}

PRINCIPALS = {
    "air-reader": ("alpha-env", "大气读者", ["air-reader"]),
    "water-reader": ("alpha-env", "水资料读者", ["water-reader"]),
    "dual-reader": ("alpha-env", "双库读者", ["environment-reader"]),
    "no-access": ("alpha-env", "无知识库授权主体", ["guest"]),
    "beta-reader": ("beta-env", "乙企业大气读者", ["air-reader"]),
}


def main() -> int:
    LOCAL.mkdir(parents=True, exist_ok=True)
    creds: dict = {}
    if CREDENTIALS_MD.exists():
        creds = parse_credentials_md(CREDENTIALS_MD.read_text(encoding="utf-8"))
    else:
        # One-time migration from the old JSON sheet (no re-hash churn).
        legacy = LOCAL / "credentials.json"
        if legacy.exists():
            creds = json.loads(legacy.read_text(encoding="utf-8"))

    principals: dict = {}
    for user_id, (enterprise, display, roles) in PRINCIPALS.items():
        entry = creds.setdefault(user_id, {})
        password = entry.get("password") or secrets.token_urlsafe(18)
        token = entry.get("bearer") or secrets.token_urlsafe(32)
        entry.update({"password": password, "bearer": token, "enterprise": enterprise})
        principals[user_id] = {
            "enterprise": enterprise,
            "display": display,
            "roles": roles,
            "password_hash": hash_password(password, f"wa-{user_id}"),
            "bearer_sha256": [hash_token(token)],
        }

    registry = {
        "format": REGISTRY_FORMAT,
        "revision": REVISION,
        "workspaces": WORKSPACES,
        "principals": principals,
        "grants": GRANTS,
    }
    reg_path = LOCAL / "registry.json"
    reg_path.write_text(json.dumps(registry, ensure_ascii=False, indent=1), encoding="utf-8")
    reg_path.chmod(0o600)
    CREDENTIALS_MD.write_text(render_credentials_md(creds), encoding="utf-8")
    CREDENTIALS_MD.chmod(0o600)

    template = json.loads(json.dumps(registry))
    for entry in template["principals"].values():
        entry.pop("password_hash", None)
        entry["password_hash"] = "<pbkdf2-salt$hash>"
        entry["bearer_sha256"] = ["<sha256 of the bearer token>"]
    out = ROOT / "deployment/workspaces.example.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(template, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    from env_rag_final.access.registry import load_registry

    reg = load_registry(reg_path)
    print(
        f"registry {reg.revision}: {len(reg.workspaces)} workspaces, {len(reg.principals)} principals"
    )
    for user_id, principal in sorted(reg.principals.items()):
        print(f"  {user_id:14s} {principal.enterprise:10s} -> {reg.allowed_workspaces(principal)}")
    print(f"credentials: {CREDENTIALS_MD}")
    print(f"template   : {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
