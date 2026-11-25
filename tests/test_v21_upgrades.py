"""Tests for v2.1 upgrades: integrity isolation, safe window close, lifecycle, hybrid snapshot, and auto-snapshot on miss."""

from pathlib import Path
from unittest.mock import patch

from scripts import bridge_daemon, cli
from scripts.engines import tier4_lowlevel
from scripts.fallback_router import FallbackRouter
from scripts.win32_core import close_window_safe


def test_integrity_isolated_daemon_and_key_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AGY_CONTROL_HOME", str(tmp_path))
    assert bridge_daemon.get_session_key_path("medium").name == "session_medium.key"
    assert bridge_daemon.get_session_key_path("high").name == "session_high.key"
    assert bridge_daemon.get_daemon_info_path("medium").name == "daemon_medium.json"
    assert bridge_daemon.get_daemon_info_path("high").name == "daemon_high.json"

    (tmp_path / "session_medium.key").write_text("m" * 64, encoding="utf-8")
    (tmp_path / "session_high.key").write_text("h" * 64, encoding="utf-8")
    assert cli._read_session_key("medium") == "m" * 64
    assert cli._read_session_key("high") == "h" * 64


def test_close_window_safe_refuses_protected_process() -> None:
    with patch(
        "scripts.win32_core.get_window_info",
        return_value={"hwnd": 12345, "title": "Program Manager", "process_name": "explorer.exe"},
    ):
        res = close_window_safe(12345)
        assert res["ok"] is False
        assert res["code"] == "PROTECTED_PROCESS"


def test_windows_clipboard_and_wait_timeout() -> None:
    router = FallbackRouter()
    fake_win = {
        "hwnd": 111,
        "title": "Demo Window",
        "process_name": "notepad.exe",
        "class_name": "Notepad",
        "rect": (0, 0, 800, 600),
        "is_iconic": False,
        "is_visible": True,
    }
    with (
        patch("scripts.fallback_router.find_windows", return_value=[fake_win]),
        patch("scripts.fallback_router.check_uipi_access", return_value={"allowed": True, "target_label": "medium"}),
    ):
        w_res = router.list_windows_cmd({})
        assert w_res["ok"] is True
        assert w_res["count"] == 1
        assert w_res["windows"][0]["category"] == "DESKTOP_APP"

    had_orig, orig_val = tier4_lowlevel.get_clipboard_text()
    try:
        assert router.clipboard_cmd({"action": "set", "text": "Kiểm thử v2.1"})["ok"] is True
        got = router.clipboard_cmd({"action": "get"})
        assert got["ok"] is True and got["text"] == "Kiểm thử v2.1"
        assert router.clipboard_cmd({"action": "clear"})["ok"] is True
    finally:
        tier4_lowlevel.set_clipboard_text(orig_val if had_orig else None)

    with patch("scripts.fallback_router.find_windows", return_value=[]):
        wait_res = router.wait_cmd({"window": "NeverExistsXYZ", "timeout_ms": 120})
        assert wait_res["ok"] is False
        assert wait_res["code"] == "WAIT_TIMEOUT"


def test_snapshot_auto_falls_back_from_empty_tree_to_vision() -> None:
    router = FallbackRouter()
    with (
        patch.object(
            router,
            "_resolve_target",
            return_value={"hwnd": 100, "title": "Demo", "process_name": "notepad.exe", "class_name": "Notepad"},
        ),
        patch("scripts.engines.tier2_uia.snapshot_uia_tree", return_value={"ok": True, "count": 0, "elements": []}),
        patch(
            "scripts.engines.tier3_vision.snapshot",
            return_value={"ok": True, "tier": "tier3_vision", "image_path": "snap_grid.png", "elapsed_ms": 15.0},
        ),
    ):
        res = router.snapshot({"mode": "auto"})
        assert res["ok"] is True
        assert res["tier"] == "tier3_vision"
        assert res["image_path"] == "snap_grid.png"


def test_click_attaches_fallback_snapshot_on_ocr_miss() -> None:
    router = FallbackRouter()
    with (
        patch.object(
            router,
            "_resolve_target",
            return_value={"hwnd": 200, "title": "CapCut", "process_name": "CapCut.exe", "class_name": "Qt6QWindowIcon"},
        ),
        patch("scripts.fallback_router.check_uipi_access", return_value={"allowed": True}),
        patch(
            "scripts.engines.tier25_ocr.find_text_on_screen",
            return_value={"ok": False, "code": "OCR_TEXT_NOT_FOUND", "lines": ["Timeline"]},
        ),
        patch(
            "scripts.engines.tier3_vision.snapshot",
            return_value={"ok": True, "image_path": "fallback_snap.png"},
        ),
    ):
        res = router.click({"text": "MissingIcon"})
        assert res["ok"] is False
        assert res["code"] == "OCR_TEXT_NOT_FOUND"
        assert res["fallback_snapshot_path"] == "fallback_snap.png"
