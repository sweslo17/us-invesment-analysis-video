"""影片合成:直式短影片(1080×1920),段級渲染。

每個 segment 一支 clip,段內把旁白切成句、逐句配音後串接(句間留呼吸、段尾留停頓),
字幕以「頁」為單位逐字卡拉OK掃色(edge-tts word boundary 對齊;拿不到就按字寬比例),
每頁最多兩行、永不蓋到中段的圖表。圖表段有 Ken Burns 緩推 + 滑入、段首自畫布色淡入、
全片底部金色進度條。字卡的文字也走 ASS(pop-in 動畫),底圖只是漸層色。

**版面避開 YouTube Shorts 播放器的 UI**(見 ``layout_safe_zone``):底部約 400px 被標題/
頻道列蓋住、右側約 170px 是按讚欄,字幕、大數字 callout、CTA 一律放在安全區內。
最終串接後過音訊母帶鏈(BGM ducking + loudnorm),見 ``finalize_master``。
配音以可注入的 ``synth_fn`` 提供。
斷句/字幕在 ``video.captions``、版面與 ASS 元件在 ``video.ass``。
"""

from __future__ import annotations

import json
import math
import struct
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from loguru import logger

from pmb.charts.cards import accent_for, render_card_background
from pmb.charts.select import render_chart
from pmb.schemas.script import Script
from pmb.schemas.snapshot import Snapshot
from pmb.tts.edge import SynthResult, WordBoundary, probe_duration
from pmb.video.ass import (
    ASS_TEMPLATE,
    BG_HEX,
    CARD_CENTER_Y,
    CARD_LINE_H,
    CARD_MAX_UNITS,
    CHART_BAND_TOP,
    CHART_BOX_H,
    CHART_BOX_W,
    FADE_TAG,
    GOLD_HEX,
    HEIGHT,
    KICKER_GAP,
    POP_IN,
    WIDTH,
    ass_time,
    common_events,
    full_event,
)
from pmb.video.captions import build_caption_pages, split_sentences

# synth_fn(text, out_path, planned_duration) -> SynthResult
SynthFn = Callable[[str, Path, float], SynthResult]

_FPS = 25
_GAP = 0.18  # 句間呼吸(秒)
_TAIL = 0.35  # 段尾停頓(秒)
_FADE_IN = 0.20  # 段首自畫布色淡入
_FADE_OUT = 0.60  # 全片收尾淡出(烤在最後一段)
_ZOOM_AMOUNT = 0.08  # Ken Burns 段內總推進幅度
_SLIDE_PX = 70  # 圖表段首自下方滑入的位移
_SLIDE_SEC = 0.40
_PROGRESS_H = 10  # 底部進度條高(px)
_SHORTS_CAP = 180.0  # YouTube Shorts 長度上限(超過會被當一般影片)


class _Take(NamedTuple):
    """一句配音的實測結果(供段級串接與字幕對時)。"""

    text: str
    audio: str  # work_dir 內檔名
    duration: float  # 實測秒數(probe)
    words: list[WordBoundary]



def build_card_ass(
    headline: str,
    *,
    tag: str | None,
    duration: float,
    font: str,
    badge: str | None = None,
    cta: str | None = None,
) -> str:
    """組字卡用的 .ass:大標 pop-in(置中)+ 選配 kicker 小標(上方)+ 角標/CTA。

    字卡底圖只有漸層色(``cards.render_card_background``),文字全走這裡,才能動。
    """
    from pmb.charts.cards import wrap_card_text

    lines = wrap_card_text(headline, max_units=CARD_MAX_UNITS)
    top = CARD_CENTER_Y - len(lines) * CARD_LINE_H // 2
    pos = f"{{\\an5\\pos(540,{CARD_CENTER_Y})}}"
    events: list[str] = [full_event("card", duration, pos + POP_IN + "\\N".join(lines))]
    if tag:
        kicker_pos = f"{{\\an5\\pos(540,{top - KICKER_GAP})}}"
        events.append(full_event("kicker", duration, kicker_pos + FADE_TAG + tag))
    events += common_events(duration, badge=badge, cta=cta)
    return ASS_TEMPLATE.format(font=font, events="\n".join(events))


