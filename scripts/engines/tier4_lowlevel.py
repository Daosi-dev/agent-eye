"""Tier 4: Pre-Focus Guard, Hardware ScanCode SendInput, and Atomic Unicode Clipboard."""

from __future__ import annotations

import ctypes
import time
from typing import Any

from scripts.display_mapper import physical_to_sendinput_abs
from scripts.human_kinematics import generate_keystroke_timings
from scripts.win32_core import (
    CF_UNICODETEXT,
    EXTENDED_VKS,
    GMEM_MOVEABLE,
    INPUT,
    INPUT_KEYBOARD,
    INPUT_MOUSE,
    KEYBDINPUT,
    KEYEVENTF_EXTENDEDKEY,
    KEYEVENTF_KEYUP,
    KEYEVENTF_SCANCODE,
    KEYEVENTF_UNICODE,
    MAPVK_VK_TO_VSC,
    MOUSEEVENTF_ABSOLUTE,
    MOUSEEVENTF_HWHEEL,
    MOUSEEVENTF_LEFTDOWN,
    MOUSEEVENTF_LEFTUP,
    MOUSEEVENTF_MIDDLEDOWN,
    MOUSEEVENTF_MIDDLEUP,
    MOUSEEVENTF_MOVE,
    MOUSEEVENTF_RIGHTDOWN,
    MOUSEEVENTF_RIGHTUP,
    MOUSEEVENTF_VIRTUALDESK,
    MOUSEEVENTF_WHEEL,
    MOUSEINPUT,
    SW_RESTORE,
    VK_MAP,
    check_uipi_access,
    get_foreground_window,
    is_blocked_shortcut,
    kernel32,
    normalize_shortcut,
    send_inputs,
    user32,
)


def ensure_window_focus(hwnd: int, timeout_ms: int = 120) -> dict[str, Any]:
    """Safely activate target hwnd using AttachThreadInput after UIPI verification."""
    if not hwnd:
        return {"ok": True, "already_focused": True}
    uipi = check_uipi_access(hwnd)
    if not uipi["allowed"]:
        return {
            "ok": False,
            "code": "ELEVATION_REQUIRED",
            "error": (
                f"Target window requires '{uipi['target_label']}' integrity, "
                f"but daemon runs at '{uipi['current_label']}'."
            ),
            "uipi": uipi,
        }

    if get_foreground_window() == hwnd:
        return {"ok": True, "already_focused": True}

    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.03)

    pid = ctypes.c_ulong(0)
    target_tid = int(user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)))
    fg_hwnd = get_foreground_window()
    fg_tid = int(user32.GetWindowThreadProcessId(fg_hwnd, ctypes.byref(pid))) if fg_hwnd else 0
    cur_tid = int(kernel32.GetCurrentThreadId())

    attached_fg = False
    attached_tgt = False
    try:
        if fg_tid and fg_tid != cur_tid:
            attached_fg = bool(user32.AttachThreadInput(cur_tid, fg_tid, True))
        if target_tid and target_tid != cur_tid and target_tid != fg_tid:
            attached_tgt = bool(user32.AttachThreadInput(cur_tid, target_tid, True))

        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached_tgt:
            user32.AttachThreadInput(cur_tid, target_tid, False)
        if attached_fg:
            user32.AttachThreadInput(cur_tid, fg_tid, False)

    deadline = time.perf_counter() + (timeout_ms / 1000.0)
    while time.perf_counter() < deadline:
        if get_foreground_window() == hwnd:
            return {"ok": True, "already_focused": False}
        time.sleep(0.005)

    return {
        "ok": get_foreground_window() == hwnd,
        "already_focused": False,
        "foreground_hwnd": get_foreground_window(),
    }


def make_mouse_abs_input(phys_x: int, phys_y: int, flags: int, mouse_data: int = 0) -> INPUT:
    abs_x, abs_y = physical_to_sendinput_abs(phys_x, phys_y)
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi = MOUSEINPUT(
        dx=abs_x,
        dy=abs_y,
        mouseData=mouse_data & 0xFFFFFFFF,
        dwFlags=flags | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
        time=0,
        dwExtraInfo=0,
    )
    return inp


