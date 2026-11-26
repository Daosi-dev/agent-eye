"""Zero-Neon Swiss Editorial / Industrial Precision Skia C++ primitives (1920x1080 @ 60fps)."""

from __future__ import annotations

import functools
import math
from pathlib import Path
import unicodedata

import numpy as np
import skia

WIDTH = 1920
HEIGHT = 1080

# ---------------------------------------------------------------------------
# Strict Zero-Neon Editorial Palette
# ---------------------------------------------------------------------------
PAPER = (244, 242, 236)       # #F4F2EC Warm Studio Alabaster
WHITE = (255, 255, 255)       # #FFFFFF Crisp Porcelain UI Surface
INK = (20, 20, 19)            # #141413 Primary Deep Charcoal Ink
GRAPHITE = (110, 107, 100)    # #6E6B64 Secondary Editorial Copy
RULE = (218, 213, 202)        # #DAD5CA 1px Architectural Dividers & Rules
STONE = (206, 201, 189)       # #CEC9BD Secondary Chart Fill
SLATE_BAR = (158, 152, 140)   # #9E988C Midtone Chart Fill
MATTE_DARK = (27, 27, 25)     # #1B1B19 Matte Charcoal Hardware Surface
DARK_EDGE = (50, 49, 46)      # #32312E 1px Border on Matte Dark
VERMILION = (212, 69, 26)     # #D4451A Braun / International Signal Vermilion
SAGE = (30, 107, 75)          # #1E6B4B Print-Ink Forest Sage (verified state)

_FONTS_DIR = Path(__file__).resolve().parent / "fonts"


def rgba(r: int, g: int, b: int, a: int = 255) -> int:
    return skia.ColorSetARGB(int(max(0, min(255, a))), int(r), int(g), int(b))


def clamp01(x: float) -> float:
    return 0.0 if x <= 0.0 else (1.0 if x >= 1.0 else float(x))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * clamp01(t)


def ease_out_expo(t: float) -> float:
    t = clamp01(t)
    return 1.0 if t >= 1.0 else 1.0 - (2.0 ** (-10.0 * t))


def ease_in_out_quart(t: float) -> float:
    t = clamp01(t)
    if t < 0.5:
        return 8.0 * (t ** 4)
    return 1.0 - ((-2.0 * t + 2.0) ** 4) / 2.0


def ease_in_out_cubic(t: float) -> float:
    t = clamp01(t)
    if t < 0.5:
        return 4.0 * (t ** 3)
    return 1.0 - ((-2.0 * t + 2.0) ** 3) / 2.0


def ease_out_quint(t: float) -> float:
    t = clamp01(t)
    return 1.0 - ((1.0 - t) ** 5)


def spring_snappy(t: float, dur: float = 0.42) -> float:
    """Critically damped snappy spring with negligible micro-settle."""
    x = clamp01(t / max(1e-4, dur))
    if x >= 1.0:
        return 1.0
    return 1.0 - math.exp(-7.5 * x) * (math.cos(8.0 * x) + 0.35 * math.sin(8.0 * x))


# ---------------------------------------------------------------------------
# Typography: Bundled OFL Studio Fonts + Custom Tracking
# ---------------------------------------------------------------------------
def _fourcc(tag: str) -> int:
    return (ord(tag[0]) << 24) | (ord(tag[1]) << 16) | (ord(tag[2]) << 8) | ord(tag[3])


@functools.lru_cache(maxsize=16)
def _base_typeface(filename: str) -> skia.Typeface:
    path = _FONTS_DIR / filename
    tf = skia.Typeface.MakeFromFile(str(path))
    if tf is None:
        raise FileNotFoundError(f"Bundled studio font missing or unreadable: {path}")
    return tf


