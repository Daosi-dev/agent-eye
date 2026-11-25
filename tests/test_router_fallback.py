"""Tests for Smart Capability Router, RouteCache, Circuit Breaker, Safety Guards & Batch."""

import time
from unittest.mock import patch

from scripts.engines import tier2_uia
from scripts.fallback_router import FallbackRouter, RouteCache, classify_window, detect_human_gate
from scripts.win32_core import is_blocked_shortcut, is_protected_process


def test_window_classification_speed_and_accuracy() -> None:
    t0 = time.perf_counter()
    assert classify_window({"class_name": "#32770", "process_name": "chrome.exe"}) == "FILE_DIALOG"
    assert classify_window({"class_name": "Chrome_WidgetWin_1", "process_name": "chrome.exe"}) == "BROWSER"
    assert classify_window({"class_name": "Qt6QWindowIcon", "process_name": "CapCut.exe"}) == "CANVAS_APP"
    assert classify_window({"class_name": "Godot_Engine", "process_name": "Godot_v4.exe"}) == "CANVAS_APP"
    assert classify_window({"class_name": "Notepad", "process_name": "notepad.exe"}) == "DESKTOP_APP"
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert elapsed_ms < 5.0


def test_route_cache_auto_promotes_after_two_uia_misses() -> None:
    cache = RouteCache()
    win = {"process_name": "custom_ui.exe", "class_name": "CustomCanvas"}
    assert cache.get(win).preferred_tier is None
    cache.record_uia_miss(win)
    assert cache.get(win).preferred_tier is None
    cache.record_uia_miss(win)
    assert cache.get(win).preferred_tier == "tier25_ocr"


def test_uia_circuit_breaker_timeout() -> None:
    def _slow_op() -> dict:
        time.sleep(0.35)
        return {"ok": True}

    t0 = time.perf_counter()
    res = tier2_uia._run_with_deadline(_slow_op, timeout_ms=80)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert not res["ok"]
    assert res["code"] == "UIA_TIMEOUT"
    assert elapsed_ms < 180.0


def test_human_gate_and_safety_guards() -> None:
    assert detect_human_gate("Please Verify you are human to continue")
    assert detect_human_gate("Powered by cf-turnstile")
    assert not detect_human_gate("Welcome to Antigravity Documentation")

    blocked, _ = is_blocked_shortcut("win+l")
    assert blocked
    blocked_meta, _ = is_blocked_shortcut("meta+shift+d")
    assert blocked_meta
    blocked_forced, _ = is_blocked_shortcut("win+l", force=True)
    assert not blocked_forced

    assert is_protected_process("lsass.exe")
    assert not is_protected_process("notepad.exe")


def test_elevation_required_guard() -> None:
    router = FallbackRouter()
    with (
        patch.object(router, "_resolve_target", return_value={"hwnd": 99999, "title": "Admin App", "process_name": "cmd.exe", "class_name": "ConsoleWindowClass"}),
        patch("scripts.fallback_router.check_uipi_access", return_value={"allowed": False, "current_label": "medium", "target_label": "high"}),
    ):
        res = router.click({"text": "OK"})
        assert not res["ok"]
        assert res["code"] == "ELEVATION_REQUIRED"


def test_batch_stops_on_error() -> None:
    router = FallbackRouter()
    res = router.batch(
        {
            "steps": [
                {"action": "sleep", "ms": 5},
                {"action": "hotkey", "keys": "win+l"},
                {"action": "sleep", "ms": 5},
            ]
        }
    )
    assert not res["ok"]
    assert res["failed_step"] == 1
    assert res["code"] == "BLOCKED_SHORTCUT"
    assert len(res["results"]) == 2
