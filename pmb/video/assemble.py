"""影片合成:直式短影片(1080×1920),段級渲染。

每個 segment 一支 clip,段內把旁白切成句、逐句配音後串接(句間留呼吸、段尾留停頓),
字幕以「頁」為單位逐字卡拉OK掃色(edge-tts word boundary 對齊;拿不到就按字寬比例),
每頁最多兩行、永不蓋到中段的圖表。圖表段有 Ken Burns 緩推、段首自畫布色淡入、
全片底部金色進度條。最終串接後過音訊母帶鏈(BGM ducking + loudnorm),見
``finalize_master``。配音以可注入的 ``synth_fn`` 提供。
"""

from __future__ import annotations

import json
import math
import re
import struct
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from loguru import logger

from pmb.charts.cards import accent_for, render_headline_card
from pmb.charts.select import render_chart
from pmb.schemas.script import Script
from pmb.schemas.snapshot import Snapshot
from pmb.tts.edge import SynthResult, WordBoundary, probe_duration

# synth_fn(text, out_path, planned_duration) -> SynthResult
SynthFn = Callable[[str, Path, float], SynthResult]

# 直式短影片畫布(9:16)
_WIDTH, _HEIGHT = 1080, 1920
_BG_HEX = "0D1B2A"  # 與 charts.library._CANVAS 一致
_GOLD_HEX = "FFD166"  # 品牌金(標題/進度條/字幕掃色)
# 圖表置於畫面中段:上方留給標題、下方留給逐頁字幕。圖為直式,等比縮放後塞進此框置中。
_CHART_BAND_TOP = 250
_CHART_BOX_W = 1040
_CHART_BOX_H = 1180  # 框底 = 250+1180 = 1430,字幕頁最多兩行、頂緣約 1560,不會相蓋
_FPS = 25
_GAP = 0.18  # 句間呼吸(秒)
_TAIL = 0.35  # 段尾停頓(秒)
_FADE_IN = 0.20  # 段首自畫布色淡入
_FADE_OUT = 0.60  # 全片收尾淡出(烤在最後一段)
_ZOOM_AMOUNT = 0.06  # Ken Burns 段內總推進幅度
_PROGRESS_H = 10  # 底部進度條高(px)
_MAX_UNITS = 14  # 字幕每行寬度上限(中文 1、英數 0.55)
_MAX_LINES = 2  # 字幕每頁最多行數(保證不蓋圖)
_SHORTS_CAP = 180.0  # YouTube Shorts 長度上限(超過會被當一般影片)

# 用 .ass 並指定 PlayResY=1920,字級/邊界都以實際像素計。字幕在底(Alignment=2)、
# 標題在頂(Alignment=8),都不蓋到中間的圖表。含 SecondaryColour 供卡拉OK掃色:
# 未唸到 = Secondary(白),唸過 = Primary(金)。
_STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
    "BackColour, Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV"
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
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        _STYLE_FORMAT,
        "Style: sub,{font},64,&H0066D1FF,&H00FFFFFF,&H00201810,&H78000000,1,1,5,1,2,60,60,200",
        "Style: title,{font},120,&H0066D1FF,&H00FFFFFF,&H00201810,&H00000000,1,1,3,0,8,40,40,64",
        "",
        "[Events]",
        _EVENT_FORMAT,
        "{events}",
        "",
    ]
)

# 句尾標點不含 ASCII 句點「.」,否則 3.8% 這類小數會被誤切
_SENT_RE = re.compile(r"[^。!?！?;;；\n]+[。!?！?;;；]?")