@functools.lru_cache(maxsize=32)
def _typeface(style_key: str, opsz_display: bool = False) -> skia.Typeface:
    if style_key == "serif_regular":
        return _base_typeface("InstrumentSerif-Regular.ttf")
    if style_key == "serif_italic":
        return _base_typeface("InstrumentSerif-Italic.ttf")

    coords = []
    if style_key.startswith("inter_"):
        base = _base_typeface("Inter-Variable.ttf")
        weights = {
            "inter_regular": 400.0,
            "inter_medium": 500.0,
            "inter_semibold": 600.0,
            "inter_bold": 700.0,
        }
        w = weights.get(style_key, 400.0)
        coords.append(skia.FontArguments.VariationPosition.Coordinate(_fourcc("wght"), w))
        if opsz_display:
            coords.append(skia.FontArguments.VariationPosition.Coordinate(_fourcc("opsz"), 32.0))
    elif style_key.startswith("mono_"):
        base = _base_typeface("JetBrainsMono-Variable.ttf")
        w = 600.0 if style_key == "mono_semibold" else 400.0
        coords.append(skia.FontArguments.VariationPosition.Coordinate(_fourcc("wght"), w))
    else:
        return _base_typeface("Inter-Variable.ttf")

    pos = skia.FontArguments.VariationPosition(
        skia.FontArguments.VariationPosition.Coordinates(coords)
    )
    cloned = base.makeClone(skia.FontArguments().setVariationDesignPosition(pos))
    return cloned if cloned is not None else base


@functools.lru_cache(maxsize=256)
def get_font(style: str, size: float) -> skia.Font:
    """Return calibrated OFL studio Skia Font."""
    # Allow crisp ergonomic aliases
    alias = {
        "display": "inter_bold",
        "sans_bold": "inter_bold",
        "sans_semi": "inter_semibold",
        "sans_med": "inter_medium",
        "sans": "inter_regular",
        "serif": "serif_regular",
        "serif_italic": "serif_italic",
        "mono": "mono_regular",
        "mono_bold": "mono_semibold",
        "mono_semi": "mono_semibold",
    }.get(style, style)
    tf = _typeface(alias, opsz_display=(size >= 36.0 and alias.startswith("inter_")))
    f = skia.Font(tf, float(size))
    f.setSubpixel(True)
    f.setEdging(skia.Font.Edging.kSubpixelAntiAlias)
    return f


@functools.lru_cache(maxsize=2048)
def _build_tracked_blob(style: str, size: float, text: str, tracking_em: float) -> tuple[skia.TextBlob | None, float]:
    nfc = unicodedata.normalize("NFC", text)
    if not nfc:
        return None, 0.0
    font = get_font(style, size)
    if abs(tracking_em) < 1e-4:
        w = float(font.measureText(nfc))
        return None, w
    glyphs = font.textToGlyphs(nfc)
    if len(glyphs) != len(nfc) or len(glyphs) == 0:
        w = float(font.measureText(nfc))
        return None, w
    widths = font.getWidths(glyphs)
    track_px = float(size) * float(tracking_em)
    positions = []
    cur_x = 0.0
    for idx, w in enumerate(widths):
        positions.append((cur_x, 0.0))
        cur_x += float(w)
        if idx < len(widths) - 1:
            cur_x += track_px
    blob = skia.TextBlob.MakeFromPosText(nfc, positions, font)
    return blob, cur_x


def measure_tracked_text(style: str, size: float, text: str, tracking_em: float = 0.0) -> float:
    _, w = _build_tracked_blob(style, float(size), text, round(float(tracking_em), 4))
    return float(w)


def draw_tracked_text(
    canvas: skia.Canvas,
    style: str,
    size: float,
    text: str,
    x: float,
    baseline_y: float,
    color_rgba: tuple[int, int, int, int] | tuple[int, int, int],
    tracking_em: float = 0.0,
) -> float:
    """Draw tracked studio text and return its rendered advance width."""
    a = color_rgba[3] if len(color_rgba) == 4 else 255
    paint = skia.Paint(Color=rgba(color_rgba[0], color_rgba[1], color_rgba[2], a), AntiAlias=True)
    nfc = unicodedata.normalize("NFC", text)
    if not nfc:
        return 0.0
    t_key = round(float(tracking_em), 4)
    blob, adv = _build_tracked_blob(style, float(size), nfc, t_key)
    if blob is not None:
        canvas.drawTextBlob(blob, float(x), float(baseline_y), paint)
    else:
        canvas.drawString(nfc, float(x), float(baseline_y), get_font(style, float(size)), paint)
    return adv


