"""圖表段:圖表框 + 頂部標題 + 大數字 callout + 逐頁卡拉OK字幕。"""

from __future__ import annotations

from pmb.schemas.script import ChartSegment
from pmb.video.ass import (
    ASS_TEMPLATE,
    FADE_TAG,
    POP_IN,
    common_events,
    full_event,
    top_layout,
)
from pmb.video.segments.base import (
    RenderContext,
    SegmentRenderer,
    Take,
    Visual,
    caption_events,
    take_starts,
)


def build_segment_ass(
    takes: list[Take],
    seg_duration: float,
    *,
    title: str | None,
    font: str,
    stat: str | None = None,
    stat_label: str | None = None,
    badge: str | None = None,
    cta: str | None = None,
    starts: list[float] | None = None,
    title_style: str = "title",
) -> str:
    """組圖表段用的 .ass:逐頁卡拉OK字幕(含句間偏移)+ 頂部標題 + 大數字 callout + 角標/CTA。

    callout(``stat``/``stat_label``)疊在圖表下方的留白處,是手機上一眼能抓到的重點數字;
    沒給就不畫,舊 script 相容。``starts`` 沒給就依各句停頓自行累算。``title_style`` 是標題的
    ASS 樣式(有橫幅時用縮小下移的 ``title_b``)。
    """
    events: list[str] = []
    if title:
        events.append(full_event(title_style, seg_duration, FADE_TAG + title))
    if stat:
        if stat_label:
            events.append(full_event("statlabel", seg_duration, FADE_TAG + stat_label))
        events.append(full_event("stat", seg_duration, POP_IN + stat))
    events += common_events(seg_duration, badge=badge, cta=cta)
    events += caption_events(takes, starts if starts is not None else take_starts(takes))
    return ASS_TEMPLATE.format(font=font, events="\n".join(events))


class ChartRenderer(SegmentRenderer):
    def render(self, seg: ChartSegment, ctx: RenderContext) -> Visual:
        layout = top_layout(ctx.banner)
        ass = build_segment_ass(
            ctx.takes, ctx.duration, title=seg.title, font=ctx.font, stat=seg.stat,
            stat_label=seg.stat_label, badge=ctx.badge, cta=ctx.cta, starts=ctx.starts,
            title_style=layout.title_style,
        )
        return Visual(ctx.chart_paths[seg.chart_id], False, ass, "seg",
                      chart_box=(layout.content_top, layout.chart_box_h))
