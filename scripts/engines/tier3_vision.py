"""Tier 3: Thread-safe MSS Snapshot, Outer-Ruler Grid, Adaptive Click, and Drag-Verify."""

from __future__ import annotations

import math
from pathlib import Path
import threading
import time
from typing import Any, Callable

import mss
from mss.exception import ScreenShotError
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from PIL import Image

from scripts.display_mapper import (
    get_monitor,
    list_monitors,
    norm_to_physical,
    physical_to_norm,
    render_outer_ruler_grid,
    render_zoom_crop,
)
from scripts.engines.tier4_lowlevel import (
    ensure_window_focus,
    mouse_button_event,
    move_mouse_abs,
    send_mouse_click,
)
from scripts.human_kinematics import (
    HumanYieldInterrupt,
    check_user_interrupt,
    execute_path,
    generate_drag_path,
    generate_move_path,
)
from scripts.win32_core import (
    check_uipi_access,
    find_windows,
    get_cursor_pos,
    get_desktop_environment,
    get_foreground_window,
    get_gui_thread_info,
    get_state_dir,
    set_cursor_pos,
    window_from_point,
)

_THREAD_LOCAL = threading.local()


class DesktopCaptureUnavailableError(RuntimeError):
    """Raised when screen capture is blocked in a locked, headless, or isolated desktop."""

    def __init__(self, message: str, desktop_env: dict[str, Any] | None = None):
        super().__init__(message)
        self.desktop_env = desktop_env or get_desktop_environment()


def _desktop_capture_error_payload(exc: DesktopCaptureUnavailableError) -> dict[str, Any]:
    return {
        "ok": False,
        "code": "DESKTOP_CAPTURE_UNAVAILABLE",
        "tier": "tier3_vision",
        "desktop": exc.desktop_env,
        "error": (
            "Screen capture unavailable in non-interactive, locked, or sandboxed desktop session "
            f"({exc.desktop_env.get('thread_desktop') or 'unknown'}): {exc}"
        ),
    }


def _get_mss() -> Any:
    """Each thread owns its own MSS instance because Windows GDI DCs are thread-bound."""
    sct = getattr(_THREAD_LOCAL, "sct", None)
    if sct is None:
        mss_cls = getattr(mss, "MSS", mss.mss)
        sct = mss_cls()
        _THREAD_LOCAL.sct = sct
    return sct


def capture_region_pil(left: int, top: int, width: int, height: int) -> Image.Image:
    sct = _get_mss()
    try:
        raw = sct.grab({"left": int(left), "top": int(top), "width": max(1, int(width)), "height": max(1, int(height))})
    except (ScreenShotError, OSError) as exc:
        raise DesktopCaptureUnavailableError(str(exc), get_desktop_environment()) from exc
    return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")


def capture_monitor_pil(monitor_index: int = 0) -> tuple[Image.Image, dict[str, Any], list[dict[str, Any]]]:
    mons = list_monitors()
    mon = get_monitor(monitor_index, mons)
    img = capture_region_pil(mon["left"], mon["top"], mon["width"], mon["height"])
    return img, mon, mons


def snapshot(
    monitor_index: int = 0,
    window_title: str | None = None,
    grid: bool = True,
    out_path: str | None = None,
) -> dict[str, Any]:
    """Capture screen (or matched window) and optionally render Outer-Ruler 1000x1000 frame."""
    t0 = time.perf_counter()
    mons = list_monitors()
    mon = get_monitor(monitor_index, mons)

    target_win: dict[str, Any] | None = None
    try:
        if window_title:
            matches = find_windows(title_query=window_title, visible_only=True)
            if matches:
                target_win = matches[0]
                l, t, r, b = target_win["rect"]
                w = max(1, r - l)
                h = max(1, b - t)
                pil_img = capture_region_pil(l, t, w, h)
                capture_bounds = {"left": l, "top": t, "width": w, "height": h, "scope": "window"}
            else:
                pil_img = capture_region_pil(mon["left"], mon["top"], mon["width"], mon["height"])
                capture_bounds = {
                    "left": mon["left"],
                    "top": mon["top"],
                    "width": mon["width"],
                    "height": mon["height"],
                    "scope": "monitor_fallback",
                }
        else:
            pil_img = capture_region_pil(mon["left"], mon["top"], mon["width"], mon["height"])
            capture_bounds = {
                "left": mon["left"],
                "top": mon["top"],
                "width": mon["width"],
                "height": mon["height"],
                "scope": "monitor",
            }
    except DesktopCaptureUnavailableError as exc:
        return _desktop_capture_error_payload(exc)

    snap_dir = get_state_dir() / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time() * 1000)

    raw_path = snap_dir / f"snap_{ts}_raw.png"
    pil_img.save(raw_path, format="PNG")

    final_img = render_outer_ruler_grid(pil_img) if grid else pil_img
    grid_path = Path(out_path) if out_path else (snap_dir / f"snap_{ts}_grid.png")
    grid_path.parent.mkdir(parents=True, exist_ok=True)
    final_img.save(grid_path, format="PNG")

    return {
        "ok": True,
        "tier": "tier3_vision",
        "image_path": str(grid_path),
        "raw_image_path": str(raw_path),
        "raw_size": [pil_img.width, pil_img.height],
        "output_size": [final_img.width, final_img.height],
        "grid_enabled": grid,
        "ruler_margin_px": 28 if grid else 0,
        "capture_bounds": capture_bounds,
        "monitor": mon,
        "monitors": mons,
        "window": target_win,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
    }


