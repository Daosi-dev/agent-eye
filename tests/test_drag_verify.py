"""Tests for Single-Stroke Bezier/Fitts Drag & NCC Micro-Correction math."""

import numpy as np

from scripts.engines.tier3_vision import compute_micro_drag_compensation, find_template_ncc
from scripts.human_kinematics import generate_drag_path, generate_move_path


def test_bezier_fitts_drag_profile() -> None:
    pts, press_hold, release_hold = generate_drag_path(100, 200, 600, 240, mode="human")
    assert len(pts) >= 14
    assert 90.0 <= press_hold <= 140.0
    assert 60.0 <= release_hold <= 100.0
    assert (pts[-1].x, pts[-1].y) == (600, 240)
    # Fitts bell-curve: endpoints take longer per step than the cruise middle
    assert pts[0].delay_ms > pts[len(pts) // 2].delay_ms
    assert pts[-1].delay_ms > pts[len(pts) // 2].delay_ms

    turbo_pts = generate_move_path(0, 0, 500, 300, mode="turbo")
    assert sum(p.delay_ms for p in turbo_pts) <= 50.0


def test_ncc_detects_drag_error_and_computes_micro_correct() -> None:
    rng = np.random.default_rng(42)
    search = rng.integers(10, 40, size=(180, 180), dtype=np.uint8).astype(np.float32)

    # Create distinct 28x28 slider knob texture
    tpl = np.zeros((28, 28), dtype=np.float32)
    tpl[4:24, 4:24] = 180.0
    tpl[10:18, 10:18] = 250.0
    tpl[12:16, 6:22] = 60.0

    # Place knob 12px left and 7px down from search center (90, 90) -> at (78, 97)
    actual_cx, actual_cy = 78, 97
    search[actual_cy - 14 : actual_cy + 14, actual_cx - 14 : actual_cx + 14] = tpl

    mx, my, score = find_template_ncc(tpl, search)
    assert score > 0.99
    assert (mx, my) == (actual_cx, actual_cy)

    comp = compute_micro_drag_compensation(mx, my, 90, 90, score)
    assert comp["should_correct"] is True
    assert comp["delta_x"] == 12
    assert comp["delta_y"] == -7

    # Tolerance <= 4px should NOT trigger micro-drag
    comp_ok = compute_micro_drag_compensation(88, 92, 90, 90, score)
    assert comp_ok["should_correct"] is False
