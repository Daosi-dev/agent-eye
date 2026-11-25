"""Tests for Atomic Vietnamese Unicode Clipboard round-trip and OCR diacritic matching."""

from unittest.mock import patch

from scripts.engines.tier25_ocr import strip_diacritics
from scripts.engines.tier4_lowlevel import (
    atomic_clipboard_paste,
    get_clipboard_text,
    set_clipboard_text,
)


def test_vietnamese_clipboard_roundtrip_and_restore() -> None:
    had_orig, orig_val = get_clipboard_text()
    sentinel = "Sentinel Before Test — Giữ nguyên dữ liệu!"
    vn_payload = "Xin chào Việt Nam — Đắk Lắk 100%!"

    try:
        assert set_clipboard_text(sentinel)
        ok, read_back = get_clipboard_text()
        assert ok and read_back == sentinel

        with patch("scripts.engines.tier4_lowlevel.send_hotkey", return_value={"ok": True}):
            res = atomic_clipboard_paste(vn_payload, restore_delay_ms=30)
            assert res["ok"] is True
            assert res["clipboard_restored"] is True

        ok_after, after_val = get_clipboard_text()
        assert ok_after and after_val == sentinel
    finally:
        set_clipboard_text(orig_val if had_orig else None)


def test_vietnamese_diacritic_strip_matching() -> None:
    assert strip_diacritics("Xuất Video Đỉnh Cao") == "xuat video dinh cao"
    assert strip_diacritics("Đăng Nhập") == "dang nhap"
