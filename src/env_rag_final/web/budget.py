"""Goal-wide durable reservation ledger. Restarts never reset call caps."""

from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path

CAPS = {"retrieval": 40, "answer": 60, "extra_answer": 20, "keyword": 40, "embedding": 160}
MAX_EMBED_TEXTS = 32
# Existing service: 8192 tokens per text. This additional conservative character
# cap is fixed before live requests; large corpus text is never silently cut.
MAX_EMBED_CHARS = 32_000


class BudgetExhausted(RuntimeError):
    pass


class Ledger:
    caps = CAPS
    mode = "goal"

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            try:
                with path.open("x") as f:
                    json.dump(
                        {
                            "mode": self.mode,
                            "caps": self.caps,
                            "reserved": {},
                            "issued": {},
                            "events": [],
                        },
                        f,
                    )
            except FileExistsError:
                pass

    def _update(self, fn):
        with self.path.open("r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            data = json.load(f)
            if data["caps"] != self.caps or data.get("mode", "goal") != self.mode:
                raise ValueError("共享预算配置不符；不能重置或提高本次 Goal 的额度")
            result = fn(data)
            f.seek(0)
            json.dump(data, f, ensure_ascii=False)
            f.truncate()
            f.flush()
            os.fsync(f.fileno())
            return result

    def reserve(self, services: list[str], request_id: str, operation: str):
        if not services or len(services) != len(set(services)):
            raise ValueError("budget services must be unique")

        def change(data):
            for key in services:
                if key not in self.caps:
                    raise ValueError("unknown budget service")
                if self.caps[key] is not None and data["reserved"].get(key, 0) >= self.caps[key]:
                    data["events"].append(
                        {
                            "request_id": request_id,
                            "operation": operation,
                            "status": "refused",
                            "service": key,
                            "issued": 0,
                            "time": time.time(),
                        }
                    )
                    return False
            for key in services:
                data["reserved"][key] = data["reserved"].get(key, 0) + 1
            data["events"].append(
                {
                    "request_id": request_id,
                    "operation": operation,
                    "status": "reserved",
                    "services": services,
                    "time": time.time(),
                }
            )
            return True

        if not self._update(change):
            raise BudgetExhausted("共享调用额度已耗尽；没有发出此次请求")

    def issued(self, services: list[str], request_id: str, operation: str):
        def change(data):
            events = [
                e
                for e in data["events"]
                if e["request_id"] == request_id and e["operation"] == operation
            ]
            for key in services:
                reserved = sum(e["status"] == "reserved" and key in e["services"] for e in events)
                issued = sum(e["status"] == "issued" and key in e["services"] for e in events)
                if issued >= reserved:
                    raise RuntimeError("I/O must have a reservation")
                data["issued"][key] = data["issued"].get(key, 0) + 1
            data["events"].append(
                {
                    "request_id": request_id,
                    "operation": operation,
                    "status": "issued",
                    "services": services,
                    "time": time.time(),
                }
            )

        self._update(change)

    def snapshot(self):
        return self._update(lambda data: json.loads(json.dumps(data)))


class InteractiveLedger(Ledger):
    """Separate manual-use accounting; provider limits and per-request guards still apply."""

    caps = dict.fromkeys(CAPS)
    mode = "interactive"


def check_embedding_batch(texts):
    if not isinstance(texts, list) or not texts or any(not isinstance(t, str) for t in texts):
        raise ValueError("embedding batch must contain text")
    if len(texts) > MAX_EMBED_TEXTS or sum(map(len, texts)) > MAX_EMBED_CHARS:
        raise BudgetExhausted("embedding 批次超出预定文本/字符上限，零调用拒绝")
