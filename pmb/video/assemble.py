"""影片合成:每個 segment 一張圖 + 該段配音 + 燒字幕,串成 30 秒 mp4。

每段獨立合成(圖隨旁白切換、字幕跟著該段),再用 ffmpeg concat 串接。配音以可注入的
``synth_fn`` 提供(dry-run 用靜音、正式用 edge-tts)。圖表由腳本的 charts 即時渲染。
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from loguru import logger

from pmb.charts.select import render_chart
from pmb.schemas.script import Script
from pmb.schemas.snapshot import Snapshot
from pmb.tts.edge import SynthResult

# synth_fn(text, out_path, planned_duration) -> SynthResult
SynthFn = Callable[[str, Path, float], SynthResult]

_CANVAS = (1280, 720)
_SUBTITLE_STYLE = "FontName=PingFang TC,FontSize=24,PrimaryColour=&H00000000,Outline=0,MarginV=40"


def _timestamp(seconds: float) -> str:
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    millis = int(round((secs - int(secs)) * 1000))
    return f"{int(hours):02d}:{int(minutes):02d}:{int(secs):02d},{millis:03d}"


def build_srt(cues: list[tuple[str, float, float]]) -> str:
    """把 (文字, 起點秒, 長度秒) 列表組成 SRT 字幕。"""
    blocks = []
    for i, (text, start, duration) in enumerate(cues, start=1):
        blocks.append(f"{i}\n{_timestamp(start)} --> {_timestamp(start + duration)}\n{text}\n")
    return "\n".join(blocks)


def segment_timeline(durations: list[float]) -> tuple[list[float], float]:
    """由各段實際長度算累積起點與總長。"""
    starts: list[float] = []
    total = 0.0
    for d in durations:
        starts.append(total)
        total += d
    return starts, total


def _run_ffmpeg(args: list[str], cwd: Path) -> None:
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        logger.error("ffmpeg 失敗:{}", proc.stderr[-800:])
        raise RuntimeError(f"ffmpeg 失敗(rc={proc.returncode})")


def _make_clip(
    image: str, audio: str, srt: str | None, out: str, duration: float, cwd: Path
) -> None:
    """單段:靜止圖 + 配音 +(選配)燒字幕 → mp4。以 basename 在 cwd 內執行,免去路徑跳脫。"""
    width, height = _CANVAS
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=white"
    )
    if srt:
        vf += f",subtitles={srt}:force_style='{_SUBTITLE_STYLE}'"
    _run_ffmpeg(
        [
            "ffmpeg", "-y", "-loop", "1", "-i", image, "-i", audio,
            "-vf", vf, "-t", f"{duration}", "-r", "25",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", out,
        ],
        cwd=cwd,
    )


def assemble_video(
    script: Script,
    snapshot: Snapshot,
    out_path: str | Path,
    *,
    synth_fn: SynthFn,
    work_dir: str | Path,
    subtitles: bool = True,
) -> Path:
    """合成整支影片並回傳 mp4 路徑。"""
    out_path = Path(out_path).resolve()
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    # 1. 渲染腳本選的圖(以 chart id 命名)
    chart_paths = {spec.id: render_chart(spec, snapshot, work_dir).name for spec in script.charts}

    # 2. 每段:配音 + 合成單段 clip
    clip_names: list[str] = []
    for i, seg in enumerate(script.segments):
        audio_name = f"seg_{i}.mp3"
        result = synth_fn(seg.vo, work_dir / audio_name, seg.duration)
        srt_name = None
        if subtitles:
            srt_name = f"seg_{i}.srt"
            (work_dir / srt_name).write_text(
                build_srt([(seg.vo, 0.0, result.duration)]), encoding="utf-8"
            )
        clip_name = f"clip_{i}.mp4"
        _make_clip(
            chart_paths[seg.chart_id], audio_name, srt_name, clip_name, result.duration, work_dir
        )
        clip_names.append(clip_name)

    # 3. concat 串接
    listing = work_dir / "clips.txt"
    listing.write_text("".join(f"file '{name}'\n" for name in clip_names), encoding="utf-8")
    _run_ffmpeg(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "clips.txt",
         "-c", "copy", str(out_path)],
        cwd=work_dir,
    )
    logger.info("影片合成完成 → {}", out_path)
    return out_path
