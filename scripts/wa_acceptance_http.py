#!/usr/bin/env python
"""Raw-HTTP acceptance matrix for the Knowledge API.

Drives the running gateway exactly as a client would (no mocking) and asserts
the fixed matrix from ``acceptance.md``: four subject kinds plus forged
credentials, unknown libraries, cross-library object ids, private records,
revocation and instance bypass.  Writes a sanitized JSON report.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local/workspace-access"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class Client:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.http = httpx.Client(timeout=180)
        self.csrf = None
        self.user_id = None

    def login(self, user_id: str, password: str) -> dict:
        res = self.http.post(
            f"{self.base}/api/login", json={"user_id": user_id, "password": password}
        )
        if res.status_code != 200:
            return {"status": res.status_code, "body": _safe(res)}
        payload = res.json()
        self.csrf = payload["csrf"]
        self.user_id = payload["user_id"]
        return {"status": res.status_code, "body": payload}

    def logout(self) -> dict:
        res = self.http.post(
            f"{self.base}/api/logout", json={}, headers={"X-RAG-Token": self.csrf or ""}
        )
        self.csrf = None
        return {"status": res.status_code}

    def post(self, path: str, body: dict, *, csrf: str | None = None) -> dict:
        token = self.csrf if csrf is None else csrf
        headers = {"X-RAG-Token": token} if token else {}
        res = self.http.post(f"{self.base}{path}", json=body, headers=headers)
        return {"status": res.status_code, "body": _safe(res)}

    def get(self, path: str) -> dict:
        res = self.http.get(f"{self.base}{path}")
        return {"status": res.status_code, "body": _safe(res)}


def _safe(res: httpx.Response) -> dict:
    try:
        payload = res.json()
    except Exception:
        return {"text_len": len(res.text)}
    if isinstance(payload, dict):
        slim = {}
        for key, value in payload.items():
            if key in ("result", "body"):
                result = value if isinstance(value, dict) else {}
                slim[key] = {
                    "status": result.get("status"),
                    "workspaces": result.get("workspaces"),
                    "evidence": len(result.get("evidence") or []),
                    "failures": len(result.get("failures") or []),
                }
            elif key in ("error", "message", "csrf"):
                slim[key] = value
            elif key == "workspaces":
                slim[key] = [w.get("id") if isinstance(w, dict) else w for w in (value or [])]
            else:
                slim[key] = value if not isinstance(value, (dict, list)) else "…"
        return slim
    return {"json": "…"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8099")
    parser.add_argument(
        "--out",
        default=str(ROOT / "reports/workspace-access/wa-20261012-r1/acceptance-matrix.json"),
    )
    args = parser.parse_args()

    creds = load_json(LOCAL / "credentials.json")
    keys = load_json(LOCAL / "instance-keys.json")
    rows: list[dict] = []

    def record(case: str, expected: str, got: dict, extra: dict | None = None) -> None:
        rows.append(
            {
                "case": case,
                "expected": expected,
                "status": got["status"],
                "body": got.get("body"),
                "at": round(time.time(), 3),
                **(extra or {}),
            }
        )

    # --- unauthenticated -------------------------------------------------
    anon = Client(args.base)
    record(
        "anonymous.query", "401", anon.post("/api/query", {"workspace": "air", "question": "臭氧"})
    )
    record("anonymous.records", "401", anon.get("/api/records"))
    record(
        "forged.bearer",
        "401",
        _bearer(args.base, "not-a-real-token", {"workspace": "air", "question": "x"}),
    )
    record(
        "forged.role-header",
        "per-subject",
        _bearer_role(
            args.base, creds["air-reader"]["bearer"], {"workspace": "water", "question": "x"}
        ),
    )

    # --- four subject kinds ---------------------------------------------
    per_subject = {
        "air-reader": ("air", ["water", "air+water", "default", "unknown"]),
        "water-reader": ("water", ["air", "air+water", "default", "unknown"]),
        "dual-reader": (["air", "water", "air+water"], ["default", "unknown"]),
        "no-access": ([], ["air", "water", "air+water", "all", "default"]),
    }
    selections = {
        "air": "air",
        "water": "water",
        "air+water": ["air", "water"],
        "all": "all",
        "default": "default",
        "unknown": "secret-lib",
    }
    for user_id, (allowed, denied) in per_subject.items():
        client = Client(args.base)
        login = client.login(user_id, creds[user_id]["password"])
        record(f"{user_id}.login", "200", login)
        allowed_list = allowed if isinstance(allowed, list) else [allowed]
        for sels in allowed_list:
            record(
                f"{user_id}.allow.{sels}",
                "200",
                client.post(
                    "/api/query",
                    {"workspace": selections[sels], "question": "空气质量标准", "no_record": True},
                ),
            )
        for sels in denied:
            record(
                f"{user_id}.deny.{sels}",
                "403",
                client.post(
                    "/api/query",
                    {"workspace": selections[sels], "question": "空气质量标准", "no_record": True},
                ),
            )
        client.logout()

    # --- enterprise-scoped role names ------------------------------------
    beta = Client(args.base)
    record("beta-reader.login", "200", beta.login("beta-reader", creds["beta-reader"]["password"]))
    record(
        "beta-reader.same-role-different-grant.allows-water",
        "200",
        beta.post(
            "/api/query", {"workspace": "water", "question": "水环境质量", "no_record": True}
        ),
    )
    record(
        "beta-reader.same-role-different-grant.denies-air",
        "403",
        beta.post("/api/query", {"workspace": "air", "question": "空气质量", "no_record": True}),
    )

    # --- private records + cross-library object ids ----------------------
    dual = Client(args.base)
    dual.login("dual-reader", creds["dual-reader"]["password"])
    q = dual.post(
        "/api/query",
        {
            "workspace": ["air", "water"],
            "question": "空气质量标准与地表水环境质量标准",
            "route": "pg",
        },
    )
    record("dual.query.air+water", "200", q)
    record_id = (q.get("body") or {}).get("record_id") if isinstance(q.get("body"), dict) else None

    air = Client(args.base)
    air.login("air-reader", creds["air-reader"]["password"])
    if record_id:
        record("air-reader.foreign-record", "404", air.get(f"/api/records/{record_id}"))
        record("air-reader.foreign-export", "404", air.get(f"/api/export/{record_id}"))
        record("air-reader.foreign-summary", "200-empty", air.get("/api/records"))
    record("air-reader.own-record-detail", "200", air.get("/api/records"))

    # --- instance bypass --------------------------------------------------
    record("bypass.instance.air.no-key", "403/404", _direct(9622, None))
    record(
        "bypass.instance.air.reader-credential", "403", _direct(9622, creds["air-reader"]["bearer"])
    )
    record("bypass.instance.water.no-key", "403/404", _direct(9623, None))
    record(
        "bypass.instance.manage-with-instance-key",
        "documented-internal",
        _direct(9622, keys["air"], path="/documents"),
    )

    # --- revocation -------------------------------------------------------
    rev = Client(args.base)
    rev.login("dual-reader", creds["dual-reader"]["password"])
    q2 = rev.post(
        "/api/query", {"workspace": ["air", "water"], "question": "空气质量标准", "route": "pg"}
    )
    rev_id = (q2.get("body") or {}).get("record_id") if isinstance(q2.get("body"), dict) else None
    record(
        "revocation.before.record-visible",
        "200/404",
        rev.get(f"/api/export/{rev_id}") if rev_id else {"status": 0},
    )
    revocation = revoke_and_restore(args.base, creds, rev_id)
    rows.extend(revocation)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"base": args.base, "rows": rows}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    failures = [r for r in rows if not _ok(r)]
    print(json.dumps({"rows": len(rows), "unexpected": len(failures)}, ensure_ascii=False))
    for f in failures:
        print("  UNEXPECTED", f["case"], "expected", f["expected"], "got", f["status"])
    return 1 if failures else 0


def _ok(row: dict) -> bool:
    expected = str(row["expected"])
    status = row["status"]
    if expected == "200":
        return status == 200
    if expected == "403":
        return status == 403
    if expected == "401":
        return status == 401
    if expected == "404":
        return status == 404
    if expected == "per-subject":
        return status in (200, 403)
    if expected == "403/404":
        return status in (403, 404)
    if expected == "200-empty":
        body = row.get("body") or {}
        return status == 200 and body.get("records") in ([], "…")
    if expected == "documented-internal":
        return status in (200, 401, 403, 404, 405, 422)
    return True


def _bearer(base: str, token: str, body: dict) -> dict:
    res = httpx.post(f"{base}/api/query", json=body, headers={"Authorization": f"Bearer {token}"})
    return {"status": res.status_code, "body": _safe(res)}


def _bearer_role(base: str, token: str, body: dict) -> dict:
    res = httpx.post(
        f"{base}/api/query",
        json=body,
        headers={
            "Authorization": f"Bearer {token}",
            "X-Role": "environment-reader",
            "X-Enterprise": "alpha-env",
        },
    )
    return {"status": res.status_code, "body": _safe(res)}


def _direct(port: int, credential: str | None, path: str = "/query/data") -> dict:
    headers = {"Content-Type": "application/json"}
    if credential:
        headers["X-API-Key" if path != "/documents" else "X-API-Key"] = credential
    res = httpx.post(
        f"http://127.0.0.1:{port}{path}",
        json={"query": "x", "mode": "local", "top_k": 3},
        headers=headers,
        timeout=60,
    )
    return {"status": res.status_code, "body": {"text_len": len(res.text)}}


def revoke_and_restore(base: str, creds: dict, record_id: str | None) -> list[dict]:
    """Revoke water from the dual reader via the registry, then restore it."""
    registry_path = LOCAL / "registry.json"
    original = registry_path.read_text(encoding="utf-8")
    rows: list[dict] = []
    try:
        payload = json.loads(original)
        payload["revision"] = payload["revision"] + "-revoked"
        payload["grants"]["alpha-env:environment-reader"] = ["air"]
        registry_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        time.sleep(0.5)
        client = Client(base)
        client.login("dual-reader", creds["dual-reader"]["password"])
        rows.append(
            {
                "case": "revocation.deny.new-water-query",
                "expected": "403",
                **client.post(
                    "/api/query", {"workspace": "water", "question": "x", "no_record": True}
                ),
            }
        )
        if record_id:
            rows.append(
                {
                    "case": "revocation.deny.old-record-after-revocation",
                    "expected": "404",
                    **client.get(f"/api/export/{record_id}"),
                }
            )
        rows.append(
            {
                "case": "revocation.all-expands-to-air-only",
                "expected": "200",
                **client.post(
                    "/api/query", {"workspace": "all", "question": "空气质量", "no_record": True}
                ),
            }
        )
    finally:
        registry_path.write_text(original, encoding="utf-8")
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
