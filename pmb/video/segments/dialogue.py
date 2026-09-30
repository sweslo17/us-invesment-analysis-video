"""對話框:2–4 句,泡泡隨各自配音逐句彈出(A 角靠左藍、B 角靠右琥珀)。

泡泡句不跑底部字幕(泡泡本身就是字);``vo`` 旁白部分照常卡拉OK字幕。
沒有可發音內容的句子(如「……?」)在句子計畫與畫面兩邊**同一套規則**剔除,泡泡與配音不錯位。
"""

from __future__ import annotations

from loguru import logger

from pmb.schemas.script import DialogueLine, DialogueSegment
from pmb.video.ass import (
    ASS_TEMPLATE,
    FADE_TAG,
    ass_color,
    common_events,
    full_event,
    rounded_rect,
    shape_event,
    text_event,
)
from pmb.video.captions import has_speakable, is_beat, strip_beat, text_units, wrap_lines
from pmb.video.segments.base import (
    BEAT_GAP,
    GAP,
    RenderContext,
    SegmentRenderer,
    Utterance,
    Visual,
    canvas_background,
    caption_events,
    plan_vo,
)

_SLOT_TOPS = (300, 530, 760, 990)  # 4 個固定槽位的頂緣(每槽約 230px)
_LABEL_FS = 40
_LABEL_GAP = 52  # 角色名頂緣到泡泡頂緣
_BUBBLE_LAYOUTS = ((60, 12), (48, 15))  # (字級, 每行字寬):先大字,超過 2 行改小字
_PAD = 22
_RADIUS = 26
_LEFT_X = 70
_RIGHT_EDGE = 870  # B 角泡泡右緣(右側 170px 是按讚欄)
_COLORS = {"a": ("#185FA5", "#85B7EB"), "b": ("#854F0B", "#FAC775")}  # (泡泡, 角色名)
_TEXT_HEX = "#FFFFFF"


def speakable_lines(seg: DialogueSegment) -> list[DialogueLine]:
    """有可發音內容的對話句;句子計畫與畫面共用這一個過濾,泡泡與配音才不會錯位。"""
    return [line for line in seg.lines if has_speakable(strip_beat(line.text))]


def bubble_layout(text: str) -> tuple[list[str], int]:
    """泡泡內文斷行 + 字級:60px 每行 12 字寬;超過 2 行改 48px 每行 15 字寬;仍超過截成 2 行。"""
    for size, units in _BUBBLE_LAYOUTS:
        lines = wrap_lines(text, units)
        if len(lines) <= 2:
            return lines, size
    size, units = _BUBBLE_LAYOUTS[-1]
    lines = wrap_lines(text, units)
    logger.warning("對話泡泡過長,截成兩行:{}", text)
    return [lines[0], lines[1].rstrip() + "…"], size


def build_dialogue_ass(seg: DialogueSegment, ctx: RenderContext) -> str:
    """逐句泡泡:角色名 + 圓角框 + 內文,三個事件都從該句配音起點開始顯示到段尾。"""
    events: list[str] = []
    if seg.title:
        events.append(full_event("title", ctx.duration, FADE_TAG + seg.title))
    events += common_events(ctx.duration, badge=ctx.badge, cta=ctx.cta)
    for k, line in enumerate(speakable_lines(seg)[: len(_SLOT_TOPS)]):
        start = ctx.starts[k]
        top = _SLOT_TOPS[k]
        lines, size = bubble_layout(line.text)
        w = int(max(text_units(t) for t in lines) * size) + 2 * _PAD
        h = len(lines) * int(size * 1.2) + 2 * _PAD
        x = _LEFT_X if line.voice == "a" else _RIGHT_EDGE - w
        bubble_hex, label_hex = _COLORS[line.voice]
        label_x, label_align = (x, 7) if line.voice == "a" else (x + w, 9)
        events.append(
            text_event(start, ctx.duration, label_x, top, line.speaker, size=_LABEL_FS,
                       color=ass_color(label_hex), align=label_align)
        )
        events.append(
            shape_event(start, ctx.duration, x, top + _LABEL_GAP, rounded_rect(w, h, _RADIUS),
                        ass_color(bubble_hex))
        )
        events.append(
            text_event(start, ctx.duration, x + _PAD, top + _LABEL_GAP + _PAD, "\\N".join(lines),
                       size=size, color=ass_color(_TEXT_HEX))
        )
    events += caption_events(ctx.takes, ctx.starts)
    return ASS_TEMPLATE.format(font=ctx.font, events="\n".join(events))


class DialogueRenderer(SegmentRenderer):
    def utterances(self, seg: DialogueSegment) -> list[Utterance]:
        lines = [
            Utterance(line.text, line.voice, BEAT_GAP if is_beat(line.text) else GAP, False)
            for line in speakable_lines(seg)
        ]
        return lines + plan_vo(seg.vo)

    def render(self, seg: DialogueSegment, ctx: RenderContext) -> Visual:
        return Visual(canvas_background(ctx.work_dir), True, build_dialogue_ass(seg, ctx),
                      "dialogue")