def move_mouse_abs(phys_x: int, phys_y: int) -> None:
    send_inputs([make_mouse_abs_input(phys_x, phys_y, MOUSEEVENTF_MOVE)])


def mouse_button_event(phys_x: int, phys_y: int, button: str, down: bool) -> None:
    flag_map = {
        ("left", True): MOUSEEVENTF_LEFTDOWN,
        ("left", False): MOUSEEVENTF_LEFTUP,
        ("right", True): MOUSEEVENTF_RIGHTDOWN,
        ("right", False): MOUSEEVENTF_RIGHTUP,
        ("middle", True): MOUSEEVENTF_MIDDLEDOWN,
        ("middle", False): MOUSEEVENTF_MIDDLEUP,
    }
    flag = flag_map[(button, down)]
    send_inputs([make_mouse_abs_input(phys_x, phys_y, MOUSEEVENTF_MOVE | flag)])


def send_mouse_click(phys_x: int, phys_y: int, button: str = "left", clicks: int = 1) -> None:
    for idx in range(max(1, clicks)):
        mouse_button_event(phys_x, phys_y, button, True)
        time.sleep(0.014)
        mouse_button_event(phys_x, phys_y, button, False)
        if idx < clicks - 1:
            time.sleep(0.055)


def send_mouse_wheel(phys_x: int, phys_y: int, dy: int = 0, dx: int = 0) -> None:
    move_mouse_abs(phys_x, phys_y)
    events: list[INPUT] = []
    if dy:
        events.append(make_mouse_abs_input(phys_x, phys_y, MOUSEEVENTF_WHEEL, int(dy) * 120))
    if dx:
        events.append(make_mouse_abs_input(phys_x, phys_y, MOUSEEVENTF_HWHEEL, int(dx) * 120))
    if events:
        send_inputs(events)


def _scancode_input(vk: int, key_up: bool = False) -> INPUT:
    scan = int(user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC))
    flags = KEYEVENTF_SCANCODE
    if vk in EXTENDED_VKS:
        flags |= KEYEVENTF_EXTENDEDKEY
    if key_up:
        flags |= KEYEVENTF_KEYUP
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki = KEYBDINPUT(wVk=0 if scan else vk, wScan=scan, dwFlags=flags if scan else (KEYEVENTF_KEYUP if key_up else 0), time=0, dwExtraInfo=0)
    return inp


def send_hotkey(combo: str, force: bool = False, target_hwnd: int = 0) -> dict[str, Any]:
    """Validate against blocked combos, ensure focus if target_hwnd given, and inject hardware scancodes."""
    blocked, matched = is_blocked_shortcut(combo, force=force)
    if blocked:
        return {
            "ok": False,
            "code": "BLOCKED_SHORTCUT",
            "error": f"Shortcut '{combo}' matched safety guard '{matched}'. Pass --force to override.",
        }
    if target_hwnd:
        foc = ensure_window_focus(target_hwnd)
        if not foc.get("ok") and foc.get("code") == "ELEVATION_REQUIRED":
            return foc

    tokens = normalize_shortcut(combo)
    if not tokens:
        return {"ok": False, "code": "INVALID_SHORTCUT", "error": "Empty key combo."}

    vks: list[int] = []
    for tok in tokens:
        vk = VK_MAP.get(tok)
        if vk is None and len(tok) == 1:
            vk = ord(tok.upper())
        if vk is None:
            return {"ok": False, "code": "UNKNOWN_KEY", "error": f"Unknown key token: '{tok}'"}
        vks.append(vk)

    downs = [_scancode_input(vk, key_up=False) for vk in vks]
    ups = [_scancode_input(vk, key_up=True) for vk in reversed(vks)]
    send_inputs(downs)
    time.sleep(0.018)
    send_inputs(ups)
    return {"ok": True, "tier": "tier4_lowlevel", "keys": tokens}


def _open_clipboard_retry(retries: int = 6) -> bool:
    for _ in range(retries):
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.005)
    return False