def draw_masked_tracked_text(
    canvas: skia.Canvas,
    style: str,
    size: float,
    text: str,
    x: float,
    baseline_y: float,
    color_rgba: tuple[int, int, int, int] | tuple[int, int, int],
    progress: float,
    tracking_em: float = 0.0,
    slide_px: float | None = None,
) -> float:
    """Baseline-clipped upward kinetic type reveal (ease_out_expo, zero overshoot)."""
    p = clamp01(progress)
    if p <= 0.005:
        return measure_tracked_text(style, size, text, tracking_em)
    e = ease_out_expo(p)
    offset = (slide_px if slide_px is not None else size * 0.92) * (1.0 - e)
    top = baseline_y - size * 1.15
    bottom = baseline_y + size * 0.34
    adv = measure_tracked_text(style, size, text, tracking_em)

    canvas.save()
    canvas.clipRect(skia.Rect.MakeLTRB(x - 12.0, top, x + adv + 28.0, bottom), doAntiAlias=True)
    r, g, b = color_rgba[0], color_rgba[1], color_rgba[2]
    base_a = color_rgba[3] if len(color_rgba) == 4 else 255
    fade_a = int(base_a * min(1.0, e * 1.35))
    draw_tracked_text(canvas, style, size, text, x, baseline_y + offset, (r, g, b, fade_a), tracking_em)
    canvas.restore()
    return adv


# ---------------------------------------------------------------------------
# Static Tactile Alabaster Paper Backdrop (Zero Neon, Pre-Baked)
# ---------------------------------------------------------------------------
_PAPER_BACKDROP_IMG: skia.Image | None = None


def get_paper_backdrop() -> skia.Image:
    """Build and cache once the tactile #F4F2EC warm paper backdrop with Swiss registration marks."""
    global _PAPER_BACKDROP_IMG
    if _PAPER_BACKDROP_IMG is not None:
        return _PAPER_BACKDROP_IMG

    rng = np.random.default_rng(2026)
    base = np.empty((HEIGHT, WIDTH, 4), dtype=np.uint8)
    # Subtle micro-paper texture (±2 luma grain)
    noise = rng.integers(-2, 3, size=(HEIGHT, WIDTH), dtype=np.int16)
    # BGRA byte order in memory for kBGRA_8888_ColorType
    base[:, :, 0] = np.clip(PAPER[2] + noise, 0, 255).astype(np.uint8)
    base[:, :, 1] = np.clip(PAPER[1] + noise, 0, 255).astype(np.uint8)
    base[:, :, 2] = np.clip(PAPER[0] + noise, 0, 255).astype(np.uint8)
    base[:, :, 3] = 255

    surf = skia.Surface.MakeRasterDirect(
        skia.ImageInfo.MakeN32Premul(WIDTH, HEIGHT),
        base,
    )
    c = surf.getCanvas()

    # Very subtle radial edge warmth (studio photography vignette on paper, ultra gentle)
    vig = skia.GradientShader.MakeRadial(
        center=(WIDTH * 0.5, HEIGHT * 0.45),
        radius=WIDTH * 0.72,
        colors=[rgba(255, 255, 255, 18), rgba(210, 204, 190, 28)],
        positions=[0.0, 1.0],
    )
    c.drawRect(skia.Rect.MakeWH(WIDTH, HEIGHT), skia.Paint(Shader=vig))

    # Whisper-quiet architectural corner registration crosshairs (+28px inset)
    reg_p = skia.Paint(Color=rgba(*GRAPHITE, 75), StrokeWidth=1.0)
    for rx, ry in ((34, 34), (WIDTH - 34, 34), (34, HEIGHT - 34), (WIDTH - 34, HEIGHT - 34)):
        c.drawLine(rx - 8, ry, rx + 8, ry, reg_p)
        c.drawLine(rx, ry - 8, rx, ry + 8, reg_p)

    _PAPER_BACKDROP_IMG = surf.makeImageSnapshot()
    return _PAPER_BACKDROP_IMG


def draw_paper_backdrop(canvas: skia.Canvas) -> None:
    canvas.drawImage(get_paper_backdrop(), 0.0, 0.0)


