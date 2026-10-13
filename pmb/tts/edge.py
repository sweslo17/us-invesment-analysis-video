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

# 2026-10 起 Microsoft 對舊 host(speech.platform.bing.com)的 v1 Sec-MS-GEC token 一律回 403
# (美國自 10/12)。Edge 155 改走 api.msedgeservices.com,該 host 仍收 v1 token,但金鑰參數名改為
# Ocp-Apim-Subscription-Key。edge-tts 7.2.8 未修(見 rany2/edge-tts#490、#491、#492)。
MSEDGE_WSS_BASE = "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1"


def ensure_working_endpoint() -> None:
    """edge-tts 仍用 v1 token 時,把合成 WebSocket 改指新 host(冪等)。

    上游改用 v2 token 後舊 host 又能用,此時不動上游設定——墊片隨升級自動失效。
    """
    import edge_tts.communicate as comm
    from edge_tts.constants import TRUSTED_CLIENT_TOKEN

    if not comm.SEC_MS_GEC_VERSION.startswith("1-") or comm.WSS_URL.startswith(MSEDGE_WSS_BASE):
        return
    comm.WSS_URL = f"{MSEDGE_WSS_BASE}?Ocp-Apim-Subscription-Key={TRUSTED_CLIENT_TOKEN}"
    logger.info("edge-tts 仍用 v1 token,合成改走 {}", MSEDGE_WSS_BASE)


class WordBoundary(BaseModel):
    text: str
    start: float  # 秒
    duration: float


class SynthResult(BaseModel):
    audio_path: str
    duration: float
    words: list[WordBoundary] = []


async def _edge_async(
    text: str, out_path: Path, voice: str, rate: str, pitch: str
) -> SynthResult:
    import edge_tts

    ensure_working_endpoint()
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
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
    rate: str = "+30%",
    pitch: str = "+0Hz",
    retries: int = 3,
    retry_delay: float = 2.0,
) -> SynthResult:
    """以 edge-tts 合成單段語音(含逐字時間戳)。

    ``rate`` 控制語速(短影片用快語速);``pitch`` 微調音高(如 "+5Hz" 可降低單調感,
    幅度別超過 ±15Hz)。
    """
    out_path = Path(out_path)
    return call_with_retry(
        lambda: asyncio.run(_edge_async(text, out_path, voice, rate, pitch)),
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
