"""影片合成:直式短影片(1080×1920)。

每段一張圖;段內把旁白切成「一句一句」,每句各自配音 + 一張字幕卡(字幕跟著語音逐句播,
與圖表標題分開)。圖在上、字幕帶在下。配音以可注入的 ``synth_fn`` 提供。
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from loguru import logger

from pmb.charts.cards import accent_for, render_headline_card
from pmb.charts.select import render_chart
from pmb.schemas.script import Script
from pmb.schemas.snapshot import Snapshot
from pmb.tts.edge import SynthResult

# synth_fn(text, out_path, planned_duration) -> SynthResult
SynthFn = Callable[[str, Path, float], SynthResult]

# 直式短影片畫布(9:16)
_WIDTH, _HEIGHT = 1080, 1920
_BG = "0x0D1B2A"
_CHART_W = 1040
_CHART_Y = 430
# 字幕樣式(ASS):置中、半透明黑底框、白粗體;字幕 ≠ 圖表標題,且逐句播放
_SUB_STYLE = (
    "Alignment=2,MarginV=115,FontName=PingFang TC,Fontsize=14,"
    "PrimaryColour=&H00FFFFFF,BorderStyle=3,Outline=4,Shadow=0,"
    "BackColour=&HC0101010,Bold=1"
)

# 句尾標點不含 ASCII 句點「.」,否則 3.8% 這類小數會被誤切
_SENT_RE = re.compile(r"[^。!?！？;；\n]+[。!?！？;；]?")


def split_sentences(text: str) -> list[str]:
    """把旁白切成句子(保留句尾標點),供逐句字幕。沒有標點則整段為一句。

    刻意不把 ASCII 句點當句尾,避免 3.8%、0.53 這類小數被切斷。
    """
    parts = [m.group().strip() for m in _SENT_RE.finditer(text)]
    return [p for p in parts if p]


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


def _make_subclip(image: str, audio: str, srt: str, out: str, duration: float, cwd: Path) -> None:
    """單句子片:直式畫布 = 深色底 + 上方圖表 + 下方逐句字幕,配該句語音。"""
    filter_complex = (
        f"color=c={_BG}:s={_WIDTH}x{_HEIGHT}:d={duration}[bg];"
        f"[0:v]scale={_CHART_W}:-1[ch];"
        f"[bg][ch]overlay=(W-w)/2:{_CHART_Y}[bgc];"
        f"[bgc]subtitles={srt}:force_style='{_SUB_STYLE}',setsar=1[v]"
    )
    _run_ffmpeg(
        [
            "ffmpeg", "-y", "-loop", "1", "-i", image, "-i", audio,
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "1:a", "-t", f"{duration}", "-r", "25",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", out,
        ],
        cwd=cwd,
    )


def _make_card_clip(card: str, audio: str, out: str, duration: float, cwd: Path) -> None:
    """時事標題卡片段:全屏卡片(大字已烤進圖)+ 旁白,快速閃過,無額外字幕。"""
    _run_ffmpeg(
        [
            "ffmpeg", "-y", "-loop", "1", "-i", card, "-i", audio,
            "-vf", f"scale={_WIDTH}:{_HEIGHT},setsar=1",
            "-t", f"{duration}", "-r", "25",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", out,
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
) -> Path:
    """合成直式短影片並回傳 mp4 路徑。段內逐句配音 + 逐句字幕。"""
    out_path = Path(out_path).resolve()
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    chart_paths = {spec.id: render_chart(spec, snapshot, work_dir).name for spec in script.charts}

    clip_names: list[str] = []
    for i, seg in enumerate(script.segments):
        if seg.headline is not None:
            # 時事標題卡:全屏大字、快速閃過(增加視覺變化)
            card_name = f"card{i}.png"
            render_headline_card(
                str(work_dir / card_name), seg.headline, accent=accent_for(i), tag="盤前快報"
            )
            audio_name = f"card{i}.mp3"
            result = synth_fn(seg.vo, work_dir / audio_name, seg.duration)
            clip_name = f"k{i}.mp4"
            _make_card_clip(card_name, audio_name, clip_name, result.duration, work_dir)
            clip_names.append(clip_name)
            continue

        chart = chart_paths[seg.chart_id]
        sentences = split_sentences(seg.vo) or [seg.vo]
        planned_each = seg.duration / len(sentences)
        for j, sentence in enumerate(sentences):
            audio_name = f"s{i}_{j}.mp3"
            result = synth_fn(sentence, work_dir / audio_name, planned_each)
            srt_name = f"s{i}_{j}.srt"
            (work_dir / srt_name).write_text(
                build_srt([(sentence, 0.0, result.duration)]), encoding="utf-8"
            )
            clip_name = f"c{i}_{j}.mp4"
            _make_subclip(chart, audio_name, srt_name, clip_name, result.duration, work_dir)
            clip_names.append(clip_name)

    listing = work_dir / "clips.txt"
    listing.write_text("".join(f"file '{name}'\n" for name in clip_names), encoding="utf-8")
    _run_ffmpeg(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "clips.txt",
         "-c", "copy", str(out_path)],
        cwd=work_dir,
    )
    logger.info("直式影片合成完成 → {}", out_path)
    return out_path
