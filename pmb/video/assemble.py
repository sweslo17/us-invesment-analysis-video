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
_CHART_Y = 560  # 圖表置於畫面中段(上方留給標題、下方留給字幕)
# 用 .ass 並指定 PlayResY=1920,字級/邊界都以實際像素計(避免 SRT force_style 的 288 縮放)。
# 字幕在底(Alignment=2)、標題在頂(Alignment=8),都不蓋到中間的圖表。
_STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, "
    "Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV"
)
_EVENT_FORMAT = (
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
)
_ASS_TEMPLATE = "\n".join(
    [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        _STYLE_FORMAT,
        "Style: sub,{font},62,&H00FFFFFF,&H00000000,&HA0000000,1,3,6,0,2,70,70,230",
        "Style: title,{font},120,&H0066D9FF,&H00202020,&H00000000,1,1,7,0,8,40,40,64",
        "",
        "[Events]",
        _EVENT_FORMAT,
        "{events}",
        "",
    ]
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


_BREAK_AFTER = "，、,。!?!?;；:：…)）」』】"


def wrap_caption(text: str, max_units: int = 14) -> str:
    """把一行字幕依寬度切成多行(中文算 1、英數算 0.55),優先在標點後斷行。

    回傳以 ASS 換行符 ``\\N`` 連接的多行,確保不超出畫面寬度。
    """
    lines: list[str] = []
    cur: list[str] = []
    width = 0.0
    for ch in text:
        cur.append(ch)
        width += 1.0 if not ch.isascii() else 0.55
        if (ch in _BREAK_AFTER and width >= max_units * 0.55) or width >= max_units:
            lines.append("".join(cur))
            cur = []
            width = 0.0
    if cur:
        lines.append("".join(cur))
    return "\\N".join(lines)


def _ass_time(seconds: float) -> str:
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def build_ass(
    sentence: str, duration: float, *, title: str | None = None, font: str = "Noto Sans CJK TC"
) -> str:
    """組一段子片用的 .ass:底部逐句字幕 + (選配)頂部主題標題,皆全片長顯示。

    ``font`` 為 CJK 字型名(雲端 Linux 用 Noto Sans CJK TC,本機 macOS 用 PingFang TC)。
    """
    end = _ass_time(duration)
    events = [f"Dialogue: 0,0:00:00.00,{end},sub,,0,0,0,,{wrap_caption(sentence)}"]
    if title:
        events.append(f"Dialogue: 0,0:00:00.00,{end},title,,0,0,0,,{title}")
    return _ASS_TEMPLATE.format(font=font, events="\n".join(events))


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


def _make_subclip(image: str, audio: str, ass: str, out: str, duration: float, cwd: Path) -> None:
    """單句子片:直式畫布 = 上方主題標題 + 中間圖表 + 下方逐句字幕(互不重疊),配該句語音。"""
    chain = (
        f"color=c={_BG}:s={_WIDTH}x{_HEIGHT}:d={duration}[bg];"
        f"[0:v]scale={_CHART_W}:-1[ch];"
        f"[bg][ch]overlay=(W-w)/2:{_CHART_Y}[v0];"
        f"[v0]subtitles={ass},setsar=1[v]"
    )
    _run_ffmpeg(
        [
            "ffmpeg", "-y", "-loop", "1", "-i", image, "-i", audio,
            "-filter_complex", chain,
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
    font: str = "Noto Sans CJK TC",
) -> Path:
    """合成直式短影片並回傳 mp4 路徑。段內逐句配音 + 逐句字幕。"""
    out_path = Path(out_path).resolve()
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    chart_paths = {spec.id: render_chart(spec, snapshot, work_dir).name for spec in script.charts}

    clip_names: list[str] = []
    for i, seg in enumerate(script.segments):
        if seg.headline is not None:
            # 時事標題卡 / slogan / 金句:全屏大字、快速閃過(增加視覺變化)
            card_name = f"card{i}.png"
            render_headline_card(
                str(work_dir / card_name),
                seg.headline,
                accent=accent_for(i),
                tag=seg.tag or "盤前快報",
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
            ass_name = f"s{i}_{j}.ass"
            (work_dir / ass_name).write_text(
                build_ass(sentence, result.duration, title=seg.title, font=font), encoding="utf-8"
            )
            clip_name = f"c{i}_{j}.mp4"
            _make_subclip(chart, audio_name, ass_name, clip_name, result.duration, work_dir)
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
