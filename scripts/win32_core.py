"""Shared 64-bit-safe Win32 ctypes bindings, DPI awareness, UIPI checks, and safety guards."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
from typing import Any

# Base scalar types
ULONG_PTR = ctypes.c_size_t
HWND = wintypes.HWND
HANDLE = wintypes.HANDLE
DWORD = wintypes.DWORD
WORD = wintypes.WORD
LONG = wintypes.LONG
BOOL = wintypes.BOOL
UINT = wintypes.UINT
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
LRESULT = ctypes.c_ssize_t

# Input constants
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
INPUT_HARDWARE = 2

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

MAPVK_VK_TO_VSC = 0

# Window & process constants
SW_RESTORE = 9
SW_SHOW = 5
GW_OWNER = 4
WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
BM_CLICK = 0x00F5

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TOKEN_INTEGRITY_LEVEL = 25

# Integrity RIDs
SECURITY_MANDATORY_UNTRUSTED_RID = 0x0000
SECURITY_MANDATORY_LOW_RID = 0x1000
SECURITY_MANDATORY_MEDIUM_RID = 0x2000
SECURITY_MANDATORY_MEDIUM_PLUS_RID = 0x2100
SECURITY_MANDATORY_HIGH_RID = 0x3000
SECURITY_MANDATORY_SYSTEM_RID = 0x4000

# System metrics
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

# Clipboard
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

# Safety rules
BLOCKED_SHORTCUT_BASES: tuple[frozenset[str], ...] = (
    frozenset({"alt", "f4"}),
    frozenset({"win", "l"}),
    frozenset({"win", "d"}),
    frozenset({"alt", "tab"}),
    frozenset({"win", "r"}),
    frozenset({"win", "x"}),
    frozenset({"win", "e"}),
    frozenset({"ctrl", "shift", "esc"}),
)

PROTECTED_PROCESSES: frozenset[str] = frozenset(
    {
        "csrss.exe",
        "wininit.exe",
        "winlogon.exe",
        "services.exe",
        "lsass.exe",
        "smss.exe",
        "lsaiso.exe",
        "dwm.exe",
        "explorer.exe",
    }
)

# Virtual key map
VK_MAP: dict[str, int] = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "shift": 0x10,
    "lshift": 0xA0,
    "rshift": 0xA1,
    "ctrl": 0x11,
    "control": 0x11,
    "lctrl": 0xA2,
    "rctrl": 0xA3,
    "alt": 0x12,
    "menu": 0x12,
    "lalt": 0xA4,
    "ralt": 0xA5,
    "pause": 0x13,
    "capslock": 0x14,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "pageup": 0x21,
    "pgup": 0x21,
    "pagedown": 0x22,
    "pgdn": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "printscreen": 0x2C,
    "insert": 0x2D,
    "delete": 0x2E,
    "del": 0x2E,
    "win": 0x5B,
    "lwin": 0x5B,
    "rwin": 0x5C,
    "meta": 0x5B,
    "cmd": 0x5B,
    "super": 0x5B,
}
for _i in range(1, 25):
    VK_MAP[f"f{_i}"] = 0x6F + _i
for _c in "0123456789":
    VK_MAP[_c] = ord(_c)
for _c in "abcdefghijklmnopqrstuvwxyz":
    VK_MAP[_c] = ord(_c.upper())

EXTENDED_VKS: frozenset[int] = frozenset(
    {
        0x21,
        0x22,
        0x23,
        0x24,
        0x25,
        0x26,
        0x27,
        0x28,
        0x2D,
        0x2E,
        0x5B,
        0x5C,
        0xA3,
        0xA5,
    }
)


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", LONG),
        ("dy", LONG),
        ("mouseData", DWORD),
        ("dwFlags", DWORD),
        ("time", DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", WORD),
        ("wScan", WORD),
        ("dwFlags", DWORD),
        ("time", DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", DWORD),
        ("wParamL", WORD),
        ("wParamH", WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _anonymous_ = ("_input",)
    _fields_ = [
        ("type", DWORD),
        ("_input", _INPUT_UNION),
    ]


if ctypes.sizeof(ctypes.c_void_p) == 8:
    assert ctypes.sizeof(INPUT) == 40, f"Expected 64-bit INPUT size 40, got {ctypes.sizeof(INPUT)}"


class POINT(ctypes.Structure):
    _fields_ = [("x", LONG), ("y", LONG)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", LONG),
        ("top", LONG),
        ("right", LONG),
        ("bottom", LONG),
    ]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", DWORD),
        ("flags", DWORD),
        ("hwndActive", HWND),
        ("hwndFocus", HWND),
        ("hwndCapture", HWND),
        ("hwndMenuOwner", HWND),
        ("hwndMoveSize", HWND),
        ("hwndCaret", HWND),
        ("rcCaret", RECT),
    ]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", DWORD)]


class TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [("Label", SID_AND_ATTRIBUTES)]


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
try:
    shcore = ctypes.WinDLL("shcore", use_last_error=True)
except OSError:
    shcore = None

# Configure key Win32 signatures cleanly for 64-bit pointers
user32.SendInput.argtypes = [UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = UINT
user32.WindowFromPoint.argtypes = [POINT]
user32.WindowFromPoint.restype = HWND
user32.GetWindowTextLengthW.argtypes = [HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(DWORD)]
user32.GetWindowThreadProcessId.restype = DWORD
user32.GetWindowRect.argtypes = [HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = BOOL
user32.IsIconic.argtypes = [HWND]
user32.IsIconic.restype = BOOL
user32.IsWindowVisible.argtypes = [HWND]
user32.IsWindowVisible.restype = BOOL
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = HWND
user32.SetForegroundWindow.argtypes = [HWND]
user32.SetForegroundWindow.restype = BOOL
user32.BringWindowToTop.argtypes = [HWND]
user32.BringWindowToTop.restype = BOOL
user32.ShowWindow.argtypes = [HWND, ctypes.c_int]
user32.ShowWindow.restype = BOOL
user32.AttachThreadInput.argtypes = [DWORD, DWORD, BOOL]
user32.AttachThreadInput.restype = BOOL
user32.GetGUIThreadInfo.argtypes = [DWORD, ctypes.POINTER(GUITHREADINFO)]
user32.GetGUIThreadInfo.restype = BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.MapVirtualKeyW.argtypes = [UINT, UINT]
user32.MapVirtualKeyW.restype = UINT
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = BOOL
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = BOOL
user32.SendMessageW.argtypes = [HWND, UINT, WPARAM, LPARAM]
user32.SendMessageW.restype = LRESULT
user32.PostMessageW.argtypes = [HWND, UINT, WPARAM, LPARAM]
user32.PostMessageW.restype = BOOL
user32.FindWindowExW.argtypes = [HWND, HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowExW.restype = HWND
user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFOEXW)]
user32.GetMonitorInfoW.restype = BOOL

kernel32.OpenProcess.argtypes = [DWORD, BOOL, DWORD]
kernel32.OpenProcess.restype = HANDLE
kernel32.CloseHandle.argtypes = [HANDLE]
kernel32.CloseHandle.restype = BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [HANDLE, DWORD, wintypes.LPWSTR, ctypes.POINTER(DWORD)]
kernel32.QueryFullProcessImageNameW.restype = BOOL
kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = DWORD
kernel32.GetCurrentProcessId.argtypes = []
kernel32.GetCurrentProcessId.restype = DWORD
kernel32.GlobalAlloc.argtypes = [UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
kernel32.GlobalUnlock.restype = BOOL
kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
kernel32.GlobalFree.restype = ctypes.c_void_p

user32.OpenClipboard.argtypes = [HWND]
user32.OpenClipboard.restype = BOOL
user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = BOOL
user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = BOOL
user32.GetClipboardData.argtypes = [UINT]
user32.GetClipboardData.restype = ctypes.c_void_p
user32.SetClipboardData.argtypes = [UINT, ctypes.c_void_p]
user32.SetClipboardData.restype = ctypes.c_void_p

advapi32.OpenProcessToken.argtypes = [HANDLE, DWORD, ctypes.POINTER(HANDLE)]
advapi32.OpenProcessToken.restype = BOOL
advapi32.GetTokenInformation.argtypes = [
    HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    DWORD,
    ctypes.POINTER(DWORD),
]
advapi32.GetTokenInformation.restype = BOOL
advapi32.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
advapi32.GetSidSubAuthority.argtypes = [ctypes.c_void_p, DWORD]
advapi32.GetSidSubAuthority.restype = ctypes.POINTER(DWORD)

_DPI_INITIALIZED = False


def enable_dpi_awareness() -> str:
    """Lock Per-Monitor DPI Awareness v2 so coordinates match physical screen pixels."""
    global _DPI_INITIALIZED
    if _DPI_INITIALIZED:
        return "already_initialized"
    try:
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = BOOL
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            _DPI_INITIALIZED = True
            return "per_monitor_v2"
    except Exception:
        pass
    if shcore is not None:
        try:
            hr = shcore.SetProcessDpiAwareness(2)
            if hr in (0, -2147024891):  # S_OK or E_ACCESSDENIED (already set)
                _DPI_INITIALIZED = True
                return "per_monitor_v1"
        except Exception:
            pass
    try:
        user32.SetProcessDPIAware()
        _DPI_INITIALIZED = True
        return "system_dpi_aware"
    except Exception:
        return "unaware"


def get_state_dir() -> Path:
    """Return runtime state directory (%LOCALAPPDATA%\\AntigravityControl or AGY_CONTROL_HOME)."""
    override = os.environ.get("AGY_CONTROL_HOME")
    if override:
        path = Path(override)
    else:
        local_app_data = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        path = Path(local_app_data) / "AntigravityControl"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_cursor_pos() -> tuple[int, int]:
    pt = POINT()
    if user32.GetCursorPos(ctypes.byref(pt)):
        return int(pt.x), int(pt.y)
    return 0, 0


def set_cursor_pos(x: int, y: int) -> bool:
    return bool(user32.SetCursorPos(int(x), int(y)))


def get_foreground_window() -> int:
    return int(user32.GetForegroundWindow() or 0)


def window_from_point(x: int, y: int) -> int:
    hwnd = user32.WindowFromPoint(POINT(int(x), int(y)))
    if not hwnd:
        return 0
    # GA_ROOT = 2
    user32.GetAncestor.argtypes = [HWND, UINT]
    user32.GetAncestor.restype = HWND
    root = user32.GetAncestor(hwnd, 2)
    return int(root or hwnd)


def get_process_name(pid: int) -> str:
    if not pid:
        return ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return Path(buf.value).name.lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def get_window_info(hwnd: int) -> dict[str, Any]:
    if not hwnd:
        return {
            "hwnd": 0,
            "title": "",
            "class_name": "",
            "pid": 0,
            "process_name": "",
            "rect": (0, 0, 0, 0),
            "is_iconic": False,
            "is_visible": False,
        }
    title_len = user32.GetWindowTextLengthW(hwnd)
    title_buf = ctypes.create_unicode_buffer(max(title_len + 2, 2))
    user32.GetWindowTextW(hwnd, title_buf, len(title_buf))

    cls_buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls_buf, len(cls_buf))

    pid = DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))

    return {
        "hwnd": int(hwnd),
        "title": title_buf.value,
        "class_name": cls_buf.value,
        "pid": int(pid.value),
        "process_name": get_process_name(int(pid.value)),
        "rect": (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)),
        "is_iconic": bool(user32.IsIconic(hwnd)),
        "is_visible": bool(user32.IsWindowVisible(hwnd)),
    }


def find_windows(
    title_query: str | None = None,
    process_query: str | None = None,
    class_query: str | None = None,
    visible_only: bool = True,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    enum_proc_t = ctypes.WINFUNCTYPE(BOOL, HWND, LPARAM)

    title_l = title_query.lower() if title_query else None
    proc_l = process_query.lower() if process_query else None
    cls_l = class_query.lower() if class_query else None

    def _cb(hwnd: int, _lparam: int) -> bool:
        if visible_only and not user32.IsWindowVisible(hwnd):
            return True
        info = get_window_info(hwnd)
        if title_l and title_l not in info["title"].lower():
            return True
        if proc_l and proc_l not in info["process_name"].lower():
            return True
        if cls_l and cls_l not in info["class_name"].lower():
            return True
        results.append(info)
        return True

    user32.EnumWindows.argtypes = [enum_proc_t, LPARAM]
    user32.EnumWindows.restype = BOOL
    user32.EnumWindows(enum_proc_t(_cb), 0)
    return results


def get_gui_thread_info(hwnd: int = 0) -> dict[str, Any]:
    tid = 0
    if hwnd:
        pid = DWORD(0)
        tid = int(user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)))
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(GUITHREADINFO)
    ok = user32.GetGUIThreadInfo(tid, ctypes.byref(info))
    if not ok:
        return {
            "ok": False,
            "hwnd_active": 0,
            "hwnd_focus": 0,
            "hwnd_caret": 0,
            "caret_rect": (0, 0, 0, 0),
        }
    return {
        "ok": True,
        "hwnd_active": int(info.hwndActive or 0),
        "hwnd_focus": int(info.hwndFocus or 0),
        "hwnd_caret": int(info.hwndCaret or 0),
        "caret_rect": (
            int(info.rcCaret.left),
            int(info.rcCaret.top),
            int(info.rcCaret.right),
            int(info.rcCaret.bottom),
        ),
    }


def integrity_label(rid: int | None) -> str:
    if rid is None:
        return "unknown"
    if rid < SECURITY_MANDATORY_LOW_RID:
        return "untrusted"
    if rid < SECURITY_MANDATORY_MEDIUM_RID:
        return "low"
    if rid < SECURITY_MANDATORY_HIGH_RID:
        return "medium"
    if rid < SECURITY_MANDATORY_SYSTEM_RID:
        return "high"
    return "system"


def get_process_integrity_level(pid: int | None = None) -> tuple[int | None, str]:
    target_pid = pid or int(kernel32.GetCurrentProcessId())
    h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, target_pid)
    if not h_proc:
        # Access denied when opening higher-integrity or protected process token
        err = ctypes.get_last_error()
        if err == 5:  # ERROR_ACCESS_DENIED
            return SECURITY_MANDATORY_HIGH_RID, "high_or_protected"
        return None, "unknown"
    h_tok = HANDLE()
    try:
        if not advapi32.OpenProcessToken(h_proc, TOKEN_QUERY, ctypes.byref(h_tok)):
            err = ctypes.get_last_error()
            if err == 5:
                return SECURITY_MANDATORY_HIGH_RID, "high_or_protected"
            return None, "unknown"
        needed = DWORD(0)
        advapi32.GetTokenInformation(h_tok, TOKEN_INTEGRITY_LEVEL, None, 0, ctypes.byref(needed))
        if needed.value == 0:
            return None, "unknown"
        buf = ctypes.create_string_buffer(needed.value)
        if not advapi32.GetTokenInformation(
            h_tok, TOKEN_INTEGRITY_LEVEL, buf, needed.value, ctypes.byref(needed)
        ):
            return None, "unknown"
        tml = ctypes.cast(buf, ctypes.POINTER(TOKEN_MANDATORY_LABEL)).contents
        count_ptr = advapi32.GetSidSubAuthorityCount(tml.Label.Sid)
        if not count_ptr:
            return None, "unknown"
        sub_count = count_ptr.contents.value
        if sub_count == 0:
            return None, "unknown"
        rid_ptr = advapi32.GetSidSubAuthority(tml.Label.Sid, sub_count - 1)
        rid = int(rid_ptr.contents.value)
        return rid, integrity_label(rid)
    finally:
        if h_tok:
            kernel32.CloseHandle(h_tok)
        kernel32.CloseHandle(h_proc)


def check_uipi_access(target_hwnd: int) -> dict[str, Any]:
    """Check in <1ms whether the current daemon can send UI input to target_hwnd."""
    cur_rid, cur_label = get_process_integrity_level(None)
    if not target_hwnd:
        return {
            "allowed": True,
            "current_rid": cur_rid,
            "current_label": cur_label,
            "target_rid": None,
            "target_label": "unknown",
        }
    pid = DWORD(0)
    user32.GetWindowThreadProcessId(target_hwnd, ctypes.byref(pid))
    tgt_rid, tgt_label = get_process_integrity_level(int(pid.value))
    if cur_rid is not None and tgt_rid is not None and tgt_rid > cur_rid:
        return {
            "allowed": False,
            "current_rid": cur_rid,
            "current_label": cur_label,
            "target_rid": tgt_rid,
            "target_label": tgt_label,
            "target_pid": int(pid.value),
        }
    return {
        "allowed": True,
        "current_rid": cur_rid,
        "current_label": cur_label,
        "target_rid": tgt_rid,
        "target_label": tgt_label,
        "target_pid": int(pid.value),
    }


def normalize_shortcut(combo: str) -> list[str]:
    aliases = {
        "control": "ctrl",
        "lctrl": "ctrl",
        "rctrl": "ctrl",
        "lshift": "shift",
        "rshift": "shift",
        "lalt": "alt",
        "ralt": "alt",
        "menu": "alt",
        "meta": "win",
        "cmd": "win",
        "super": "win",
        "lwin": "win",
        "rwin": "win",
        "return": "enter",
        "escape": "esc",
        "del": "delete",
    }
    tokens: list[str] = []
    for raw in combo.lower().replace("-", "+").split("+"):
        part = raw.strip()
        if not part:
            continue
        tokens.append(aliases.get(part, part))
    return tokens


def is_blocked_shortcut(combo: str, force: bool = False) -> tuple[bool, str | None]:
    if force:
        return False, None
    tokens = set(normalize_shortcut(combo))
    for blocked in BLOCKED_SHORTCUT_BASES:
        if blocked.issubset(tokens):
            return True, "+".join(sorted(blocked))
    return False, None


def is_process_elevated() -> bool:
    """Return True if the current process has Administrator elevation."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin() != 0)
    except Exception:
        rid, _ = get_process_integrity_level(None)
        return rid is not None and rid >= SECURITY_MANDATORY_HIGH_RID


