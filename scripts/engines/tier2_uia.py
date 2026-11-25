"""Tier 2: Windows IUIAutomation (comtypes) & Win32 #32770 Native File Dialog Fast-Path."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import ctypes
import threading
import time
from typing import Any

import comtypes
import comtypes.client

from scripts.win32_core import (
    BM_CLICK,
    WM_GETTEXT,
    WM_GETTEXTLENGTH,
    WM_SETTEXT,
    check_uipi_access,
    find_windows,
    get_foreground_window,
    get_window_info,
    user32,
)

_THREAD_LOCAL = threading.local()
_UIA_GEN_LOCK = threading.Lock()
_UIA_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="uia-worker")

# Pattern IDs from UIAutomationClient
UIA_INVOKE_PATTERN_ID = 10000
UIA_SELECTION_ITEM_PATTERN_ID = 10010
UIA_VALUE_PATTERN_ID = 10002
UIA_TOGGLE_PATTERN_ID = 10015
UIA_NAME_PROPERTY_ID = 30005
UIA_AUTOMATION_ID_PROPERTY_ID = 30011
UIA_CONTROL_TYPE_PROPERTY_ID = 30003


def _ensure_uia_client() -> tuple[Any, Any]:
    """Initialize thread-local COM MTA apartment & IUIAutomation singleton."""
    uia = getattr(_THREAD_LOCAL, "uia", None)
    mod = getattr(_THREAD_LOCAL, "mod", None)
    if uia is not None and mod is not None:
        return uia, mod

    # COINIT_MULTITHREADED = 0
    ctypes.windll.ole32.CoInitializeEx(None, 0)
    with _UIA_GEN_LOCK:
        mod = comtypes.client.GetModule("UIAutomationCore.dll")
    uia = comtypes.client.CreateObject(
        "{ff48dba4-60ef-4201-aa87-54103eef594e}",
        interface=mod.IUIAutomation,
    )
    _THREAD_LOCAL.uia = uia
    _THREAD_LOCAL.mod = mod
    return uia, mod


def check_uia_available() -> bool:
    try:
        uia, _ = _ensure_uia_client()
        return uia is not None
    except Exception:
        return False


def _find_descendant_hwnd_by_class(parent_hwnd: int, class_name: str) -> int:
    """Recursively locate first child window matching class_name (e.g. Edit in #32770)."""
    target_l = class_name.lower()
    found = 0
    enum_proc_t = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_ssize_t)

    def _cb(child_hwnd: int, _lp: int) -> int:
        nonlocal found
        buf = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(child_hwnd, buf, len(buf))
        if buf.value.lower() == target_l:
            found = int(child_hwnd)
            return 0
        return 1

    user32.EnumChildWindows.argtypes = [ctypes.c_void_p, enum_proc_t, ctypes.c_ssize_t]
    user32.EnumChildWindows.restype = ctypes.c_int
    user32.EnumChildWindows(parent_hwnd, enum_proc_t(_cb), 0)
    return found


def handle_file_dialog_fastpath(
    hwnd: int,
    text: str | None = None,
    submit: bool = True,
) -> dict[str, Any]:
    """Fill and submit Windows #32770 Open/Save As dialog silently via Win32 messages."""
    t0 = time.perf_counter()
    uipi = check_uipi_access(hwnd)
    if not uipi["allowed"]:
        return {"ok": False, "code": "ELEVATION_REQUIRED", "error": "Elevated file dialog.", "uipi": uipi}

    if text is not None:
        edit_hwnd = _find_descendant_hwnd_by_class(hwnd, "Edit")
        if not edit_hwnd:
            return {"ok": False, "code": "DIALOG_EDIT_NOT_FOUND", "error": "Could not locate Edit field in #32770 dialog."}
        buf = ctypes.create_unicode_buffer(text)
        user32.SendMessageW(edit_hwnd, WM_SETTEXT, 0, ctypes.addressof(buf))

    if submit:
        ok_btn = user32.FindWindowExW(hwnd, None, "Button", None)
        # Control ID 1 = IDOK ("Open" / "Save")
        dlg_item = user32.GetDlgItem(hwnd, 1) if hasattr(user32, "GetDlgItem") else ok_btn
        btn_hwnd = dlg_item or ok_btn
        if btn_hwnd:
            user32.PostMessageW(btn_hwnd, BM_CLICK, 0, 0)

    return {
        "ok": True,
        "tier": "tier2_uia",
        "method": "win32_file_dialog_fastpath",
        "background": True,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
    }


def _resolve_target_hwnd(title: str | None) -> int:
    if title:
        wins = find_windows(title_query=title, visible_only=True)
        if wins:
            return int(wins[0]["hwnd"])
    return get_foreground_window()


