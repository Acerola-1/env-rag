#!/usr/bin/env python
"""Real-browser acceptance for the Knowledge API web page.

Drives a headless Chromium (Microsoft Edge) over the DevTools protocol: real
page load, real JavaScript, real network calls to the gateway.  Captures
desktop and narrow-screen screenshots plus an operation log.

This is a browser run, not a DOM scrape: every step awaits the page's own code.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from wa_credentials import load_credentials  # noqa: E402

LOCAL = ROOT / ".local/workspace-access"
EDGE = "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"


class Browser:
    def __init__(self, port: int, profile: Path):
        self.port = port
        self.profile = profile
        self.proc: subprocess.Popen | None = None
        self.ws: websockets.WebSocketClientProtocol | None = None
        self._id = 0

    def start(self) -> None:
        self.proc = subprocess.Popen(
            [
                EDGE,
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                f"--user-data-dir={self.profile}",
                f"--remote-debugging-port={self.port}",
                "--window-size=1280,900",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(60):
            try:
                res = httpx.get(f"http://127.0.0.1:{self.port}/json/version", timeout=2)
                if res.status_code == 200:
                    return
            except Exception:
                time.sleep(0.5)
        raise RuntimeError("browser did not expose the debugging port")

    async def connect(self) -> None:
        targets = httpx.get(f"http://127.0.0.1:{self.port}/json", timeout=5).json()
        page = next(t for t in targets if t["type"] == "page")
        self.ws = await websockets.connect(
            page["webSocketDebuggerUrl"], max_size=64 * 1024 * 1024, open_timeout=30
        )

    async def send(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        await self.ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=180))
            if message.get("id") == self._id:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})

    async def evaluate(self, expression: str, await_promise: bool = False):
        result = await self.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": await_promise,
                "userGesture": True,
            },
        )
        if result.get("exceptionDetails"):
            raise RuntimeError(json.dumps(result["exceptionDetails"])[:400])
        return result.get("result", {}).get("value")

    async def goto(self, url: str) -> None:
        await self.send("Page.enable")
        await self.send("Page.navigate", {"url": url})
        for _ in range(240):
            state = await self.evaluate("document.readyState")
            if state == "complete":
                break
            await asyncio.sleep(0.25)

    async def wait_for(self, expression: str, timeout: float = 60.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if await self.evaluate(expression):
                return True
            await asyncio.sleep(0.25)
        return False

    async def screenshot(self, path: Path, width: int, height: int, mobile: bool = False) -> None:
        await self.send(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": width,
                "height": height,
                "deviceScaleFactor": 1,
                "mobile": mobile,
            },
        )
        await asyncio.sleep(0.4)
        result = await self.send("Page.captureScreenshot", {"format": "png"})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(result["data"]))

    def stop(self) -> None:
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except Exception:
                self.proc.kill()


async def run(base: str, out_dir: Path, creds: dict) -> dict:
    log: list[dict] = []

    def note(step: str, detail=None) -> None:
        log.append({"step": step, "detail": detail, "at": round(time.time(), 3)})

    port = _free_port()
    profile = Path(tempfile.mkdtemp(prefix="wa-edge-"))
    browser = Browser(port, profile)
    try:
        browser.start()
        await browser.connect()
        await browser.goto(base)
        note("load", await browser.evaluate("document.title"))

        async def login(user_id: str, expect_ok: bool = True) -> None:
            await browser.evaluate(
                f"""(function(){{
                    const u=document.getElementById('user_id');
                    const p=document.getElementById('password');
                    u.value={json.dumps(user_id)}; p.value={json.dumps(creds[user_id]["password"])};
                    document.getElementById('login-form').dispatchEvent(new Event('submit',{{cancelable:true,bubbles:true}}));
                }})()"""
            )
            if expect_ok:
                ok = await browser.wait_for(
                    "document.getElementById('app-panel').hidden === false", 30
                )
                note(f"login.{user_id}", {"app_panel_visible": ok})
            else:
                ok = await browser.wait_for(
                    "document.getElementById('login-error').hidden === false", 30
                )
                note(f"login.{user_id}.rejected", {"error_shown": ok})

        async def libraries() -> list:
            return await browser.evaluate(
                "Array.from(document.querySelectorAll('#libs input[name=lib]')).map(i=>i.value)"
            )

        async def submit_question(question: str, route: str = "pg", mode: str = "local") -> None:
            await browser.evaluate(
                f"""(function(){{
                    document.getElementById('question').value={json.dumps(question)};
                    document.getElementById('route').value={json.dumps(route)};
                    document.getElementById('mode').value={json.dumps(mode)};
                    document.getElementById('ask').dispatchEvent(new Event('submit',{{cancelable:true,bubbles:true}}));
                }})()"""
            )
            await browser.wait_for(
                "document.getElementById('ask-status').textContent.length>0"
                " && document.getElementById('ask-status').textContent.indexOf('查询中') === -1",
                240,
            )

        # ---- air reader -------------------------------------------------
        await login("air-reader")
        note("air-reader.libraries", await libraries())
        await submit_question("臭氧污染防治攻坚行动方案的攻坚目标")
        ok = await browser.wait_for("document.getElementById('result-panel').hidden === false", 120)
        note(
            "air-reader.pg-query",
            {
                "result_panel": ok,
                "meta": await browser.evaluate(
                    "document.getElementById('result-meta').textContent"
                ),
                "evidence": await browser.evaluate(
                    "document.querySelectorAll('#evidence li').length"
                ),
            },
        )
        await browser.screenshot(out_dir / "desktop-air-query.png", 1280, 900)
        # generate
        await browser.evaluate("document.getElementById('generate').click()")
        await browser.wait_for(
            "document.getElementById('generation').textContent.includes('模型')", 240
        )
        note(
            "air-reader.generate",
            (await browser.evaluate("document.getElementById('generation').textContent"))[:200],
        )
        await browser.screenshot(out_dir / "desktop-air-generation.png", 1280, 900)
        # analytic text fetch through the page's own link
        text_ok = await browser.evaluate(
            "(async()=>{const a=document.querySelector('#evidence .evidence-links a');"
            "if(!a) return 'no-link';const r=await fetch(a.getAttribute('href'));"
            "return r.status + ':' + (await r.text()).length;})()",
            await_promise=True,
        )
        note("air-reader.parsed-text", text_ok)
        # A forged selection cannot widen access: the page's own API call with a
        # workspace the principal is not granted is refused by the server.
        forged = await browser.evaluate(
            "(async()=>{const csrf=document.getElementById('logout')?null:null;"
            "const meta=await (await fetch('/api/me')).json();"
            "const r=await fetch('/api/query',{method:'POST',headers:{'Content-Type':'application/json','X-RAG-Token':meta.csrf},"
            "body:JSON.stringify({workspace:'water',question:'地表水环境质量标准',no_record:true})});"
            "let b=null;try{b=await r.json()}catch(e){};return r.status+' '+(b&&b.error||'');})()",
            await_promise=True,
        )
        note("air-reader.forged-water", forged)
        # A UI element injected by page script cannot change the sent selection.
        await browser.evaluate(
            """(function(){const f=document.createElement('input');f.type='radio';f.name='lib';f.value='water';f.id='forged';document.getElementById('libs').appendChild(f);f.checked=true;})()"""
        )
        await submit_question("地表水环境质量标准")
        note(
            "air-reader.dom-injection-effective-selection",
            await browser.evaluate("document.getElementById('ask-status').textContent"),
        )
        # narrow screen
        await browser.screenshot(out_dir / "narrow-air.png", 390, 844, mobile=True)
        await browser.screenshot(out_dir / "desktop-air-records.png", 1280, 900)
        await browser.evaluate("document.getElementById('logout').click()")
        await browser.wait_for("document.getElementById('login-panel').hidden === false", 30)
        note("air-reader.logout", True)

        # ---- dual reader -------------------------------------------------
        await login("dual-reader")
        note("dual-reader.libraries", await libraries())
        await browser.evaluate("document.getElementById('lib-all').click()")
        await submit_question("空气质量标准与地表水环境质量标准", route="pg")
        await browser.wait_for("document.getElementById('result-panel').hidden === false", 180)
        note(
            "dual-reader.pg+pg-query",
            {
                "meta": await browser.evaluate(
                    "document.getElementById('result-meta').textContent"
                ),
                "evidence": await browser.evaluate(
                    "document.querySelectorAll('#evidence li').length"
                ),
            },
        )
        await browser.screenshot(out_dir / "desktop-dual-query.png", 1280, 900)
        # Switching library is a pure client act: no HTTP request is issued at
        # all, which is the strongest form of "switching does not call a model".
        switch = await browser.evaluate(
            "(function(){"
            "const before=performance.getEntriesByType('resource').length;"
            "const el=document.getElementById('lib-all');"
            "el.dispatchEvent(new Event('change',{bubbles:true}));"
            "const after=performance.getEntriesByType('resource').length;"
            "return JSON.stringify({before:before,after:after,"
            "status:document.getElementById('ask-status').textContent,"
            "selected:(document.querySelector('#libs input[name=lib]:checked')||{}).value});"
            "})()"
        )
        await asyncio.sleep(1)
        after_switch = await browser.evaluate("performance.getEntriesByType('resource').length")
        note(
            "dual-reader.switch-no-model",
            {"switch": json.loads(switch), "resources_after_1s": after_switch},
        )
        await browser.evaluate("document.getElementById('logout').click()")
        await browser.wait_for("document.getElementById('login-panel').hidden === false", 30)

        # ---- water reader -------------------------------------------------
        await login("water-reader")
        note("water-reader.libraries", await libraries())
        await submit_question("地表水环境质量标准的分类", route="lightrag", mode="local")
        await browser.wait_for("document.getElementById('result-panel').hidden === false", 180)
        note(
            "water-reader.lightrag-local",
            {
                "meta": await browser.evaluate(
                    "document.getElementById('result-meta').textContent"
                ),
                "evidence": await browser.evaluate(
                    "document.querySelectorAll('#evidence li').length"
                ),
            },
        )
        await browser.screenshot(out_dir / "desktop-water-lightrag.png", 1280, 900)
        await browser.evaluate("document.getElementById('logout').click()")
        await browser.wait_for("document.getElementById('login-panel').hidden === false", 30)

        # ---- no access ----------------------------------------------------
        await login("no-access")
        note(
            "no-access.libraries",
            {
                "inputs": await libraries(),
                "empty_notice": await browser.evaluate(
                    "document.getElementById('libs-empty').hidden === false"
                ),
            },
        )
        prompt_state = await browser.evaluate("document.getElementById('libs-empty').textContent")
        note("no-access.notice", prompt_state)
        await browser.screenshot(out_dir / "desktop-no-access.png", 1280, 900)

        # ---- keyboard basics ----------------------------------------------
        focus = await browser.evaluate(
            "(function(){const el=document.getElementById('logout');el.focus();return document.activeElement.id;})()"
        )
        note("keyboard.focus", focus)
        await browser.screenshot(out_dir / "narrow-no-access.png", 390, 844, mobile=True)
        return {"steps": log, "screenshots": sorted(p.name for p in out_dir.glob("*.png"))}
    finally:
        browser.stop()
        shutil.rmtree(profile, ignore_errors=True)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8099")
    parser.add_argument(
        "--out",
        default=str(ROOT / "reports/workspace-access/wa-20261012-r1/browser"),
    )
    args = parser.parse_args()
    if not Path(EDGE).exists():
        print("no Chromium-based browser found", file=sys.stderr)
        return 2
    creds = load_credentials()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(run(args.base, out_dir, creds))
    (out_dir / "operations.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(
        json.dumps(
            {"steps": len(report["steps"]), "screenshots": report["screenshots"]},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
