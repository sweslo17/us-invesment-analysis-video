"""影片合成:直式短影片(1080×1920),段級渲染。

每個 segment 一支 clip,段內把旁白切成句、逐句配音後串接(句間留呼吸、段尾留停頓),
字幕以「頁」為單位逐字卡拉OK掃色(edge-tts word boundary 對齊;拿不到就按字寬比例),
每頁最多兩行、永不蓋到中段的圖表。圖表段有 Ken Burns 緩推 + 滑入、段首自畫布色淡入、
全片底部金色進度條。字卡的文字也走 ASS(pop-in 動畫),底圖只是漸層色。

**版面避開 YouTube Shorts 播放器的 UI**(見 ``layout_safe_zone``):底部約 400px 被標題/
頻道列蓋住、右側約 170px 是按讚欄,字幕、大數字 callout、CTA 一律放在安全區內。
最終串接後過音訊母帶鏈(BGM ducking + loudnorm),見 ``finalize_master``。
配音以可注入的 ``synth_fn`` 提供。
斷句/字幕在 ``video.captions``、版面與 ASS 元件在 ``video.ass``,段型各自的畫面與句子計畫
在 ``video.segments``(registry)。
"""

from __future__ import annotations

import json
import math
import struct
import subprocess
from collections.abc import Callable
from pathlib import Path

from loguru import logger

from pmb.charts.select import render_chart
from pmb.schemas.script import Script, Segment, VoiceKey
from pmb.schemas.snapshot import Snapshot
from pmb.tts.edge import SynthResult, probe_duration
from pmb.video.ass import (
    BG_HEX,
    CHART_BAND_TOP,
    CHART_BOX_H,
    CHART_BOX_W,
    FPS,
    GOLD_HEX,
    HEIGHT,
    WIDTH,
)
from pmb.video.captions import has_speakable
from pmb.video.segments.base import (
    GAP,
    RenderContext,
    Take,
    Utterance,
    append_outro,
    segment_duration,
    take_starts,
)
from pmb.video.segments.registry import renderer_for
from pmb.video.segments.sting import StingSegment

# synth_fn(text, out_path, planned_duration, voice) -> SynthResult;voice 是 narrator / a / b
SynthFn = Callable[[str, Path, float, VoiceKey], SynthResult]
_SEC_PER_CHAR = 0.18  # 估長(dry-run 靜音配音長度用;實際段長一律以實測為準)

_FADE_IN = 0.20  # 段首自畫布色淡入
_FADE_OUT = 0.60  # 全片收尾淡出(烤在最後一段)
_ZOOM_AMOUNT = 0.08  # Ken Burns 段內總推進幅度
_SLIDE_PX = 70  # 圖表段首自下方滑入的位移
_SLIDE_SEC = 0.40
_PROGRESS_H = 10  # 底部進度條高(px)
_SHORTS_CAP = 180.0  # YouTube Shorts 長度上限(超過會被當一般影片)


def _planned_seconds(text: str) -> float:
    return max(0.6, len(text) * _SEC_PER_CHAR)


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