# ---------------------------------------------------------------------------
# Physical Studio Card with Cached Soft Contact Shadow (Zero Neon Glow)
# ---------------------------------------------------------------------------
_SHADOW_STAMPS: dict[tuple[int, int, int, int], skia.Image] = {}


def _get_contact_shadow(w: int, h: int, radius: int, elev: int = 16) -> skia.Image:
    key = (w, h, radius, elev)
    cached = _SHADOW_STAMPS.get(key)
    if cached is not None:
        return cached
    pad = elev * 3
    surf = skia.Surface(w + pad * 2, h + pad * 2)
    sc = surf.getCanvas()
    rr = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(pad, pad, w, h), radius, radius)
    # Penumbra soft ambient shadow
    sc.drawRRect(
        rr,
        skia.Paint(
            Color=rgba(20, 19, 16, 22),
            MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, float(elev) * 1.15),
            AntiAlias=True,
        ),
    )
    # Crisp contact umbra underneath
    sc.drawRRect(
        skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(pad, pad + 3, w, h), radius, radius),
        skia.Paint(
            Color=rgba(20, 19, 16, 28),
            MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 5.0),
            AntiAlias=True,
        ),
    )
    img = surf.makeImageSnapshot()
    _SHADOW_STAMPS[key] = img
    return img


def draw_paper_card(
    canvas: skia.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    radius: float = 12.0,
    fill_rgb: tuple[int, int, int] = WHITE,
    fill_alpha: int = 255,
    border_rgb: tuple[int, int, int] = RULE,
    border_alpha: int = 255,
    border_w: float = 1.2,
    shadow_elev: int = 16,
) -> None:
    """Render clean physical card with realistic studio contact shadow and 1px hairline border."""
    if shadow_elev > 0:
        pad = shadow_elev * 3
        sh = _get_contact_shadow(int(round(w)), int(round(h)), int(round(radius)), shadow_elev)
        canvas.drawImage(sh, x - pad, y - pad + shadow_elev * 0.45)

    rect = skia.Rect.MakeXYWH(x, y, w, h)
    rr = skia.RRect.MakeRectXY(rect, radius, radius)
    canvas.drawRRect(rr, skia.Paint(Color=rgba(*fill_rgb, fill_alpha), AntiAlias=True))
    if border_alpha > 0 and border_w > 0:
        canvas.drawRRect(
            rr,
            skia.Paint(
                Color=rgba(*border_rgb, border_alpha),
                Style=skia.Paint.kStroke_Style,
                StrokeWidth=border_w,
                AntiAlias=True,
            ),
        )


# ---------------------------------------------------------------------------
# Running Editorial Chrome & Progress Rule
# ---------------------------------------------------------------------------
def draw_editorial_chrome(canvas: skia.Canvas, t: float, index_label: str, total_sec: float = 32.0) -> None:
    """Swiss editorial running header and razor-thin bottom progress track."""
    parts = index_label.split("/", 1)
    num = parts[0].strip()
    rest = parts[1].strip() if len(parts) > 1 else ""

    nx = 110.0
    nw = draw_tracked_text(canvas, "mono_bold", 14, num, nx, 48, (*VERMILION, 255), tracking_em=0.10)
    if rest:
        draw_tracked_text(
            canvas,
            "mono",
            14,
            f"  /  {rest}",
            nx + nw,
            48,
            (*GRAPHITE, 255),
            tracking_em=0.10,
        )

    right_lbl = "ANTIGRAVITY-HUMAN-CONTROL"
    rw = measure_tracked_text("mono", 13, right_lbl, tracking_em=0.12)
    draw_tracked_text(canvas, "mono", 13, right_lbl, WIDTH - 110.0 - rw, 48, (*GRAPHITE, 220), tracking_em=0.12)

    # Hairline top rule
    canvas.drawLine(110.0, 68.0, WIDTH - 110.0, 68.0, skia.Paint(Color=rgba(*RULE, 255), StrokeWidth=1.0))

    # Crisp 3px bottom progress indicator
    prog = clamp01(t / total_sec)
    canvas.drawRect(skia.Rect.MakeXYWH(0.0, HEIGHT - 3.0, WIDTH, 3.0), skia.Paint(Color=rgba(*RULE, 200)))
    canvas.drawRect(skia.Rect.MakeXYWH(0.0, HEIGHT - 3.0, WIDTH * prog, 3.0), skia.Paint(Color=rgba(*VERMILION, 240)))


