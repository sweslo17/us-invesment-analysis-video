"""好壞消息:上下兩格色塊。上格段首出現,下格在旁白第 2 句開始時出現(冷面反差的主場)。"""

from __future__ import annotations

from loguru import logger

from pmb.schemas.script import Panel, SplitSegment
from pmb.video.ass import (
    ASS_TEMPLATE,
    FADE_TAG,
    GOLD_HEX,
    ass_color,
    common_events,
    full_event,
    rounded_rect,
    shape_event,
    text_event,
)
from pmb.video.captions import wrap_lines
from pmb.video.segments.base import (
    RenderContext,
    SegmentRenderer,
    Visual,
    canvas_background,
    caption_events,
)

_X = 60
_W = 830  # 右緣 890,避開右側按讚欄
_TOPS = (290, 800)
_H = 470
_RADIUS = 28
_INSET = 40
_LABEL_FS = 48
_STAT_FS = 100
# (字級, 最多行數):有 stat 時字要讓位給數字
_LAYOUTS_WITH_STAT = ((96, 1), (80, 2))
_LAYOUTS_NO_STAT = ((96, 2), (80, 2))
_TONES = {  # (底色, 標籤色)
    "good": ("#173404", "#97C459"),
    "bad": ("#501313", "#F09595"),
    "neutral": ("#0C447C", "#85B7EB"),
}
_TEXT_HEX = "#FFFFFF"


def panel_text_layout(text: str, *, has_stat: bool) -> tuple[list[str], int]:
    """格子內文斷行 + 字級;都放不下就用最小字級截成允許的行數。"""
    layouts = _LAYOUTS_WITH_STAT if has_stat else _LAYOUTS_NO_STAT
    for size, max_lines in layouts:
        lines = wrap_lines(text, int((_W - 2 * _INSET) / size))
        if len(lines) <= max_lines:
            return lines, size
    size, max_lines = layouts[-1]
    logger.warning("好壞消息格子文字過長,截斷:{}", text)
    return wrap_lines(text, int((_W - 2 * _INSET) / size))[:max_lines], size


def reveal_times(ctx: RenderContext) -> tuple[float, float]:
    """上格段首;下格在第 2 句起點,只有 1 句就在段長一半。"""
    bottom = ctx.starts[1] if len(ctx.starts) >= 2 else ctx.duration * 0.5
    return 0.0, bottom


def _panel_events(panel: Panel, top: int, start: float, end: float) -> list[str]:
    bg_hex, label_hex = _TONES[panel.tone]
    events = [
        shape_event(start, end, _X, top, rounded_rect(_W, _H, _RADIUS), ass_color(bg_hex)),
        text_event(start, end, _X + _INSET, top + 36, panel.label, size=_LABEL_FS,
                   color=ass_color(label_hex)),
    ]
    lines, size = panel_text_layout(panel.text, has_stat=bool(panel.stat))
    events.append(text_event(start, end, _X + _INSET, top + 110, "\\N".join(lines), size=size,
                             color=ass_color(_TEXT_HEX)))
    if panel.stat:
        events.append(text_event(start, end, _X + _INSET, top + _H - 24, panel.stat,
                                 size=_STAT_FS, color=ass_color(GOLD_HEX), align=1))
    return events


class SplitRenderer(SegmentRenderer):
    def render(self, seg: SplitSegment, ctx: RenderContext) -> Visual:
        events: list[str] = []
        if seg.title:
            events.append(full_event("title", ctx.duration, FADE_TAG + seg.title))
        events += common_events(ctx.duration, badge=ctx.badge, cta=ctx.cta)
        top_at, bottom_at = reveal_times(ctx)
        events += _panel_events(seg.top, _TOPS[0], top_at, ctx.duration)
        events += _panel_events(seg.bottom, _TOPS[1], bottom_at, ctx.duration)
        events += caption_events(ctx.takes, ctx.starts)
        ass = ASS_TEMPLATE.format(font=ctx.font, events="\n".join(events))
        return Visual(canvas_background(ctx.work_dir), True, ass, "split")