def get_integrity_tag() -> str:
    """Return 'high' for elevated Admin sessions and 'medium' for standard sessions."""
    return "high" if is_process_elevated() else "medium"


def close_window_safe(hwnd: int) -> dict[str, Any]:
    """Close a window safely after verifying protected-process and UIPI boundaries."""
    if not hwnd:
        return {"ok": False, "code": "WINDOW_NOT_FOUND", "error": "No target window handle."}
    info = get_window_info(hwnd)
    proc_name = str(info.get("process_name", ""))
    if is_protected_process(proc_name):
        return {
            "ok": False,
            "code": "PROTECTED_PROCESS",
            "process_name": proc_name,
            "error": f"Refusing to close protected OS/shell process '{proc_name}'.",
        }
    uipi = check_uipi_access(hwnd)
    if not uipi["allowed"]:
        return {
            "ok": False,
            "code": "ELEVATION_REQUIRED",
            "error": f"Window '{info.get('title', '')}' requires '{uipi['target_label']}' integrity.",
            "uipi": uipi,
        }
    posted = bool(user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))
    return {
        "ok": posted,
        "tier": "tier2_uia",
        "hwnd": int(hwnd),
        "title": info.get("title", ""),
        "process_name": proc_name,
    }


def is_protected_process(process_name: str) -> bool:
    return process_name.strip().lower() in PROTECTED_PROCESSES