# ---------------------------------------------------------------------------
# Precision Optical Aperture Mark (Braun / Leica Inspired, Zero Glow)
# ---------------------------------------------------------------------------
def draw_aperture_logo(canvas: skia.Canvas, cx: float, cy: float, r: float, t: float, alpha: float = 1.0) -> None:
    a = clamp01(alpha)
    if a <= 0.01:
        return
    a255 = int(255 * a)
    # Outer precision bezel ring
    canvas.drawCircle(
        cx,
        cy,
        r,
        skia.Paint(Color=rgba(*INK, a255), Style=skia.Paint.kStroke_Style, StrokeWidth=max(2.0, r * 0.055), AntiAlias=True),
    )
    # Inner scale ring
    canvas.drawCircle(
        cx,
        cy,
        r * 0.72,
        skia.Paint(Color=rgba(*GRAPHITE, int(140 * a)), Style=skia.Paint.kStroke_Style, StrokeWidth=1.2, AntiAlias=True),
    )

    # 6 rotating architectural aperture segments
    rot = t * 0.55
    seg_p = skia.Paint(
        Color=rgba(*INK, int(225 * a)),
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=max(1.8, r * 0.042),
        StrokeCap=skia.Paint.kRound_Cap,
        AntiAlias=True,
    )
    for idx in range(6):
        ang = rot + idx * (math.pi / 3.0)
        x0 = cx + math.cos(ang) * (r * 0.34)
        y0 = cy + math.sin(ang) * (r * 0.34)
        x1 = cx + math.cos(ang + 0.58) * (r * 0.68)
        y1 = cy + math.sin(ang + 0.58) * (r * 0.68)
        canvas.drawLine(x0, y0, x1, y1, seg_p)

    # Single sharp signal vermilion optical iris pip
    canvas.drawCircle(cx, cy, max(4.0, r * 0.14), skia.Paint(Color=rgba(*VERMILION, a255), AntiAlias=True))


# ---------------------------------------------------------------------------
# Vector Checkmark, Smooth Bezier Arc, Cursor & Editorial Pill Tag
# ---------------------------------------------------------------------------
def draw_vector_check(
    canvas: skia.Canvas,
    cx: float,
    cy: float,
    size: float,
    progress: float,
    rgb: tuple[int, int, int] = SAGE,
    stroke_w: float = 2.6,
) -> None:
    p = clamp01(progress)
    if p <= 0.01:
        return
    path = skia.Path()
    path.moveTo(cx - size * 0.34, cy + size * 0.03)
    path.lineTo(cx - size * 0.08, cy + size * 0.28)
    path.lineTo(cx + size * 0.36, cy - size * 0.24)
    pm = skia.PathMeasure(path, False)
    total = pm.getLength()
    seg = skia.Path()
    pm.getSegment(0.0, total * ease_out_expo(p), seg, True)
    canvas.drawPath(
        seg,
        skia.Paint(
            Color=rgba(*rgb, 255),
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=stroke_w,
            StrokeCap=skia.Paint.kRound_Cap,
            StrokeJoin=skia.Paint.kRound_Join,
            AntiAlias=True,
        ),
    )


def draw_bezier_arc(
    canvas: skia.Canvas,
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    base_rgba: tuple[int, int, int, int],
    *,
    progress: float | None = None,
    active_rgb: tuple[int, int, int] = VERMILION,
    width: float = 2.4,
) -> None:
    path = skia.Path()
    path.moveTo(p0[0], p0[1])
    path.cubicTo(p1[0], p1[1], p2[0], p2[1], p3[0], p3[1])
    canvas.drawPath(
        path,
        skia.Paint(
            Color=rgba(*base_rgba),
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=width,
            StrokeCap=skia.Paint.kRound_Cap,
            AntiAlias=True,
        ),
    )
    if progress is not None and 0.0 <= progress <= 1.0:
        pm = skia.PathMeasure(path, False)
        total = pm.getLength()
        dist = total * clamp01(progress)
        seg = skia.Path()
        pm.getSegment(0.0, dist, seg, True)
        canvas.drawPath(
            seg,
            skia.Paint(
                Color=rgba(*active_rgb, 255),
                Style=skia.Paint.kStroke_Style,
                StrokeWidth=width * 1.4,
                StrokeCap=skia.Paint.kRound_Cap,
                AntiAlias=True,
            ),
        )
        res = pm.getPosTan(dist)
        if len(res) == 2:
            pos, _tan = res
            ok = True
        else:
            ok, pos, _tan = res
        if ok:
            canvas.drawCircle(pos.fX, pos.fY, 4.5, skia.Paint(Color=rgba(*active_rgb, 255), AntiAlias=True))


