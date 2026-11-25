"""Tier 2.5: Persistent Warm Windows.Media.Ocr Worker (~40-65ms per capture, zero extra wheels)."""

from __future__ import annotations

import json
import subprocess
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any

from scripts.engines.tier3_vision import (
    DesktopCaptureUnavailableError,
    _desktop_capture_error_payload,
    capture_region_pil,
)
from scripts.win32_core import find_windows, get_state_dir

_PS_OCR_SCRIPT = r"""
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime

$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Storage.Streams.RandomAccessStreamReference, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Foundation, ContentType=WindowsRuntime]

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await-WinRT($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    return $netTask.Result
}

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) {
    $langs = [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages
    if ($langs.Count -gt 0) {
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($langs[0])
    }
}
$langTag = if ($null -ne $engine) { $engine.RecognizerLanguage.LanguageTag } else { "" }

$avail = @()
foreach ($l in [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages) {
    $avail += $l.LanguageTag
}

[Console]::Out.WriteLine((@{ ok = ($null -ne $engine); ready = $true; lang = $langTag; available = $avail } | ConvertTo-Json -Compress))
[Console]::Out.Flush()

while ($true) {
    $line = [Console]::In.ReadLine()
    if ($null -eq $line) { break }
    $line = $line.Trim()
    if ($line -eq "") { continue }
    try {
        $req = $line | ConvertFrom-Json
        if ($req.cmd -eq "quit") { break }
        if ($req.cmd -eq "info") {
            [Console]::Out.WriteLine((@{ ok = ($null -ne $engine); lang = $langTag; available = $avail } | ConvertTo-Json -Compress))
            [Console]::Out.Flush()
            continue
        }
        if ($null -eq $engine) {
            [Console]::Out.WriteLine((@{ ok = $false; error = "No Windows OCR language pack installed." } | ConvertTo-Json -Compress))
            [Console]::Out.Flush()
            continue
        }
        $imgPath = [string]$req.image_path
        $file = Await-WinRT ([Windows.Storage.StorageFile]::GetFileFromPathAsync($imgPath)) ([Windows.Storage.StorageFile])
        $stream = Await-WinRT ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
        $decoder = Await-WinRT ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bitmap = Await-WinRT ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $ocrRes = Await-WinRT ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])

        $linesOut = @()
        $wordsOut = @()
        foreach ($ln in $ocrRes.Lines) {
            $linesOut += $ln.Text
            foreach ($w in $ln.Words) {
                $r = $w.BoundingRect
                $wordsOut += @{
                    text = $w.Text
                    x = [math]::Round($r.X, 1)
                    y = [math]::Round($r.Y, 1)
                    w = [math]::Round($r.Width, 1)
                    h = [math]::Round($r.Height, 1)
                }
            }
        }
        $stream.Dispose()
        $bitmap.Dispose()
        [Console]::Out.WriteLine((@{ ok = $true; lang = $langTag; lines = $linesOut; words = $wordsOut } | ConvertTo-Json -Compress -Depth 5))
        [Console]::Out.Flush()
    } catch {
        [Console]::Out.WriteLine((@{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress))
        [Console]::Out.Flush()
    }
}
"""


def strip_diacritics(text: str) -> str:
    """Normalize text for Vietnamese diacritic-insensitive matching (đ->d, NFKD strip)."""
    replaced = text.replace("đ", "d").replace("Đ", "D")
    nfkd = unicodedata.normalize("NFKD", replaced)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch)).lower().strip()


