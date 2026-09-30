"""好壞消息:上下兩格色塊。上格段首出現,下格在旁白第 2 句開始時出現(冷面反差的主場)。"""

from __future__ import annotations

from pmb.schemas.script import Panel, SplitSegment
from pmb.video.ass import (
    ASS_TEMPLATE,
    FADE_TAG,
    GOLD_HEX,
    WHITE_HEX,
    ass_color,
    common_events,
    full_event,
    rounded_rect,
    shape_event,
    text_event,
)
from pmb.video.segments.base import (
    RenderContext,
    SegmentRenderer,
    Visual,
    canvas_background,
    caption_events,
)
from pmb.video.textfit import fit_lines, line_px

_X = 60
_W = 830  # 右緣 890,避開右側按讚欄
_TOPS = (290, 800)
_H = 470
_RADIUS = 28
_INSET = 40
_INNER_W = _W - 2 * _INSET  # 格內文字最寬 750px:任何文字都落在 x=100..850
_LABEL_FS = 48
_STAT_FS = 100
_BODY_SIZES = (96, 80)
_BODY_MAX_LINES = 2
_TONES = {  # (底色, 標籤色)
    "good": ("#173404", "#97C459"),
    "bad": ("#501313", "#F09595"),
    "neutral": ("#0C447C", "#85B7EB"),
}


def panel_text_layout(text: str, *, has_stat: bool) -> tuple[list[str], int]:
    """格子內文斷行 + 字級:放不下先縮字級,縮到底還是放不下就截成 2 行並補「…」。

    沒有大數字:96px → 80px,最多 2 行。有大數字:內文要讓位給數字,只有 96px 一行放得下才
    用大字;否則直接 80px、最多 2 行(2 行 80px 離大數字頂緣仍有空隙),再放不下才縮字級/截斷。
    """
    if not has_stat:
        return fit_lines(text, max_width=_INNER_W, sizes=_BODY_SIZES, max_lines=_BODY_MAX_LINES)
    large, small = _BODY_SIZES
    flat = " ".join(text.split())
    if line_px(flat, large) <= _INNER_W:  # 量整段寬度,不走 wrap_px 的標點斷行偏好
        return ([flat] if flat else []), large
    return fit_lines(text, max_width=_INNER_W, sizes=(small,), max_lines=_BODY_MAX_LINES)


def _fit_one_line(text: str, size: int) -> tuple[str, int]:
    """標籤/大數字:單行,放不下先縮字級、到底還放不下補「…」。"""
    lines, fitted = fit_lines(text, max_width=_INNER_W, sizes=(size,), max_lines=1)
    return "".join(lines), fitted


def reveal_times(ctx: RenderContext) -> tuple[float, float]:
    """上格段首;下格在第 2 句起點,只有 1 句就在段長一半。"""
    bottom = ctx.starts[1] if len(ctx.starts) >= 2 else ctx.duration * 0.5
    return 0.0, bottom


def _panel_events(panel: Panel, top: int, start: float, end: float) -> list[str]:
    bg_hex, label_hex = _TONES[panel.tone]
    label, label_size = _fit_one_line(panel.label, _LABEL_FS)
    lines, size = panel_text_layout(panel.text, has_stat=bool(panel.stat))
    events = [
        shape_event(start, end, _X, top, rounded_rect(_W, _H, _RADIUS), ass_color(bg_hex)),
        text_event(start, end, _X + _INSET, top + 36, label, size=label_size,
                   color=ass_color(label_hex)),
        text_event(start, end, _X + _INSET, top + 110, "\\N".join(lines), size=size,
                   color=ass_color(WHITE_HEX)),
    ]
    if panel.stat:
        stat, stat_size = _fit_one_line(panel.stat, _STAT_FS)
        events.append(text_event(start, end, _X + _INSET, top + _H - 24, stat,
                                 size=stat_size, color=ass_color(GOLD_HEX), align=1))
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
