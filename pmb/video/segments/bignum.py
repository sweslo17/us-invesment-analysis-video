"""全屏大數字:label → 大數字(0.2s 起、0.6s 內從 0 跳到定值)→ 一行脈絡;字幕照跑。

數字格式(正負號、千分位、小數位、單位)全程保留;解析不了就靜態顯示並記 WARNING。
所有文字都以 ``textfit`` 的像素寬度模型排版,保證置中後左右緣都在 540 ± 370 之內
(右緣 910,不碰 Shorts 右側按讚欄)。
"""

from __future__ import annotations

import re
from typing import NamedTuple

from loguru import logger

from pmb.schemas.script import BignumSegment
from pmb.video.ass import (
    ASS_TEMPLATE,
    GOLD_HEX,
    WHITE_HEX,
    ass_color,
    ass_time,
    common_events,
    escape_text,
    text_event,
)
from pmb.video.segments.base import (
    RenderContext,
    SegmentRenderer,
    Visual,
    canvas_background,
    caption_events,
)
from pmb.video.textfit import FLOOR_SIZE, fit_lines, line_px, shorten

_CENTER_X = 540
_LABEL_Y = 560
_VALUE_Y = 820
_CONTEXT_Y = 1060
_LABEL_FS = 52
_VALUE_FS = 260  # 大數字字級上限,寬值再往下縮
_TEXT_MAX_W = 740  # 置中 540 ± 370:右緣 910,不碰按讚欄
_CONTEXT_FS = 60
_CONTEXT_MAX_LINES = 2
_COUNT_START = 0.2
_COUNT_DUR = 0.6
_FPS = 25
_LABEL_HEX = "#8FA3B8"
_NUM_RE = re.compile(r"^(?P<prefix>\D*?)(?P<num>\d[\d,]*(?:\.\d+)?)(?P<suffix>.*)$")


class ParsedNumber(NamedTuple):
    prefix: str
    number: float
    suffix: str
    decimals: int
    commas: bool


def parse_number(value: str) -> ParsedNumber | None:
    match = _NUM_RE.match(value.strip())
    if match is None:
        return None
    raw = match.group("num")
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    return ParsedNumber(
        match.group("prefix"), float(raw.replace(",", "")), match.group("suffix"),
        decimals, "," in raw,
    )


def _format(p: ParsedNumber, x: float) -> str:
    body = f"{x:,.{p.decimals}f}" if p.commas else f"{x:.{p.decimals}f}"
    return f"{p.prefix}{body}{p.suffix}"


def count_up_frames(
    value: str,
    seg_end: float,
    *,
    start: float = _COUNT_START,
    dur: float = _COUNT_DUR,
    fps: int = _FPS,
) -> list[tuple[float, float, str]]:
    """逐幀 (起, 迄, 文字):0 → 目標值(ease-out),最後一幀停到段尾顯示原字串。

    保證三件事:最後一幀文字 == ``value``、每幀 t0 < t1、沒有任何幀超過 ``seg_end``
    (段比動畫短時,動畫在段尾被截斷,最後一幀直接改成定值)。
    """
    if seg_end <= 0:
        return []
    parsed = parse_number(value)
    if parsed is None:
        logger.warning("大數字「{}」解析不了,改靜態顯示", value)
        return [(0.0, seg_end, value)]
    n = max(1, round(dur * fps))
    timeline = [(0.0, start, _format(parsed, 0.0))]
    for k in range(n):
        eased = 1 - (1 - k / n) ** 3
        text = _format(parsed, parsed.number * eased)
        timeline.append((start + k / fps, start + (k + 1) / fps, text))
    timeline.append((start + n / fps, seg_end, value))
    frames = [(t0, min(t1, seg_end), text) for t0, t1, text in timeline if t0 < seg_end]
    frames[-1] = (frames[-1][0], frames[-1][1], value)  # 被段尾截斷時,最後一幀也要是定值
    return frames


def value_font_size(value: str) -> int:
    """大數字字級:整串以 ``line_px`` 量,取 <= 260 且寬度 <= 740px 的最大字級(下限 36)。"""
    unit_px = line_px(value, 1)
    size = _VALUE_FS if unit_px <= 0 else min(_VALUE_FS, int(_TEXT_MAX_W / unit_px))
    while size > FLOOR_SIZE and line_px(value, size) > _TEXT_MAX_W:
        size -= 1  # 浮點誤差的保險:確保真的放得進
    return max(size, FLOOR_SIZE)


def _fit_value(value: str) -> tuple[str, int]:
    """(要顯示的大數字, 字級):縮到 36 還放不下才硬截斷補「…」。"""
    size = value_font_size(value)
    if line_px(value, size) > _TEXT_MAX_W:
        logger.warning("大數字「{}」過長,截斷顯示", value)
        value = shorten(value, size, _TEXT_MAX_W)
    return value, size


def _fit_label(label: str) -> tuple[str, int]:
    """label:單行,放不下先縮字級、到底還放不下補「…」。"""
    lines, size = fit_lines(label, max_width=_TEXT_MAX_W, sizes=(_LABEL_FS,), max_lines=1)
    return "".join(lines), size


def _value_event(t0: float, t1: float, text: str, size: int) -> str:
    """大數字的一幀:固定在中央、不滑入不淡入(逐幀換字,動畫會在每幀重播)。"""
    tags = (
        f"{{\\an5\\pos({_CENTER_X},{_VALUE_Y})\\fs{size}\\1c{ass_color(GOLD_HEX)}\\bord0\\shad0}}"
    )
    return (
        f"Dialogue: 1,{ass_time(t0)},{ass_time(t1)},free,,0,0,0,,{tags}{escape_text(text)}"
    )


class BignumRenderer(SegmentRenderer):
    def render(self, seg: BignumSegment, ctx: RenderContext) -> Visual:
        end = ctx.duration
        events = common_events(end, badge=ctx.badge, cta=ctx.cta)
        label, label_size = _fit_label(seg.label)
        events.append(text_event(0.0, end, _CENTER_X, _LABEL_Y, label, size=label_size,
                                 color=ass_color(_LABEL_HEX), align=5))
        value, value_size = _fit_value(seg.value)
        events += [
            _value_event(t0, t1, text, value_size) for t0, t1, text in count_up_frames(value, end)
        ]
        if seg.context:
            lines, size = fit_lines(seg.context, max_width=_TEXT_MAX_W, sizes=(_CONTEXT_FS,),
                                    max_lines=_CONTEXT_MAX_LINES)
            events.append(text_event(0.0, end, _CENTER_X, _CONTEXT_Y, "\\N".join(lines),
                                     size=size, color=ass_color(WHITE_HEX), align=5))
        events += caption_events(ctx.takes, ctx.starts)
        ass = ASS_TEMPLATE.format(font=ctx.font, events="\n".join(events))
        return Visual(canvas_background(ctx.work_dir), True, ass, "bignum")
