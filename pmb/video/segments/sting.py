"""開場口號轉場:hook 之後約 1 秒的品牌時刻(頻道字樣 + 口號 + 音效)。系統插入,不在 Script 裡。

頻道字樣與口號都可由設定檔改,所以一律以 ``textfit`` 的像素寬度模型排成單行、置中 540,
左右緣保證在 540 ± 370(右緣 910,不碰 Shorts 右側按讚欄);太長先縮字級,縮到底才補「…」。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from pmb.video.ass import (
    ASS_TEMPLATE,
    CENTER_X,
    CENTERED_TEXT_MAX_W,
    GOLD_HEX,
    POP_IN,
    WHITE_HEX,
    ass_color,
    common_events,
    text_event,
)
from pmb.video.segments.base import (
    RenderContext,
    SegmentRenderer,
    Utterance,
    Visual,
    canvas_background,
)
from pmb.video.textfit import fit_one_line

_WORDMARK_Y = 760
_SLOGAN_Y = 920
_WORDMARK_FS = 120
_SLOGAN_FS = 84


class StingSegment(BaseModel):
    kind: Literal["sting"] = "sting"
    text: str  # 口號(settings.slogan_intro)
    channel: str
    sfx: str | None = None  # 音效檔絕對路徑

    @property
    def spoken_text(self) -> str:
        """與腳本段同名的屬性:assemble 記「無可發音內容」時不必分辨段型。"""
        return self.text


def _wordmark_event(end: float, channel: str) -> str:
    """頻道字樣:金色大字置中,原地 pop-in(layer 1,蓋在畫布上)。"""
    text, size = fit_one_line(channel, _WORDMARK_FS, CENTERED_TEXT_MAX_W)
    return text_event(0.0, end, CENTER_X, _WORDMARK_Y, text, size=size,
                      color=ass_color(GOLD_HEX), align=5, move_px=None, effect=POP_IN)


class StingRenderer(SegmentRenderer):
    lead_in = 0.15  # 音效先響,口號晚一拍進
    min_duration = 1.2
    optional = True  # 口號配音失敗就整段略過,影片照出

    def utterances(self, seg: StingSegment) -> list[Utterance]:
        return [Utterance(seg.text, caption=False)]

    def render(self, seg: StingSegment, ctx: RenderContext) -> Visual:
        slogan, slogan_size = fit_one_line(seg.text, _SLOGAN_FS, CENTERED_TEXT_MAX_W)
        events = [
            _wordmark_event(ctx.duration, seg.channel),
            text_event(ctx.starts[0], ctx.duration, CENTER_X, _SLOGAN_Y, slogan,
                       size=slogan_size, color=ass_color(WHITE_HEX), align=5),
        ]
        events += common_events(ctx.duration, badge=ctx.badge, cta=None)
        ass = ASS_TEMPLATE.format(font=ctx.font, events="\n".join(events))
        return Visual(canvas_background(ctx.work_dir), True, ass, "sting", sfx=seg.sfx)
