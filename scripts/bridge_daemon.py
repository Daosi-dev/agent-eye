"""Persistent Warm Daemon over authenticated 127.0.0.1 TCP_NODELAY socket."""

from __future__ import annotations

import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import socketserver
import subprocess
import sys
import threading
import time
from typing import Any

from scripts.win32_core import (
    enable_dpi_awareness,
    get_integrity_tag,
    get_process_integrity_level,
    get_state_dir,
)

enable_dpi_awareness()


def get_session_key_path(tag: str | None = None) -> Path:
    t = tag or get_integrity_tag()
    return get_state_dir() / f"session_{t}.key"


def get_daemon_info_path(tag: str | None = None) -> Path:
    t = tag or get_integrity_tag()
    return get_state_dir() / f"daemon_{t}.json"


def ensure_session_key(tag: str | None = None) -> str:
    t = tag or get_integrity_tag()
    key_path = get_session_key_path(t)
    if key_path.exists():
        val = key_path.read_text(encoding="utf-8-sig").strip()
        if len(val) >= 32:
            return val
    val = secrets.token_hex(32)
    key_path.write_text(val, encoding="utf-8")
    # Restrict ACL strictly by integrity level
    try:
        if t == "high":
            # Administrators (*S-1-5-32-544) & SYSTEM (*S-1-5-18) only; Medium processes cannot read
            subprocess.run(
                [
                    "icacls",
                    str(key_path),
                    "/inheritance:r",
                    "/grant:r",
                    "*S-1-5-32-544:(R,W)",
                    "/grant:r",
                    "*S-1-5-18:(F)",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                creationflags=0x08000000,
            )
        else:
            username = os.environ.get("USERNAME", "")
            if username:
                subprocess.run(
                    ["icacls", str(key_path), "/inheritance:r", "/grant:r", f"{username}:(R,W)"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    creationflags=0x08000000,
                )
    except Exception:
        pass
    return val


class _DaemonServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], handler_cls: Any, router: Any, session_key: str):
        self.router = router
        self.session_key = session_key
        self.started_at = time.time()
        self.shutdown_event = threading.Event()
        super().__init__(server_address, handler_cls)


class _RequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        while True:
            raw = self.rfile.readline(4 * 1024 * 1024)
            if not raw:
                break
            t0 = time.perf_counter()
            try:
                req = json.loads(raw.decode("utf-8"))
            except Exception as exc:
                self._send({"ok": False, "code": "INVALID_JSON", "error": str(exc)})
                continue

            key = str(req.get("key", ""))
            if not hmac.compare_digest(key.encode("utf-8"), self.server.session_key.encode("utf-8")):
                self._send({"ok": False, "code": "AUTH_FAILED", "error": "Invalid session key."})
                continue

            cmd = str(req.get("cmd", ""))
            args = req.get("args") or {}
            debug = bool(req.get("debug", False))

            if cmd == "ping":
                rid, label = get_process_integrity_level(None)
                resp: dict[str, Any] = {
                    "ok": True,
                    "pid": os.getpid(),
                    "uptime_s": round(time.time() - self.server.started_at, 2),
                    "integrity": label,
                    "integrity_rid": rid,
                }
            elif cmd == "shutdown":
                resp = {"ok": True, "message": "Daemon shutting down."}
                self._send(resp)
                self.server.shutdown_event.set()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            else:
                try:
                    resp = self.server.router.dispatch(cmd, args, debug=debug)
                except Exception as exc:
                    resp = {"ok": False, "code": "INTERNAL_ERROR", "error": str(exc)}

            resp["daemon_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
            self._send(resp)

    def _send(self, payload: dict[str, Any]) -> None:
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        self.wfile.write(data)
        self.wfile.flush()


def run_daemon(port: int = 0) -> None:
    from scripts.fallback_router import FallbackRouter

    session_key = ensure_session_key()
    router = FallbackRouter()
    server = _DaemonServer(("127.0.0.1", port), _RequestHandler, router, session_key)
    actual_port = int(server.server_address[1])

    info_path = get_daemon_info_path()
    info_path.write_text(
        json.dumps(
            {
                "host": "127.0.0.1",
                "port": actual_port,
                "pid": os.getpid(),
                "python": sys.executable,
                "started_at": time.time(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        try:
            router.close()
        except Exception:
            pass
        try:
            if info_path.exists():
                cur = json.loads(info_path.read_text(encoding="utf-8"))
                if cur.get("pid") == os.getpid():
                    info_path.unlink(missing_ok=True)
        except Exception:
            pass
        server.server_close()


if __name__ == "__main__":
    p = int(os.environ.get("AGY_DAEMON_PORT", "0"))
    run_daemon(p)
