"""Tier 1: Raw CDP Hybrid Engine using locally installed Chrome/Edge/Brave."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any
import urllib.request
import winreg

from websockets.sync.client import connect as ws_connect

from scripts.win32_core import get_state_dir

GATE_MARKERS: tuple[str, ...] = (
    "verify you are human",
    "just a moment...",
    "attention required! | cloudflare",
    "g-recaptcha",
    "h-captcha",
    "cf-turnstile",
    "security check",
    "are you a robot",
)


def discover_browsers() -> dict[str, str]:
    """Dynamically locate Chrome, Edge, and Brave executables via Registry & standard dirs."""
    found: dict[str, str] = {}
    candidates = {
        "chrome": [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"),
        ],
        "edge": [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"),
        ],
        "brave": [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\brave.exe"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\brave.exe"),
        ],
    }

    for name, reg_paths in candidates.items():
        for root, subkey in reg_paths:
            try:
                with winreg.OpenKey(root, subkey) as k:
                    val, _ = winreg.QueryValueEx(k, None)
                    if val and Path(val).exists():
                        found[name] = val
                        break
            except OSError:
                continue

    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    lad = os.environ.get("LOCALAPPDATA", "")
    fallback_paths = {
        "chrome": [
            Path(pf) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(pf86) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(lad) / "Google" / "Chrome" / "Application" / "chrome.exe",
        ],
        "edge": [
            Path(pf86) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            Path(pf) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        ],
        "brave": [
            Path(pf) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
            Path(lad) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
        ],
    }
    for name, paths in fallback_paths.items():
        if name in found:
            continue
        for p in paths:
            if p.exists():
                found[name] = str(p)
                break
    return found


def _probe_cdp_http(port: int, timeout: float = 0.05) -> list[dict[str, Any]] | None:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/json/list")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        return None
    return None


def find_cdp_endpoint() -> dict[str, Any] | None:
    """Discover an active CDP WebSocket page endpoint in <50ms."""
    lad = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    profile_dir = get_state_dir() / "BrowserProfile"
    active_port_files = [
        profile_dir / "DevToolsActivePort",
        Path(lad) / "Google" / "Chrome" / "User Data" / "DevToolsActivePort",
        Path(lad) / "Microsoft" / "Edge" / "User Data" / "DevToolsActivePort",
    ]
    candidate_ports: list[int] = []
    for f in active_port_files:
        if f.exists():
            try:
                lines = f.read_text(encoding="utf-8").splitlines()
                if lines:
                    p = int(lines[0].strip())
                    if p not in candidate_ports:
                        candidate_ports.append(p)
            except Exception:
                pass
    for p in (9222, 9223):
        if p not in candidate_ports:
            candidate_ports.append(p)

    for port in candidate_ports:
        targets = _probe_cdp_http(port, timeout=0.05)
        if not targets:
            continue
        pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
        if pages:
            return {"port": port, "page": pages[0], "pages": pages}
    return None


def open_browser(
    url: str = "about:blank",
    browser: str = "auto",
    port: int = 9222,
    headless: bool = False,
) -> dict[str, Any]:
    """Launch user's native Chrome/Edge/Brave with persistent automation profile & CDP."""
    t0 = time.perf_counter()
    installed = discover_browsers()
    if not installed:
        return {"ok": False, "code": "NO_BROWSER_FOUND", "error": "No Chrome, Edge, or Brave binary found."}

    chosen_name = browser if browser in installed else next(
        (b for b in ("chrome", "edge", "brave") if b in installed), ""
    )
    exe = installed[chosen_name]

    # Reuse existing CDP browser if already running
    existing = find_cdp_endpoint()
    if existing:
        try:
            with CDPClient(existing["page"]["webSocketDebuggerUrl"]) as cdp:
                if url and url != "about:blank":
                    cdp.call("Page.navigate", {"url": url})
            return {
                "ok": True,
                "tier": "tier1_browser",
                "reused": True,
                "browser": chosen_name,
                "port": existing["port"],
                "url": url,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }
        except Exception:
            pass

    profile_dir = get_state_dir() / "BrowserProfile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        exe,
        f"--user-data-dir={profile_dir}",
        f"--remote-debugging-port={port}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if headless:
        cmd.append("--headless=new")
    cmd.append(url)

    subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=0x00000200,  # CREATE_NEW_PROCESS_GROUP
    )

    deadline = time.perf_counter() + 4.0
    while time.perf_counter() < deadline:
        ep = find_cdp_endpoint()
        if ep:
            return {
                "ok": True,
                "tier": "tier1_browser",
                "reused": False,
                "browser": chosen_name,
                "executable": exe,
                "port": ep["port"],
                "profile_dir": str(profile_dir),
                "url": ep["page"].get("url", url),
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }
        time.sleep(0.08)

    return {"ok": False, "code": "CDP_START_TIMEOUT", "error": "Browser launched but CDP port did not respond."}


