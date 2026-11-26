"""100% original 48kHz Stereo DSP Sound Design Engine using NumPy + SciPy."""

from __future__ import annotations

import math
from pathlib import Path
import wave

import numpy as np
from scipy import signal

SAMPLE_RATE = 48000
DURATION_SEC = 32.0


def _pan_stereo(mono: np.ndarray, pan: float | np.ndarray) -> np.ndarray:
    """Equal-power stereo panner (-1.0 left .. +1.0 right)."""
    p = np.clip(pan, -1.0, 1.0)
    theta = (p + 1.0) * (math.pi / 4.0)
    left = mono * np.cos(theta)
    right = mono * np.sin(theta)
    return np.column_stack([left, right]).astype(np.float32)


def _place(mix: np.ndarray, stereo: np.ndarray, t_sec: float, gain: float = 1.0) -> None:
    if len(stereo) == 0:
        return
    idx = int(round(t_sec * SAMPLE_RATE))
    if idx >= len(mix):
        return
    end = min(len(mix), idx + len(stereo))
    take = end - idx
    if take <= 0:
        return
    mix[idx:end] += stereo[:take] * float(gain)


def synth_ambient_pad(duration_sec: float = DURATION_SEC) -> np.ndarray:
    """Evolving Cmaj9 -> Am9 -> Fmaj9 -> G6sus4 warm cinema pad with sweeping lowpass."""
    n = int(round(duration_sec * SAMPLE_RATE))
    t = np.linspace(0, duration_sec, n, endpoint=False, dtype=np.float64)

    chords = [
        # Cmaj9: C2, G2, E3, B3, D4
        (65.41, 98.00, 164.81, 246.94, 293.66),
        # Am9: A1, E2, C3, G3, B3
        (55.00, 82.41, 130.81, 196.00, 246.94),
        # Fmaj9: F2, C3, A3, E4, G4
        (87.31, 130.81, 220.00, 329.63, 392.00),
        # G6sus4: G1, D2, C3, E3, A3
        (49.00, 73.42, 130.81, 164.81, 220.00),
    ]

    seg_len = duration_sec / len(chords)
    fade_w = 1.35

    left = np.zeros(n, dtype=np.float64)
    right = np.zeros(n, dtype=np.float64)

    for c_idx, freqs in enumerate(chords):
        c_start = c_idx * seg_len
        c_end = (c_idx + 1) * seg_len
        # Smooth overlapping trapezoidal weights
        w_in = np.clip((t - (c_start - fade_w * 0.5)) / fade_w, 0.0, 1.0)
        w_out = np.clip(((c_end + fade_w * 0.5) - t) / fade_w, 0.0, 1.0)
        if c_idx == 0:
            w_in = np.ones_like(t)
        if c_idx == len(chords) - 1:
            w_out = np.ones_like(t)
        weight = np.sin(np.minimum(w_in, w_out) * (math.pi / 2.0)) ** 2

        chord_l = np.zeros(n, dtype=np.float64)
        chord_r = np.zeros(n, dtype=np.float64)
        for v_idx, f in enumerate(freqs):
            detune = 1.0 + (0.0028 if v_idx % 2 == 0 else -0.0024)
            # Warm fundamental + subtle 2nd harmonic
            chord_l += 0.22 * np.sin(2 * math.pi * f * t) + 0.04 * np.sin(2 * math.pi * (f * 2.0) * t)
            chord_r += 0.22 * np.sin(2 * math.pi * (f * detune) * t + 0.6) + 0.04 * np.sin(2 * math.pi * (f * 2.0 * detune) * t)

        left += chord_l * weight
        right += chord_r * weight

    # Filter with warm lowpass + gentle rhythmic breath (120 BPM subtle pulse)
    sos = signal.butter(4, 780.0, btype="low", fs=SAMPLE_RATE, output="sos")
    left = signal.sosfilt(sos, left)
    right = signal.sosfilt(sos, right)

    breath = 0.84 + 0.16 * np.sin(2 * math.pi * 1.0 * t)  # gentle 60 BPM swell
    env_master = np.minimum(np.clip(t / 1.1, 0.0, 1.0), np.clip((duration_sec - t) / 1.8, 0.0, 1.0))
    stereo = np.column_stack([left * breath * env_master, right * breath * env_master]).astype(np.float32)
    return stereo * 0.18


