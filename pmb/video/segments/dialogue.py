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
from pmb.video.captions import has_speakable, is_beat, strip_beat, wrap_lines
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
_SIZES = (60, 48)  # 內文字級:先大字,超過 2 行改小字
_MIN_SIZE = 36  # 不可斷的長英數串把字級壓到這裡為止
_SIZE_STEP = 4
_PAD = 22
_RADIUS = 26
_LEFT_X = 70
_RIGHT_EDGE = 870  # B 角泡泡右緣(右側 170px 是按讚欄)
_MAX_INNER = (_RIGHT_EDGE - _LEFT_X) - 2 * _PAD  # 泡泡內文最寬 756px:任何泡泡都落在 70..870
# 中日韓全形字在 libass 裡的實際字寬 = 字級 × 0.713。實測:PingFang TC、Bold、fs=60,
# 15 個「測」與 5 個「測」的墨跡寬差 / 10 = 42.8px;libass 的 \fs 是行高,不是 em,所以不是 1.0。
# 換字型(VIDEO_FONT)要重新量。
_CJK_EM = 0.713
_COLORS = {"a": ("#185FA5", "#85B7EB"), "b": ("#854F0B", "#FAC775")}  # (泡泡, 角色名)
_TEXT_HEX = "#FFFFFF"
_WIDE_ASCII = "%&@MWmw"  # 實測比一般英數寬的字元(約 0.8–1.0 個全形字)
_NARROW_ASCII = ".,:;'!()ijl|"  # 實測只有約 0.25–0.35 個全形字(空白沒量,維持保守)


def speakable_lines(seg: DialogueSegment) -> list[DialogueLine]:
    """有可發音內容的對話句;句子計畫與畫面共用這一個過濾,泡泡與配音才不會錯位。"""
    return [line for line in seg.lines if has_speakable(strip_beat(line.text))]


def _char_units(ch: str) -> float:
    """單字寬度(全形字 = 1)。英文大寫/數字/少數寬符號比 ``captions.char_units`` 的 0.55 寬
    (PingFang TC 實測:大寫約 0.65–0.75、數字 0.6、``%`` 約 1.0),標點與細字母則窄很多;
    其餘維持保守估寬,框才包得住字又不至於留太多空。"""
    if not ch.isascii():
        return 1.0
    if ch in _WIDE_ASCII:
        return 0.95
    if ch in _NARROW_ASCII:
        return 0.35
    return 0.7 if ch.isupper() or ch.isdigit() else 0.55


def _line_px(line: str, size: int) -> float:
    """一行文字在 ``size`` 字級下的估計像素寬。"""
    return sum(_char_units(ch) for ch in line) * size * _CJK_EM


def _wrap(text: str, size: int) -> list[str]:
    """依泡泡內文最大寬度斷行。``wrap_lines`` 是「寬度到了才斷」,一行最多超過容量 1 個字寬,
    所以容量先扣 1,保證一般文字斷出來的每行都放得進 ``_MAX_INNER``。"""
    return wrap_lines(text, _MAX_INNER / (size * _CJK_EM) - 1)


def _shorten(line: str, size: int) -> str:
    """連下限字級都放不進的行:從尾巴砍字、補「…」到放得進。"""
    base = line.rstrip("…").rstrip()
    while base and _line_px(base + "…", size) > _MAX_INNER:
        base = base[:-1]
    return base + "…"


def bubble_layout(text: str) -> tuple[list[str], int]:
    """泡泡內文斷行 + 字級。

    先 60px,超過 2 行改 48px,仍超過截成 2 行(尾端「…」)。``wrap_lines`` 不會從中間切英數串,
    最寬行放不進 ``_MAX_INNER`` 時再一路縮字級(下限 ``_MIN_SIZE``);還是放不進就硬砍,
    所以無論輸入為何,泡泡與內文都不會超出 x=870。內文裡的換行先併成空白(斷行只由寬度決定)。
    """
    text = " ".join(text.split())
    for size in _SIZES:
        lines = _wrap(text, size)
        if len(lines) <= 2:
            break
    else:
        logger.warning("對話泡泡過長,截成兩行:{}", text)
        lines = [lines[0], _shorten(lines[1], size)]
    while size > _MIN_SIZE and max(_line_px(ln, size) for ln in lines) > _MAX_INNER:
        size = max(size - _SIZE_STEP, _MIN_SIZE)
        lines = _wrap(text, size)
        if len(lines) > 2:
            lines = [lines[0], _shorten(lines[1], size)]
    if any(_line_px(ln, size) > _MAX_INNER for ln in lines):
        logger.warning("對話泡泡單行過寬,硬砍到放得進:{}", text)
        lines = [ln if _line_px(ln, size) <= _MAX_INNER else _shorten(ln, size) for ln in lines]
    return lines, size


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
        w = int(max(_line_px(t, size) for t in lines)) + 2 * _PAD
        h = len(lines) * size + 2 * _PAD  # libass 行距 = 字級,文字在框內上下置中
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