class WinRTOcrWorker:
    """Persistent warm PowerShell WinRT OCR worker."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._info: dict[str, Any] | None = None

    def _ensure_started(self) -> dict[str, Any]:
        if self._proc is not None and self._proc.poll() is None:
            return self._info or {"ok": True}

        script_path = get_state_dir() / "winrt_ocr_worker.ps1"
        script_path.write_text(_PS_OCR_SCRIPT, encoding="utf-8")

        self._proc = subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            creationflags=0x08000000,
        )
        assert self._proc.stdout is not None
        banner = self._proc.stdout.readline()
        if not banner:
            self._info = {"ok": False, "error": "WinRT OCR worker failed to emit startup banner."}
            return self._info
        self._info = json.loads(banner)
        return self._info

    def get_info(self) -> dict[str, Any]:
        with self._lock:
            return self._ensure_started()

    def recognize_file(self, image_path: str | Path) -> dict[str, Any]:
        t0 = time.perf_counter()
        with self._lock:
            info = self._ensure_started()
            if not info.get("ok"):
                return {"ok": False, "code": "OCR_UNAVAILABLE", "error": info.get("error", "WinRT OCR unavailable.")}
            assert self._proc is not None and self._proc.stdin is not None and self._proc.stdout is not None
            req = json.dumps({"cmd": "ocr", "image_path": str(Path(image_path).resolve())}, ensure_ascii=False)
            self._proc.stdin.write(req + "\n")
            self._proc.stdin.flush()
            resp_line = self._proc.stdout.readline()
            if not resp_line:
                self._proc = None
                return {"ok": False, "code": "OCR_WORKER_CRASH", "error": "WinRT OCR worker terminated unexpectedly."}
            res = json.loads(resp_line)
            res["elapsed_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
            return res

    def close(self) -> None:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                try:
                    assert self._proc.stdin is not None
                    self._proc.stdin.write('{"cmd":"quit"}\n')
                    self._proc.stdin.flush()
                    self._proc.wait(timeout=1.0)
                except Exception:
                    self._proc.kill()
            self._proc = None


_WORKER = WinRTOcrWorker()


def get_ocr_worker() -> WinRTOcrWorker:
    return _WORKER


def find_text_on_screen(
    query: str,
    window_title: str | None = None,
    monitor_index: int = 0,
) -> dict[str, Any]:
    """Capture target window/monitor and locate query text using persistent WinRT OCR."""
    t0 = time.perf_counter()
    from scripts.display_mapper import get_monitor, list_monitors

    try:
        if window_title:
            wins = find_windows(title_query=window_title, visible_only=True)
            if wins:
                l, t, r, b = wins[0]["rect"]
                origin_x, origin_y = l, t
                pil_img = capture_region_pil(l, t, max(1, r - l), max(1, b - t))
            else:
                mon = get_monitor(monitor_index, list_monitors())
                origin_x, origin_y = mon["left"], mon["top"]
                pil_img = capture_region_pil(mon["left"], mon["top"], mon["width"], mon["height"])
        else:
            mon = get_monitor(monitor_index, list_monitors())
            origin_x, origin_y = mon["left"], mon["top"]
            pil_img = capture_region_pil(mon["left"], mon["top"], mon["width"], mon["height"])
    except DesktopCaptureUnavailableError as exc:
        return _desktop_capture_error_payload(exc)

    tmp_img = get_state_dir() / "ocr_probe.bmp"
    pil_img.save(tmp_img, format="BMP")
    ocr = _WORKER.recognize_file(tmp_img)
    if not ocr.get("ok"):
        return ocr

    words = ocr.get("words") or []
    q_norm = strip_diacritics(query)
    q_tokens = [tok for tok in q_norm.split() if tok]

    # Single-token exact/substring match first, then consecutive multi-word phrase match
    matched_boxes: list[dict[str, Any]] = []
    if len(q_tokens) <= 1:
        for w in words:
            wt = strip_diacritics(str(w.get("text", "")))
            if q_norm and q_norm in wt:
                matched_boxes.append(w)
                break
    else:
        for i in range(len(words) - len(q_tokens) + 1):
            window_words = words[i : i + len(q_tokens)]
            joined = " ".join(strip_diacritics(str(w.get("text", ""))) for w in window_words)
            if q_norm in joined:
                matched_boxes = window_words
                break

    if not matched_boxes:
        return {
            "ok": False,
            "code": "OCR_TEXT_NOT_FOUND",
            "tier": "tier25_ocr",
            "lines": ocr.get("lines", []),
            "error": f"Text '{query}' not found via WinRT OCR.",
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    x1 = min(float(w["x"]) for w in matched_boxes)
    y1 = min(float(w["y"]) for w in matched_boxes)
    x2 = max(float(w["x"]) + float(w["w"]) for w in matched_boxes)
    y2 = max(float(w["y"]) + float(w["h"]) for w in matched_boxes)
    cx = origin_x + round((x1 + x2) / 2.0)
    cy = origin_y + round((y1 + y2) / 2.0)

    return {
        "ok": True,
        "tier": "tier25_ocr",
        "lang": ocr.get("lang", ""),
        "matched_text": " ".join(str(w.get("text", "")) for w in matched_boxes),
        "center_phys": [cx, cy],
        "bbox_phys": [origin_x + round(x1), origin_y + round(y1), origin_x + round(x2), origin_y + round(y2)],
        "lines": ocr.get("lines", []),
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
    }
