"""程序化音效:開場口號轉場的「咻 + 叭叭」,呼應頻道名「早發車」。

``assets/sfx/`` 放了自備的 ``sting.*`` 就用自備的;否則純 numpy 合成,零版權疑慮。
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
from loguru import logger

_SR = 44100
_TOTAL_SEC = 0.55
_USER_NAMES = ("sting.wav", "sting.mp3", "sting.m4a")


def _horn(duration: float, freqs: tuple[float, ...] = (370.0, 466.16)) -> np.ndarray:
    """短喇叭:兩音和聲、帶點方波的粗糙感,快起音快收。"""
    t = np.arange(int(duration * _SR)) / _SR
    tone = sum(0.65 * np.sin(2 * np.pi * f * t) + 0.35 * np.sign(np.sin(2 * np.pi * f * t))
               for f in freqs) / len(freqs)
    env = np.clip(np.minimum(t / 0.01, (duration - t) / 0.03), 0.0, 1.0)
    return tone * env


def _whoosh(duration: float, rng: np.random.Generator) -> np.ndarray:
    """咻:白噪音過一階低通,截止頻率由低往高掃(聲音由悶變亮),包絡先升後降。"""
    n = int(duration * _SR)
    noise = rng.standard_normal(n)
    alphas = np.linspace(0.02, 0.35, n)
    out = np.empty(n)
    acc = 0.0
    for i in range(n):
        acc += alphas[i] * (noise[i] - acc)
        out[i] = acc
    return out * np.sin(np.pi * np.linspace(0.0, 1.0, n)) ** 2


def generate_sting(out_path: str | Path) -> Path:
    """合成約 0.55 秒的轉場音效(咻 + 兩聲短喇叭)寫成 mono WAV;已存在就沿用。"""
    out_path = Path(out_path)
    if out_path.exists():
        return out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    total = np.zeros(int(_TOTAL_SEC * _SR))
    whoosh = _whoosh(0.30, rng)
    total[: len(whoosh)] += 0.6 * whoosh / (np.abs(whoosh).max() or 1.0)
    for start in (0.10, 0.30):
        horn = _horn(0.14)
        i = int(start * _SR)
        total[i : i + len(horn)] += 0.5 * horn
    pcm = (total / (np.abs(total).max() or 1.0) * 0.7 * 32767).astype("<i2")
    with wave.open(str(out_path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(_SR)
        fh.writeframes(pcm.tobytes())
    logger.info("程序化轉場音效 → {}", out_path)
    return out_path


def resolve_sting_sfx(sfx_dir: Path, work_dir: Path) -> Path | None:
    """挑轉場音效:自備檔優先,否則程序化合成;失敗就略過音效(口號照播)。"""
    for name in _USER_NAMES:
        candidate = Path(sfx_dir) / name
        if candidate.exists():
            logger.info("轉場音效用自備檔:{}", candidate)
            return candidate.resolve()
    try:
        return generate_sting(Path(work_dir) / "sting_sfx.wav").resolve()
    except Exception as exc:  # noqa: BLE001
        logger.warning("轉場音效生成失敗,略過音效:{}", exc)
        return None
