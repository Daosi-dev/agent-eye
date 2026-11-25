"""Multi-monitor DPI discovery, 1000x1000 coordinate math, and Outer-Ruler rendering."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from scripts.win32_core import (
    MONITORINFOEXW,
    RECT,
    SM_CXVIRTUALSCREEN,
    SM_CYVIRTUALSCREEN,
    SM_XVIRTUALSCREEN,
    SM_YVIRTUALSCREEN,
    enable_dpi_awareness,
    shcore,
    user32,
)

enable_dpi_awareness()

MDT_EFFECTIVE_DPI = 0
MONITORINFOF_PRIMARY = 0x00000001


def get_virtual_screen_bounds() -> dict[str, int]:
    """Return full multi-monitor Virtual Screen rectangle."""
    left = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
    top = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
    width = int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
    height = int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
    return {"left": left, "top": top, "width": max(1, width), "height": max(1, height)}


def list_monitors() -> list[dict[str, Any]]:
    """Enumerate all connected monitors with physical pixels, negative offsets, and DPI scale."""
    enable_dpi_awareness()
    monitors: list[dict[str, Any]] = []
    cb_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(RECT),
        ctypes.c_ssize_t,
    )

    def _callback(hmonitor: int, _hdc: int, _lprect: Any, _lparam: int) -> bool:
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if not user32.GetMonitorInfoW(ctypes.c_void_p(hmonitor), ctypes.byref(info)):
            return True
        dpi_x = wintypes.UINT(96)
        dpi_y = wintypes.UINT(96)
        if shcore is not None:
            try:
                shcore.GetDpiForMonitor.argtypes = [
                    ctypes.c_void_p,
                    ctypes.c_int,
                    ctypes.POINTER(wintypes.UINT),
                    ctypes.POINTER(wintypes.UINT),
                ]
                shcore.GetDpiForMonitor.restype = ctypes.c_long
                shcore.GetDpiForMonitor(
                    ctypes.c_void_p(hmonitor),
                    MDT_EFFECTIVE_DPI,
                    ctypes.byref(dpi_x),
                    ctypes.byref(dpi_y),
                )
            except Exception:
                pass
        rc = info.rcMonitor
        width = int(rc.right - rc.left)
        height = int(rc.bottom - rc.top)
        monitors.append(
            {
                "device": info.szDevice,
                "left": int(rc.left),
                "top": int(rc.top),
                "right": int(rc.right),
                "bottom": int(rc.bottom),
                "width": width,
                "height": height,
                "dpi_x": int(dpi_x.value),
                "dpi_y": int(dpi_y.value),
                "scale_percent": round((int(dpi_x.value) / 96.0) * 100),
                "is_primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
            }
        )
        return True

    user32.EnumDisplayMonitors.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        cb_type,
        ctypes.c_ssize_t,
    ]
    user32.EnumDisplayMonitors.restype = wintypes.BOOL
    user32.EnumDisplayMonitors(None, None, cb_type(_callback), 0)

    # Order primary monitor as index 0, remaining left-to-right then top-to-bottom
    monitors.sort(key=lambda m: (not m["is_primary"], m["left"], m["top"]))
    for idx, mon in enumerate(monitors):
        mon["index"] = idx
    return monitors


def get_monitor(monitor_index: int = 0, monitors: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    mons = monitors if monitors is not None else list_monitors()
    if not mons:
        vs = get_virtual_screen_bounds()
        return {
            "index": 0,
            "device": "VIRTUAL",
            "left": vs["left"],
            "top": vs["top"],
            "right": vs["left"] + vs["width"],
            "bottom": vs["top"] + vs["height"],
            "width": vs["width"],
            "height": vs["height"],
            "dpi_x": 96,
            "dpi_y": 96,
            "scale_percent": 100,
            "is_primary": True,
        }
    if 0 <= monitor_index < len(mons):
        return mons[monitor_index]
    return mons[0]


def clamp(val: float, low: float, high: float) -> float:
    return max(low, min(high, val))


def norm_to_physical(
    norm_x: float,
    norm_y: float,
    monitor_index: int = 0,
    monitors: list[dict[str, Any]] | None = None,
) -> tuple[int, int]:
    """Convert normalized (0..1000, 0..1000) coordinates to absolute physical desktop pixels."""
    mon = get_monitor(monitor_index, monitors)
    nx = clamp(float(norm_x), 0.0, 1000.0)
    ny = clamp(float(norm_y), 0.0, 1000.0)
    phys_x = mon["left"] + round((nx / 1000.0) * max(1, mon["width"] - 1))
    phys_y = mon["top"] + round((ny / 1000.0) * max(1, mon["height"] - 1))
    return int(phys_x), int(phys_y)


def physical_to_norm(
    phys_x: int,
    phys_y: int,
    monitor_index: int | None = None,
    monitors: list[dict[str, Any]] | None = None,
) -> tuple[float, float, int]:
    """Convert physical pixels back to normalized (0..1000) and containing monitor index."""
    mons = monitors if monitors is not None else list_monitors()
    chosen: dict[str, Any] | None = None
    if monitor_index is not None:
        chosen = get_monitor(monitor_index, mons)
    else:
        for m in mons:
            if m["left"] <= phys_x < m["right"] and m["top"] <= phys_y < m["bottom"]:
                chosen = m
                break
        if chosen is None:
            chosen = get_monitor(0, mons)
    nx = ((phys_x - chosen["left"]) / max(1, chosen["width"] - 1)) * 1000.0
    ny = ((phys_y - chosen["top"]) / max(1, chosen["height"] - 1)) * 1000.0
    return round(clamp(nx, 0.0, 1000.0), 2), round(clamp(ny, 0.0, 1000.0), 2), int(chosen["index"])


def physical_to_sendinput_abs(
    phys_x: int,
    phys_y: int,
    virtual_bounds: dict[str, int] | None = None,
) -> tuple[int, int]:
    """Map physical Virtual Screen coordinates into Win32 SendInput 0..65535 absolute space."""
    vs = virtual_bounds if virtual_bounds is not None else get_virtual_screen_bounds()
    vx = vs["left"]
    vy = vs["top"]
    vw = max(2, vs["width"])
    vh = max(2, vs["height"])
    abs_x = round(((phys_x - vx) * 65535) / (vw - 1))
    abs_y = round(((phys_y - vy) * 65535) / (vh - 1))
    return int(clamp(abs_x, 0, 65535)), int(clamp(abs_y, 0, 65535))


def _load_font(size: int = 11) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for font_name in ("consola.ttf", "segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_outer_ruler_grid(
    pil_img: Image.Image,
    margin: int = 28,
) -> Image.Image:
    """
    Wrap captured image in a crisp Outer-Ruler 0..1000 frame + subtle translucent hairlines.
    Keeps inner UI elements 100% unobstructed by numeric labels.
    """
    src = pil_img.convert("RGBA")
    w, h = src.size
    out_w = w + 2 * margin
    out_h = h + 2 * margin

    canvas = Image.new("RGBA", (out_w, out_h), (22, 24, 29, 255))
    canvas.paste(src, (margin, margin))

    # Translucent inner hairlines (separate overlay so original RGB pixels remain clean/readable)
    overlay = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)

    major_line = (0, 220, 255, 58)
    minor_line = (255, 255, 255, 30)

    for step in range(50, 1000, 50):
        x = margin + round((step / 1000.0) * max(1, w - 1))
        y = margin + round((step / 1000.0) * max(1, h - 1))
        if step % 100 == 0:
            odraw.line([(x, margin), (x, margin + h - 1)], fill=major_line, width=1)
            odraw.line([(margin, y), (margin + w - 1, y)], fill=major_line, width=1)
        else:
            # Dashed subtle 50-unit hairlines
            for dy in range(margin, margin + h, 10):
                odraw.line([(x, dy), (x, min(margin + h - 1, dy + 4))], fill=minor_line, width=1)
            for dx in range(margin, margin + w, 10):
                odraw.line([(dx, y), (min(margin + w - 1, dx + 4), y)], fill=minor_line, width=1)

    canvas = Image.alpha_composite(canvas, overlay)
    draw = ImageDraw.Draw(canvas)
    font = _load_font(10)

    # Frame border around captured screenshot
    draw.rectangle(
        [margin - 1, margin - 1, margin + w, margin + h],
        outline=(0, 210, 245, 220),
        width=1,
    )

    # Outer ticks and 0..1000 numeric labels along all 4 margins
    for step in range(0, 1001, 25):
        x = margin + round((step / 1000.0) * max(1, w - 1))
        y = margin + round((step / 1000.0) * max(1, h - 1))
        is_major = step % 100 == 0
        is_mid = step % 50 == 0
        tick_len = 8 if is_major else (5 if is_mid else 3)
        tick_col = (0, 225, 255, 255) if is_major else (160, 175, 195, 220)

        # Top & Bottom ticks
        draw.line([(x, margin - 1), (x, margin - 1 - tick_len)], fill=tick_col, width=1)
        draw.line([(x, margin + h), (x, margin + h + tick_len)], fill=tick_col, width=1)
        # Left & Right ticks
        draw.line([(margin - 1, y), (margin - 1 - tick_len, y)], fill=tick_col, width=1)
        draw.line([(margin + w, y), (margin + w + tick_len, y)], fill=tick_col, width=1)

        if is_major:
            label = str(step)
            bbox = draw.textbbox((0, 0), label, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            tx = max(2, min(out_w - tw - 2, x - tw // 2))
            ty = max(2, min(out_h - th - 2, y - th // 2))

            # Top & bottom labels
            draw.text((tx, 3), label, fill=(235, 244, 255, 255), font=font)
            draw.text((tx, margin + h + 10), label, fill=(235, 244, 255, 255), font=font)
            # Left & right labels
            draw.text((max(2, margin - 10 - tw), ty), label, fill=(235, 244, 255, 255), font=font)
            draw.text((margin + w + 10, ty), label, fill=(235, 244, 255, 255), font=font)

    return canvas.convert("RGB")


def render_zoom_crop(
    pil_img: Image.Image,
    rel_x: int,
    rel_y: int,
    radius: int = 110,
    scale: int = 2,
) -> Image.Image:
    """Create zoomed local verification crop around (rel_x, rel_y) with target crosshair."""
    w, h = pil_img.size
    x1 = max(0, rel_x - radius)
    y1 = max(0, rel_y - radius)
    x2 = min(w, rel_x + radius)
    y2 = min(h, rel_y + radius)
    crop = pil_img.crop((x1, y1, x2, y2)).convert("RGB")
    zoomed = crop.resize((crop.width * scale, crop.height * scale), Image.Resampling.NEAREST)
    draw = ImageDraw.Draw(zoomed)
    cx = (rel_x - x1) * scale
    cy = (rel_y - y1) * scale
    draw.line([(cx - 18, cy), (cx + 18, cy)], fill=(0, 235, 255), width=2)
    draw.line([(cx, cy - 18), (cx, cy + 18)], fill=(0, 235, 255), width=2)
    draw.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], outline=(255, 90, 90), width=2)
    return zoomed
