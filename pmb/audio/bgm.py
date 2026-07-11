"""程序化 BGM:合成一段低調的和弦 pad loop,當 assets/bgm 沒有音檔時的預設背景床。

不下載、不依賴任何外部素材,純 numpy 合成,零版權疑慮。混音時壓在 VO 下方
(見 video.assemble.finalize_master 的 ducking),聽感是「有氛圍」而非「有音樂」。
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
from loguru import logger

_SR = 44100
# 每個和弦 6 秒、四個和弦 = 24 秒 loop;音高走 Am7 → Fmaj7 → Cmaj7 → G,平穩不搶戲
_CHORDS: list[list[float]] = [
    [110.00, 164.81, 196.00, 261.63],  # A2 E3 G3 C4 (Am7)
    [87.31, 130.81, 164.81, 220.00],  # F2 C3 E3 A3 (Fmaj7)
    [130.81, 196.00, 246.94, 329.63],  # C3 G3 B3 E4 (Cmaj7)
    [98.00, 146.83, 246.94, 293.66],  # G2 D3 B3 D4 (G)
]
_CHORD_SEC = 6.0


def _pad_note(freq: float, duration: float, detune_cents: float = 0.0) -> np.ndarray:
    """單音 pad:基音 + 兩個弱泛音,慢起音慢收尾。"""
    f = freq * (2.0 ** (detune_cents / 1200.0))
    t = np.arange(int(duration * _SR)) / _SR
    tone = (
        np.sin(2 * np.pi * f * t)
        + 0.35 * np.sin(2 * np.pi * 2 * f * t)
        + 0.10 * np.sin(2 * np.pi * 3 * f * t)
    )
    attack = min(1.2, duration / 3)
    release = min(1.6, duration / 3)
    env = np.ones_like(t)
    n_a = int(attack * _SR)
    n_r = int(release * _SR)
    env[:n_a] = np.linspace(0.0, 1.0, n_a) ** 2
    env[-n_r:] = np.linspace(1.0, 0.0, n_r) ** 2
    return tone * env


def generate_default_pad(out_path: str | Path) -> Path:
    """合成 24 秒、44.1kHz 立體聲 pad loop 並寫成 WAV;已存在就直接沿用。"""
    out_path = Path(out_path)
    if out_path.exists():
        return out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total_n = int(len(_CHORDS) * _CHORD_SEC * _SR)
    left = np.zeros(total_n)
    right = np.zeros(total_n)
    for i, chord in enumerate(_CHORDS):
        start = int(i * _CHORD_SEC * _SR)
        for freq in chord:
            note_l = _pad_note(freq, _CHORD_SEC, detune_cents=-3.0)
            note_r = _pad_note(freq, _CHORD_SEC, detune_cents=+3.0)
            left[start : start + len(note_l)] += note_l
            right[start : start + len(note_r)] += note_r

    # 極慢的呼吸感 LFO,避免 pad 死板
    t = np.arange(total_n) / _SR
    lfo = 1.0 + 0.10 * np.sin(2 * np.pi * 0.15 * t)
    left *= lfo
    right *= lfo

    peak = max(np.abs(left).max(), np.abs(right).max()) or 1.0
    scale = 0.5 / peak
    stereo = np.empty((total_n, 2))
    stereo[:, 0] = left * scale
    stereo[:, 1] = right * scale
    pcm = (stereo * 32767).astype("<i2")

    with wave.open(str(out_path), "wb") as fh:
        fh.setnchannels(2)
        fh.setsampwidth(2)
        fh.setframerate(_SR)
        fh.writeframes(pcm.tobytes())
    logger.info("程序化 BGM pad → {}", out_path)
    return out_path
