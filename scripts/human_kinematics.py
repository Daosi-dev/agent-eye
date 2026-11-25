"""Adaptive Turbo & Humanized Mouse/Keyboard Kinematics (Bezier + WindMouse + Fitts)."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
import time
from typing import Callable

from scripts.win32_core import get_cursor_pos, is_panic_pressed


class HumanYieldInterrupt(RuntimeError):
    """Raised when Ctrl+Alt+Esc panic or physical user mouse takeover is detected."""


@dataclass
class PathPoint:
    x: int
    y: int
    delay_ms: float


def check_user_interrupt(expected_x: int | None = None, expected_y: int | None = None, tolerance_px: int = 22) -> None:
    """Abort immediately on panic hotkey or if the human user physically moved the mouse."""
    if is_panic_pressed():
        raise HumanYieldInterrupt("Emergency stop hotkey (Ctrl+Alt+Esc) pressed.")
    if expected_x is not None and expected_y is not None:
        cx, cy = get_cursor_pos()
        if math.hypot(cx - expected_x, cy - expected_y) > tolerance_px:
            raise HumanYieldInterrupt(
                f"User mouse movement detected (expected ({expected_x},{expected_y}), actual ({cx},{cy}))."
            )


def _cubic_bezier(p0: tuple[float, float], p1: tuple[float, float], p2: tuple[float, float], p3: tuple[float, float], t: float) -> tuple[float, float]:
    u = 1.0 - t
    tt = t * t
    uu = u * u
    uuu = uu * u
    ttt = tt * t
    x = uuu * p0[0] + 3 * uu * t * p1[0] + 3 * u * tt * p2[0] + ttt * p3[0]
    y = uuu * p0[1] + 3 * uu * t * p1[1] + 3 * u * tt * p2[1] + ttt * p3[1]
    return x, y


def _fitts_bell_weights(steps: int) -> list[float]:
    """Generate bell-curve step durations: 20% accel, 60% cruise, 20% decel."""
    if steps <= 1:
        return [1.0]
    weights: list[float] = []
    for i in range(steps):
        progress = i / max(1, steps - 1)
        # Speed profile peaks in middle -> delay per step is inverse of speed (slower at ends)
        speed = 0.35 + 0.65 * math.sin(progress * math.pi)
        weights.append(1.0 / max(0.25, speed))
    total = sum(weights)
    return [w / total for w in weights]


def generate_move_path(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    mode: str = "turbo",
    rng: random.Random | None = None,
) -> list[PathPoint]:
    """
    Generate move trajectory from (x1, y1) to (x2, y2).
    - turbo: 3-5 smooth fast points over 25-45ms.
    - human: Cubic Bezier + WindMouse micro-perturbation + Fitts bell-curve + optional overshoot.
    """
    r = rng or random.Random()
    dist = math.hypot(x2 - x1, y2 - y1)
    if dist < 2.0:
        return [PathPoint(int(x2), int(y2), 2.0)]

    if mode != "human":
        steps = 3 if dist < 250 else 5
        total_ms = 22.0 if dist < 250 else 38.0
        per_step = total_ms / steps
        pts: list[PathPoint] = []
        for i in range(1, steps + 1):
            t = i / steps
            # Slight ease-out curve
            eased = 1.0 - (1.0 - t) * (1.0 - t)
            px = round(x1 + (x2 - x1) * eased)
            py = round(y1 + (y2 - y1) * eased)
            pts.append(PathPoint(px, py, per_step))
        pts[-1] = PathPoint(int(x2), int(y2), per_step)
        return pts

    # Humanized mode: Cubic Bezier + WindMouse gravity/wind blend + optional overshoot
    dx = x2 - x1
    dy = y2 - y1
    nx = -dy / dist
    ny = dx / dist
    arc_mag = min(42.0, max(4.0, dist * r.uniform(0.05, 0.14))) * r.choice([-1.0, 1.0])

    c1 = (x1 + dx * r.uniform(0.22, 0.36) + nx * arc_mag, y1 + dy * r.uniform(0.22, 0.36) + ny * arc_mag)
    c2 = (x1 + dx * r.uniform(0.64, 0.80) + nx * (arc_mag * 0.45), y1 + dy * r.uniform(0.64, 0.80) + ny * (arc_mag * 0.45))

    # 25% overshoot chance for >300px moves
    target_x, target_y = float(x2), float(y2)
    do_overshoot = dist > 300.0 and r.random() < 0.25
    if do_overshoot:
        overshoot_px = r.uniform(3.0, 6.0)
        target_x = x2 + (dx / dist) * overshoot_px
        target_y = y2 + (dy / dist) * overshoot_px

    steps = max(12, min(42, int(dist / 18.0) + 8))
    total_ms = max(110.0, min(420.0, 95.0 + dist * 0.28))
    weights = _fitts_bell_weights(steps)

    wind_x = 0.0
    wind_y = 0.0
    sqrt3 = math.sqrt(3.0)
    points: list[PathPoint] = []
    for i in range(1, steps + 1):
        t = i / steps
        bx, by = _cubic_bezier((float(x1), float(y1)), c1, c2, (target_x, target_y), t)
        # WindMouse decaying perturbation
        decay = max(0.0, 1.0 - t)
        wind_x = wind_x / sqrt3 + (r.uniform(-1.0, 1.0) * 1.4 * decay)
        wind_y = wind_y / sqrt3 + (r.uniform(-1.0, 1.0) * 1.4 * decay)
        px = round(bx + wind_x)
        py = round(by + wind_y)
        if i >= steps - 2 and i < steps:
            px += r.choice([-1, 0, 1])
            py += r.choice([-1, 0, 1])
        points.append(PathPoint(px, py, total_ms * weights[i - 1]))

    if do_overshoot:
        # Smooth pull-back to exact target
        for k in range(1, 4):
            kt = k / 3.0
            px = round(target_x + (x2 - target_x) * kt)
            py = round(target_y + (y2 - target_y) * kt)
            points.append(PathPoint(px, py, r.uniform(12.0, 20.0)))

    points[-1] = PathPoint(int(x2), int(y2), max(6.0, points[-1].delay_ms))
    return points


def generate_drag_path(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    mode: str = "human",
    rng: random.Random | None = None,
) -> tuple[list[PathPoint], float, float]:
    """
    Generate single-stroke drag trajectory with gentle 3-8px arc and pre/post hold delays.
    Returns (stroke_points, press_hold_ms, release_hold_ms).
    """
    r = rng or random.Random()
    dist = math.hypot(x2 - x1, y2 - y1)
    if mode == "turbo":
        steps = 6 if dist < 200 else 10
        pts: list[PathPoint] = []
        for i in range(1, steps + 1):
            t = i / steps
            px = round(x1 + (x2 - x1) * t)
            py = round(y1 + (y2 - y1) * t)
            pts.append(PathPoint(px, py, 6.0))
        pts[-1] = PathPoint(int(x2), int(y2), 6.0)
        return pts, 35.0, 25.0

    # Humanized single-stroke drag
    press_hold_ms = r.uniform(90.0, 140.0)
    release_hold_ms = r.uniform(60.0, 100.0)

    if dist < 2.0:
        return [PathPoint(int(x2), int(y2), 12.0)], press_hold_ms, release_hold_ms

    dx = x2 - x1
    dy = y2 - y1
    nx = -dy / dist
    ny = dx / dist
    arc_px = r.uniform(3.0, 8.0) * r.choice([-1.0, 1.0])

    c1 = (x1 + dx * 0.28 + nx * arc_px, y1 + dy * 0.28 + ny * arc_px)
    c2 = (x1 + dx * 0.72 + nx * arc_px * 0.7, y1 + dy * 0.72 + ny * arc_px * 0.7)

    steps = max(14, min(48, int(dist / 12.0) + 10))
    total_ms = max(150.0, min(520.0, 120.0 + dist * 0.45))
    weights = _fitts_bell_weights(steps)

    pts = []
    for i in range(1, steps + 1):
        t = i / steps
        bx, by = _cubic_bezier((float(x1), float(y1)), c1, c2, (float(x2), float(y2)), t)
        pts.append(PathPoint(round(bx), round(by), total_ms * weights[i - 1]))
    pts[-1] = PathPoint(int(x2), int(y2), max(8.0, pts[-1].delay_ms))
    return pts, press_hold_ms, release_hold_ms


def generate_keystroke_timings(text: str, rng: random.Random | None = None) -> list[tuple[str, float, float]]:
    """Return list of (char, dwell_ms, flight_ms) following human typing distribution."""
    r = rng or random.Random()
    timings: list[tuple[str, float, float]] = []
    prev_upper = False
    for ch in text:
        dwell = max(40.0, min(100.0, r.gauss(65.0, 12.0)))
        flight = r.uniform(55.0, 160.0)
        is_upper = ch.isupper()
        if ch in (" ", ",", ".", ";", "!", "?") or (is_upper and not prev_upper):
            flight += r.uniform(80.0, 150.0)
        prev_upper = is_upper
        timings.append((ch, round(dwell, 1), round(flight, 1)))
    return timings


def execute_path(
    points: list[PathPoint],
    move_fn: Callable[[int, int], None],
    yield_guard: bool = True,
) -> None:
    """Step through generated path points while checking user mouse takeover & panic hotkey."""
    last_x: int | None = None
    last_y: int | None = None
    for pt in points:
        if yield_guard:
            check_user_interrupt(last_x, last_y)
        move_fn(pt.x, pt.y)
        last_x, last_y = pt.x, pt.y
        if pt.delay_ms > 0:
            time.sleep(pt.delay_ms / 1000.0)
