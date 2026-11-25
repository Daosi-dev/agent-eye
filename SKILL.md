---
name: antigravity-human-control
description: Use when operating Windows desktop applications, browsers, native file dialogs, or custom-rendered canvas/creative software (CapCut, Godot, Blender, games) requiring fast background automation, WinRT OCR text locating, DPI-accurate 1000x1000 vision or UIA tree snapshots, window/app lifecycle control, single-stroke drag-and-verify, batch pipelines, or Vietnamese/Unicode text input.
---

# antigravity-human-control

Fast hybrid Windows & Browser control CLI backed by an integrity-isolated Warm Daemon (`<10ms` IPC) and a 5-stage Smart Capability Router. All commands return one JSON object (`ok`, `tier`, `elapsed_ms`, or `code`/`error`).

Always route GUI, browser, window, clipboard, and keyboard/mouse actions through `scripts/cli.py` rather than ad-hoc `pyautogui` calls.

## Execution Routing (Automatic)

1. **Tier 1 (`tier1_browser`)**: Raw CDP WebSocket over local Chrome/Edge/Brave (`<15ms`, 100% background).
2. **Tier 2 (`tier2_uia`)**: Windows `IUIAutomation` (tree snapshot + pattern invoke) & `#32770` Open/Save fast-path (`<80ms` circuit breaker).
3. **Tier 2.5 (`tier25_ocr`)**: Persistent warm `Windows.Media.Ocr` worker (`~50ms`, diacritic-insensitive matching) for canvas/custom UIs when `--text` is passed.
4. **Tier 3 (`tier3_vision`)**: Per-Monitor DPI v2 `mss` capture + Outer-Ruler `1000x1000` grid + Adaptive Turbo cursor (restores original cursor) or `--human` Bezier/Fitts + 3-phase Drag-Verify-MicroCorrect.
5. **Tier 4 (`tier4_lowlevel`)**: `AttachThreadInput` pre-focus guard, hardware `ScanCode` `SendInput`, and Atomic UTF-16LE Clipboard Paste.

## Quick Command Reference

Define `$HC` to point to the installed skill directory (works from any workspace; cross-agent fallback: `$HOME\.agents\skills\antigravity-human-control`):

```powershell
$HC = "$HOME\.gemini\config\skills\antigravity-human-control"
$PY = "$HC\.venv\Scripts\python.exe"
$CLI = "$HC\scripts\cli.py"

# Health check & window discovery
& $PY $CLI doctor
& $PY $CLI windows --title "Notepad"

# App & window lifecycle (launch, focus, wait, safe close, clipboard)
& $PY $CLI launch --target "notepad.exe" --wait-title "Notepad"
& $PY $CLI focus --title "Notepad"
& $PY $CLI wait --text "Save" --timeout-ms 3000
& $PY $CLI close --title "Notepad"
& $PY $CLI clipboard get
& $PY $CLI clipboard set --text "Xin chào Việt Nam!"

# Hybrid snapshot: --mode vision (Outer-Ruler 1000x1000 PNG), tree (compact UIA refs), or auto
& $PY $CLI snapshot --mode vision
& $PY $CLI snapshot --window "Notepad" --mode auto
& $PY $CLI snapshot --window "CapCut" --monitor 0

# Smart click: prefers CDP -> UIA -> WinRT OCR; attaches fallback_snapshot_path if OCR misses
& $PY $CLI click --selector "#submit-btn"
& $PY $CLI click --text "Export" --title "CapCut"
& $PY $CLI click --x 512 --y 340 --monitor 0
& $PY $CLI double_click --x 200 --y 400
& $PY $CLI right_click --x 200 --y 400

# Single-stroke Bezier drag + post-drag NCC verification & micro-correction (>4px)
& $PY $CLI drag --x1 180 --y1 500 --x2 640 --y2 500

# Vietnamese/Unicode-safe input (Atomic Clipboard restore by default; --human for keystroke timing)
& $PY $CLI type --text "Xin chào Việt Nam!" --enter
& $PY $CLI hotkey --keys "ctrl+s"

# Extract DOM, UIA tree, WinRT OCR text, or OCR an explicit image file
& $PY $CLI extract --title "Notepad"
& $PY $CLI extract --ocr --monitor 0
& $PY $CLI extract --ocr --image "path\to\capture.png"

# Launch Chrome/Edge with persistent automation profile & CDP enabled
& $PY $CLI open_browser --url "https://example.com"

# Batch multi-step pipeline in one daemon call (~200ms vs 15-20s across LLM turns)
& $PY $CLI batch --steps '[{"action":"click","text":"Export"},{"action":"wait_text","text":"File name","timeout_ms":3000},{"action":"type","text":"final_cut.mp4","enter":true}]'

# Optional click-through Debug HUD (0% GPU when off; toggle hotkey Ctrl+Alt+H)
& $PY $CLI hud on
& $PY $CLI click --x 500 --y 500 --debug
```

## Mandatory Guardrails & Error Handling

- **`HUMAN_HANDOFF_REQUIRED`**: Returned if a CAPTCHA, Turnstile, or human verification gate is detected. **Stop immediately** and ask the user to complete verification in the visible UI. Never attempt to solve or bypass anti-bot challenges.
- **`ELEVATION_REQUIRED`**: Returned (`<1ms` token integrity check) if the target window runs at higher integrity (Administrator) than the current daemon (`daemon_medium` vs `daemon_high`). Report clearly and advise the user to launch an elevated session via `scripts\open_elevated_shell.ps1` (standard Windows UAC prompt). Never attempt silent UAC/UIPI bypass.
- **`DESKTOP_CAPTURE_UNAVAILABLE`**: Returned if screen capture is blocked by a locked, headless, or isolated sandbox desktop (`thread_desktop != Default`). Report the block clearly instead of retrying capture.
- **`PROTECTED_PROCESS`**: Returned if `close` targets critical OS/shell processes (`explorer.exe`, `csrss.exe`, `lsass.exe`, etc.).
- **`USER_INTERRUPT`**: Returned if `Ctrl+Alt+Esc` panic hotkey is pressed or physical user mouse movement is detected mid-stroke. Yield control cleanly.
- **`drag` Verification**: Inspect `verify_crop_path` and `micro_corrected` in the JSON output when precision matters (sliders, timelines, canvas handles).
- **Cursor Safety**: In default `turbo` mode, `click` restores the original physical mouse position after clicking; pass `--no-restore-cursor` or `--human` if cursor persistence is desired.
