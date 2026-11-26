---
name: agent-eye-motion-studio
description: Use when creating standalone 60fps Motion Graphics showcase films, interactive UI animations, or synthesized studio audio for the agent-eye / antigravity-human-control project.
---

# Agent-Eye Motion Studio (`agent-eye-motion-studio`)

Standalone C++-backed Motion Graphics pipeline built exclusively for `agent-eye` using **Google Skia (`skia-python`)**, **`scipy.signal` 48kHz Stereo DSP**, bundled OFL typography, and **`ffmpeg`** (`libx264` + `aac`). Zero reliance on external workspace assets or generic templates.

## Architecture

- `motion_studio/fonts/`: Bundled OFL studio typefaces (`InstrumentSerif-Regular.ttf`, `InstrumentSerif-Italic.ttf`, `Inter-Variable.ttf`, `JetBrainsMono-Variable.ttf`) cloned across optical sizes and variable weights (`400`, `500`, `600`, `700`) with full Vietnamese NFC glyph coverage.
- `motion_studio/skia_primitives.py`: Zero-Neon Swiss Editorial design tokens (`#F4F2EC` warm studio paper, `#141413` charcoal ink, `#DAD5CA` 1px architectural rules, `#1B1B19` matte hardware slate, `#D4451A` signal vermilion, `#1E6B4B` print sage), tracked `skia.TextBlob` typography, cached studio contact shadows, baseline-clipped kinetic reveals (`ease_out_expo`), aperture logo mark, and vector checkmarks (`PathMeasure`).
- `motion_studio/audio_dsp.py`: Original `48kHz` stereo sound design — detuned ambient synth pad (`Cmaj9 → Am9 → Fmaj9 → G6sus4`), band-pass swept air whooshes, harmonic pentatonic chimes (`C5–C6`), tactile damped UI clicks, sub-bass impacts, and `-1.0 dBFS` tanh mastering.
- `motion_studio/render_launch_film.py`: 6-act continuous-camera compositor (`1920x1080` @ `60fps`) with horizontal architectural curtain wipes (`ease_in_out_quart`), `1/2`-res optical DOF rack focus, live 2.5x optical loupe sampling, and explicit `-t <duration>` muxing (never `-shortest`).

## Zero-Neon Anti-Slop Design Rules

1. **Zero Neon / Zero AI Slop**: Never use dark-void neon gradients, cyberpunk glows, aurora blobs, or arbitrary floating cards. Anchor compositions on tactile warm studio paper (`#F4F2EC`) with generous negative space (`≥40%`) and disciplined Swiss grid rules.
2. **Editorial Typography & Tracking**: Pair neo-grotesque `Inter` (tight `-0.032em` display tracking) with `Instrument Serif Italic` emphasis and tracked `JetBrains Mono` telemetry indices.
3. **One Focal Point & Curtain Wipes**: Move one focal element per beat using `ease_out_expo` / critically damped springs (`spring_snappy`), and transition scenes cleanly via `0.38s` architectural curtain wipes synced to audio cues.
4. **Synced Harmonic Audio**: Every UI reveal, spline glide, keystroke, and sub-pixel lock pairs with bespoke `scipy` DSP foley and stereo panning.

## Two-Stage Render & Visual QA Workflow

1. **Stage 1 — Styleframe Audit** (fast iteration before full encode):
```powershell
.\.venv\Scripts\python.exe -m motion_studio.render_launch_film --styleframes media\styleframes
```
Inspect `contact_sheet.png` and individual styleframe PNGs via `read_file`; iterate until layout, tracking, contrast, and alignment pass cleanly.

2. **Stage 2 — Full 60fps Render & Video Audit**:
```powershell
.\.venv\Scripts\python.exe -m motion_studio.render_launch_film --out media\agent-eye-launch-v3-60fps.mp4
ffprobe -v error -show_entries stream=codec_name,width,height,r_frame_rate,sample_rate,channels -show_entries format=duration,size -of default=noprint_wrappers=1 media\agent-eye-launch-v3-60fps.mp4
```
Always inspect the rendered `.mp4` end-to-end via `read_file` before delivery.