def draw_cursor(canvas: skia.Canvas, x: float, y: float, scale: float = 1.0, light_ring: bool = True) -> None:
    """Render sharp crisp architectural pointer cursor."""
    pts = [
        (0.0, 0.0),
        (0.0, 21.0),
        (4.8, 16.5),
        (8.6, 24.5),
        (11.6, 23.0),
        (7.8, 15.0),
        (14.5, 14.5),
    ]
    path = skia.Path()
    path.moveTo(x + pts[0][0] * scale, y + pts[0][1] * scale)
    for px, py in pts[1:]:
        path.lineTo(x + px * scale, y + py * scale)
    path.close()

    # Subtle contact drop shadow
    sh = skia.Path()
    sh.moveTo(x + (pts[0][0] + 1.5) * scale, y + (pts[0][1] + 2.5) * scale)
    for px, py in pts[1:]:
        sh.lineTo(x + (px + 1.5) * scale, y + (py + 2.5) * scale)
    sh.close()
    canvas.drawPath(
        sh,
        skia.Paint(
            Color=rgba(0, 0, 0, 75),
            MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 3.0),
            AntiAlias=True,
        ),
    )
    canvas.drawPath(path, skia.Paint(Color=rgba(*INK, 255), AntiAlias=True))
    if light_ring:
        canvas.drawPath(
            path,
            skia.Paint(
                Color=rgba(*WHITE, 255),
                Style=skia.Paint.kStroke_Style,
                StrokeWidth=2.0,
                StrokeJoin=skia.Paint.kRound_Join,
                AntiAlias=True,
            ),
        )


def draw_tag(
    canvas: skia.Canvas,
    x: float,
    y: float,
    text: str,
    *,
    font_style: str = "mono_bold",
    font_size: float = 15.0,
    bg_rgb: tuple[int, int, int] = WHITE,
    border_rgb: tuple[int, int, int] = RULE,
    text_rgb: tuple[int, int, int] = INK,
    tracking_em: float = 0.05,
    leading_check: float | None = None,
    dot_rgb: tuple[int, int, int] | None = None,
) -> float:
    """Draw a clean flat editorial specification pill/tag and return its width."""
    tw = measure_tracked_text(font_style, font_size, text, tracking_em)
    lead_w = 24.0 if leading_check is not None else (18.0 if dot_rgb is not None else 0.0)
    w = tw + lead_w + 32.0
    h = font_size + 20.0
    rr = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x, y, w, h), 6.0, 6.0)
    canvas.drawRRect(rr, skia.Paint(Color=rgba(*bg_rgb, 255), AntiAlias=True))
    canvas.drawRRect(
        rr,
        skia.Paint(Color=rgba(*border_rgb, 255), Style=skia.Paint.kStroke_Style, StrokeWidth=1.2, AntiAlias=True),
    )
    if leading_check is not None:
        draw_vector_check(canvas, x + 21.0, y + h / 2.0, 15.0, leading_check, rgb=text_rgb, stroke_w=2.4)
    elif dot_rgb is not None:
        canvas.drawCircle(x + 19.0, y + h / 2.0, 4.0, skia.Paint(Color=rgba(*dot_rgb, 255), AntiAlias=True))

    draw_tracked_text(
        canvas,
        font_style,
        font_size,
        text,
        x + 16.0 + lead_w,
        y + h / 2.0 + font_size * 0.34,
        (*text_rgb, 255),
        tracking_em=tracking_em,
    )
    return w
