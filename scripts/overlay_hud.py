"""On-demand Click-Through Win32 Debug Overlay HUD (0% GPU/CPU when disabled)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from typing import Any

from scripts.display_mapper import get_monitor, list_monitors
from scripts.win32_core import enable_dpi_awareness, get_state_dir

WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_POPUP = 0x80000000

LWA_COLORKEY = 0x00000001
SW_SHOWNA = 8
SW_HIDE = 0

WM_PAINT = 0x000F
WM_TIMER = 0x0113
WM_DESTROY = 0x0002
WM_HOTKEY = 0x0312
WM_USER = 0x0400
WM_HUD_UPDATE = WM_USER + 42

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
VK_H = 0x48


def get_hud_info_path() -> Path:
    return get_state_dir() / "hud.json"


def read_hud_info() -> dict[str, Any] | None:
    p = get_hud_info_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def send_hud_event(event: dict[str, Any]) -> bool:
    """Fire-and-forget UDP packet to active HUD process (<0.2ms). No-op if HUD is off."""
    info = read_hud_info()
    if not info:
        return False
    port = int(info.get("port", 0))
    if not port:
        return False
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(json.dumps(event, ensure_ascii=False).encode("utf-8"), ("127.0.0.1", port))
        sock.close()
        return True
    except Exception:
        return False


def start_hud_process() -> dict[str, Any]:
    info = read_hud_info()
    if info:
        # Probe alive
        if send_hud_event({"type": "ping"}):
            return {"ok": True, "running": True, "reused": True, **info}

    repo = str(Path(__file__).resolve().parent.parent)
    exe = Path(sys.executable)
    py = str(exe.with_name("pythonw.exe")) if exe.name.lower() == "python.exe" and exe.with_name("pythonw.exe").exists() else str(exe)
    env = os.environ.copy()
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{repo}{os.pathsep}{existing_pp}" if existing_pp else repo

    subprocess.Popen(
        [py, "-m", "scripts.overlay_hud"],
        cwd=repo,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=0x08000000 | 0x00000200,
    )
    deadline = time.perf_counter() + 2.0
    while time.perf_counter() < deadline:
        info = read_hud_info()
        if info and info.get("port"):
            return {"ok": True, "running": True, "reused": False, **info}
        time.sleep(0.04)
    return {"ok": False, "code": "HUD_START_TIMEOUT", "error": "HUD process failed to start."}


def stop_hud_process() -> dict[str, Any]:
    sent = send_hud_event({"type": "quit"})
    p = get_hud_info_path()
    if p.exists():
        p.unlink(missing_ok=True)
    return {"ok": True, "stopped": sent}


def _run_hud_window() -> None:
    enable_dpi_awareness()
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    mon = get_monitor(0, list_monitors())
    vx, vy, vw, vh = mon["left"], mon["top"], mon["width"], mon["height"]

    state_lock = threading.Lock()
    state: dict[str, Any] = {
        "visible": True,
        "badge": "ANTIGRAVITY HUD READY (Ctrl+Alt+H)",
        "badge_ts": time.time(),
        "trails": [],  # list of (ts, [(x, y), ...], click_xy_or_none, arrow_or_none)
    }

    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t)

    class PAINTSTRUCT(ctypes.Structure):
        _fields_ = [
            ("hdc", wintypes.HDC),
            ("fErase", wintypes.BOOL),
            ("rcPaint", wintypes.RECT),
            ("fRestore", wintypes.BOOL),
            ("fIncUpdate", wintypes.BOOL),
            ("rgbReserved", ctypes.c_byte * 32),
        ]

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
            ("hIconSm", wintypes.HICON),
        ]

    class MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("message", wintypes.UINT),
            ("wParam", ctypes.c_size_t),
            ("lParam", ctypes.c_ssize_t),
            ("time", wintypes.DWORD),
            ("pt", wintypes.POINT),
        ]

    def _paint(hwnd: int) -> None:
        ps = PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
        if not hdc:
            return
        try:
            black_brush = gdi32.CreateSolidBrush(0x000000)
            rc_full = wintypes.RECT(0, 0, vw, vh)
            user32.FillRect(hdc, ctypes.byref(rc_full), black_brush)
            gdi32.DeleteObject(black_brush)

            now = time.time()
            with state_lock:
                if not state["visible"]:
                    return
                state["trails"] = [tr for tr in state["trails"] if now - tr[0] <= 1.25]
                badge = state["badge"]
                trails = list(state["trails"])

            # Draw badge top-right
            badge_bg = gdi32.CreateSolidBrush(0x281E14)  # BGR dark slate
            badge_pen = gdi32.CreatePen(0, 1, 0xFFE600)  # BGR cyan
            old_b = gdi32.SelectObject(hdc, badge_bg)
            old_p = gdi32.SelectObject(hdc, badge_pen)
            bx1 = max(10, vw - 360)
            gdi32.Rectangle(hdc, bx1, 14, vw - 16, 46)
            gdi32.SelectObject(hdc, old_b)
            gdi32.SelectObject(hdc, old_p)
            gdi32.DeleteObject(badge_bg)
            gdi32.DeleteObject(badge_pen)

            gdi32.SetBkMode(hdc, 1)  # TRANSPARENT
            gdi32.SetTextColor(hdc, 0xFFE600)  # Cyan
            user32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.RECT), wintypes.UINT]
            rc_txt = wintypes.RECT(bx1 + 10, 18, vw - 22, 44)
            user32.DrawTextW(hdc, badge, -1, ctypes.byref(rc_txt), 0x0020)

            # Draw cursor trails, click rings, and micro-drag vectors
            cyan_pen = gdi32.CreatePen(0, 2, 0xFFE600)
            red_pen = gdi32.CreatePen(0, 2, 0x4444FF)
            null_brush = gdi32.GetStockObject(5)  # NULL_BRUSH
            gdi32.SelectObject(hdc, null_brush)

            for _ts, pts, click_xy, arrow in trails:
                if len(pts) >= 2:
                    gdi32.SelectObject(hdc, cyan_pen)
                    p0x, p0y = pts[0][0] - vx, pts[0][1] - vy
                    gdi32.MoveToEx(hdc, p0x, p0y, None)
                    for px, py in pts[1:]:
                        gdi32.LineTo(hdc, px - vx, py - vy)
                if click_xy:
                    cx, cy = click_xy[0] - vx, click_xy[1] - vy
                    gdi32.SelectObject(hdc, red_pen)
                    gdi32.Ellipse(hdc, cx - 10, cy - 10, cx + 10, cy + 10)
                if arrow:
                    ax1, ay1 = arrow[0][0] - vx, arrow[0][1] - vy
                    ax2, ay2 = arrow[1][0] - vx, arrow[1][1] - vy
                    gdi32.SelectObject(hdc, red_pen)
                    gdi32.MoveToEx(hdc, ax1, ay1, None)
                    gdi32.LineTo(hdc, ax2, ay2)

            gdi32.DeleteObject(cyan_pen)
            gdi32.DeleteObject(red_pen)
        finally:
            user32.EndPaint(hwnd, ctypes.byref(ps))

    def _wndproc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        if msg == WM_PAINT:
            _paint(hwnd)
            return 0
        if msg == WM_TIMER:
            with state_lock:
                has_trails = len(state["trails"]) > 0
            if has_trails:
                user32.InvalidateRect(hwnd, None, False)
            return 0
        if msg == WM_HUD_UPDATE:
            user32.InvalidateRect(hwnd, None, False)
            return 0
        if msg == WM_HOTKEY:
            with state_lock:
                state["visible"] = not state["visible"]
                vis = state["visible"]
            user32.ShowWindow(hwnd, SW_SHOWNA if vis else SW_HIDE)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    wndproc_cb = WNDPROC(_wndproc)
    hinst = kernel32.GetModuleHandleW(None)
    cls_name = "AntigravityHumanControlHUD"

    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.lpfnWndProc = wndproc_cb
    wc.hInstance = hinst
    wc.lpszClassName = cls_name
    user32.RegisterClassExW(ctypes.byref(wc))

    ex_style = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    hwnd = user32.CreateWindowExW(ex_style, cls_name, "Antigravity HUD", WS_POPUP, vx, vy, vw, vh, None, None, hinst, None)
    user32.SetLayeredWindowAttributes(hwnd, 0x000000, 0, LWA_COLORKEY)
    user32.ShowWindow(hwnd, SW_SHOWNA)
    user32.RegisterHotKey(hwnd, 1, MOD_CONTROL | MOD_ALT, VK_H)
    user32.SetTimer(hwnd, 1, 60, None)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    udp_port = int(sock.getsockname()[1])

    info_path = get_hud_info_path()
    info_path.write_text(json.dumps({"port": udp_port, "pid": os.getpid()}), encoding="utf-8")

    def _udp_listener() -> None:
        while True:
            try:
                data, _ = sock.recvfrom(65535)
                ev = json.loads(data.decode("utf-8"))
                etype = ev.get("type")
                if etype == "quit":
                    user32.PostMessageW(hwnd, WM_DESTROY, 0, 0)
                    break
                if etype == "ping":
                    continue
                with state_lock:
                    if ev.get("tier"):
                        state["badge"] = str(ev["tier"])
                    pts = ev.get("points") or []
                    click_xy = ev.get("click")
                    arrow = None
                    if ev.get("start") and ev.get("end"):
                        arrow = (ev["start"], ev["end"])
                    if pts or click_xy or arrow:
                        state["trails"].append((time.time(), pts, click_xy, arrow))
                user32.PostMessageW(hwnd, WM_HUD_UPDATE, 0, 0)
            except Exception:
                break

    threading.Thread(target=_udp_listener, daemon=True).start()

    msg = MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    finally:
        sock.close()
        info_path.unlink(missing_ok=True)


if __name__ == "__main__":
    _run_hud_window()
