"""Integration tests for live WinRT OCR, DesktopCaptureUnavailableError, and Warm Daemon RPC."""

import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

from scripts.engines import tier25_ocr, tier3_vision


def _load_ui_font(size: int = 24) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for fname in ("segoeui.ttf", "arial.ttf", "consola.ttf"):
        try:
            return ImageFont.truetype(fname, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _render_ui_mockup(out_path: Path) -> Image.Image:
    img = Image.new("RGB", (1366, 768), (24, 26, 32))
    draw = ImageDraw.Draw(img)
    font = _load_ui_font(24)

    buttons = [
        ("Export Video", (1020, 40, 1260, 100), (0, 140, 210)),
        ("Save Project", (80, 40, 320, 100), (45, 55, 72)),
        ("Timeline", (80, 520, 280, 580), (45, 55, 72)),
    ]
    for label, (x1, y1, x2, y2), bg in buttons:
        draw.rectangle([x1, y1, x2, y2], fill=bg, outline=(190, 210, 230), width=2)
        draw.text((x1 + 24, y1 + 16), label, fill=(255, 255, 255), font=font)

    img.save(out_path, format="PNG")
    return img


def test_live_winrt_ocr_locates_ui_buttons_and_warms_up(tmp_path: Path) -> None:
    img_path = tmp_path / "ui_mockup.png"
    _render_ui_mockup(img_path)

    worker = tier25_ocr.WinRTOcrWorker()
    try:
        res1 = worker.recognize_file(img_path)
        assert res1["ok"] is True
        joined1 = " ".join(res1.get("lines", []))
        assert "Export Video" in joined1
        assert "Save Project" in joined1
        assert "Timeline" in joined1

        # Verify bounding box for "Export" falls cleanly inside (1020..1260, 40..100)
        export_words = [w for w in res1.get("words", []) if "Export" in w["text"]]
        assert export_words, f"Expected 'Export' word in OCR output: {res1.get('words')}"
        ew = export_words[0]
        assert 1020 <= ew["x"] <= 1260
        assert 40 <= ew["y"] <= 100

        # Second call on already-warm worker should be fast
        res2 = worker.recognize_file(img_path)
        assert res2["ok"] is True
        assert res2["elapsed_ms"] < 500.0
    finally:
        worker.close()


def test_snapshot_returns_desktop_capture_unavailable_cleanly() -> None:
    with patch(
        "scripts.engines.tier3_vision.capture_region_pil",
        side_effect=tier3_vision.DesktopCaptureUnavailableError(
            "BitBlt failed",
            {"window_station": "WinSta0", "thread_desktop": "exebox-test", "is_interactive_default": False},
        ),
    ):
        res = tier3_vision.snapshot(monitor_index=0)
        assert res["ok"] is False
        assert res["code"] == "DESKTOP_CAPTURE_UNAVAILABLE"
        assert res["desktop"]["thread_desktop"] == "exebox-test"


def test_warm_daemon_end_to_end_ipc_latency(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    cli_path = repo_root / "scripts" / "cli.py"
    env = os.environ.copy()
    env["AGY_CONTROL_HOME"] = str(tmp_path)

    def _run_cli(*args: str) -> dict:
        proc = subprocess.run(
            [sys.executable, str(cli_path), *args],
            cwd=str(repo_root),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"CLI failed ({args}): stdout={proc.stdout} stderr={proc.stderr}"
        return json.loads(proc.stdout.strip())

    try:
        start_res = _run_cli("daemon", "start")
        assert start_res["ok"] is True
        assert start_res["running"] is True

        _run_cli("daemon", "status")  # warm socket/ARP cache
        status_res = _run_cli("daemon", "status")
        assert status_res["ok"] is True
        assert status_res["running"] is True
        assert status_res["daemon_ms"] < 10.0
        assert status_res["ipc_ms"] < 50.0

        doc_res = _run_cli("doctor")
        assert doc_res["ok"] is True
        assert doc_res["uia_available"] is True
        assert "desktop_environment" in doc_res
    finally:
        subprocess.run(
            [sys.executable, str(cli_path), "daemon", "stop"],
            cwd=str(repo_root),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
