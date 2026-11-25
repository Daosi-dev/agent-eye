"""Tests for 64-bit INPUT size, DPI awareness, multi-monitor math, and Outer-Ruler rendering."""

import ctypes
from PIL import Image

from scripts.display_mapper import (
    norm_to_physical,
    physical_to_norm,
    physical_to_sendinput_abs,
    render_outer_ruler_grid,
)
from scripts.win32_core import INPUT, enable_dpi_awareness


def test_x64_input_struct_size() -> None:
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        assert ctypes.sizeof(INPUT) == 40


def test_dpi_awareness_enabled() -> None:
    mode = enable_dpi_awareness()
    assert mode in {"per_monitor_v2", "per_monitor_v1", "system_dpi_aware", "already_initialized"}


def test_negative_multimonitor_roundtrip() -> None:
    monitors = [
        {"index": 0, "left": 0, "top": 0, "right": 1920, "bottom": 1080, "width": 1920, "height": 1080, "is_primary": True},
        {"index": 1, "left": -1366, "top": 0, "right": 0, "bottom": 768, "width": 1366, "height": 768, "is_primary": False},
    ]
    for mon_idx in (0, 1):
        for nx, ny in ((0.0, 0.0), (250.0, 500.0), (500.0, 500.0), (1000.0, 1000.0)):
            px, py = norm_to_physical(nx, ny, monitor_index=mon_idx, monitors=monitors)
            rx, ry, r_idx = physical_to_norm(px, py, monitor_index=mon_idx, monitors=monitors)
            assert r_idx == mon_idx
            assert abs(rx - nx) <= 1.2
            assert abs(ry - ny) <= 1.2

    # Negative monitor origin maps cleanly inside Virtual Screen 0..65535
    vs = {"left": -1366, "top": 0, "width": 3286, "height": 1080}
    ax_left, ay_top = physical_to_sendinput_abs(-1366, 0, virtual_bounds=vs)
    ax_right, ay_bot = physical_to_sendinput_abs(1919, 1079, virtual_bounds=vs)
    assert ax_left == 0 and ay_top == 0
    assert ax_right == 65535 and ay_bot == 65535


def test_outer_ruler_dimensions() -> None:
    img = Image.new("RGB", (800, 600), (40, 45, 55))
    out = render_outer_ruler_grid(img, margin=28)
    assert out.size == (856, 656)
    # Center pixel remains clean (only subtle translucent hairline if on grid line, not solid label)
    center_px = out.getpixel((28 + 375, 28 + 275))
    assert center_px == (40, 45, 55)
