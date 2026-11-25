"""Ultra-fast stdlib-only CLI gateway communicating with the Warm Daemon."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any


def _integrity_tag() -> str:
    try:
        return "high" if ctypes.windll.shell32.IsUserAnAdmin() != 0 else "medium"
    except Exception:
        return "medium"


def _state_dir() -> Path:
    override = os.environ.get("AGY_CONTROL_HOME")
    if override:
        p = Path(override)
    else:
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        p = Path(local) / "AntigravityControl"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _python_for_daemon() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":
        pyw = exe.with_name("pythonw.exe")
        if pyw.exists():
            return str(pyw)
    return str(exe)


def _read_daemon_info(tag: str | None = None) -> dict[str, Any] | None:
    t = tag or _integrity_tag()
    p = _state_dir() / f"daemon_{t}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_session_key(tag: str | None = None) -> str:
    t = tag or _integrity_tag()
    p = _state_dir() / f"session_{t}.key"
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8-sig").strip()


def _send_rpc(cmd: str, args: dict[str, Any], debug: bool = False, timeout: float = 30.0) -> dict[str, Any]:
    info = _read_daemon_info()
    key = _read_session_key()
    if not info or not key:
        raise ConnectionError("Daemon not initialized.")
    host = str(info.get("host", "127.0.0.1"))
    port = int(info["port"])
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        payload = json.dumps({"key": key, "cmd": cmd, "args": args, "debug": debug}, ensure_ascii=False) + "\n"
        sock.sendall(payload.encode("utf-8"))
        chunks: list[bytes] = []
        while True:
            buf = sock.recv(65536)
            if not buf:
                break
            chunks.append(buf)
            if b"\n" in buf:
                break
        raw = b"".join(chunks).split(b"\n", 1)[0]
        if not raw:
            raise ConnectionError("Empty response from daemon.")
        return json.loads(raw.decode("utf-8"))


def _ensure_daemon_running() -> dict[str, Any] | None:
    try:
        resp = _send_rpc("ping", {}, timeout=1.0)
        if resp.get("ok"):
            return resp
    except Exception:
        pass

    env = os.environ.copy()
    repo = str(_repo_root())
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{repo}{os.pathsep}{existing_pp}" if existing_pp else repo

    creation_flags = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [_python_for_daemon(), "-m", "scripts.bridge_daemon"],
        cwd=repo,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )

    deadline = time.perf_counter() + 8.0
    while time.perf_counter() < deadline:
        try:
            resp = _send_rpc("ping", {}, timeout=0.4)
            if resp.get("ok"):
                return resp
        except Exception:
            time.sleep(0.025)
    return None


def _handle_daemon_cmd(action: str) -> dict[str, Any]:
    if action == "status":
        try:
            t0 = time.perf_counter()
            resp = _send_rpc("ping", {}, timeout=1.0)
            resp["ipc_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
            resp["running"] = True
            return resp
        except Exception:
            return {"ok": True, "running": False}
    if action == "start":
        t0 = time.perf_counter()
        resp = _ensure_daemon_running()
        if not resp:
            return {"ok": False, "code": "DAEMON_START_FAILED", "error": "Timed out starting bridge_daemon."}
        resp["running"] = True
        resp["start_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
        return resp
    if action == "stop":
        try:
            return _send_rpc("shutdown", {}, timeout=2.0)
        except Exception:
            return {"ok": True, "message": "Daemon was not running."}
    if action == "restart":
        _handle_daemon_cmd("stop")
        time.sleep(0.1)
        return _handle_daemon_cmd("start")
    return {"ok": False, "code": "INVALID_ACTION", "error": f"Unknown daemon action: {action}"}


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--debug", action="store_true", help="Enable HUD telemetry for this command.")

    parser = argparse.ArgumentParser(
        prog="antigravity-control",
        description="Fast hybrid Windows & Browser control CLI backed by a Warm Daemon.",
        parents=[common],
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", parents=[common], help="Inspect DPI, monitors, browsers, OCR, UIA, and daemon latency.")

    p_daemon = sub.add_parser("daemon", parents=[common], help="Manage background Warm Daemon.")
    p_daemon.add_argument("action", choices=["start", "stop", "status", "restart"])

    p_snap = sub.add_parser("snapshot", parents=[common], help="Capture screenshot (vision/tree/auto) with Outer-Ruler 1000x1000 grid.")
    p_snap.add_argument("--monitor", type=int, default=0)
    p_snap.add_argument("--window", type=str, default=None)
    p_snap.add_argument("--mode", choices=["auto", "vision", "tree"], default="vision")
    p_snap.add_argument("--no-grid", action="store_true")
    p_snap.add_argument("--out", type=str, default=None)

    def _add_click_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--text", type=str, default=None)
        p.add_argument("--selector", type=str, default=None)
        p.add_argument("--title", type=str, default=None)
        p.add_argument("--x", type=float, default=None)
        p.add_argument("--y", type=float, default=None)
        p.add_argument("--monitor", type=int, default=0)
        p.add_argument("--button", choices=["left", "right", "middle"], default="left")
        p.add_argument("--clicks", type=int, default=1)
        p.add_argument("--human", action="store_true")
        p.add_argument("--no-restore-cursor", action="store_true")
        p.add_argument("--no-snapshot-on-fail", action="store_true")

    p_click = sub.add_parser("click", parents=[common], help="Click via smart capability routing (CDP/UIA/OCR/Vision).")
    _add_click_args(p_click)

    p_dclick = sub.add_parser("double_click", parents=[common], help="Double-click via smart routing.")
    _add_click_args(p_dclick)

    p_rclick = sub.add_parser("right_click", parents=[common], help="Right-click via smart routing.")
    _add_click_args(p_rclick)

    p_drag = sub.add_parser("drag", parents=[common], help="Single-stroke Bezier drag with verify & micro-correction.")
    p_drag.add_argument("--x1", type=float, required=True)
    p_drag.add_argument("--y1", type=float, required=True)
    p_drag.add_argument("--x2", type=float, required=True)
    p_drag.add_argument("--y2", type=float, required=True)
    p_drag.add_argument("--monitor", type=int, default=0)
    p_drag.add_argument("--turbo", action="store_true")
    p_drag.add_argument("--human", action="store_true")
    p_drag.add_argument("--no-verify", action="store_true")

    p_type = sub.add_parser("type", parents=[common], help="Input Unicode/Vietnamese text cleanly.")
    p_type.add_argument("--text", type=str, required=True)
    p_type.add_argument("--selector", type=str, default=None)
    p_type.add_argument("--title", type=str, default=None)
    p_type.add_argument("--human", action="store_true")
    p_type.add_argument("--no-clipboard", action="store_true")
    p_type.add_argument("--enter", action="store_true")

    p_hotkey = sub.add_parser("hotkey", parents=[common], help="Send hardware scan-code hotkey combination.")
    p_hotkey.add_argument("--keys", type=str, required=True)
    p_hotkey.add_argument("--title", type=str, default=None)
    p_hotkey.add_argument("--force", action="store_true")

    p_scroll = sub.add_parser("scroll", parents=[common], help="Scroll horizontally or vertically.")
    p_scroll.add_argument("--dy", type=int, default=-3)
    p_scroll.add_argument("--dx", type=int, default=0)
    p_scroll.add_argument("--x", type=float, default=None)
    p_scroll.add_argument("--y", type=float, default=None)
    p_scroll.add_argument("--monitor", type=int, default=0)
    p_scroll.add_argument("--selector", type=str, default=None)
    p_scroll.add_argument("--title", type=str, default=None)

    p_extract = sub.add_parser("extract", parents=[common], help="Extract DOM text, UIA text, or WinRT OCR lines.")
    p_extract.add_argument("--selector", type=str, default=None)
    p_extract.add_argument("--title", type=str, default=None)
    p_extract.add_argument("--monitor", type=int, default=0)
    p_extract.add_argument("--ocr", action="store_true")
    p_extract.add_argument("--image", type=str, default=None)

    p_browser = sub.add_parser("open_browser", parents=[common], help="Launch Chrome/Edge with persistent automation profile & CDP.")
    p_browser.add_argument("--url", type=str, default="about:blank")
    p_browser.add_argument("--browser", choices=["chrome", "edge", "brave", "auto"], default="auto")
    p_browser.add_argument("--headless", action="store_true")

    p_batch = sub.add_parser("batch", parents=[common], help="Execute a multi-step action pipeline in one call.")
    p_batch.add_argument("--steps", type=str, required=True, help="JSON array string or path to .json file.")
    p_batch.add_argument("--continue-on-error", action="store_true")

    p_hud = sub.add_parser("hud", parents=[common], help="Control optional click-through Visual Debug HUD.")
    p_hud.add_argument("action", choices=["on", "off", "status", "demo"])

    p_wins = sub.add_parser("windows", parents=[common], help="List visible windows with category and integrity metadata.")
    p_wins.add_argument("--title", type=str, default=None)
    p_wins.add_argument("--process", type=str, default=None)

    p_launch = sub.add_parser("launch", parents=[common], help="Launch an application executable and optionally wait for its window.")
    p_launch.add_argument("--target", type=str, required=True)
    p_launch.add_argument("--args", type=str, default="")
    p_launch.add_argument("--wait-title", type=str, default=None)
    p_launch.add_argument("--timeout-ms", type=int, default=4000)

    p_focus = sub.add_parser("focus", parents=[common], help="Focus and restore a window by title or hwnd.")
    p_focus.add_argument("--title", type=str, default=None)
    p_focus.add_argument("--hwnd", type=int, default=None)

    p_close = sub.add_parser("close", parents=[common], help="Safely close a window (refuses protected OS/shell processes).")
    p_close.add_argument("--title", type=str, default=None)
    p_close.add_argument("--hwnd", type=int, default=None)

    p_wait = sub.add_parser("wait", parents=[common], help="Wait for a window title or WinRT OCR text on screen.")
    p_wait.add_argument("--window", type=str, default=None)
    p_wait.add_argument("--text", type=str, default=None)
    p_wait.add_argument("--monitor", type=int, default=0)
    p_wait.add_argument("--timeout-ms", type=int, default=3000)

    p_clip = sub.add_parser("clipboard", parents=[common], help="Read, write, or clear the Windows clipboard.")
    p_clip.add_argument("action", choices=["get", "set", "clear"])
    p_clip.add_argument("--text", type=str, default="")

    return parser


def main(argv: list[str] | None = None) -> int:
    t_start = time.perf_counter()
    parser = build_parser()
    args = parser.parse_args(argv)
    debug = bool(getattr(args, "debug", False))

    if args.command == "daemon":
        out = _handle_daemon_cmd(args.action)
        out["cli_total_ms"] = round((time.perf_counter() - t_start) * 1000.0, 2)
        print(json.dumps(out, ensure_ascii=False))
        return 0 if out.get("ok") else 1

    if not _ensure_daemon_running():
        out = {"ok": False, "code": "DAEMON_UNAVAILABLE", "error": "Could not start or reach bridge_daemon."}
        print(json.dumps(out, ensure_ascii=False))
        return 1

    cmd = args.command
    payload_args: dict[str, Any] = vars(args).copy()
    payload_args.pop("command", None)
    payload_args.pop("debug", None)

    if cmd == "double_click":
        cmd = "click"
        payload_args["clicks"] = 2
    elif cmd == "right_click":
        cmd = "click"
        payload_args["button"] = "right"
    elif cmd == "batch":
        raw_steps = payload_args["steps"]
        step_path = Path(raw_steps)
        if step_path.exists() and step_path.is_file():
            payload_args["steps"] = json.loads(step_path.read_text(encoding="utf-8"))
        else:
            payload_args["steps"] = json.loads(raw_steps)

    try:
        out = _send_rpc(cmd, payload_args, debug=debug)
    except Exception as exc:
        out = {"ok": False, "code": "RPC_ERROR", "error": str(exc)}

    out["cli_total_ms"] = round((time.perf_counter() - t_start) * 1000.0, 2)
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
