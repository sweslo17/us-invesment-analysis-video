"""字卡:漸層底 + ASS 大標 pop-in + kicker。"""

from __future__ import annotations

from pmb.charts.cards import accent_for, render_card_background, wrap_card_text
from pmb.schemas.script import CardSegment
from pmb.video.ass import (
    ASS_TEMPLATE,
    BANNER_H,
    BANNER_KICKER_CLEARANCE,
    BANNER_TOP,
    CARD_CENTER_Y,
    CARD_LINE_H,
    CARD_MAX_UNITS,
    FADE_TAG,
    KICKER_GAP,
    KICKER_HALF_H,
    POP_IN,
    common_events,
    full_event,
)
from pmb.video.segments.base import RenderContext, SegmentRenderer, Visual


def build_card_ass(
    headline: str,
    *,
    tag: str | None,
    duration: float,
    font: str,
    badge: str | None = None,
    cta: str | None = None,
    banner: bool = False,
) -> str:
    """組字卡用的 .ass:大標 pop-in(置中)+ 選配 kicker 小標(上方)+ 角標/CTA。

    字卡底圖只有漸層色(``cards.render_card_background``),文字全走這裡,才能動。
    ``banner`` 為真（這張字卡在中段、頂端有金色橫幅）時，大標行數很多會把 kicker 頂進橫幅底下，
    所以 kicker 的 y 往下夾，頂緣至少在橫幅底緣之下 ``BANNER_KICKER_CLEARANCE`` px。
    """
    lines = wrap_card_text(headline, max_units=CARD_MAX_UNITS)
    top = CARD_CENTER_Y - len(lines) * CARD_LINE_H // 2
    pos = f"{{\\an5\\pos(540,{CARD_CENTER_Y})}}"
    events: list[str] = [full_event("card", duration, pos + POP_IN + "\\N".join(lines))]
    if tag:
        kicker_y = top - KICKER_GAP
        if banner:
            banner_bottom = BANNER_TOP + BANNER_H
            kicker_y = max(kicker_y, banner_bottom + BANNER_KICKER_CLEARANCE + KICKER_HALF_H)
        kicker_pos = f"{{\\an5\\pos(540,{kicker_y})}}"
        events.append(full_event("kicker", duration, kicker_pos + FADE_TAG + tag))
    events += common_events(duration, badge=badge, cta=cta)
    return ASS_TEMPLATE.format(font=font, events="\n".join(events))


class CardRenderer(SegmentRenderer):
    def render(self, seg: CardSegment, ctx: RenderContext) -> Visual:
        name = f"card{ctx.index}.png"
        render_card_background(str(ctx.work_dir / name), accent=accent_for(ctx.index))
        ass = build_card_ass(
            seg.headline, tag=seg.tag, duration=ctx.duration, font=ctx.font,
            badge=ctx.badge, cta=ctx.cta, banner=ctx.banner,
        )
        return Visual(name, True, ass, "card")