class CDPClient:
    """Minimal synchronous CDP WebSocket client."""

    def __init__(self, ws_url: str, timeout: float = 4.0):
        self.ws_url = ws_url
        self.timeout = timeout
        self._msg_id = 0
        self._ws = None

    def __enter__(self) -> "CDPClient":
        self._ws = ws_connect(self.ws_url, open_timeout=self.timeout, close_timeout=1.0)
        return self

    def __exit__(self, *_args: Any) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._ws is None:
            raise RuntimeError("CDPClient not connected.")
        self._msg_id += 1
        req_id = self._msg_id
        self._ws.send(json.dumps({"id": req_id, "method": method, "params": params or {}}))
        deadline = time.perf_counter() + self.timeout
        while time.perf_counter() < deadline:
            raw = self._ws.recv(timeout=max(0.05, deadline - time.perf_counter()))
            msg = json.loads(raw)
            if msg.get("id") == req_id:
                if "error" in msg:
                    raise RuntimeError(msg["error"].get("message", "CDP error"))
                return msg.get("result", {})
        raise TimeoutError(f"CDP call '{method}' timed out.")

    def eval_js(self, expr: str) -> Any:
        res = self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
        exc = res.get("exceptionDetails")
        if exc:
            raise RuntimeError(exc.get("text", "JS exception"))
        return res.get("result", {}).get("value")


def check_page_gate(cdp: CDPClient) -> dict[str, Any] | None:
    """Detect CAPTCHA / human verification gates without attempting any bypass."""
    js = """(() => {
        const title = (document.title || '').toLowerCase();
        const body = (document.body ? document.body.innerText : '').slice(0, 1800).toLowerCase();
        const iframes = Array.from(document.querySelectorAll('iframe')).map(f => (f.src || '') + ' ' + (f.title || '')).join(' ').toLowerCase();
        const hasWidget = !!document.querySelector('.g-recaptcha, .h-captcha, .cf-turnstile, [data-sitekey]');
        return {title, body, iframes, hasWidget, url: location.href};
    })()"""
    info = cdp.eval_js(js) or {}
    haystack = " ".join(
        [
            str(info.get("title", "")),
            str(info.get("body", "")),
            str(info.get("iframes", "")),
        ]
    )
    if info.get("hasWidget") or any(m in haystack for m in GATE_MARKERS):
        return {
            "ok": False,
            "code": "HUMAN_HANDOFF_REQUIRED",
            "tier": "tier1_browser",
            "url": info.get("url", ""),
            "error": "Human verification / CAPTCHA gate detected on page. Please complete verification directly in the browser.",
        }
    return None