def _uia_find_by_text(root_el: Any, uia: Any, mod: Any, query: str) -> Any | None:
    """Fast TreeScope_Descendants search by exact Name first, then case-insensitive substring."""
    cond_exact = uia.CreatePropertyCondition(UIA_NAME_PROPERTY_ID, query)
    el = root_el.FindFirst(mod.TreeScope_Descendants, cond_exact)
    if el:
        return el

    # Bounded fallback walk over interactive controls
    true_cond = uia.CreateTrueCondition()
    arr = root_el.FindAll(mod.TreeScope_Descendants, true_cond)
    q_low = query.lower()
    count = min(arr.Length, 300) if arr else 0
    for i in range(count):
        cand = arr.GetElement(i)
        try:
            name = cand.CurrentName or ""
        except Exception:
            continue
        if q_low in name.lower():
            return cand
    return None


def _get_element_bounds(el: Any) -> tuple[int, int, int, int] | None:
    try:
        rc = el.CurrentBoundingRectangle
        w = int(rc.right - rc.left)
        h = int(rc.bottom - rc.top)
        if w <= 0 or h <= 0:
            return None
        if getattr(el, "CurrentIsOffscreen", 0):
            return None
        return int(rc.left), int(rc.top), int(rc.right), int(rc.bottom)
    except Exception:
        return None