def is_panic_pressed() -> bool:
    """Detect physical emergency stop hotkey Ctrl+Alt+Esc."""
    ctrl = (user32.GetAsyncKeyState(0x11) & 0x8000) != 0
    alt = (user32.GetAsyncKeyState(0x12) & 0x8000) != 0
    esc = (user32.GetAsyncKeyState(0x1B) & 0x8000) != 0
    return ctrl and alt and esc


def get_desktop_environment() -> dict[str, Any]:
    """Return WindowStation and ThreadDesktop names without crossing desktop boundaries."""
    winsta_name = ""
    desktop_name = ""
    try:
        user32.GetProcessWindowStation.argtypes = []
        user32.GetProcessWindowStation.restype = HANDLE
        user32.GetThreadDesktop.argtypes = [DWORD]
        user32.GetThreadDesktop.restype = HANDLE
        user32.GetUserObjectInformationW.argtypes = [
            HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            DWORD,
            ctypes.POINTER(DWORD),
        ]
        user32.GetUserObjectInformationW.restype = BOOL

        hwinsta = user32.GetProcessWindowStation()
        hdesk = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
        needed = DWORD(0)
        if hwinsta:
            buf = ctypes.create_unicode_buffer(128)
            if user32.GetUserObjectInformationW(hwinsta, 2, buf, ctypes.sizeof(buf), ctypes.byref(needed)):
                winsta_name = buf.value
        if hdesk:
            buf = ctypes.create_unicode_buffer(128)
            if user32.GetUserObjectInformationW(hdesk, 2, buf, ctypes.sizeof(buf), ctypes.byref(needed)):
                desktop_name = buf.value
    except Exception:
        pass
    return {
        "window_station": winsta_name,
        "thread_desktop": desktop_name,
        "is_interactive_default": desktop_name.lower() == "default",
    }


def send_inputs(inputs: list[INPUT]) -> int:
    if not inputs:
        return 0
    arr = (INPUT * len(inputs))(*inputs)
    return int(user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT)))