def synth_air_whoosh(dur: float = 0.55, f_low: float = 280.0, f_high: float = 2100.0, pan_start: float = -0.6, pan_end: float = 0.6) -> np.ndarray:
    """Silky band-pass swept air whoosh using pink noise + time-varying filtering."""
    n = int(round(dur * SAMPLE_RATE))
    rng = np.random.default_rng(101)
    white = rng.standard_normal(n).astype(np.float64)
    # Pink-ish rolloff
    sos_lp = signal.butter(2, 3200.0, btype="low", fs=SAMPLE_RATE, output="sos")
    pink = signal.sosfilt(sos_lp, white)

    # Blend 3 resonant bands across bell envelope
    t = np.linspace(0, 1.0, n, endpoint=False)
    bell = np.sin(math.pi * t) ** 1.7

    sos_lo = signal.butter(3, [f_low * 0.7, f_low * 1.8], btype="band", fs=SAMPLE_RATE, output="sos")
    sos_md = signal.butter(3, [(f_low + f_high) * 0.35, (f_low + f_high) * 0.75], btype="band", fs=SAMPLE_RATE, output="sos")
    sos_hi = signal.butter(3, [f_high * 0.75, f_high * 1.35], btype="band", fs=SAMPLE_RATE, output="sos")

    b_lo = signal.sosfilt(sos_lo, pink) * (1.0 - t)
    b_md = signal.sosfilt(sos_md, pink) * np.sin(math.pi * t)
    b_hi = signal.sosfilt(sos_hi, pink) * (np.sin(math.pi * t) ** 2)

    mono = (b_lo * 0.9 + b_md * 1.1 + b_hi * 0.8) * bell * 0.55
    pan = np.linspace(pan_start, pan_end, n)
    return _pan_stereo(mono, pan)


def synth_sub_impact(dur: float = 0.52) -> np.ndarray:
    """Deep cinematic sub-bass drop (92Hz -> 36Hz) with soft transient click."""
    n = int(round(dur * SAMPLE_RATE))
    t = np.linspace(0, dur, n, endpoint=False)
    freq = 36.0 + 56.0 * np.exp(-13.0 * t)
    phase = 2.0 * math.pi * np.cumsum(freq) / SAMPLE_RATE
    sub = np.sin(phase) * np.exp(-5.4 * t)
    transient = np.sin(2 * math.pi * 195.0 * t) * np.exp(-65.0 * t) * 0.35
    mono = np.tanh((sub + transient) * 1.35) * 0.65
    return np.column_stack([mono, mono]).astype(np.float32)


def synth_tactile_click(pitch: float = 1150.0, pan: float = 0.0) -> np.ndarray:
    """Crisp Apple/Linear-style damped mechanical UI tap (18ms)."""
    dur = 0.022
    n = int(round(dur * SAMPLE_RATE))
    t = np.linspace(0, dur, n, endpoint=False)
    body = np.sin(2 * math.pi * 240.0 * t) * np.exp(-240.0 * t) * 0.65
    tick = np.sin(2 * math.pi * pitch * t) * np.exp(-320.0 * t) * 0.45
    mono = (body + tick) * 0.65
    return _pan_stereo(mono, pan)


def synth_glass_chime(freq: float = 659.25, dur: float = 0.42, pan: float = 0.0) -> np.ndarray:
    """Warm harmonic pentatonic glass/marimba chime (zero harsh 8-bit tones)."""
    n = int(round(dur * SAMPLE_RATE))
    t = np.linspace(0, dur, n, endpoint=False)
    attack = np.clip(t / 0.004, 0.0, 1.0)
    f1 = np.sin(2 * math.pi * freq * t) * np.exp(-8.5 * t)
    f2 = 0.28 * np.sin(2 * math.pi * (freq * 2.0) * t) * np.exp(-16.0 * t)
    f3 = 0.09 * np.sin(2 * math.pi * (freq * 3.0) * t) * np.exp(-26.0 * t)
    mono = (f1 + f2 + f3) * attack * 0.32
    return _pan_stereo(mono, pan)


