"""配音:edge-tts(免費、zh-TW、逐字時間戳)+ dry-run 用的靜音合成。

``edge_synthesize`` 走非官方 endpoint,包 retry;``silent_synth`` 不連網(產靜音),
供 dry-run 煙霧測試。兩者皆回傳 ``SynthResult``,介面一致(日後可替換 OpenAI/ElevenLabs)。
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from loguru import logger
from pydantic import BaseModel

from pmb.data.retry import call_with_retry

DEFAULT_VOICE = "zh-TW-HsiaoChenNeural"


class WordBoundary(BaseModel):
    text: str
    start: float  # 秒
    duration: float


class SynthResult(BaseModel):
    audio_path: str
    duration: float
    words: list[WordBoundary] = []


async def _edge_async(text: str, out_path: Path, voice: str) -> SynthResult:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)
    words: list[WordBoundary] = []
    with open(out_path, "wb") as fh:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                fh.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append(
                    WordBoundary(
                        text=chunk["text"],
                        start=chunk["offset"] / 1e7,  # 100ns → 秒
                        duration=chunk["duration"] / 1e7,
                    )
                )
    duration = (words[-1].start + words[-1].duration) if words else probe_duration(out_path)
    return SynthResult(audio_path=str(out_path), duration=duration, words=words)


def edge_synthesize(
    text: str,
    out_path: str | Path,
    *,
    voice: str = DEFAULT_VOICE,
    retries: int = 3,
    retry_delay: float = 2.0,
) -> SynthResult:
    """以 edge-tts 合成單段語音(含逐字時間戳)。網路步驟,包 retry。"""
    out_path = Path(out_path)
    return call_with_retry(
        lambda: asyncio.run(_edge_async(text, out_path, voice)),
        retries=retries,
        delay=retry_delay,
        what=f"edge-tts {out_path.name}",
    )


def silent_synth(text: str, out_path: str | Path, *, duration: float = 4.0) -> SynthResult:
    """dry-run 用:產生 ``duration`` 秒靜音(不連網),介面同 edge_synthesize。"""
    out_path = Path(out_path)
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
            "-t", f"{duration}", "-q:a", "9", str(out_path),
        ],
        check=True,
        capture_output=True,
    )
    logger.debug("靜音配音 {}s → {}", duration, out_path)
    return SynthResult(audio_path=str(out_path), duration=duration, words=[])


def probe_duration(audio_path: str | Path) -> float:
    """用 ffprobe 量音檔長度(秒)。"""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())