def _grab_gray_patch(cx: int, cy: int, size: int) -> np.ndarray:
    half = size // 2
    img = capture_region_pil(cx - half, cy - half, size, size).convert("L")
    return np.asarray(img, dtype=np.float32)


def find_template_ncc(template: np.ndarray, search_img: np.ndarray) -> tuple[int, int, float]:
    """
    Fast vectorized Normalized Cross-Correlation template search.
    Returns (best_center_x, best_center_y, ncc_score) relative to search_img top-left.
    """
    th, tw = template.shape
    sh, sw = search_img.shape
    if sh < th or sw < tw:
        return sw // 2, sh // 2, 0.0

    t_mean = float(template.mean())
    t_zero = template - t_mean
    t_norm = float(np.sqrt(np.sum(t_zero * t_zero)))
    if t_norm < 1e-5:
        return sw // 2, sh // 2, 0.0

    windows = sliding_window_view(search_img, (th, tw))  # shape: (sh - th + 1, sw - tw + 1, th, tw)
    w_mean = windows.mean(axis=(2, 3), keepdims=True)
    w_zero = windows - w_mean
    numerator = np.sum(w_zero * t_zero, axis=(2, 3))
    w_norm = np.sqrt(np.sum(w_zero * w_zero, axis=(2, 3)))
    denom = w_norm * t_norm

    scores = np.where(denom > 1e-5, numerator / denom, 0.0)
    best_idx = int(np.argmax(scores))
    iy, ix = divmod(best_idx, scores.shape[1])
    best_score = float(scores[iy, ix])
    return ix + tw // 2, iy + th // 2, best_score


def compute_micro_drag_compensation(
    matched_x: int,
    matched_y: int,
    target_x: int,
    target_y: int,
    ncc_score: float,
    min_confidence: float = 0.82,
    threshold_px: float = 4.0,
    max_shift_px: float = 65.0,
) -> dict[str, Any]:
    """Determine if a drag endpoint needs micro-correction without risking wild jumps."""
    dx = int(target_x - matched_x)
    dy = int(target_y - matched_y)
    dist = math.hypot(dx, dy)
    should_correct = (ncc_score >= min_confidence) and (threshold_px < dist <= max_shift_px)
    return {
        "should_correct": should_correct,
        "delta_x": dx,
        "delta_y": dy,
        "distance_px": round(dist, 2),
        "ncc_score": round(ncc_score, 4),
    }