def synth_liquid_glide(dur: float = 2.05) -> np.ndarray:
    """Silky harmonic frequency sweep panned left-to-right for Bezier curve drag."""
    n = int(round(dur * SAMPLE_RATE))
    t = np.linspace(0, dur, n, endpoint=False)
    norm = t / dur
    freq = 220.0 + 440.0 * (norm ** 1.4)
    phase = 2.0 * math.pi * np.cumsum(freq) / SAMPLE_RATE
    env = np.sin(math.pi * norm) ** 1.4
    mono = (np.sin(phase) + 0.25 * np.sin(phase * 2.0)) * env * 0.14
    pan = np.linspace(-0.55, 0.55, n)
    return _pan_stereo(mono, pan)


def apply_stereo_shimmer(fx_bus: np.ndarray) -> np.ndarray:
    """Add subtle cross-channel stereo delay taps (65ms & 115ms) to FX bus."""
    out = fx_bus.copy()
    d1 = int(0.068 * SAMPLE_RATE)
    d2 = int(0.118 * SAMPLE_RATE)
    if d1 < len(out):
        out[d1:, 0] += fx_bus[:-d1, 1] * 0.22
        out[d1:, 1] += fx_bus[:-d1, 0] * 0.22
    if d2 < len(out):
        out[d2:, 0] += fx_bus[:-d2, 0] * 0.12
        out[d2:, 1] += fx_bus[:-d2, 1] * 0.12
    return out