def click_browser(selector: str | None = None, text: str | None = None) -> dict[str, Any]:
    t0 = time.perf_counter()
    ep = find_cdp_endpoint()
    if not ep:
        return {"ok": False, "code": "NO_CDP_ENDPOINT", "error": "No active CDP browser endpoint."}

    with CDPClient(ep["page"]["webSocketDebuggerUrl"], timeout=2.5) as cdp:
        gate = check_page_gate(cdp)
        if gate:
            return gate

        if selector:
            js = f"""(() => {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) return {{found: false}};
                const r = el.getBoundingClientRect();
                if (r.width <= 0 || r.height <= 0) return {{found: true, visible: false}};
                el.scrollIntoView({{block: 'center', inline: 'center'}});
                const r2 = el.getBoundingClientRect();
                return {{found: true, visible: true, x: r2.left + r2.width / 2, y: r2.top + r2.height / 2}};
            }})()"""
        elif text:
            js = f"""(() => {{
                const q = {json.dumps(text.lower())};
                const nodes = Array.from(document.querySelectorAll('a,button,input,select,textarea,[role="button"],[role="link"],[tabindex]'));
                for (const el of nodes) {{
                    const txt = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().toLowerCase();
                    if (!txt || !txt.includes(q)) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width <= 0 || r.height <= 0) continue;
                    el.scrollIntoView({{block: 'center', inline: 'center'}});
                    const r2 = el.getBoundingClientRect();
                    return {{found: true, visible: true, x: r2.left + r2.width / 2, y: r2.top + r2.height / 2}};
                }}
                return {{found: false}};
            }})()"""
        else:
            return {"ok": False, "code": "MISSING_TARGET", "error": "Provide --selector or --text for Tier 1 click."}

        target = cdp.eval_js(js)
        if not target or not target.get("found") or not target.get("visible"):
            return {"ok": False, "code": "ELEMENT_NOT_FOUND", "error": "Browser element not found or invisible."}

        cx = float(target["x"])
        cy = float(target["y"])
        cdp.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": cx, "y": cy})
        cdp.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": cx, "y": cy, "button": "left", "clickCount": 1})
        cdp.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": cx, "y": cy, "button": "left", "clickCount": 1})

        return {
            "ok": True,
            "tier": "tier1_browser",
            "background": True,
            "viewport_xy": [round(cx, 1), round(cy, 1)],
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }


def type_browser(selector: str, text: str, enter: bool = False) -> dict[str, Any]:
    t0 = time.perf_counter()
    ep = find_cdp_endpoint()
    if not ep:
        return {"ok": False, "code": "NO_CDP_ENDPOINT", "error": "No active CDP browser endpoint."}

    with CDPClient(ep["page"]["webSocketDebuggerUrl"], timeout=2.5) as cdp:
        gate = check_page_gate(cdp)
        if gate:
            return gate
        ok = cdp.eval_js(
            f"""(() => {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) return false;
                el.focus();
                return true;
            }})()"""
        )
        if not ok:
            return {"ok": False, "code": "ELEMENT_NOT_FOUND", "error": f"Selector '{selector}' not found."}

        cdp.call("Input.insertText", {"text": text})
        if enter:
            cdp.call("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "windowsVirtualKeyCode": 13})
            cdp.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "windowsVirtualKeyCode": 13})
        return {
            "ok": True,
            "tier": "tier1_browser",
            "background": True,
            "length": len(text),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }


def scroll_browser(dy: int = -3, dx: int = 0) -> dict[str, Any]:
    t0 = time.perf_counter()
    ep = find_cdp_endpoint()
    if not ep:
        return {"ok": False, "code": "NO_CDP_ENDPOINT", "error": "No active CDP browser endpoint."}
    with CDPClient(ep["page"]["webSocketDebuggerUrl"], timeout=2.0) as cdp:
        cdp.eval_js(f"window.scrollBy({int(dx) * -80}, {int(dy) * -120})")
        return {
            "ok": True,
            "tier": "tier1_browser",
            "background": True,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }


def extract_browser(selector: str = "body") -> dict[str, Any]:
    t0 = time.perf_counter()
    ep = find_cdp_endpoint()
    if not ep:
        return {"ok": False, "code": "NO_CDP_ENDPOINT", "error": "No active CDP browser endpoint."}
    with CDPClient(ep["page"]["webSocketDebuggerUrl"], timeout=2.5) as cdp:
        gate = check_page_gate(cdp)
        if gate:
            return gate
        data = cdp.eval_js(
            f"""(() => {{
                const el = document.querySelector({json.dumps(selector or "body")});
                return {{
                    url: location.href,
                    title: document.title,
                    text: el ? (el.innerText || el.textContent || '') : ''
                }};
            }})()"""
        )
        return {
            "ok": True,
            "tier": "tier1_browser",
            "url": data.get("url", ""),
            "title": data.get("title", ""),
            "text": str(data.get("text", ""))[:16000],
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }
