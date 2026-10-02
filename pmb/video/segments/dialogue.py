"""對話框:2–4 句,泡泡隨各自配音逐句彈出(A 角靠左藍、B 角靠右琥珀)。

泡泡句不跑底部字幕(泡泡本身就是字);``vo`` 旁白部分照常卡拉OK字幕。
沒有可發音內容的句子(如「……?」)在句子計畫與畫面兩邊**同一套規則**剔除,泡泡與配音不錯位。
"""

from __future__ import annotations

from typing import NamedTuple

from pmb.schemas.script import DialogueLine, DialogueSegment
from pmb.video.ass import (
    ASS_TEMPLATE,
    CONTENT_TOP,
    FADE_TAG,
    WHITE_HEX,
    ass_color,
    center_block_top,
    common_events,
    full_event,
    rounded_rect,
    shape_event,
    text_event,
    top_layout,
)
from pmb.video.captions import has_speakable, is_beat, strip_beat
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
from pmb.video.textfit import fit_lines, line_px

_SLOT_PITCH = 230  # 相鄰兩個泡泡的間距(角色名頂緣到下一個角色名頂緣)
_MAX_BUBBLES = 4
_LABEL_FS = 40
_LABEL_GAP = 52  # 角色名頂緣到泡泡頂緣
_SIZES = (60, 48)  # 內文字級:先大字,超過 2 行改小字;再長由 fit_lines 續縮、截斷
_MAX_LINES = 2
_PAD = 22
_RADIUS = 26
_LEFT_X = 70
_RIGHT_EDGE = 870  # B 角泡泡右緣(右側 170px 是按讚欄)
_MAX_INNER = (_RIGHT_EDGE - _LEFT_X) - 2 * _PAD  # 泡泡內文最寬 756px:任何泡泡都落在 70..870
_COLORS = {"a": ("#185FA5", "#85B7EB"), "b": ("#854F0B", "#FAC775")}  # (泡泡, 角色名)


def speakable_lines(seg: DialogueSegment) -> list[DialogueLine]:
    """有可發音內容的對話句;句子計畫與畫面共用這一個過濾,泡泡與配音才不會錯位。"""
    return [line for line in seg.lines if has_speakable(strip_beat(line.text))]


def bubble_layout(text: str) -> tuple[list[str], int]:
    """泡泡內文斷行 + 字級(寬度模型與縮字/截斷規則見 ``textfit.fit_lines``)。

    先 60px,超過 2 行改 48px,再長續縮(下限 36px)、最後截成 2 行(尾端「…」);
    英數長串不從中間切,單串自己就超寬才硬切。每行都放得進 ``_MAX_INNER``,
    所以無論輸入為何,泡泡與內文都不會超出 x=870。內文裡的換行先併成空白。
    """
    return fit_lines(text, max_width=_MAX_INNER, sizes=_SIZES, max_lines=_MAX_LINES)


def bubble_tops(heights: list[int], top: int = CONTENT_TOP) -> list[int]:
    """各泡泡的角色名頂緣 y(泡泡框頂緣 = 這個值 + ``_LABEL_GAP``)。

    相鄰泡泡維持固定的 ``_SLOT_PITCH``,整塊(第一個角色名頂緣 → 最後一個泡泡的真實底緣)
    在內容帶裡上下置中:泡泡少就落在畫面中間,不再全擠在上半。``heights`` 是各泡泡框的實際高度，
    ``top`` 是內容帶上緣（有橫幅時要比橫幅底緣低）。
    """
    if not heights:
        return []
    block = (len(heights) - 1) * _SLOT_PITCH + _LABEL_GAP + heights[-1]
    first = center_block_top(block, top)
    return [first + k * _SLOT_PITCH for k in range(len(heights))]


class _Bubble(NamedTuple):
    """一個泡泡的版面:內文斷行、字級與框的寬高(libass 行距 = 字級,文字在框內上下置中)。"""

    line: DialogueLine
    lines: list[str]
    size: int
    w: int
    h: int


def _bubble(line: DialogueLine) -> _Bubble:
    lines, size = bubble_layout(line.text)
    w = int(max(line_px(t, size) for t in lines)) + 2 * _PAD
    return _Bubble(line, lines, size, w, len(lines) * size + 2 * _PAD)


def build_dialogue_ass(seg: DialogueSegment, ctx: RenderContext) -> str:
    """逐句泡泡:角色名 + 圓角框 + 內文,三個事件都從該句配音起點開始顯示到段尾。"""
    layout = top_layout(ctx.banner)
    events: list[str] = []
    if seg.title:
        events.append(full_event(layout.title_style, ctx.duration, FADE_TAG + seg.title))
    events += common_events(ctx.duration, badge=ctx.badge, cta=ctx.cta)
    bubbles = [_bubble(line) for line in speakable_lines(seg)[:_MAX_BUBBLES]]
    tops = bubble_tops([b.h for b in bubbles], layout.content_top)
    for k, (bubble, top) in enumerate(zip(bubbles, tops, strict=True)):
        line, lines, size, w, h = bubble
        start = ctx.starts[k]
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
                       size=size, color=ass_color(WHITE_HEX))
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