def build_audio_track(out_wav: Path, duration_sec: float = DURATION_SEC) -> None:
    """Compose and master the 48kHz stereo soundtrack into out_wav."""
    total_samples = int(round(duration_sec * SAMPLE_RATE))
    pad_bus = synth_ambient_pad(duration_sec)
    fx_bus = np.zeros((total_samples, 2), dtype=np.float32)

    # Act I: Hook kinetic typography taps & Brand Reveal impact (2.2s)
    _place(fx_bus, synth_tactile_click(980.0, -0.2), 0.15, gain=0.6)
    _place(fx_bus, synth_tactile_click(1120.0, 0.2), 1.05, gain=0.6)
    _place(fx_bus, synth_air_whoosh(0.55, 280.0, 2200.0, -0.5, 0.5), 2.00, gain=0.65)
    _place(fx_bus, synth_sub_impact(), 2.22, gain=0.85)
    _place(fx_bus, synth_glass_chime(523.25, 0.55, 0.0), 2.24, gain=0.65)  # C5
    _place(fx_bus, synth_glass_chime(659.25, 0.55, 0.25), 2.34, gain=0.50)  # E5
    for idx in range(4):
        _place(fx_bus, synth_tactile_click(1200.0 + idx * 80.0, -0.3 + idx * 0.2), 2.95 + idx * 0.12, gain=0.45)

    # Act II: 5-Tier Smart Router spline pulses (pentatonic C5 D5 E5 G5 A5)
    _place(fx_bus, synth_air_whoosh(0.55, 260.0, 1900.0, -0.7, 0.7), 5.10, gain=0.68)
    pentatonic = (523.25, 587.33, 659.25, 783.99, 880.00)
    for idx, freq in enumerate(pentatonic):
        ts = 6.00 + idx * 0.90
        pan = -0.55 + idx * 0.275
        _place(fx_bus, synth_tactile_click(1050.0 + idx * 60, pan), ts - 0.12, gain=0.4)
        _place(fx_bus, synth_glass_chime(freq, 0.48, pan), ts, gain=0.62)

    # Act III: Silent CDP click + DOF #32770 Dialog + Atomic Vietnamese Paste
    _place(fx_bus, synth_air_whoosh(0.50, 300.0, 1800.0, 0.6, -0.6), 11.10, gain=0.62)
    _place(fx_bus, synth_glass_chime(659.25, 0.35, -0.35), 12.25, gain=0.55)
    _place(fx_bus, synth_air_whoosh(0.45, 340.0, 2100.0, -0.3, 0.4), 13.30, gain=0.60)
    _place(fx_bus, synth_tactile_click(1450.0, 0.25), 14.45, gain=0.75)
    _place(fx_bus, synth_glass_chime(783.99, 0.45, 0.25), 14.52, gain=0.58)
    _place(fx_bus, synth_tactile_click(1320.0, 0.3), 16.05, gain=0.72)
    _place(fx_bus, synth_glass_chime(1046.50, 0.45, 0.3), 16.08, gain=0.55)

    # Act IV: Outer-Ruler Canvas + OCR Lock + Bezier Drag + 2.5x Loupe Micro-Drag
    _place(fx_bus, synth_air_whoosh(0.55, 250.0, 2300.0, -0.7, 0.7), 17.70, gain=0.68)
    _place(fx_bus, synth_sub_impact(), 17.85, gain=0.60)
    _place(fx_bus, synth_glass_chime(783.99, 0.45, 0.4), 18.45, gain=0.65)
    _place(fx_bus, synth_liquid_glide(2.05), 19.80, gain=0.80)
    _place(fx_bus, synth_air_whoosh(0.40, 400.0, 1700.0, 0.2, 0.5), 21.95, gain=0.55)
    # Micro-drag snap + resolved major chime at 23.45s
    _place(fx_bus, synth_tactile_click(1500.0, 0.15), 23.10, gain=0.65)
    _place(fx_bus, synth_sub_impact(), 23.45, gain=0.70)
    _place(fx_bus, synth_glass_chime(523.25, 0.65, -0.2), 23.45, gain=0.55)
    _place(fx_bus, synth_glass_chime(783.99, 0.65, 0.0), 23.48, gain=0.52)
    _place(fx_bus, synth_glass_chime(1046.50, 0.70, 0.25), 23.51, gain=0.60)

    # Act V: Editorial Benchmark 76x + Safety Badges
    _place(fx_bus, synth_air_whoosh(0.50, 280.0, 2100.0, 0.6, -0.6), 24.90, gain=0.65)
    _place(fx_bus, synth_glass_chime(880.00, 0.55, 0.0), 25.95, gain=0.62)
    for idx in range(3):
        _place(fx_bus, synth_tactile_click(1180.0 + idx * 90, -0.4 + idx * 0.4), 26.65 + idx * 0.15, gain=0.55)

    # Act VI: Terminal Typing & Warm Outro
    _place(fx_bus, synth_air_whoosh(0.50, 260.0, 1800.0, -0.5, 0.5), 28.70, gain=0.62)
    for k in range(16):
        _place(fx_bus, synth_tactile_click(1250.0 + (k % 5) * 95.0, -0.25 + (k % 3) * 0.25), 29.05 + k * 0.095, gain=0.45)
    _place(fx_bus, synth_sub_impact(), 30.65, gain=0.72)
    _place(fx_bus, synth_glass_chime(523.25, 0.90, -0.2), 30.68, gain=0.55)
    _place(fx_bus, synth_glass_chime(1046.50, 0.95, 0.2), 30.72, gain=0.55)

    fx_wet = apply_stereo_shimmer(fx_bus)
    mix = pad_bus + fx_wet

    # Soft limiter peaking cleanly at -1.0 dBFS (~0.89)
    peak = float(np.max(np.abs(mix)))
    if peak > 0.0:
        mix = np.tanh(mix * (0.95 / max(0.85, peak))) * 0.89

    pcm = np.clip(mix * 32767.0, -32767, 32767).astype(np.int16)
    with wave.open(str(out_wav), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())