def _click_uia_sync(hwnd: int, text: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    uia, mod = _ensure_uia_client()
    root = uia.ElementFromHandle(hwnd) if hwnd else uia.GetRootElement()
    if not root:
        return {"ok": False, "code": "UIA_NO_ROOT", "error": "Could not acquire UIA root element."}

    el = _uia_find_by_text(root, uia, mod, text)
    if not el:
        return {"ok": False, "code": "UIA_NOT_FOUND", "error": f"UIA element '{text}' not found."}

    bounds = _get_element_bounds(el)

    # Try semantic patterns first (100% background, zero mouse hijacking)
    for pat_id, method_name in (
        (UIA_INVOKE_PATTERN_ID, "Invoke"),
        (UIA_TOGGLE_PATTERN_ID, "Toggle"),
        (UIA_SELECTION_ITEM_PATTERN_ID, "Select"),
    ):
        try:
            unk = el.GetCurrentPattern(pat_id)
            if unk:
                if pat_id == UIA_INVOKE_PATTERN_ID:
                    unk.QueryInterface(mod.IUIAutomationInvokePattern).Invoke()
                elif pat_id == UIA_TOGGLE_PATTERN_ID:
                    unk.QueryInterface(mod.IUIAutomationTogglePattern).Toggle()
                else:
                    unk.QueryInterface(mod.IUIAutomationSelectionItemPattern).Select()
                return {
                    "ok": True,
                    "tier": "tier2_uia",
                    "background": True,
                    "pattern": method_name,
                    "bounds": list(bounds) if bounds else None,
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                }
        except Exception:
            continue

    if bounds is None:
        return {"ok": False, "code": "UIA_NO_BOUNDS", "error": "UIA element has empty or offscreen BoundingRectangle."}

    return {
        "ok": False,
        "code": "UIA_NO_PATTERN_HAS_BOUNDS",
        "bounds": list(bounds),
        "center_phys": [(bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2],
        "error": "UIA element found with bounds but no semantic Invoke pattern.",
    }


def _type_uia_sync(hwnd: int, text: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    info = get_window_info(hwnd)
    if info.get("class_name") == "#32770":
        return handle_file_dialog_fastpath(hwnd, text=text, submit=False)

    uia, mod = _ensure_uia_client()
    focused = uia.GetFocusedElement()
    if focused:
        try:
            unk = focused.GetCurrentPattern(UIA_VALUE_PATTERN_ID)
            if unk:
                vp = unk.QueryInterface(mod.IUIAutomationValuePattern)
                if not vp.CurrentIsReadOnly:
                    vp.SetValue(text)
                    return {
                        "ok": True,
                        "tier": "tier2_uia",
                        "background": True,
                        "method": "ValuePattern",
                        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                    }
        except Exception:
            pass
    return {"ok": False, "code": "UIA_VALUE_UNSUPPORTED", "error": "Focused control has no writable ValuePattern."}


def _extract_uia_sync(hwnd: int) -> dict[str, Any]:
    t0 = time.perf_counter()
    uia, mod = _ensure_uia_client()
    root = uia.ElementFromHandle(hwnd) if hwnd else uia.GetRootElement()
    if not root:
        return {"ok": False, "code": "UIA_NO_ROOT", "error": "No UIA root."}
    arr = root.FindAll(mod.TreeScope_Descendants, uia.CreateTrueCondition())
    texts: list[str] = []
    seen: set[str] = set()
    limit = min(arr.Length, 250) if arr else 0
    for i in range(limit):
        try:
            name = (arr.GetElement(i).CurrentName or "").strip()
        except Exception:
            continue
        if name and name not in seen:
            seen.add(name)
            texts.append(name)
    if not texts:
        return {"ok": False, "code": "UIA_EMPTY_TREE", "error": "UIA tree returned no readable names."}
    return {
        "ok": True,
        "tier": "tier2_uia",
        "text": "\n".join(texts)[:16000],
        "count": len(texts),
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
    }


def _run_with_deadline(fn: Any, *args: Any, timeout_ms: int = 80) -> dict[str, Any]:
    fut = _UIA_EXECUTOR.submit(fn, *args)
    try:
        return fut.result(timeout=timeout_ms / 1000.0)
    except FutureTimeoutError:
        return {
            "ok": False,
            "code": "UIA_TIMEOUT",
            "error": f"UIA operation exceeded {timeout_ms}ms circuit breaker.",
        }
    except Exception as exc:
        return {"ok": False, "code": "UIA_ERROR", "error": str(exc)}


def click_uia(text: str, title: str | None = None, timeout_ms: int = 80) -> dict[str, Any]:
    hwnd = _resolve_target_hwnd(title)
    if hwnd:
        uipi = check_uipi_access(hwnd)
        if not uipi["allowed"]:
            return {"ok": False, "code": "ELEVATION_REQUIRED", "error": "Target window is elevated.", "uipi": uipi}
    return _run_with_deadline(_click_uia_sync, hwnd, text, timeout_ms=timeout_ms)


def type_uia(text: str, title: str | None = None, timeout_ms: int = 80) -> dict[str, Any]:
    hwnd = _resolve_target_hwnd(title)
    if hwnd:
        uipi = check_uipi_access(hwnd)
        if not uipi["allowed"]:
            return {"ok": False, "code": "ELEVATION_REQUIRED", "error": "Target window is elevated.", "uipi": uipi}
    return _run_with_deadline(_type_uia_sync, hwnd, text, timeout_ms=timeout_ms)


INTERACTIVE_CONTROL_TYPES: dict[int, str] = {
    50000: "Button",
    50002: "CheckBox",
    50003: "ComboBox",
    50004: "Edit",
    50005: "Hyperlink",
    50007: "ListItem",
    50011: "MenuItem",
    50013: "RadioButton",
    50015: "Slider",
    50019: "TabItem",
    50024: "TreeItem",
}


def _snapshot_uia_tree_sync(hwnd: int, max_elements: int = 120) -> dict[str, Any]:
    from scripts.display_mapper import physical_to_norm

    t0 = time.perf_counter()
    uia, mod = _ensure_uia_client()
    root = uia.ElementFromHandle(hwnd) if hwnd else uia.GetRootElement()
    if not root:
        return {"ok": False, "code": "UIA_NO_ROOT", "error": "No UIA root."}

    arr = root.FindAll(mod.TreeScope_Descendants, uia.CreateTrueCondition())
    elements: list[dict[str, Any]] = []
    limit = min(arr.Length, 450) if arr else 0
    for i in range(limit):
        if len(elements) >= max_elements:
            break
        cand = arr.GetElement(i)
        try:
            ctype = int(cand.CurrentControlType)
        except Exception:
            continue
        role = INTERACTIVE_CONTROL_TYPES.get(ctype)
        if not role:
            continue
        bounds = _get_element_bounds(cand)
        if not bounds:
            continue
        try:
            name = (cand.CurrentName or "").strip()
        except Exception:
            name = ""
        cx = (bounds[0] + bounds[2]) // 2
        cy = (bounds[1] + bounds[3]) // 2
        nx, ny, mon_idx = physical_to_norm(cx, cy)
        elements.append(
            {
                "ref": f"e{len(elements) + 1}",
                "role": role,
                "name": name,
                "norm_xy": [nx, ny],
                "monitor": mon_idx,
                "rect": list(bounds),
            }
        )

    return {
        "ok": True,
        "tier": "tier2_uia",
        "mode": "tree",
        "hwnd": hwnd,
        "count": len(elements),
        "elements": elements,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
    }


def snapshot_uia_tree(
    title: str | None = None,
    max_elements: int = 120,
    timeout_ms: int = 100,
) -> dict[str, Any]:
    hwnd = _resolve_target_hwnd(title)
    if not hwnd:
        return {"ok": False, "code": "UIA_NO_WINDOW", "error": "No matching visible window for UIA tree snapshot."}
    return _run_with_deadline(_snapshot_uia_tree_sync, hwnd, max_elements, timeout_ms=timeout_ms)


def extract_uia(title: str | None = None, timeout_ms: int = 120) -> dict[str, Any]:
    hwnd = _resolve_target_hwnd(title)
    return _run_with_deadline(_extract_uia_sync, hwnd, timeout_ms=timeout_ms)