def get_clipboard_text() -> tuple[bool, str | None]:
    """Return (had_unicode_text, text_or_none)."""
    if not _open_clipboard_retry():
        return False, None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return False, None
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return False, None
        try:
            text = ctypes.wstring_at(ptr)
            return True, text
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text: str | None) -> bool:
    """Set CF_UNICODETEXT on Windows Clipboard (or empty if text is None)."""
    if not _open_clipboard_retry():
        return False
    try:
        user32.EmptyClipboard()
        if text is None:
            return True
        raw = text.encode("utf-16-le") + b"\x00\x00"
        hmem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(raw))
        if not hmem:
            return False
        ptr = kernel32.GlobalLock(hmem)
        if not ptr:
            kernel32.GlobalFree(hmem)
            return False
        try:
            ctypes.memmove(ptr, raw, len(raw))
        finally:
            kernel32.GlobalUnlock(hmem)
        if not user32.SetClipboardData(CF_UNICODETEXT, hmem):
            kernel32.GlobalFree(hmem)
            return False
        return True
    finally:
        user32.CloseClipboard()


def atomic_clipboard_paste(
    text: str,
    target_hwnd: int = 0,
    restore_delay_ms: int = 75,
    press_enter: bool = False,
) -> dict[str, Any]:
    """Save clipboard -> write UTF-16LE text -> Ctrl+V -> restore original clipboard."""
    if target_hwnd:
        foc = ensure_window_focus(target_hwnd)
        if not foc.get("ok") and foc.get("code") == "ELEVATION_REQUIRED":
            return foc

    had_prev, prev_text = get_clipboard_text()
    if not set_clipboard_text(text):
        return {"ok": False, "code": "CLIPBOARD_LOCKED", "error": "Failed to write Windows clipboard."}

    try:
        time.sleep(0.01)
        res = send_hotkey("ctrl+v", force=True)
        if not res.get("ok"):
            return res
        time.sleep(max(30, restore_delay_ms) / 1000.0)
        if press_enter:
            send_hotkey("enter", force=True)
            time.sleep(0.02)
    finally:
        set_clipboard_text(prev_text if had_prev else None)

    return {
        "ok": True,
        "tier": "tier4_lowlevel",
        "method": "atomic_clipboard_paste",
        "length": len(text),
        "clipboard_restored": True,
    }


def send_unicode_text(
    text: str,
    human: bool = False,
    target_hwnd: int = 0,
    press_enter: bool = False,
) -> dict[str, Any]:
    """Inject Unicode characters directly via KEYEVENTF_UNICODE (for --no-clipboard or --human)."""
    if target_hwnd:
        foc = ensure_window_focus(target_hwnd)
        if not foc.get("ok") and foc.get("code") == "ELEVATION_REQUIRED":
            return foc

    timings = generate_keystroke_timings(text) if human else [(ch, 4.0, 2.0) for ch in text]
    for ch, dwell_ms, flight_ms in timings:
        if ch == "\n":
            send_hotkey("enter", force=True)
        else:
            utf16 = ch.encode("utf-16-le")
            code_units = [int.from_bytes(utf16[i : i + 2], "little") for i in range(0, len(utf16), 2)]
            downs = []
            ups = []
            for cu in code_units:
                d = INPUT(type=INPUT_KEYBOARD)
                d.ki = KEYBDINPUT(wVk=0, wScan=cu, dwFlags=KEYEVENTF_UNICODE, time=0, dwExtraInfo=0)
                u = INPUT(type=INPUT_KEYBOARD)
                u.ki = KEYBDINPUT(wVk=0, wScan=cu, dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, time=0, dwExtraInfo=0)
                downs.append(d)
                ups.append(u)
            send_inputs(downs)
            if human:
                time.sleep(dwell_ms / 1000.0)
            send_inputs(ups)
        if human:
            time.sleep(flight_ms / 1000.0)

    if press_enter:
        send_hotkey("enter", force=True)

    return {
        "ok": True,
        "tier": "tier4_lowlevel",
        "method": "unicode_keystrokes",
        "human": human,
        "length": len(text),
    }