def split_sentences(text: str) -> list[str]:
    """把旁白切成句子(保留句尾標點),供逐句配音與逐頁字幕。沒有標點則整段為一句。

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


def _char_units(ch: str) -> float:
    return 1.0 if not ch.isascii() else 0.55


def _wrap_lines(text: str, max_units: int = _MAX_UNITS) -> list[str]:
    """依寬度切行(中文算 1、英數算 0.55),優先在標點後斷行。行串接 == 原文。"""
    lines: list[str] = []
    cur: list[str] = []
    width = 0.0
    for ch in text:
        cur.append(ch)
        width += _char_units(ch)
        if (ch in _BREAK_AFTER and width >= max_units * 0.55) or width >= max_units:
            lines.append("".join(cur))
            cur = []
            width = 0.0
    if cur:
        lines.append("".join(cur))
    return lines


def wrap_caption(text: str, max_units: int = _MAX_UNITS) -> str:
    """把一行字幕依寬度切成多行,回傳以 ASS 換行符 ``\\N`` 連接的多行。"""
    return "\\N".join(_wrap_lines(text, max_units))


class CaptionPage(NamedTuple):
    """一頁字幕:``text`` 已含 ``\\N`` 斷行;時間相對句首;karaoke 為 (顯示塊, centisec)。"""

    text: str
    start: float
    end: float
    karaoke: list[tuple[str, int]]


def _char_spans_from_words(
    sentence: str, words: list[WordBoundary]
) -> list[tuple[float, float]] | None:
    """用 word boundary 對齊出每個字的 (起,迄) 秒。對不上(TTS 正規化)回 None。"""
    n = len(sentence)
    spans: list[tuple[float, float] | None] = [None] * n
    cursor = 0
    for w in words:
        token = w.text.strip()
        if not token:
            continue
        idx = sentence.find(token, cursor)
        if idx < 0:
            return None
        for i in range(idx, min(idx + len(token), n)):
            spans[i] = (w.start, w.start + w.duration)
        cursor = idx + len(token)
    # 沒被 boundary 覆蓋的字(標點/空白):併入前一個字的時間;開頭的併入後一個
    last: tuple[float, float] | None = None
    for i in range(n):
        if spans[i] is not None:
            last = spans[i]
        elif last is not None:
            spans[i] = (last[1], last[1])
    first = next((s for s in spans if s is not None), None)
    if first is None:
        return None
    for i in range(n):
        if spans[i] is None:
            spans[i] = (first[0], first[0])
        else:
            break
    return [s if s is not None else (first[0], first[0]) for s in spans]


def _char_spans_proportional(sentence: str, duration: float) -> list[tuple[float, float]]:
    """按字寬比例把句長攤給每個字(拿不到 word boundary 時的後備)。"""
    weights = [_char_units(ch) for ch in sentence]
    total_w = sum(weights) or 1.0
    spans: list[tuple[float, float]] = []
    acc = 0.0
    for w in weights:
        start = duration * acc / total_w
        acc += w
        spans.append((start, duration * acc / total_w))
    return spans


def build_caption_pages(
    sentence: str,
    words: list[WordBoundary],
    duration: float,
    *,
    max_units: int = _MAX_UNITS,
    max_lines: int = _MAX_LINES,
) -> list[CaptionPage]:
    """把一句切成逐頁字幕(每頁 ≤ ``max_lines`` 行),附逐字卡拉OK時間。

    頁的起訖時間來自 word boundary(拿不到就按字寬比例),頁與頁相接不留黑洞;
    最後一頁停留到句尾。
    """
    if not sentence:
        return []
    spans = (_char_spans_from_words(sentence, words) if words else None) or (
        _char_spans_proportional(sentence, duration)
    )
    lines = _wrap_lines(sentence, max_units)
    page_line_groups = [lines[i : i + max_lines] for i in range(0, len(lines), max_lines)]

    pages: list[CaptionPage] = []
    char_pos = 0
    boundaries: list[tuple[int, int, set[int]]] = []  # (起字, 迄字, 行斷點集合)
    for group in page_line_groups:
        start_pos = char_pos
        breaks: set[int] = set()
        for j, line in enumerate(group):
            char_pos += len(line)
            if j < len(group) - 1:
                breaks.add(char_pos - 1)  # 此字之後插入 \N
        boundaries.append((start_pos, char_pos, breaks))

    for k, (lo, hi, breaks) in enumerate(boundaries):
        page_start = spans[lo][0]
        page_end = duration if k == len(boundaries) - 1 else spans[boundaries[k + 1][0]][0]
        # 卡拉OK塊:同時間片的連續字合成一塊,塊長順延到下一塊起點(吞掉字間空隙)
        chunks: list[tuple[str, float, float]] = []  # (text, start, end)
        for i in range(lo, hi):
            ch, (s, e) = sentence[i], spans[i]
            if chunks and chunks[-1][1] == s and chunks[-1][2] == e:
                chunks[-1] = (chunks[-1][0] + ch, s, e)
            else:
                chunks.append((ch, s, e))
            if i in breaks:
                text, s0, e0 = chunks[-1]
                chunks[-1] = (text + "\\N", s0, e0)
        karaoke: list[tuple[str, int]] = []
        for j, (text, s, e) in enumerate(chunks):
            until = chunks[j + 1][1] if j < len(chunks) - 1 else page_end
            cs = max(1, round((max(until, e) - s) * 100))
            karaoke.append((text, cs))
        page_text = "".join(t for t, _, _ in chunks)
        pages.append(CaptionPage(page_text, page_start, page_end, karaoke))
    return pages


def _ass_time(seconds: float) -> str:
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def build_ass(
    sentence: str, duration: float, *, title: str | None = None, font: str = "Noto Sans CJK TC"
) -> str:
    """組單句用的 .ass(底部字幕 + 選配頂部標題,皆全長顯示)。段級請用 build_segment_ass。"""
    end = _ass_time(duration)
    events = [f"Dialogue: 0,0:00:00.00,{end},sub,,0,0,0,,{wrap_caption(sentence)}"]
    if title:
        events.append(f"Dialogue: 0,0:00:00.00,{end},title,,0,0,0,,{title}")
    return _ASS_TEMPLATE.format(font=font, events="\n".join(events))


class _Take(NamedTuple):
    """一句配音的實測結果(供段級串接與字幕對時)。"""

    text: str
    audio: str  # work_dir 內檔名
    duration: float  # 實測秒數(probe)
    words: list[WordBoundary]


def build_segment_ass(
    takes: list[_Take],
    seg_duration: float,
    *,
    title: str | None,
    font: str,
) -> str:
    """組一段用的 .ass:各句逐頁卡拉OK字幕(含句間偏移)+ 選配頂部標題。"""
    events: list[str] = []
    if title:
        events.append(
            f"Dialogue: 0,0:00:00.00,{_ass_time(seg_duration)},title,,0,0,0,,{title}"
        )
    offset = 0.0
    for take in takes:
        for page in build_caption_pages(take.text, take.words, take.duration):
            start = _ass_time(offset + page.start)
            end = _ass_time(offset + page.end)
            text = "".join(f"{{\\k{cs}}}{chunk}" for chunk, cs in page.karaoke)
            events.append(f"Dialogue: 0,{start},{end},sub,,0,0,0,,{text}")
        offset += take.duration + _GAP
    return _ASS_TEMPLATE.format(font=font, events="\n".join(events))


def segment_timeline(durations: list[float]) -> tuple[list[float], float]:
    """由各段實際長度算累積起點與總長。"""
    starts: list[float] = []
    total = 0.0
    for d in durations:
        starts.append(total)
        total += d
    return starts, total


def _png_size(path: Path) -> tuple[int, int]:
    """讀 PNG IHDR 取 (寬, 高),不引入影像庫。"""
    with open(path, "rb") as fh:
        header = fh.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"非 PNG 檔:{path}")
    width, height = struct.unpack(">II", header[16:24])
    return int(width), int(height)


def _fit_box(w: int, h: int, box_w: int, box_h: int) -> tuple[int, int]:
    """等比縮進外框,回傳偶數化的 (寬, 高)(libx264 需要偶數維度)。"""
    scale = min(box_w / w, box_h / h)
    fw = max(2, int(w * scale) // 2 * 2)
    fh = max(2, int(h * scale) // 2 * 2)
    return fw, fh


def _run_ffmpeg(args: list[str], cwd: Path) -> None:
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        logger.error("ffmpeg 失敗:{}", proc.stderr[-800:])
        raise RuntimeError(f"ffmpeg 失敗(rc={proc.returncode})")


def _audio_graph(n_takes: int, seg_duration: float) -> str:
    """句音串接子圖:takes 為輸入 1..n,句間插呼吸、段尾 pad 到段長,輸出 [a]。"""
    parts: list[str] = []
    for i in range(n_takes):
        parts.append(
            f"[{i + 1}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=mono[a{i}]"
        )
    if n_takes == 1:
        chain = "[a0]"
    else:
        n_gaps = n_takes - 1
        gap_labels = [f"[g{i}]" for i in range(n_gaps)]
        if n_gaps == 1:
            parts.append(f"anullsrc=r=44100:cl=mono:d={_GAP}[g0]")
        else:
            parts.append(f"anullsrc=r=44100:cl=mono:d={_GAP}[gsrc]")
            parts.append(f"[gsrc]asplit={n_gaps}{''.join(gap_labels)}")
        interleaved: list[str] = []
        for i in range(n_takes):
            interleaved.append(f"[a{i}]")
            if i < n_gaps:
                interleaved.append(gap_labels[i])
        parts.append(f"{''.join(interleaved)}concat=n={2 * n_takes - 1}:v=0:a=1[acat]")
        chain = "[acat]"
    parts.append(f"{chain}apad=whole_dur={seg_duration:.3f}[a]")
    return ";".join(parts)


def _render_segment_clip(
    *,
    image: str,
    is_card: bool,
    takes: list[_Take],
    seg_duration: float,
    ass_name: str | None,
    global_offset: float,
    global_total: float,
    is_last: bool,
    out: str,
    work_dir: Path,
) -> None:
    """單段 clip:畫布 + (圖表縮排/全屏卡)Ken Burns + 字幕 + 進度條 + 淡入(末段加淡出)。"""
    frames = max(1, math.ceil(seg_duration * _FPS))
    img_w, img_h = _png_size(work_dir / image)
    if is_card:
        # 全屏卡:標準 Ken Burns(邊緣裁進來沒關係,卡片留白極大)
        out_w, out_h = _WIDTH, _HEIGHT
        ox, oy = 0, 0
        prep = f"[0:v]scale={out_w * 2}:{out_h * 2}:flags=lanczos"
    else:
        # 圖表:縮小一階塞進框,再用畫布同色 padding 墊回;zoompan 只推進 padding,
        # 圖上貼邊的字(數值標註/時間軸文字)永遠不會被裁掉
        inner_w = int(_CHART_BOX_W / (1 + _ZOOM_AMOUNT))
        inner_h = int(_CHART_BOX_H / (1 + _ZOOM_AMOUNT))
        fit_w, fit_h = _fit_box(img_w, img_h, inner_w, inner_h)
        out_w = int(fit_w * (1 + _ZOOM_AMOUNT)) // 2 * 2
        out_h = int(fit_h * (1 + _ZOOM_AMOUNT)) // 2 * 2
        ox = (_WIDTH - out_w) // 2
        oy = _CHART_BAND_TOP + (_CHART_BOX_H - out_h) // 2
        prep = (
            f"[0:v]scale={fit_w * 2}:{fit_h * 2}:flags=lanczos,"
            f"pad={out_w * 2}:{out_h * 2}:(ow-iw)/2:(oh-ih)/2:color=0x{_BG_HEX}"
        )

    chain: list[str] = [
        f"color=c=0x{_BG_HEX}:s={_WIDTH}x{_HEIGHT}:r={_FPS}:d={seg_duration:.3f}[bg]",
        # 先放大 2 倍再 zoompan,消除整數座標取樣的抖動;緩推 {_ZOOM_AMOUNT:.0%}
        (
            f"{prep},"
            f"zoompan=z='1+{_ZOOM_AMOUNT}*on/{frames}':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={out_w}x{out_h}:fps={_FPS}[ken]"
        ),
        f"[bg][ken]overlay={ox}:{oy}[v0]",
    ]
    label = "[v0]"
    if ass_name:
        chain.append(f"{label}subtitles={ass_name}[v1]")
        label = "[v1]"
    chain.append(
        f"color=c=0x{_GOLD_HEX}:s={_WIDTH}x{_PROGRESS_H}:r={_FPS}:d={seg_duration:.3f}[pb]"
    )
    chain.append(
        f"{label}[pb]overlay="
        f"x='-w+w*min(1,({global_offset:.3f}+t)/{max(global_total, 0.001):.3f})':"
        f"y={_HEIGHT - _PROGRESS_H}[v2]"
    )
    fade = f"[v2]fade=t=in:st=0:d={_FADE_IN}:color=0x{_BG_HEX}"
    if is_last:
        out_st = max(seg_duration - _FADE_OUT, 0)
        fade += f",fade=t=out:st={out_st:.3f}:d={_FADE_OUT}:color=0x{_BG_HEX}"
    chain.append(f"{fade}[v]")
    chain.append(_audio_graph(len(takes), seg_duration))

    args = ["ffmpeg", "-y", "-loop", "1", "-i", image]
    for take in takes:
        args += ["-i", take.audio]
    args += [
        "-filter_complex", ";".join(chain),
        "-map", "[v]", "-map", "[a]",
        "-t", f"{seg_duration:.3f}", "-r", str(_FPS),
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
        out,
    ]
    _run_ffmpeg(args, cwd=work_dir)


def _measure_loudness(path: Path, cwd: Path) -> dict | None:
    """loudnorm 第一遍:量測整體響度,回傳 measured_* dict;量不到(如全靜音)回 None。"""
    proc = subprocess.run(
        [
            "ffmpeg", "-i", str(Path(path).resolve()), "-af",
            "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-",
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        logger.warning("響度量測 ffmpeg 失敗:{}", proc.stderr[-400:])
        return None
    tail = proc.stderr[-1600:]
    start = tail.rfind("{")
    if start < 0:
        return None
    try:
        # JSON 區塊後面還有 ffmpeg 收尾行,用 raw_decode 只取第一個物件
        data, _ = json.JSONDecoder().raw_decode(tail[start:])
    except json.JSONDecodeError:
        return None
    if any("-inf" in str(data.get(k, "")) for k in ("input_i", "input_tp")):
        return None
    return data


def finalize_master(
    concat_path: Path,
    out_path: Path,
    total: float,
    *,
    bgm_path: Path | None,
    bgm_gain_db: float,
    work_dir: Path,
) -> None:
    """母帶鏈:VO 下墊 BGM(sidechain ducking)+ 兩遍 loudnorm(-14 LUFS)+ 收尾淡出。

    影像串流直接 copy(畫質零損);只重編音訊。BGM 缺席時仍做 loudnorm 與淡出。
    """
    # _run_ffmpeg 以 work_dir 為 cwd,這裡的輸入可能是相對路徑,一律先轉絕對,避免疊層
    concat_path = Path(concat_path).resolve()
    out_path = Path(out_path).resolve()
    bgm_path = Path(bgm_path).resolve() if bgm_path is not None else None
    measured = _measure_loudness(concat_path, work_dir)
    loudnorm = "loudnorm=I=-14:TP=-1.5:LRA=11"
    if measured:
        loudnorm += (
            f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
            f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
            f":offset={measured['target_offset']}:linear=true"
        )
    else:
        logger.warning("量不到響度(可能是靜音 dry-run),跳過 loudnorm 增益校正")

    fade_start = max(total - 0.8, 0.0)
    # VO 打磨:70Hz 高通去低頻嗡聲 + 3kHz 輕微臨場感,TTS 人聲更乾淨清晰
    vo_polish = "highpass=f=70,equalizer=f=3000:t=q:w=1:g=1.5"
    args = ["ffmpeg", "-y", "-i", str(concat_path)]
    if bgm_path is not None and Path(bgm_path).exists():
        args += ["-stream_loop", "-1", "-i", str(bgm_path)]
        graph = (
            f"[0:a]{vo_polish},asplit=2[vo][sc];"
            f"[1:a]aresample=44100,aformat=channel_layouts=mono,volume={bgm_gain_db}dB,"
            f"atrim=0:{total:.3f}[bgt];"
            # VO 一開口就把 BGM 往下壓,句間空隙讓它微微浮上來
            f"[bgt][sc]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=600[duck];"
            f"[vo][duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix];"
            f"[mix]{loudnorm},afade=t=out:st={fade_start:.3f}:d=0.8[a]"
        )
    else:
        graph = f"[0:a]{vo_polish},{loudnorm},afade=t=out:st={fade_start:.3f}:d=0.8[a]"
    args += [
        "-filter_complex", graph,
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
        "-movflags", "+faststart",
        str(out_path),
    ]
    _run_ffmpeg(args, cwd=work_dir)


def assemble_video(
    script: Script,
    snapshot: Snapshot,
    out_path: str | Path,
    *,
    synth_fn: SynthFn,
    work_dir: str | Path,
    font: str = "Noto Sans CJK TC",
    channel_name: str = "美股早發車",
    bgm_path: str | Path | None = None,
    bgm_gain_db: float = -20.0,
    master_audio: bool = True,
) -> Path:
    """合成直式短影片並回傳 mp4 路徑。段級渲染 + 卡拉OK字幕 + 動態;詳見模組 docstring。"""
    out_path = Path(out_path).resolve()
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    chart_paths = {spec.id: render_chart(spec, snapshot, work_dir).name for spec in script.charts}

    # Pass A:逐句配音 + 實測長度 → 段長與全片時間軸(進度條/收尾要用)
    seg_takes: list[list[_Take]] = []
    seg_durations: list[float] = []
    for i, seg in enumerate(script.segments):
        sentences = split_sentences(seg.vo) or [seg.vo]
        planned_each = seg.duration / max(len(sentences), 1)
        takes: list[_Take] = []
        for j, sentence in enumerate(sentences):
            audio_name = f"s{i}_{j}.mp3"
            result = synth_fn(sentence, work_dir / audio_name, planned_each)
            measured = probe_duration(work_dir / audio_name)
            takes.append(_Take(sentence, audio_name, measured, result.words))
        seg_takes.append(takes)
        seg_durations.append(
            sum(t.duration for t in takes) + _GAP * (len(takes) - 1) + _TAIL
        )

    starts, total = segment_timeline(seg_durations)
    if total > _SHORTS_CAP:
        logger.warning(
            "成片 {:.1f}s 超過 Shorts 上限 {:.0f}s,會被 YouTube 當一般影片;請縮講稿",
            total,
            _SHORTS_CAP,
        )

    # Pass B:逐段渲染 clip(圖表段帶字幕;卡片段大字已烤進圖、不疊字幕)
    clip_names: list[str] = []
    for i, seg in enumerate(script.segments):
        takes = seg_takes[i]
        is_last = i == len(script.segments) - 1
        if seg.headline is not None:
            card_name = f"card{i}.png"
            render_headline_card(
                str(work_dir / card_name),
                seg.headline,
                accent=accent_for(i),
                tag=seg.tag or channel_name,
            )
            image, is_card, ass_name = card_name, True, None
        else:
            image, is_card = chart_paths[seg.chart_id], False
            ass_name = f"seg{i}.ass"
            (work_dir / ass_name).write_text(
                build_segment_ass(takes, seg_durations[i], title=seg.title, font=font),
                encoding="utf-8",
            )
        clip_name = f"clip{i}.mp4"
        _render_segment_clip(
            image=image,
            is_card=is_card,
            takes=takes,
            seg_duration=seg_durations[i],
            ass_name=ass_name,
            global_offset=starts[i],
            global_total=total,
            is_last=is_last,
            out=clip_name,
            work_dir=work_dir,
        )
        clip_names.append(clip_name)
        logger.info("segment {}/{} 完成({:.1f}s)", i + 1, len(script.segments), seg_durations[i])

    listing = work_dir / "clips.txt"
    listing.write_text("".join(f"file '{name}'\n" for name in clip_names), encoding="utf-8")
    concat_name = "concat_raw.mp4"
    _run_ffmpeg(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "clips.txt",
         "-c", "copy", concat_name],
        cwd=work_dir,
    )

    if master_audio:
        finalize_master(
            work_dir / concat_name,
            out_path,
            total,
            bgm_path=Path(bgm_path) if bgm_path else None,
            bgm_gain_db=bgm_gain_db,
            work_dir=work_dir,
        )
    else:
        (work_dir / concat_name).replace(out_path)

    logger.info("直式影片合成完成({:.1f}s)→ {}", total, out_path)
    return out_path