def build_segment_ass(
    takes: list[_Take],
    seg_duration: float,
    *,
    title: str | None,
    font: str,
    stat: str | None = None,
    stat_label: str | None = None,
    badge: str | None = None,
    cta: str | None = None,
) -> str:
    """組圖表段用的 .ass:逐頁卡拉OK字幕(含句間偏移)+ 頂部標題 + 大數字 callout + 角標/CTA。

    callout(``stat``/``stat_label``)疊在圖表下方的留白處,是手機上一眼能抓到的重點數字;
    沒給就不畫,舊 script 相容。
    """
    events: list[str] = []
    if title:
        events.append(full_event("title", seg_duration, FADE_TAG + title))
    if stat:
        if stat_label:
            events.append(full_event("statlabel", seg_duration, FADE_TAG + stat_label))
        events.append(full_event("stat", seg_duration, POP_IN + stat))
    events += common_events(seg_duration, badge=badge, cta=cta)
    offset = 0.0
    for take in takes:
        for page in build_caption_pages(take.text, take.words, take.duration):
            start = ass_time(offset + page.start)
            end = ass_time(offset + page.end)
            text = "".join(f"{{\\k{cs}}}{chunk}" for chunk, cs in page.karaoke)
            events.append(f"Dialogue: 0,{start},{end},sub,,0,0,0,,{text}")
        offset += take.duration + _GAP
    return ASS_TEMPLATE.format(font=font, events="\n".join(events))


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
        out_w, out_h = WIDTH, HEIGHT
        ox, oy = 0, 0
        prep = f"[0:v]scale={out_w * 2}:{out_h * 2}:flags=lanczos"
    else:
        # 圖表:縮小一階塞進框,再用畫布同色 padding 墊回;zoompan 只推進 padding,
        # 圖上貼邊的字(數值標註/時間軸文字)永遠不會被裁掉
        inner_w = int(CHART_BOX_W / (1 + _ZOOM_AMOUNT))
        inner_h = int(CHART_BOX_H / (1 + _ZOOM_AMOUNT))
        fit_w, fit_h = _fit_box(img_w, img_h, inner_w, inner_h)
        out_w = int(fit_w * (1 + _ZOOM_AMOUNT)) // 2 * 2
        out_h = int(fit_h * (1 + _ZOOM_AMOUNT)) // 2 * 2
        ox = (WIDTH - out_w) // 2
        oy = CHART_BAND_TOP + (CHART_BOX_H - out_h) // 2
        prep = (
            f"[0:v]scale={fit_w * 2}:{fit_h * 2}:flags=lanczos,"
            f"pad={out_w * 2}:{out_h * 2}:(ow-iw)/2:(oh-ih)/2:color=0x{BG_HEX}"
        )

    chain: list[str] = [
        f"color=c=0x{BG_HEX}:s={WIDTH}x{HEIGHT}:r={_FPS}:d={seg_duration:.3f}[bg]",
        # 先放大 2 倍再 zoompan,消除整數座標取樣的抖動;緩推 {_ZOOM_AMOUNT:.0%}
        (
            f"{prep},"
            f"zoompan=z='1+{_ZOOM_AMOUNT}*on/{frames}':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={out_w}x{out_h}:fps={_FPS}[ken]"
        ),
        # 圖表段首自下方滑入 {_SLIDE_PX}px(二次緩出);字卡底圖不滑,文字本身有 pop-in
        (
            f"[bg][ken]overlay={ox}:{oy}[v0]"
            if is_card
            else f"[bg][ken]overlay={ox}:'{oy}+{_SLIDE_PX}*pow(max(0,1-t/{_SLIDE_SEC}),2)'[v0]"
        ),
    ]
    label = "[v0]"
    if ass_name:
        chain.append(f"{label}subtitles={ass_name}[v1]")
        label = "[v1]"
    chain.append(
        f"color=c=0x{GOLD_HEX}:s={WIDTH}x{_PROGRESS_H}:r={_FPS}:d={seg_duration:.3f}[pb]"
    )
    chain.append(
        f"{label}[pb]overlay="
        f"x='-w+w*min(1,({global_offset:.3f}+t)/{max(global_total, 0.001):.3f})':"
        f"y={HEIGHT - _PROGRESS_H}[v2]"
    )
    fade = f"[v2]fade=t=in:st=0:d={_FADE_IN}:color=0x{BG_HEX}"
    if is_last:
        out_st = max(seg_duration - _FADE_OUT, 0)
        fade += f",fade=t=out:st={out_st:.3f}:d={_FADE_OUT}:color=0x{BG_HEX}"
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
            # VO 一開口把 BGM 往下帶、句間浮回來;柔性壓(ratio 3),BGM 在講話時仍聽得見
            f"[bgt][sc]sidechaincompress=threshold=0.06:ratio=3:attack=80:release=900[duck];"
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
    usable: list[int] = []  # 有可配音內容的段索引(其餘跳過,不讓一段壞掉整支片)
    for i, seg in enumerate(script.segments):
        sentences = split_sentences(seg.vo)
        if not sentences:
            # 整段沒有可發音內容(講稿異常):跳過該段而不是讓 TTS 回空音檔炸掉全片
            logger.warning("segment {} 無可發音內容,跳過:{!r}", i, seg.vo[:40])
            seg_takes.append([])
            seg_durations.append(0.0)
            continue
        usable.append(i)
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

    # Pass B:逐段渲染 clip。圖表段:字幕 + 標題 + stat callout;字卡段:漸層底 + ASS 大字
    # pop-in。每段都疊品牌·日期角標;片尾 CTA 只放在最後一段且該段是字卡(圖表段底部有
    # 字幕,再疊 CTA 會打架)。
    d = snapshot.session_date
    badge = f"{channel_name} · {d.month}/{d.day}"
    cta_text = f"明天盤前見 · 追蹤 {channel_name}"
    last_idx = usable[-1] if usable else len(script.segments) - 1
    clip_names: list[str] = []
    for i, seg in enumerate(script.segments):
        takes = seg_takes[i]
        if not takes:
            continue  # Pass A 判定無可配音內容,已跳過
        if seg.kind not in ("chart", "card"):
            raise ValueError(f"段型「{seg.kind}」尚未支援合成")
        is_last = i == last_idx
        cta = cta_text if (is_last and seg.kind == "card") else None
        if seg.kind == "card":
            card_name = f"card{i}.png"
            render_card_background(str(work_dir / card_name), accent=accent_for(i))
            image, is_card, ass_name = card_name, True, f"card{i}.ass"
            (work_dir / ass_name).write_text(
                build_card_ass(
                    seg.headline, tag=seg.tag, duration=seg_durations[i], font=font,
                    badge=badge, cta=cta,
                ),
                encoding="utf-8",
            )
        else:
            image, is_card, ass_name = chart_paths[seg.chart_id], False, f"seg{i}.ass"
            (work_dir / ass_name).write_text(
                build_segment_ass(
                    takes, seg_durations[i], title=seg.title, font=font,
                    stat=seg.stat, stat_label=seg.stat_label, badge=badge, cta=cta,
                ),
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