def _audio_graph(
    n_takes: int,
    seg_duration: float,
    *,
    gaps: list[float] | None = None,
    lead_in: float = 0.0,
    sfx_input: int | None = None,
) -> str:
    """句音串接子圖:takes 為輸入 1..n,段首可留 ``lead_in`` 靜音、句間插各自的停頓、
    段尾 pad 到段長;``sfx_input`` 給了就把該輸入的音效從段首疊上。輸出 [a]。"""
    gaps = list(gaps) if gaps is not None else [GAP] * max(n_takes - 1, 0)
    parts: list[str] = []
    for i in range(n_takes):
        parts.append(
            f"[{i + 1}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=mono[a{i}]"
        )
    items: list[str] = []
    if lead_in > 0:
        parts.append(f"anullsrc=r=44100:cl=mono:d={lead_in:.3f}[lead]")
        items.append("[lead]")
    gap_labels: list[str] = []
    if n_takes > 1:
        n_gaps = n_takes - 1
        if len(set(gaps)) == 1:  # 停頓一樣長:一個靜音源 asplit(舊行為)
            gap_labels = [f"[g{i}]" for i in range(n_gaps)]
            if n_gaps == 1:
                parts.append(f"anullsrc=r=44100:cl=mono:d={gaps[0]:.3f}[g0]")
            else:
                parts.append(f"anullsrc=r=44100:cl=mono:d={gaps[0]:.3f}[gsrc]")
                parts.append(f"[gsrc]asplit={n_gaps}{''.join(gap_labels)}")
        else:
            for i, gap in enumerate(gaps):
                parts.append(f"anullsrc=r=44100:cl=mono:d={gap:.3f}[g{i}]")
                gap_labels.append(f"[g{i}]")
    for i in range(n_takes):
        items.append(f"[a{i}]")
        if i < len(gap_labels):
            items.append(gap_labels[i])
    if len(items) == 1:
        chain = items[0]
    else:
        parts.append(f"{''.join(items)}concat=n={len(items)}:v=0:a=1[acat]")
        chain = "[acat]"
    out = "[a]" if sfx_input is None else "[vo]"
    parts.append(f"{chain}apad=whole_dur={seg_duration:.3f}{out}")
    if sfx_input is not None:
        parts.append(
            f"[{sfx_input}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=mono[sfx]"
        )
        parts.append("[vo][sfx]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
    return ";".join(parts)


def _render_segment_clip(
    *,
    image: str,
    is_card: bool,
    takes: list[Take],
    seg_duration: float,
    ass_name: str | None,
    global_offset: float,
    global_total: float,
    is_last: bool,
    out: str,
    work_dir: Path,
    lead_in: float = 0.0,
    sfx: str | None = None,
) -> None:
    """單段 clip:畫布 + (圖表縮排/全屏卡)Ken Burns + 字幕 + 進度條 + 淡入(末段加淡出)。"""
    frames = max(1, math.ceil(seg_duration * FPS))
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
        f"color=c=0x{BG_HEX}:s={WIDTH}x{HEIGHT}:r={FPS}:d={seg_duration:.3f}[bg]",
        # 先放大 2 倍再 zoompan,消除整數座標取樣的抖動;緩推 {_ZOOM_AMOUNT:.0%}
        (
            f"{prep},"
            f"zoompan=z='1+{_ZOOM_AMOUNT}*on/{frames}':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={out_w}x{out_h}:fps={FPS}[ken]"
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
        f"color=c=0x{GOLD_HEX}:s={WIDTH}x{_PROGRESS_H}:r={FPS}:d={seg_duration:.3f}[pb]"
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
    chain.append(
        _audio_graph(
            len(takes), seg_duration, gaps=[t.gap_after for t in takes[:-1]], lead_in=lead_in,
            sfx_input=len(takes) + 1 if sfx else None,
        )
    )

    args = ["ffmpeg", "-y", "-loop", "1", "-i", image]
    for take in takes:
        args += ["-i", take.audio]
    if sfx:
        args += ["-i", sfx]
    args += [
        "-filter_complex", ";".join(chain),
        "-map", "[v]", "-map", "[a]",
        "-t", f"{seg_duration:.3f}", "-r", str(FPS),
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


def _insert_sting(
    units: list[tuple[int, Segment | StingSegment]],
    slogan: str,
    channel: str,
    sfx: str | Path | None,
) -> None:
    """在 hook(第一段)之後插入開場口號轉場;索引用 0,只影響 ``sting0.ass`` 檔名。
    音效路徑先轉絕對:ffmpeg 以 work_dir 為 cwd 執行。"""
    sfx_path = str(Path(sfx).resolve()) if sfx else None
    units.insert(1, (0, StingSegment(text=slogan, channel=channel, sfx=sfx_path)))


def _plan_units(
    units: list[tuple[int, Segment | StingSegment]], slogan_outro: str | None
) -> list[list[Utterance]]:
    """各 unit 的句子計畫(只留可發音的句子);收尾口號接在「最後一個有計畫的腳本段」。

    系統插入的 sting 不算腳本段,收尾口號不會接到它後面。"""
    plans = [
        [utt for utt in renderer_for(seg.kind).utterances(seg) if has_speakable(utt.tts_text)]
        for _, seg in units
    ]
    last_script = next(
        (u for u in range(len(units) - 1, -1, -1) if plans[u] and units[u][1].kind != "sting"),
        None,
    )
    if last_script is not None:
        plans[last_script] = append_outro(plans[last_script], slogan_outro)
    return plans


def _synthesize_takes(
    plan: list[Utterance], u: int, work_dir: Path, synth_fn: SynthFn
) -> list[Take]:
    """逐句配音並量測實際長度;音檔命名 ``s{unit}_{句序}.mp3``。"""
    takes: list[Take] = []
    for j, utt in enumerate(plan):
        audio_name = f"s{u}_{j}.mp3"
        result = synth_fn(
            utt.tts_text, work_dir / audio_name, _planned_seconds(utt.tts_text), utt.voice
        )
        measured = probe_duration(work_dir / audio_name)
        takes.append(
            Take(utt.text, audio_name, measured, result.words, utt.gap_after, utt.caption)
        )
    return takes


def _render_optional(render: Callable[..., str], u: int, kind: str) -> str | None:
    """渲染 optional 段:失敗先不帶音效重試一次,仍失敗回 None(呼叫端略過該段,影片照出)。"""
    try:
        return render(u)
    except RuntimeError as exc:
        logger.warning("{} 渲染失敗,拿掉音效重試一次:{}", kind, exc)
    try:
        return render(u, with_sfx=False)
    except RuntimeError as exc:
        logger.warning("{} 不帶音效仍渲染失敗,略過該段(影片照出):{}", kind, exc)
        return None


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
    slogan_intro: str | None = None,
    slogan_outro: str | None = None,
    sting_sfx: str | Path | None = None,
) -> Path:
    """合成直式短影片並回傳 mp4 路徑。段級渲染 + 卡拉OK字幕 + 動態;詳見模組 docstring。

    ``slogan_intro`` 給了就在 hook 後插口號轉場(``sting_sfx`` 為其音效);``slogan_outro``
    接在最後一段(模型已寫同義句就不重複)。口號轉場配音失敗只略過該段;渲染失敗(如音效檔
    解不開)先拿掉音效重試,仍失敗才略過該段——影片都照出。"""
    out_path = Path(out_path).resolve()
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    chart_paths = {spec.id: render_chart(spec, snapshot, work_dir).name for spec in script.charts}

    # Pass A:各段的句子計畫 → 逐句配音 + 實測長度 → 段長與全片時間軸(進度條/收尾要用)
    units: list[tuple[int, Segment | StingSegment]] = list(enumerate(script.segments))
    if slogan_intro and units:
        _insert_sting(units, slogan_intro, channel_name, sting_sfx)
    plans = _plan_units(units, slogan_outro)
    seg_takes: list[list[Take]] = []
    seg_durations: list[float] = []
    usable: list[int] = []  # 有可配音內容的 unit 索引(其餘跳過,不讓一段壞掉整支片)
    for u, (i, seg) in enumerate(units):
        renderer = renderer_for(seg.kind)
        plan = plans[u]
        if not plan:
            logger.warning(
                "segment {}({})無可發音內容,跳過:{!r}", i, seg.kind, seg.spoken_text[:40]
            )
            seg_takes.append([])
            seg_durations.append(0.0)
            continue
        try:
            takes = _synthesize_takes(plan, u, work_dir, synth_fn)
        except Exception as exc:  # noqa: BLE001
            if not renderer.optional:
                raise
            logger.warning("{} 配音失敗,略過該段(影片照出):{}", seg.kind, exc)
            seg_takes.append([])
            seg_durations.append(0.0)
            continue
        usable.append(u)
        seg_takes.append(takes)
        seg_durations.append(
            segment_duration(takes, lead_in=renderer.lead_in, min_duration=renderer.min_duration)
        )

    starts, total = segment_timeline(seg_durations)
    if total > _SHORTS_CAP:
        logger.warning(
            "成片 {:.1f}s 超過 Shorts 上限 {:.0f}s,會被 YouTube 當一般影片;請縮講稿",
            total,
            _SHORTS_CAP,
        )

    # Pass B:逐段渲染 clip。畫面(底圖 + .ass)由各段型 renderer 產出;每段都疊品牌·日期
    # 角標,片尾 CTA 只放在最後一段且該段是字卡(圖表段底部有字幕,再疊 CTA 會打架)。
    d = snapshot.session_date
    badge = f"{channel_name} · {d.month}/{d.day}"
    cta_text = f"明天盤前見 · 追蹤 {channel_name}"

    def render_unit(u: int, *, with_sfx: bool = True) -> str:
        """渲染第 ``u`` 個 unit 的 clip,回傳檔名;時間軸(starts/total/usable)在呼叫當下讀。"""
        i, seg = units[u]
        takes = seg_takes[u]
        renderer = renderer_for(seg.kind)
        is_last = u == (usable[-1] if usable else len(units) - 1)
        ctx = RenderContext(
            index=i, duration=seg_durations[u], takes=takes,
            starts=take_starts(takes, renderer.lead_in), font=font, work_dir=work_dir,
            badge=badge, cta=cta_text if (is_last and seg.kind == "card") else None,
            chart_paths=chart_paths,
        )
        visual = renderer.render(seg, ctx)
        ass_name = f"{visual.stem}{i}.ass"
        (work_dir / ass_name).write_text(visual.ass, encoding="utf-8")
        clip_name = f"clip{u}.mp4"
        _render_segment_clip(
            image=visual.image, is_card=visual.is_card, takes=takes,
            seg_duration=seg_durations[u], ass_name=ass_name, global_offset=starts[u],
            global_total=total, is_last=is_last, out=clip_name, work_dir=work_dir,
            lead_in=renderer.lead_in, sfx=visual.sfx if with_sfx else None,
        )
        logger.info(
            "segment {}/{}({})完成({:.1f}s)", u + 1, len(units), seg.kind, seg_durations[u]
        )
        return clip_name

    # optional 段(口號轉場)先渲染:失敗先拿掉音效重試一次(音效壞檔不該殺掉整支片),仍失敗
    # 就整段略過並從時間軸拿掉,再渲染其餘各段——進度條與總長都以定案的時間軸計算,不留空洞。
    # 目前只有一段 optional,它渲染時時間軸就是最終版本。
    clips: dict[int, str] = {}
    for u in [u for u in usable if renderer_for(units[u][1].kind).optional]:
        clip = _render_optional(render_unit, u, units[u][1].kind)
        if clip is not None:
            clips[u] = clip
            continue
        seg_takes[u] = []
        seg_durations[u] = 0.0
        usable.remove(u)
        starts, total = segment_timeline(seg_durations)
    for u in usable:  # Pass A 判定無可配音內容的段不在 usable 裡,已跳過
        if u not in clips:
            clips[u] = render_unit(u)
    clip_names = [clips[u] for u in usable]

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
