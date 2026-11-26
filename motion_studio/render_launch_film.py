"""Zero-Neon Swiss Editorial Motion Graphics Renderer (1920x1080 @ 60fps, 32.0s)."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import skia

from motion_studio.audio_dsp import DURATION_SEC, build_audio_track
from motion_studio.skia_primitives import (
    DARK_EDGE,
    GRAPHITE,
    HEIGHT,
    INK,
    MATTE_DARK,
    PAPER,
    RULE,
    SAGE,
    SLATE_BAR,
    STONE,
    VERMILION,
    WHITE,
    WIDTH,
    clamp01,
    draw_aperture_logo,
    draw_bezier_arc,
    draw_cursor,
    draw_editorial_chrome,
    draw_masked_tracked_text,
    draw_paper_backdrop,
    draw_paper_card,
    draw_tag,
    draw_tracked_text,
    draw_vector_check,
    ease_in_out_cubic,
    ease_in_out_quart,
    ease_out_expo,
    ease_out_quint,
    get_font,
    measure_tracked_text,
    rgba,
    spring_snappy,
)

FPS = 60
TOTAL_FRAMES = int(round(DURATION_SEC * FPS))  # 1,920 frames

# Reusable offscreen surfaces for optical DOF and architectural curtain wipes
_BROWSER_DOF_SURF: skia.Surface | None = None
_OUT_SURF: skia.Surface | None = None
_IN_SURF: skia.Surface | None = None


def _get_dof_surface() -> skia.Surface:
    global _BROWSER_DOF_SURF
    if _BROWSER_DOF_SURF is None:
        _BROWSER_DOF_SURF = skia.Surface(WIDTH // 2, HEIGHT // 2)
    return _BROWSER_DOF_SURF


def _get_transition_surfaces() -> tuple[skia.Surface, skia.Surface]:
    global _OUT_SURF, _IN_SURF
    if _OUT_SURF is None:
        _OUT_SURF = skia.Surface(WIDTH, HEIGHT)
    if _IN_SURF is None:
        _IN_SURF = skia.Surface(WIDTH, HEIGHT)
    return _OUT_SURF, _IN_SURF


# ---------------------------------------------------------------------------
# Act I (0.0s - 5.10s): Swiss Kinetic Type + Architectural Brand Specimen
# ---------------------------------------------------------------------------
def _draw_act1_hook(canvas: skia.Canvas, t: float) -> None:
    line1 = "AI agents write code."
    w1 = measure_tracked_text("sans_semi", 84, line1, -0.035)
    draw_masked_tracked_text(
        canvas,
        "sans_semi",
        84,
        line1,
        (WIDTH - w1) / 2.0,
        435,
        (*INK, 255),
        (t - 0.12) / 0.42,
        tracking_em=-0.035,
    )

    if t >= 1.00:
        s_a = "Why are they still "
        s_b = "blind"
        s_c = " on Windows?"
        wa = measure_tracked_text("sans_semi", 84, s_a, -0.035)
        wb = measure_tracked_text("serif_italic", 98, s_b, -0.02)
        wc = measure_tracked_text("sans_semi", 84, s_c, -0.035)
        sx = (WIDTH - (wa + wb + wc)) / 2.0
        p2 = (t - 1.00) / 0.42
        draw_masked_tracked_text(canvas, "sans_semi", 84, s_a, sx, 545, (*INK, 255), p2, tracking_em=-0.035)
        draw_masked_tracked_text(
            canvas,
            "serif_italic",
            98,
            s_b,
            sx + wa,
            545,
            (*VERMILION, 255),
            (t - 1.06) / 0.42,
            tracking_em=-0.02,
        )
        draw_masked_tracked_text(
            canvas,
            "sans_semi",
            84,
            s_c,
            sx + wa + wb,
            545,
            (*INK, 255),
            (t - 1.10) / 0.42,
            tracking_em=-0.035,
        )

    if t >= 1.35:
        rp = ease_out_expo((t - 1.35) / 0.40)
        hw = 340.0 * rp
        canvas.drawLine(WIDTH / 2.0 - hw, 610, WIDTH / 2.0 + hw, 610, skia.Paint(Color=rgba(*RULE, 255), StrokeWidth=1.2))
        cap = "LEGACY VISION LOOPS  ·  5,400MS / CLICK  ·  HIJACKS PHYSICAL MOUSE"
        cw = measure_tracked_text("mono", 16, cap, 0.08)
        draw_tracked_text(
            canvas,
            "mono",
            16,
            cap,
            (WIDTH - cw) / 2.0,
            652,
            (*GRAPHITE, int(255 * rp)),
            tracking_em=0.08,
        )


def _draw_act1_specimen(canvas: skia.Canvas, t: float) -> None:
    st = max(0.0, t - 2.20)
    logo_r = 50.0
    title = "antigravity-human-control"
    tw = measure_tracked_text("sans_bold", 72, title, -0.034)
    total_w = (logo_r * 2.0) + 34.0 + tw
    left_x = (WIDTH - total_w) / 2.0

    draw_aperture_logo(canvas, left_x + logo_r, 438, logo_r, t, alpha=clamp01((t - 2.05) / 0.35))

    tx = left_x + (logo_r * 2.0) + 34.0
    draw_masked_tracked_text(
        canvas,
        "sans_bold",
        72,
        title,
        tx,
        444,
        (*INK, 255),
        st / 0.42,
        tracking_em=-0.034,
    )

    sub = "Native speed. Human precision."
    draw_masked_tracked_text(
        canvas,
        "serif_italic",
        42,
        sub,
        tx,
        504,
        (*GRAPHITE, 255),
        (st - 0.12) / 0.42,
        tracking_em=-0.015,
    )

    # Subtle spec strip separated by 1px architectural rules
    strip_y = 605.0
    strip_w = 1120.0
    sx = (WIDTH - strip_w) / 2.0
    rule_p = ease_out_expo((st - 0.25) / 0.45)
    canvas.drawLine(sx, strip_y, sx + strip_w * rule_p, strip_y, skia.Paint(Color=rgba(*RULE, 255), StrokeWidth=1.0))
    canvas.drawLine(sx, strip_y + 72, sx + strip_w * rule_p, strip_y + 72, skia.Paint(Color=rgba(*RULE, 255), StrokeWidth=1.0))

    agents = ("Antigravity", "Claude Code", "Codex CLI", "Gemini CLI")
    cell_w = strip_w / 4.0
    for idx, name in enumerate(agents):
        cx = sx + idx * cell_w
        if idx > 0:
            canvas.drawLine(cx, strip_y + 14, cx, strip_y + 58, skia.Paint(Color=rgba(*RULE, int(255 * rule_p)), StrokeWidth=1.0))
        cue_t = 2.95 + idx * 0.12
        ap = clamp01((t - cue_t) / 0.22)
        if ap > 0.01:
            e = ease_out_expo(ap)
            sq = 7.0 * e
            canvas.drawRect(
                skia.Rect.MakeXYWH(cx + 28, strip_y + 36 - sq / 2.0, sq, sq),
                skia.Paint(Color=rgba(*VERMILION, int(255 * e))),
            )
            draw_tracked_text(
                canvas,
                "mono",
                14,
                f"0{idx + 1}",
                cx + 46,
                strip_y + 41,
                (*GRAPHITE, int(255 * e)),
                tracking_em=0.06,
            )
            draw_tracked_text(
                canvas,
                "sans_med",
                20,
                name,
                cx + 82,
                strip_y + 42,
                (*INK, int(255 * e)),
                tracking_em=-0.015,
            )

    # Bottom technical footnote
    if st >= 1.1:
        fa = int(230 * clamp01((st - 1.1) / 0.35))
        foot = "v2.1.0  ·  <10MS WARM DAEMON  ·  5-TIER WINDOWS & BROWSER SKILL"
        fw = measure_tracked_text("mono", 14, foot, 0.08)
        draw_tracked_text(canvas, "mono", 14, foot, (WIDTH - fw) / 2.0, 742, (*GRAPHITE, fa), tracking_em=0.08)


def draw_act_1(_surface: skia.Surface, canvas: skia.Canvas, t: float) -> None:
    if t < 2.00:
        _draw_act1_hook(canvas, t)
    elif t < 2.38:
        wp = ease_in_out_quart((t - 2.00) / 0.38)
        out_s, in_s = _get_transition_surfaces()
        oc = out_s.getCanvas()
        draw_paper_backdrop(oc)
        _draw_act1_hook(oc, 2.00)
        canvas.save()
        canvas.translate(-85.0 * wp, 0.0)
        canvas.drawImage(out_s.makeImageSnapshot(), 0.0, 0.0)
        canvas.restore()

        ic = in_s.getCanvas()
        draw_paper_backdrop(ic)
        _draw_act1_specimen(ic, t)
        cut_x = WIDTH * (1.0 - wp)
        canvas.save()
        canvas.clipRect(skia.Rect.MakeLTRB(cut_x, 0.0, WIDTH, HEIGHT))
        canvas.drawImage(in_s.makeImageSnapshot(), 0.0, 0.0)
        canvas.restore()
        canvas.drawLine(cut_x, 0.0, cut_x, HEIGHT, skia.Paint(Color=rgba(*INK, 255), StrokeWidth=1.5))
    else:
        _draw_act1_specimen(canvas, t)


# ---------------------------------------------------------------------------
# Act II (5.10s - 11.10s): Swiss Architectural 5-Engine Router Table
# ---------------------------------------------------------------------------
def draw_act_2(_surface: skia.Surface, canvas: skia.Canvas, t: float) -> None:
    st = max(0.0, t - 5.10)
    draw_editorial_chrome(canvas, t, "01 / CAPABILITY ROUTER")

    # Headline lockup
    h1 = "Five engines. "
    h2 = "One deterministic router."
    w1 = measure_tracked_text("sans_semi", 54, h1, -0.032)
    p_head = st / 0.42
    draw_masked_tracked_text(canvas, "sans_semi", 54, h1, 110, 152, (*INK, 255), p_head, tracking_em=-0.032)
    draw_masked_tracked_text(canvas, "serif_italic", 62, h2, 110 + w1, 152, (*GRAPHITE, 255), (st - 0.08) / 0.42, tracking_em=-0.015)

    # Clean architectural bus schematic
    bus_y = 244.0
    canvas.drawLine(110, bus_y, WIDTH - 110, bus_y, skia.Paint(Color=rgba(*RULE, 255), StrokeWidth=1.2))
    nodes = (
        (110.0, "cli.py  ·  <25ms stdlib"),
        (560.0, "bridge_daemon  ·  127.0.0.1 TCP_NODELAY"),
        (1140.0, "fallback_router  ·  Cache + 80ms Breaker"),
    )
    for nx, label in nodes:
        draw_tag(canvas, nx, bus_y - 17.5, label, font_style="mono", font_size=14, bg_rgb=WHITE, border_rgb=RULE, text_rgb=INK, tracking_em=0.04, dot_rgb=VERMILION if "router" in label else INK)

    # Determine active column smoothly synced with 5 pentatonic chimes (6.00, 6.90, 7.80, 8.70, 9.60)
    cues = (6.00, 6.90, 7.80, 8.70, 9.60)
    active_f = -1.0
    if t >= cues[0]:
        active_f = 0.0
        for idx in range(1, len(cues)):
            if t >= cues[idx]:
                step_p = spring_snappy(t - cues[idx], 0.36)
                active_f = (idx - 1) + step_p

    # 5-Column Swiss Table
    tx0, ty0, tw, th = 110.0, 336.0, 1700.0, 520.0
    col_w = tw / 5.0

    # Top & Bottom framing rules
    canvas.drawLine(tx0, ty0, tx0 + tw, ty0, skia.Paint(Color=rgba(*INK, 255), StrokeWidth=1.5))
    canvas.drawLine(tx0, ty0 + th, tx0 + tw, ty0 + th, skia.Paint(Color=rgba(*RULE, 255), StrokeWidth=1.2))

    # Downward architectural drop line from router bus to active column
    if active_f >= 0.0:
        slide_x = tx0 + active_f * col_w
        anchor_x = slide_x + col_w * 0.5
        bus_out_x = 1290.0
        draw_bezier_arc(
            canvas,
            (bus_out_x, bus_y + 18.0),
            (bus_out_x, bus_y + 52.0),
            (anchor_x, ty0 - 44.0),
            (anchor_x, ty0),
            (*VERMILION, 190),
            width=1.6,
        )
        canvas.drawCircle(anchor_x, ty0, 4.0, skia.Paint(Color=rgba(*VERMILION, 255), AntiAlias=True))

        # Matte ink sliding highlight block underneath active column text
        canvas.drawRect(skia.Rect.MakeXYWH(slide_x, ty0, col_w, th), skia.Paint(Color=rgba(*INK, 255)))
        canvas.drawRect(skia.Rect.MakeXYWH(slide_x, ty0, col_w, 4.5), skia.Paint(Color=rgba(*VERMILION, 255)))

    engines = [
        ("01", "Raw CDP", "WebSocket", "Chrome & Edge DOM", "<15ms", "100% Background"),
        ("02", "Windows UIA", "& #32770", "Native Tree & Dialogs", "20ms", "Zero Focus Loss"),
        ("03", "WinRT OCR", "Persistent", "Canvas Text Locator", "48ms", "GPU Accelerated"),
        ("04", "Outer-Ruler", "1000×1000", "DPI v2 + Bézier Drag", "35ms", "Closed-Loop NCC"),
        ("05", "ScanCode", "& Paste", "Atomic UTF-16LE IME", "40ms", "Clipboard Safe"),
    ]

    for idx, (num, n1, n2, desc, lat, cap) in enumerate(engines):
        cx = tx0 + idx * col_w
        if idx > 0:
            canvas.drawLine(cx, ty0, cx, ty0 + th, skia.Paint(Color=rgba(*RULE, 220), StrokeWidth=1.0))

        # Subtle blend state when matte block overlaps this column
        overlap = clamp01(1.0 - abs(active_f - idx)) if active_f >= 0.0 else 0.0
        is_dark_bg = overlap > 0.55

        num_col = VERMILION if is_dark_bg else GRAPHITE
        pri_col = PAPER if is_dark_bg else INK
        sub_col = (182, 178, 168) if is_dark_bg else GRAPHITE
        lat_col = PAPER if is_dark_bg else INK
        cap_col = VERMILION if not is_dark_bg else (238, 128, 92)

        px = cx + 28.0
        draw_tracked_text(canvas, "mono_bold", 15, num, px, ty0 + 48, (*num_col, 255), 0.08)
        draw_tracked_text(canvas, "sans_semi", 30, n1, px, ty0 + 114, (*pri_col, 255), -0.025)
        draw_tracked_text(canvas, "sans_semi", 30, n2, px, ty0 + 150, (*pri_col, 255), -0.025)
        draw_tracked_text(canvas, "sans", 16, desc, px, ty0 + 198, (*sub_col, 255), -0.01)

        # Metric block anchored low for Swiss negative-space proportion
        canvas.drawLine(
            px,
            ty0 + 340,
            cx + col_w - 28.0,
            ty0 + 340,
            skia.Paint(Color=rgba(*(DARK_EDGE if is_dark_bg else RULE), 255), StrokeWidth=1.0),
        )
        draw_tracked_text(canvas, "sans_bold", 54, lat, px, ty0 + 412, (*lat_col, 255), -0.038)
        draw_tracked_text(canvas, "mono", 14, cap, px, ty0 + 464, (*cap_col, 255), 0.03)


# ---------------------------------------------------------------------------
# Act III (11.10s - 17.70s): Silent Background CDP + Optical DOF Rack Focus
# ---------------------------------------------------------------------------
def _draw_browser_mockup(canvas: skia.Canvas, st: float, is_triggered: bool) -> None:
    bx, by, bw, bh = 620.0, 150.0, 1140.0, 650.0
    draw_paper_card(canvas, bx, by, bw, bh, radius=14, fill_rgb=WHITE, border_rgb=RULE, shadow_elev=16)

    # Minimal light-mode Chrome header
    canvas.drawLine(bx, by + 56, bx + bw, by + 56, skia.Paint(Color=rgba(*RULE, 255), StrokeWidth=1.0))
    for i in range(3):
        canvas.drawCircle(
            bx + 28 + i * 20,
            by + 28,
            5.5,
            skia.Paint(Color=rgba(*STONE, 255), AntiAlias=True),
        )
    draw_tracked_text(
        canvas,
        "mono_bold",
        13,
        "CHROME 138  ·  RAW CDP WEBSOCKET",
        bx + 104,
        by + 33,
        (*GRAPHITE, 255),
        0.06,
    )

    # URL well
    url_rr = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(bx + 42, by + 84, bw - 84, 46), 8, 8)
    canvas.drawRRect(url_rr, skia.Paint(Color=rgba(*PAPER, 255), AntiAlias=True))
    draw_tracked_text(canvas, "mono", 15, "https://studio.local/workspace/export", bx + 64, by + 113, (*GRAPHITE, 255))

    # Inner app layout
    draw_tracked_text(canvas, "sans_bold", 42, "Project Render Ready", bx + 54, by + 206, (*INK, 255), -0.03)
    draw_tracked_text(canvas, "mono", 16, "Target: 1920x1080  ·  60fps  ·  Stereo Master", bx + 54, by + 244, (*GRAPHITE, 255))

    btn_x, btn_y, btn_w, btn_h = bx + 54, by + 296, 260, 56
    btn_bg = SAGE if is_triggered else INK
    canvas.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(btn_x, btn_y, btn_w, btn_h), 8, 8), skia.Paint(Color=rgba(*btn_bg, 255), AntiAlias=True))
    btn_txt = "✓  Export Triggered" if is_triggered else "Export Project"
    btw = measure_tracked_text("sans_semi", 19, btn_txt, -0.01)
    draw_tracked_text(canvas, "sans_semi", 19, btn_txt, btn_x + (btn_w - btw) / 2.0, btn_y + 35, (*WHITE, 255), -0.01)

    draw_tag(
        canvas,
        bx + 54,
        by + 548,
        "Physical Cursor Untouched (100% Background CDP)",
        font_style="mono_bold",
        font_size=14,
        bg_rgb=PAPER,
        border_rgb=SAGE if is_triggered else RULE,
        text_rgb=SAGE if is_triggered else GRAPHITE,
        leading_check=clamp01((st - 1.25) / 0.25) if is_triggered else None,
    )
    # Physical cursor stays untouched near bottom-left of page margin
    draw_cursor(canvas, bx + 980, by + 560, scale=1.0)


def draw_act_3(_surface: skia.Surface, canvas: skia.Canvas, t: float) -> None:
    st = max(0.0, t - 11.10)
    draw_editorial_chrome(canvas, t, "02 / SILENT BACKGROUND")

    # Asymmetric Swiss left editorial column
    draw_masked_tracked_text(canvas, "sans_semi", 64, "Zero cursor", 110, 232, (*INK, 255), st / 0.42, -0.032)
    draw_masked_tracked_text(canvas, "serif_italic", 76, "hijack.", 110, 310, (*VERMILION, 255), (st - 0.10) / 0.42, -0.02)

    body = (
        "Raw CDP dispatches clicks",
        "inside Chrome without stealing",
        "window focus or moving your",
        "physical mouse.",
    )
    bp = clamp01((st - 0.22) / 0.45)
    for idx, line in enumerate(body):
        draw_tracked_text(canvas, "sans", 20, line, 110, 384 + idx * 32, (*GRAPHITE, int(255 * bp)), -0.01)

    # Telemetry pill in left rail
    triggered = t >= 12.25
    dialog_open = t >= 13.30
    state_txt = "WIN32 #32770  ·  ATOMIC PASTE" if dialog_open else ("RAW CDP  ·  0PX CURSOR DRIFT" if triggered else "STANDBY  ·  FOCUS PRESERVED")
    draw_tag(
        canvas,
        110,
        564,
        state_txt,
        font_style="mono_bold",
        font_size=13,
        bg_rgb=WHITE,
        border_rgb=RULE,
        text_rgb=INK,
        dot_rgb=SAGE if (triggered or dialog_open) else GRAPHITE,
    )

    # Background Chrome window (blurred via reusable 1/2-res offscreen surface on DOF rack focus)
    blur_p = ease_in_out_cubic((st - 2.20) / 0.50) if st >= 2.20 else 0.0
    if blur_p <= 0.02:
        _draw_browser_mockup(canvas, st, triggered)
    else:
        dof_s = _get_dof_surface()
        dc = dof_s.getCanvas()
        dc.clear(rgba(0, 0, 0, 0))
        dc.save()
        dc.scale(0.5, 0.5)
        _draw_browser_mockup(dc, st, triggered)
        dc.restore()

        img = dof_s.makeImageSnapshot()
        sigma = 7.0 * blur_p
        sc = 1.0 - 0.035 * blur_p
        canvas.save()
        canvas.translate(1190, 475)
        canvas.scale(sc, sc)
        canvas.translate(-1190, -475)
        canvas.drawImageRect(
            img,
            skia.Rect.MakeWH(WIDTH, HEIGHT),
            skia.SamplingOptions(skia.FilterMode.kLinear),
            skia.Paint(ImageFilter=skia.ImageFilters.Blur(sigma, sigma)),
        )
        canvas.restore()
        # Subtle atmospheric depth fade over defocused browser card only
        canvas.drawRect(
            skia.Rect.MakeXYWH(590, 125, 1210, 710),
            skia.Paint(Color=rgba(*PAPER, int(48 * blur_p))),
        )

    # Foreground Windows #32770 Save As dialog (appears cleanly at 13.30s)
    if st >= 2.20:
        dp = spring_snappy(st - 2.20, 0.44)
        dw, dh = 760.0, 440.0
        dx = 1000.0
        dy = 370.0 + (1.0 - dp) * 48.0

        draw_paper_card(canvas, dx, dy, dw, dh, radius=14, fill_rgb=WHITE, border_rgb=INK, border_w=1.2, shadow_elev=22)

        draw_tracked_text(canvas, "mono_bold", 13, "WINDOWS DIALOG (#32770)  ·  FAST-PATH", dx + 38, dy + 44, (*VERMILION, 255), 0.06)
        draw_tracked_text(canvas, "sans_bold", 34, "Save As", dx + 38, dy + 94, (*INK, 255), -0.025)
        draw_tracked_text(canvas, "sans", 16, "File name:", dx + 38, dy + 148, (*GRAPHITE, 255))

        # Crisp architectural input field
        in_rr = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(dx + 38, dy + 166, dw - 76, 58), 8, 8)
        canvas.drawRRect(in_rr, skia.Paint(Color=rgba(*PAPER, 255), AntiAlias=True))
        in_border = SAGE if t >= 14.45 else INK
        canvas.drawRRect(in_rr, skia.Paint(Color=rgba(*in_border, 255), Style=skia.Paint.kStroke_Style, StrokeWidth=1.5, AntiAlias=True))

        if t >= 14.45:
            fn = "Báo cáo Dự án — Đắk Lắk 2026.mp4"
            tp = clamp01((t - 14.45) / 0.65)
            chars = max(1, int(len(fn) * tp))
            draw_tracked_text(canvas, "sans_med", 22, fn[:chars], dx + 58, dy + 203, (*INK, 255), -0.01)

            draw_tag(
                canvas,
                dx + 38,
                dy + 252,
                "Atomic Clipboard Restored  ·  UTF-16LE Safe",
                font_style="mono_bold",
                font_size=14,
                bg_rgb=PAPER,
                border_rgb=SAGE,
                text_rgb=SAGE,
                leading_check=clamp01((t - 14.55) / 0.25),
            )

        saved = t >= 16.05
        sbx, sby, sbw, sbh = dx + dw - 208, dy + dh - 86, 170, 52
        canvas.drawRRect(
            skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(sbx, sby, sbw, sbh), 8, 8),
            skia.Paint(Color=rgba(*(SAGE if saved else INK), 255), AntiAlias=True),
        )
        s_txt = "Saved  ✓" if saved else "Save"
        sw = measure_tracked_text("sans_semi", 18, s_txt, -0.01)
        draw_tracked_text(canvas, "sans_semi", 18, s_txt, sbx + (sbw - sw) / 2.0, sby + 32, (*WHITE, 255), -0.01)


# ---------------------------------------------------------------------------
# Act IV (17.70s - 24.90s): Matte Graphite Canvas + Paper Vernier Ruler + 2.5x Loupe
# ---------------------------------------------------------------------------
def draw_act_4(surface: skia.Surface, canvas: skia.Canvas, t: float) -> None:
    st = max(0.0, t - 17.70)

    # Dynamic camera tracking during Bezier Fitts drag (19.60s -> 22.80s)
    zoom_in = ease_in_out_cubic((st - 1.90) / 1.40) if st >= 1.90 else 0.0
    zoom_out = ease_in_out_cubic((st - 4.30) / 0.85) if st >= 4.30 else 0.0
    cam_zoom = 1.0 + 0.13 * zoom_in - 0.06 * zoom_out
    focus_x = 960.0 + 210.0 * zoom_in
    focus_y = 540.0 + 115.0 * zoom_in

    fx, fy, fw, fh = 140.0, 124.0, 1640.0, 864.0
    margin = 36.0
    ix, iy, iw, ih = fx + margin, fy + margin, fw - margin * 2, fh - margin * 2
    ty = iy + 480.0

    px_start = ix + round(0.22 * iw)
    px_target = ix + round(0.74 * iw)
    px_undershoot = px_target - 14.0
    py_handle = ty + 24.0

    canvas.save()
    canvas.clipRect(skia.Rect.MakeLTRB(0.0, 72.0, WIDTH, HEIGHT - 4.0))
    canvas.translate(focus_x, focus_y)
    canvas.scale(cam_zoom, cam_zoom)
    canvas.translate(-focus_x, -focus_y)

    # Paper Vernier 1000x1000 Ruler Bezel surrounding the matte graphite canvas
    draw_paper_card(canvas, fx, fy, fw, fh, radius=10, fill_rgb=PAPER, border_rgb=INK, border_w=1.2, shadow_elev=18)

    # Inset matte graphite workspace
    inner_rect = skia.Rect.MakeXYWH(ix, iy, iw, ih)
    canvas.drawRect(inner_rect, skia.Paint(Color=rgba(*MATTE_DARK, 255)))

    # Crisp Vernier ticks around the perimeter (vertical axes skip 0/1000 to keep corners clean)
    for step in range(0, 1001, 50):
        gx = ix + round((step / 1000.0) * iw)
        gy = iy + round((step / 1000.0) * ih)
        major = step % 100 == 0
        if 0 < step < 1000 and major:
            canvas.drawLine(gx, iy, gx, iy + ih, skia.Paint(Color=rgba(255, 255, 255, 16), StrokeWidth=1.0))
            canvas.drawLine(ix, gy, ix + iw, gy, skia.Paint(Color=rgba(255, 255, 255, 16), StrokeWidth=1.0))
        tlen = 9.0 if major else 4.5
        tp = skia.Paint(Color=rgba(*INK, 230) if major else rgba(*GRAPHITE, 160), StrokeWidth=1.2)
        canvas.drawLine(gx, iy - 1, gx, iy - 1 - tlen, tp)
        canvas.drawLine(gx, iy + ih + 1, gx, iy + ih + 1 + tlen, tp)
        if 0 < step < 1000:
            canvas.drawLine(ix - 1, gy, ix - 1 - tlen, gy, tp)
            canvas.drawLine(ix + iw + 1, gy, ix + iw + 1 + tlen, gy, tp)
        if major:
            lbl = str(step)
            lw = measure_tracked_text("mono_bold", 11, lbl)
            draw_tracked_text(canvas, "mono_bold", 11, lbl, gx - lw / 2.0, fy + 19, (*INK, 230))
            draw_tracked_text(canvas, "mono_bold", 11, lbl, gx - lw / 2.0, iy + ih + 25, (*INK, 230))
            if 0 < step < 1000:
                draw_tracked_text(canvas, "mono_bold", 11, lbl, fx + 6, gy + 4, (*INK, 230))
                draw_tracked_text(canvas, "mono_bold", 11, lbl, ix + iw + 12, gy + 4, (*INK, 230))

    # Matte workspace header bar
    canvas.drawRect(skia.Rect.MakeXYWH(ix, iy, iw, 64), skia.Paint(Color=rgba(36, 35, 32, 255)))
    canvas.drawLine(ix, iy + 64, ix + iw, iy + 64, skia.Paint(Color=rgba(*DARK_EDGE, 255), StrokeWidth=1.2))
    draw_tracked_text(canvas, "mono_bold", 15, "CREATIVE STUDIO  //  CUSTOM CANVAS WORKSPACE", ix + 24, iy + 38, (*PAPER, 240), 0.05)

    for idx, sym in enumerate(("CUT", "SPLIT", "FX", "LUT", "MIX")):
        tbx = ix + 670 + idx * 84
        canvas.drawRRect(
            skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(tbx, iy + 14, 72, 36), 6, 6),
            skia.Paint(Color=rgba(48, 46, 42, 255), AntiAlias=True),
        )
        sw = measure_tracked_text("mono", 14, sym)
        draw_tracked_text(canvas, "mono", 14, sym, tbx + (72 - sw) / 2.0, iy + 37, (198, 194, 184, 255))

    ex, ey, ew, eh = ix + iw - 224, iy + 11, 200, 42
    canvas.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(ex, ey, ew, eh), 6, 6), skia.Paint(Color=rgba(*WHITE, 255), AntiAlias=True))
    etw = measure_tracked_text("sans_semi", 18, "Export Video", -0.01)
    draw_tracked_text(canvas, "sans_semi", 18, "Export Video", ex + (ew - etw) / 2.0, ey + 27, (*INK, 255), -0.01)

    # Matte media bin + crisp bone-white waveform monitor
    canvas.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(ix + 24, iy + 86, 300, 370), 8, 8), skia.Paint(Color=rgba(34, 33, 30, 255)))
    draw_tracked_text(canvas, "mono", 13, "MEDIA BIN (CANVAS)", ix + 44, iy + 118, (150, 146, 138, 255), 0.05)
    for i in range(4):
        ry = iy + 142 + i * 72
        canvas.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(ix + 40, ry, 268, 54), 6, 6), skia.Paint(Color=rgba(46, 44, 40, 255)))
        draw_tracked_text(canvas, "mono", 14, f"scene_0{i + 1}_60fps.mp4", ix + 56, ry + 32, (*PAPER, 225))

    canvas.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(ix + 344, iy + 86, iw - 368, 370), 8, 8), skia.Paint(Color=rgba(20, 20, 18, 255)))
    draw_tracked_text(canvas, "mono", 13, "1920x1080  ·  60.00 FPS  ·  NO UIA TREE", ix + 372, iy + 118, (168, 164, 154, 255), 0.05)
    for k in range(52):
        wbx = ix + 392 + k * 21
        wbh = max(10.0, 24.0 + 74.0 * abs(math.sin(k * 0.36 + t * 0.45)) * abs(math.sin(k * 0.14 + 0.4)))
        canvas.drawRRect(
            skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(wbx, iy + 278 - wbh, 8, wbh * 2), 3, 3),
            skia.Paint(Color=rgba(*PAPER, 200)),
        )

    # Matte hardware timeline tracks
    canvas.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(ix + 24, ty, iw - 48, ih - 504), 8, 8), skia.Paint(Color=rgba(32, 31, 28, 255)))
    canvas.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(ix + 54, ty + 48, 510, 62), 6, 6), skia.Paint(Color=rgba(52, 50, 46, 255)))
    draw_tracked_text(canvas, "mono", 14, "VIDEO TRACK 01", ix + 74, ty + 84, (*PAPER, 240))
    canvas.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(ix + 580, ty + 48, 550, 62), 6, 6), skia.Paint(Color=rgba(46, 60, 52, 255)))
    draw_tracked_text(canvas, "mono", 14, "MOTION OVERLAY", ix + 600, ty + 84, (226, 240, 232, 240))
    canvas.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(ix + 54, ty + 126, iw - 120, 54), 6, 6), skia.Paint(Color=rgba(46, 44, 42, 255)))
    draw_tracked_text(canvas, "mono", 14, "STEREO AUDIO DSP  [48kHz Master]", ix + 74, ty + 158, (206, 201, 189, 230))

    # Crisp Signal Vermilion target hairline at 740 (label clear above playhead & reticle)
    canvas.drawLine(px_target, ty, px_target, iy + ih - 24, skia.Paint(Color=rgba(*VERMILION, 240), StrokeWidth=2.4))
    draw_tracked_text(canvas, "mono_bold", 14, "TARGET 740", px_target - 46, ty - 14, (*VERMILION, 255), 0.04)

    # WinRT OCR header scan + clean vermilion bracket + foreground tag (drawn above panels!)
    if st < 2.05:
        if 0.15 <= st <= 0.72:
            scan_x = ix + iw * ease_in_out_cubic((st - 0.15) / 0.57)
            beam = skia.GradientShader.MakeLinear(
                points=[(scan_x - 65, iy), (scan_x + 4, iy)],
                colors=[rgba(*VERMILION, 0), rgba(*VERMILION, 145)],
            )
            canvas.drawRect(skia.Rect.MakeXYWH(max(ix, scan_x - 65), iy, 69, 64), skia.Paint(Shader=beam))
        if st >= 0.68:
            lp = spring_snappy(st - 0.68, 0.28)
            pad = (1.0 - lp) * 18.0 + 5.0
            canvas.drawRRect(
                skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(ex - pad, ey - pad, ew + pad * 2, eh + pad * 2), 9, 9),
                skia.Paint(Color=rgba(*VERMILION, 255), Style=skia.Paint.kStroke_Style, StrokeWidth=2.5, AntiAlias=True),
            )
            draw_tag(
                canvas,
                ex - 88,
                ey + eh + 16,
                "WINRT OCR LOCK  ·  48MS",
                font_style="mono_bold",
                font_size=14,
                bg_rgb=WHITE,
                border_rgb=INK,
                text_rgb=INK,
                leading_check=clamp01((st - 0.75) / 0.22),
            )

    # Playhead & cubic Bezier curve cursor trajectory (2.10s -> 4.15s synced to liquid glide)
    if st < 2.10:
        cur_px = px_start
        cur_x, cur_y = ex + ew * 0.85, ey + eh * 0.80
    elif st < 4.15:
        dp = ease_in_out_cubic((st - 2.10) / 2.05)
        p0 = (px_start, py_handle)
        p1 = (px_start + (px_undershoot - px_start) * 0.30, py_handle - 28.0)
        p2 = (px_start + (px_undershoot - px_start) * 0.72, py_handle - 20.0)
        p3 = (px_undershoot, py_handle)
        draw_bezier_arc(canvas, p0, p1, p2, p3, (*PAPER, 75), progress=dp, active_rgb=VERMILION, width=2.8)
        u = 1.0 - dp
        cur_x = (u ** 3) * p0[0] + 3 * (u ** 2) * dp * p1[0] + 3 * u * (dp ** 2) * p2[0] + (dp ** 3) * p3[0]
        cur_y = (u ** 3) * p0[1] + 3 * (u ** 2) * dp * p1[1] + 3 * u * (dp ** 2) * p2[1] + (dp ** 3) * p3[1]
        cur_px = cur_x
    else:
        mp = ease_out_quint((st - 5.40) / 0.35) if st >= 5.40 else 0.0
        cur_px = px_undershoot + (px_target - px_undershoot) * mp
        cur_x, cur_y = cur_px, py_handle

    # Crisp bone-white active playhead needle
    canvas.drawLine(cur_px, ty, cur_px, iy + ih - 24, skia.Paint(Color=rgba(*WHITE, 255), StrokeWidth=2.6))
    tri = skia.Path()
    tri.moveTo(cur_px - 10, ty - 6)
    tri.lineTo(cur_px + 10, ty - 6)
    tri.lineTo(cur_px, ty + 13)
    tri.close()
    canvas.drawPath(tri, skia.Paint(Color=rgba(*WHITE, 255), AntiAlias=True))
    draw_cursor(canvas, cur_x, cur_y, scale=1.05)

    canvas.restore()

    # Editorial chrome rendered crisply in screen space above the ruler bezel
    draw_editorial_chrome(canvas, t, "03 / CANVAS PRECISION")

    # 2.5x Physical Optical Magnifier Loupe (st >= 4.25s, locked on 23.45s chord)
    if st >= 4.25:
        lp = spring_snappy(st - 4.25, 0.38)
        loupe_cx, loupe_cy, loupe_r = 1545.0, 415.0, 144.0 * lp
        if loupe_r > 20.0:
            scr_tx = (px_target - focus_x) * cam_zoom + focus_x
            scr_ty = (py_handle + 8.0 - focus_y) * cam_zoom + focus_y

            sample_half = 56
            sx0 = max(0, int(scr_tx - sample_half))
            sy0 = max(0, int(scr_ty - sample_half))
            sx1 = min(WIDTH, sx0 + sample_half * 2)
            sy1 = min(HEIGHT, sy0 + sample_half * 2)
            snap = surface.makeImageSnapshot(skia.IRect.MakeLTRB(sx0, sy0, sx1, sy1))

            locked = t >= 23.45
            rim_c = SAGE if locked else VERMILION

            # Precision reticle ring over exact snap point + hairline leader to loupe
            ret_r = 25.0 * lp
            canvas.drawCircle(
                scr_tx,
                scr_ty,
                ret_r,
                skia.Paint(Color=rgba(*rim_c, 235), Style=skia.Paint.kStroke_Style, StrokeWidth=2.2, AntiAlias=True),
            )
            dx, dy = loupe_cx - scr_tx, loupe_cy - scr_ty
            dist = math.hypot(dx, dy) or 1.0
            ux, uy = dx / dist, dy / dist
            canvas.drawLine(
                scr_tx + ux * ret_r,
                scr_ty + uy * ret_r,
                loupe_cx - ux * (loupe_r + 5.0),
                loupe_cy - uy * (loupe_r + 5.0),
                skia.Paint(Color=rgba(*rim_c, 200), StrokeWidth=1.8, AntiAlias=True),
            )

            # Ambient loupe shadow
            canvas.drawCircle(
                loupe_cx,
                loupe_cy + 10.0,
                loupe_r + 6.0,
                skia.Paint(
                    Color=rgba(20, 19, 16, 85),
                    MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 14.0),
                    AntiAlias=True,
                ),
            )

            canvas.save()
            lens_path = skia.Path()
            lens_path.addCircle(loupe_cx, loupe_cy, loupe_r)
            canvas.clipPath(lens_path, doAntiAlias=True)
            canvas.drawRect(
                skia.Rect.MakeXYWH(loupe_cx - loupe_r, loupe_cy - loupe_r, loupe_r * 2, loupe_r * 2),
                skia.Paint(Color=rgba(*MATTE_DARK, 255)),
            )
            if snap is not None:
                dst_rect = skia.Rect.MakeXYWH(loupe_cx - loupe_r, loupe_cy - loupe_r, loupe_r * 2, loupe_r * 2)
                canvas.drawImageRect(snap, dst_rect, skia.SamplingOptions(skia.FilterMode.kLinear))

            # Subtle optical crosshair hairlines
            hp = skia.Paint(Color=rgba(*WHITE, 60), StrokeWidth=1.0)
            canvas.drawLine(loupe_cx - loupe_r, loupe_cy, loupe_cx + loupe_r, loupe_cy, hp)
            canvas.drawLine(loupe_cx, loupe_cy - loupe_r, loupe_cx, loupe_cy + loupe_r, hp)
            canvas.restore()

            # Porcelain inner bezel + crisp signal state outer ring
            canvas.drawCircle(
                loupe_cx,
                loupe_cy,
                loupe_r + 2.5,
                skia.Paint(Color=rgba(*WHITE, 255), Style=skia.Paint.kStroke_Style, StrokeWidth=5.0, AntiAlias=True),
            )
            canvas.drawCircle(
                loupe_cx,
                loupe_cy,
                loupe_r + 5.5,
                skia.Paint(Color=rgba(*rim_c, 255), Style=skia.Paint.kStroke_Style, StrokeWidth=2.4, AntiAlias=True),
            )

            msg = "NCC 0.99  ·  0.0PX ERROR" if locked else "NCC 0.99  ·  DRIFT -7PX"
            mw = measure_tracked_text("mono_bold", 14, msg, 0.05)
            pw = mw + (24.0 if locked else 0.0) + 32.0
            draw_tag(
                canvas,
                loupe_cx - pw / 2.0,
                loupe_cy + loupe_r + 20.0,
                msg,
                font_style="mono_bold",
                font_size=14,
                bg_rgb=WHITE,
                border_rgb=rim_c,
                text_rgb=rim_c,
                tracking_em=0.05,
                leading_check=clamp01((t - 23.45) / 0.25) if locked else None,
            )


# ---------------------------------------------------------------------------
# Act V (24.90s - 28.70s): Swiss Editorial Benchmark Poster + Safety Trio
# ---------------------------------------------------------------------------
def draw_act_5(_surface: skia.Surface, canvas: skia.Canvas, t: float) -> None:
    st = max(0.0, t - 24.90)
    draw_editorial_chrome(canvas, t, "04 / PERFORMANCE & SAFETY")

    # Monumental left hero figure (1x -> 76x landing smoothly by 25.95s)
    num_p = ease_out_expo(clamp01((t - 24.98) / 0.97))
    val = int(round(1 + 75 * num_p))
    draw_tracked_text(canvas, "sans_bold", 196, f"{val}×", 110, 356, (*INK, 255), -0.048)

    draw_masked_tracked_text(canvas, "serif_italic", 46, "faster batch workflows", 114, 422, (*VERMILION, 255), (st - 0.20) / 0.42, -0.015)
    draw_tracked_text(canvas, "mono", 15, "4-STEP EXPORT AUTOMATION BENCHMARK", 116, 466, (*GRAPHITE, 255), 0.06)

    # Right clean architectural bar chart (no enclosing cards)
    cx0, cy0, cw = 760.0, 206.0, 1050.0
    rows = [
        ("Pure Vision Loop (LLM / step)", 18.40, STONE, "18.40s", INK, 0.25),
        ("UIA-Only Skill (Fails on Canvas)", 4.80, SLATE_BAR, "4.80s", INK, 0.45),
        ("antigravity-human-control (Batch)", 0.24, VERMILION, "0.24s", VERMILION, 0.70),
    ]
    for idx, (label, sec, bar_col, val_lbl, txt_col, delay) in enumerate(rows):
        ry = cy0 + idx * 108.0
        bp = ease_out_expo(clamp01((st - delay) / 0.85))
        draw_tracked_text(canvas, "sans_med" if idx < 2 else "sans_semi", 20, label, cx0, ry, (*INK, 255), -0.015)
        draw_tracked_text(canvas, "mono_bold", 20, val_lbl, cx0 + cw - 86, ry, (*txt_col, 255), 0.02)

        track_y = ry + 18.0
        canvas.drawRect(skia.Rect.MakeXYWH(cx0, track_y, cw, 22), skia.Paint(Color=rgba(*RULE, 140)))
        fill_w = max(8.0, (sec / 18.40) * cw * bp)
        canvas.drawRect(skia.Rect.MakeXYWH(cx0, track_y, fill_w, 22), skia.Paint(Color=rgba(*bar_col, 255)))

    # Bottom 3-column architectural safety strip (cues 26.65s, 26.80s, 26.95s)
    sy = 650.0
    canvas.drawLine(110, sy, WIDTH - 110, sy, skia.Paint(Color=rgba(*INK, 255), StrokeWidth=1.5))
    canvas.drawLine(110, sy + 210, WIDTH - 110, sy + 210, skia.Paint(Color=rgba(*RULE, 255), StrokeWidth=1.2))

    guards = [
        ("01", "Integrity Isolated", "Medium & High Daemons"),
        ("02", "Human Handoff Guard", "Stops on CAPTCHA Gates"),
        ("03", "Ctrl+Alt+Esc Yield", "Instant Mouse Takeover"),
    ]
    col_w = (WIDTH - 220.0) / 3.0
    for idx, (num, title, sub) in enumerate(guards):
        gx = 110.0 + idx * col_w
        if idx > 0:
            canvas.drawLine(gx, sy, gx, sy + 210, skia.Paint(Color=rgba(*RULE, 255), StrokeWidth=1.0))

        gp = ease_out_expo(clamp01((t - (26.65 + idx * 0.15)) / 0.35))
        if gp <= 0.01:
            continue
        a = int(255 * gp)
        px = gx + (0.0 if idx == 0 else 36.0)
        draw_tracked_text(canvas, "mono_bold", 14, num, px, sy + 52, (*VERMILION, a), 0.08)
        draw_vector_check(canvas, gx + col_w - 38.0, sy + 48, 18.0, gp, SAGE, stroke_w=2.4)
        draw_tracked_text(canvas, "sans_semi", 28, title, px, sy + 114, (*INK, a), -0.025)
        draw_tracked_text(canvas, "sans", 18, sub, px, sy + 154, (*GRAPHITE, a), -0.01)


# ---------------------------------------------------------------------------
# Act VI (28.70s - 32.00s): Matte Charcoal Terminal & Clean Studio Outro
# ---------------------------------------------------------------------------
def draw_act_6(_surface: skia.Surface, canvas: skia.Canvas, t: float) -> None:
    st = max(0.0, t - 28.70)
    draw_editorial_chrome(canvas, t, "05 / GET STARTED")

    p = spring_snappy(st, 0.42)
    cw, ch = 1340.0, 356.0
    cx, cy = (WIDTH - cw) / 2.0, 174.0 + (1.0 - p) * 24.0

    # Tactile matte dark hardware terminal card sitting on warm alabaster paper
    draw_paper_card(canvas, cx, cy, cw, ch, radius=14, fill_rgb=MATTE_DARK, border_rgb=INK, border_w=1.2, shadow_elev=20)

    # Muted industrial dots (zero neon)
    for idx, col in enumerate(((201, 82, 70), (212, 161, 59), (75, 155, 106))):
        canvas.drawCircle(cx + 38 + idx * 24, cy + 34, 6.5, skia.Paint(Color=rgba(*col, 255), AntiAlias=True))

    draw_tracked_text(
        canvas,
        "mono",
        15,
        "PowerShell  —  One-Click Multi-Agent Install (No Admin Required)",
        cx + 120,
        cy + 40,
        (163, 159, 149, 255),
        0.02,
    )
    canvas.drawLine(cx, cy + 64, cx + cw, cy + 64, skia.Paint(Color=rgba(*DARK_EDGE, 255), StrokeWidth=1.2))

    # Typing cleanly timed across the 16 keystroke clicks (29.05s -> 30.48s)
    cmd = "git clone https://github.com/Daosi-dev/agent-eye.git; cd agent-eye; .\\install.ps1"
    chars = int(len(cmd) * clamp01((t - 29.02) / 1.48))
    typed = f"PS> {cmd[:chars]}"
    adv = draw_tracked_text(canvas, "mono_bold", 20, typed, cx + 44, cy + 142, (*PAPER, 255))

    # Crisp cursor block
    if t < 30.65 or int(t * 2) % 2 == 0:
        canvas.drawRect(
            skia.Rect.MakeXYWH(cx + 44 + adv + 6, cy + 123, 10, 22),
            skia.Paint(Color=rgba(*VERMILION, 235)),
        )

    # Verification output synced to 30.65s sub impact + chime
    if t >= 30.65:
        cp = clamp01((t - 30.65) / 0.32)
        a = int(255 * cp)
        draw_vector_check(canvas, cx + 56, cy + 220, 20.0, cp, (88, 184, 132), stroke_w=2.8)
        draw_tracked_text(
            canvas,
            "sans_med",
            22,
            "Linked: Antigravity  ·  Claude Code  ·  Codex  ·  Gemini CLI",
            cx + 84,
            cy + 228,
            (*PAPER, a),
            -0.015,
        )
        draw_vector_check(canvas, cx + 56, cy + 276, 20.0, cp, (88, 184, 132), stroke_w=2.8)
        draw_tracked_text(
            canvas,
            "mono",
            18,
            "Warm Daemon (<10ms IPC)  ·  WinRT OCR  ·  22/22 Tests Pass",
            cx + 84,
            cy + 283,
            (154, 212, 178, a),
        )

    # Bottom clean centered brand lockup
    cta = "github.com/Daosi-dev/agent-eye"
    ctaw = measure_tracked_text("sans_bold", 48, cta, -0.032)
    r_logo = 28.0
    lock_w = r_logo * 2.0 + 22.0 + ctaw
    lx0 = (WIDTH - lock_w) / 2.0
    draw_aperture_logo(canvas, lx0 + r_logo, 696, r_logo, t, alpha=clamp01(st / 0.35))
    draw_tracked_text(canvas, "sans_bold", 48, cta, lx0 + r_logo * 2.0 + 22.0, 712, (*INK, 255), -0.032)

    sub = "MIT LICENSE  ·  WINDOWS 10/11  ·  PYTHON 3.10–3.15"
    sw = measure_tracked_text("mono", 16, sub, 0.08)
    draw_tracked_text(canvas, "mono", 16, sub, (WIDTH - sw) / 2.0, 782, (*GRAPHITE, 255), 0.08)


# ---------------------------------------------------------------------------
# Unified Scene Timeline & Curtain Wipe Dispatcher
# ---------------------------------------------------------------------------
ACTS = (
    (0.0, 5.10, draw_act_1),
    (5.10, 11.10, draw_act_2),
    (11.10, 17.70, draw_act_3),
    (17.70, 24.90, draw_act_4),
    (24.90, 28.70, draw_act_5),
    (28.70, DURATION_SEC, draw_act_6),
)
BOUNDARIES = (5.10, 11.10, 17.70, 24.90, 28.70)
WIPE_PRE = 0.10
WIPE_POST = 0.28  # 0.38s crisp horizontal curtain wipe


def render_frame_at(surface: skia.Surface, t: float) -> None:
    canvas = surface.getCanvas()
    draw_paper_backdrop(canvas)

    # Check if t falls inside a curtain wipe transition
    for idx, b in enumerate(BOUNDARIES):
        w0 = b - WIPE_PRE
        w1 = b + WIPE_POST
        if w0 <= t <= w1:
            wp = ease_in_out_quart((t - w0) / (w1 - w0))
            out_s, in_s = _get_transition_surfaces()
            oc = out_s.getCanvas()
            draw_paper_backdrop(oc)
            ACTS[idx][2](out_s, oc, t)
            canvas.save()
            canvas.translate(-90.0 * wp, 0.0)
            canvas.drawImage(out_s.makeImageSnapshot(), 0.0, 0.0)
            canvas.restore()

            ic = in_s.getCanvas()
            draw_paper_backdrop(ic)
            ACTS[idx + 1][2](in_s, ic, t)
            cut_x = WIDTH * (1.0 - wp)
            canvas.save()
            canvas.clipRect(skia.Rect.MakeLTRB(cut_x, 0.0, WIDTH, HEIGHT))
            canvas.drawImage(in_s.makeImageSnapshot(), 0.0, 0.0)
            canvas.restore()
            canvas.drawLine(cut_x, 0.0, cut_x, HEIGHT, skia.Paint(Color=rgba(*INK, 255), StrokeWidth=1.5))
            break
    else:
        for t0, t1, fn in ACTS:
            if t0 <= t <= t1 + 1e-6:
                fn(surface, canvas, t)
                break

    # Outro gentle dissolve back into warm studio paper at end (31.45s -> 32.0s)
    if t >= 31.45:
        fade_a = int(255 * clamp01((t - 31.45) / 0.55))
        canvas.drawRect(skia.Rect.MakeWH(WIDTH, HEIGHT), skia.Paint(Color=rgba(*PAPER, fade_a)))


# ---------------------------------------------------------------------------
# Styleframes & Chunked Parallel FFmpeg Pipeline
# ---------------------------------------------------------------------------
STYLEFRAME_TS = (1.40, 3.60, 7.10, 10.00, 12.60, 15.20, 18.70, 21.00, 22.60, 23.80, 27.40, 31.00)


def render_styleframes(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    surface = skia.Surface(WIDTH, HEIGHT)
    thumbs: list[skia.Image] = []
    for idx, ts in enumerate(STYLEFRAME_TS):
        render_frame_at(surface, ts)
        img = surface.makeImageSnapshot()
        png_path = out_dir / f"sf_{idx + 1:02d}_{ts:.2f}s.png"
        img.save(str(png_path), skia.kPNG)
        thumbs.append(img)

    # Assemble crisp 3x4 contact sheet (1920x1440) for fast overview
    cols, rows = 3, 4
    tw, th = 640, 360
    sheet = skia.Surface(cols * tw, rows * th)
    sc = sheet.getCanvas()
    sc.clear(rgba(*INK, 255))
    for idx, img in enumerate(thumbs):
        c = idx % cols
        r = idx // cols
        dst = skia.Rect.MakeXYWH(c * tw, r * th, tw, th)
        sc.drawImageRect(img, dst, skia.SamplingOptions(skia.FilterMode.kLinear))
        draw_tracked_text(
            sc,
            "mono_bold",
            16,
            f"#{idx + 1:02d} @ {STYLEFRAME_TS[idx]:.2f}s",
            c * tw + 14,
            r * th + 28,
            (*VERMILION, 255),
        )
    sheet.makeImageSnapshot().save(str(out_dir / "contact_sheet.png"), skia.kPNG)
    print(f"Styleframes written to {out_dir} (12 PNGs + contact_sheet.png)")


def _render_chunk(args: tuple[int, int, str]) -> str:
    start_f, end_f, chunk_path = args
    surface = skia.Surface(WIDTH, HEIGHT)

    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgra",
        "-s",
        f"{WIDTH}x{HEIGHT}",
        "-r",
        str(FPS),
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "16",
        "-pix_fmt",
        "yuv420p",
        chunk_path,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    try:
        for frame_idx in range(start_f, end_f):
            render_frame_at(surface, frame_idx / float(FPS))
            proc.stdin.write(surface.makeImageSnapshot().tobytes())

        proc.stdin.close()
        stderr_data = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
        rc = proc.wait()
        if rc != 0:
            raise RuntimeError(f"ffmpeg chunk failed ({rc}): {stderr_data}")
    finally:
        if proc.poll() is None:
            try:
                proc.stdin.close()
            except Exception:
                pass
            proc.kill()
            proc.wait()

    return chunk_path


def render_film(out_path: Path) -> Path:
    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="agent_eye_v3_"))
    try:
        wav_path = tmp_dir / "master.wav"
        build_audio_track(wav_path, duration_sec=DURATION_SEC)

        workers = min(2, os.cpu_count() or 1)
        chunk_size = math.ceil(TOTAL_FRAMES / workers)
        tasks = []
        for idx in range(workers):
            s = idx * chunk_size
            e = min(TOTAL_FRAMES, (idx + 1) * chunk_size)
            if s < e:
                tasks.append((s, e, str(tmp_dir / f"chunk_{idx}.mp4")))

        with ProcessPoolExecutor(max_workers=workers) as pool:
            chunk_paths = list(pool.map(_render_chunk, tasks))

        concat_txt = tmp_dir / "concat.txt"
        concat_txt.write_text("\n".join(f"file '{Path(p).as_posix()}'" for p in chunk_paths), encoding="utf-8")

        video_only = tmp_dir / "video_only.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat_txt), "-c", "copy", str(video_only)],
            check=True,
        )

        # Strict explicit -t DURATION_SEC muxing (never -shortest)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(video_only),
                "-i",
                str(wav_path),
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "256k",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-t",
                f"{DURATION_SEC:.3f}",
                "-movflags",
                "+faststart",
                str(out_path),
            ],
            check=True,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Render Zero-Neon Swiss Editorial Motion Graphics film")
    parser.add_argument("--out", default="media/agent-eye-launch-v3-60fps.mp4", help="Output MP4 path")
    parser.add_argument("--styleframes", default="", help="Render 12 key styleframe PNGs + contact sheet to this directory")
    args = parser.parse_args()

    if args.styleframes:
        render_styleframes(Path(args.styleframes))
    else:
        res = render_film(Path(args.out))
        print(res)


if __name__ == "__main__":
    main()