def click_vision_physical(
    phys_x: int,
    phys_y: int,
    button: str = "left",
    clicks: int = 1,
    mode: str = "turbo",
    restore_cursor: bool = True,
    target_hwnd: int | None = None,
    hud_cb: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """
    Click physical pixel with:
    1) <1ms UIPI check
    2) Pre-Focus guard (avoids swallowed first click on inactive windows)
    3) Adaptive Turbo / Humanized trajectory + user-takeover yield
    4) 80x80 micro-patch & Caret verification (prevents accidental double-toggles)
    """
    t0 = time.perf_counter()
    orig_x, orig_y = get_cursor_pos()

    hwnd = target_hwnd or window_from_point(phys_x, phys_y)
    uipi = check_uipi_access(hwnd)
    if not uipi["allowed"]:
        return {
            "ok": False,
            "code": "ELEVATION_REQUIRED",
            "error": (
                f"Target window at ({phys_x},{phys_y}) requires '{uipi['target_label']}' integrity, "
                f"while daemon runs at '{uipi['current_label']}'."
            ),
            "uipi": uipi,
        }

    if hwnd and get_foreground_window() != hwnd:
        ensure_window_focus(hwnd)

    try:
        pre_patch = _grab_gray_patch(phys_x, phys_y, 80)
    except DesktopCaptureUnavailableError as exc:
        return _desktop_capture_error_payload(exc)
    pre_gui = get_gui_thread_info(hwnd)

    pts = generate_move_path(orig_x, orig_y, phys_x, phys_y, mode=mode)
    if hud_cb:
        hud_cb(
            {
                "type": "trail",
                "tier": f"TIER 3: VISION ({mode.upper()})",
                "points": [[p.x, p.y] for p in pts],
                "click": [phys_x, phys_y],
            }
        )

    try:
        execute_path(pts, move_mouse_abs, yield_guard=True)
        check_user_interrupt(phys_x, phys_y)
        send_mouse_click(phys_x, phys_y, button=button, clicks=clicks)
    except HumanYieldInterrupt as exc:
        return {
            "ok": False,
            "code": "USER_INTERRUPT",
            "error": str(exc),
            "phys_xy": [phys_x, phys_y],
        }

    time.sleep(0.025)
    post_patch = _grab_gray_patch(phys_x, phys_y, 80)
    post_gui = get_gui_thread_info(hwnd)

    diff = np.abs(post_patch - pre_patch)
    max_diff = float(diff.max())
    mean_diff = float(diff.mean())
    focus_changed = pre_gui.get("hwnd_focus") != post_gui.get("hwnd_focus")
    caret_changed = pre_gui.get("caret_rect") != post_gui.get("caret_rect")
    fg_ok = (not hwnd) or (get_foreground_window() == hwnd)

    escalated_t4 = False
    # Only retry via Tier 4 if window STILL isn't active AND zero micro-visual/caret reaction occurred
    if not fg_ok and max_diff < 2.0 and not focus_changed and not caret_changed:
        foc = ensure_window_focus(hwnd)
        if foc.get("ok"):
            send_mouse_click(phys_x, phys_y, button=button, clicks=clicks)
            escalated_t4 = True

    if restore_cursor and mode == "turbo":
        set_cursor_pos(orig_x, orig_y)

    nx, ny, mon_idx = physical_to_norm(phys_x, phys_y)
    return {
        "ok": True,
        "tier": "tier4_lowlevel" if escalated_t4 else "tier3_vision",
        "mode": mode,
        "phys_xy": [phys_x, phys_y],
        "norm_xy": [nx, ny],
        "monitor": mon_idx,
        "button": button,
        "clicks": clicks,
        "cursor_restored": bool(restore_cursor and mode == "turbo"),
        "verify": {
            "patch_max_diff": round(max_diff, 2),
            "patch_mean_diff": round(mean_diff, 2),
            "focus_changed": focus_changed,
            "caret_changed": caret_changed,
            "foreground_confirmed": (not hwnd) or (get_foreground_window() == hwnd),
        },
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
    }


def click_vision(
    norm_x: float,
    norm_y: float,
    monitor_index: int = 0,
    button: str = "left",
    clicks: int = 1,
    mode: str = "turbo",
    restore_cursor: bool = True,
    target_hwnd: int | None = None,
    hud_cb: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    phys_x, phys_y = norm_to_physical(norm_x, norm_y, monitor_index)
    return click_vision_physical(
        phys_x,
        phys_y,
        button=button,
        clicks=clicks,
        mode=mode,
        restore_cursor=restore_cursor,
        target_hwnd=target_hwnd,
        hud_cb=hud_cb,
    )


def drag_vision(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    monitor_index: int = 0,
    mode: str = "human",
    verify: bool = True,
    hud_cb: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """3-Phase Single-Stroke Drag: Estimate -> Bezier/Fitts Drag -> Verify & Micro-Correct."""
    t0 = time.perf_counter()
    mons = list_monitors()
    px1, py1 = norm_to_physical(x1, y1, monitor_index, mons)
    px2, py2 = norm_to_physical(x2, y2, monitor_index, mons)

    hwnd = window_from_point(px1, py1)
    uipi = check_uipi_access(hwnd)
    if not uipi["allowed"]:
        return {
            "ok": False,
            "code": "ELEVATION_REQUIRED",
            "error": (
                f"Drag target requires '{uipi['target_label']}' integrity, "
                f"while daemon runs at '{uipi['current_label']}'."
            ),
            "uipi": uipi,
        }
    if hwnd and get_foreground_window() != hwnd:
        ensure_window_focus(hwnd)

    # Capture 28x28 handle template before grabbing
    try:
        anchor_tpl = _grab_gray_patch(px1, py1, 28) if verify else None
    except DesktopCaptureUnavailableError as exc:
        return _desktop_capture_error_payload(exc)

    cur_x, cur_y = get_cursor_pos()
    approach_pts = generate_move_path(cur_x, cur_y, px1, py1, mode=mode)
    drag_pts, press_hold_ms, release_hold_ms = generate_drag_path(px1, py1, px2, py2, mode=mode)

    if hud_cb:
        hud_cb(
            {
                "type": "drag",
                "tier": f"TIER 3: DRAG ({mode.upper()})",
                "points": [[px1, py1]] + [[p.x, p.y] for p in drag_pts],
                "start": [px1, py1],
                "end": [px2, py2],
            }
        )

    try:
        execute_path(approach_pts, move_mouse_abs, yield_guard=True)
        mouse_button_event(px1, py1, "left", True)
        time.sleep(press_hold_ms / 1000.0)
        execute_path(drag_pts, move_mouse_abs, yield_guard=True)
        time.sleep(release_hold_ms / 1000.0)
        mouse_button_event(px2, py2, "left", False)
    except HumanYieldInterrupt as exc:
        mouse_button_event(px2, py2, "left", False)
        return {"ok": False, "code": "USER_INTERRUPT", "error": str(exc)}

    result: dict[str, Any] = {
        "ok": True,
        "tier": "tier3_vision",
        "mode": mode,
        "start_phys": [px1, py1],
        "target_phys": [px2, py2],
        "micro_corrected": False,
        "delta_px": [0, 0],
    }

    if verify and anchor_tpl is not None:
        time.sleep(0.14)
        search_size = 180
        half = search_size // 2
        post_rgb = capture_region_pil(px2 - half, py2 - half, search_size, search_size)
        post_gray = np.asarray(post_rgb.convert("L"), dtype=np.float32)

        match_rx, match_ry, score = find_template_ncc(anchor_tpl, post_gray)
        matched_px = (px2 - half) + match_rx
        matched_py = (py2 - half) + match_ry
        comp = compute_micro_drag_compensation(matched_px, matched_py, px2, py2, score)
        result["ncc_score"] = comp["ncc_score"]
        result["detected_delta_px"] = [comp["delta_x"], comp["delta_y"]]

        if comp["should_correct"]:
            corr_pts, p_hold, r_hold = generate_drag_path(matched_px, matched_py, px2, py2, mode="turbo")
            try:
                move_mouse_abs(matched_px, matched_py)
                time.sleep(0.02)
                mouse_button_event(matched_px, matched_py, "left", True)
                time.sleep(p_hold / 1000.0)
                execute_path(corr_pts, move_mouse_abs, yield_guard=True)
                time.sleep(r_hold / 1000.0)
                mouse_button_event(px2, py2, "left", False)
                result["micro_corrected"] = True
                result["delta_px"] = [comp["delta_x"], comp["delta_y"]]
                if hud_cb:
                    hud_cb(
                        {
                            "type": "micro_correct",
                            "tier": "TIER 3: MICRO-DRAG",
                            "start": [matched_px, matched_py],
                            "end": [px2, py2],
                        }
                    )
                time.sleep(0.08)
                post_rgb = capture_region_pil(px2 - half, py2 - half, search_size, search_size)
            except HumanYieldInterrupt:
                mouse_button_event(px2, py2, "left", False)

        crop = render_zoom_crop(post_rgb, half, half, radius=85, scale=2)
        snap_dir = get_state_dir() / "snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        crop_path = snap_dir / f"drag_verify_{int(time.time() * 1000)}.png"
        crop.save(crop_path, format="PNG")
        result["verify_crop_path"] = str(crop_path)

    result["elapsed_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    return result
