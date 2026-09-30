"""文字排版的唯一寬度模型:量字寬、依像素斷行、在格子裡縮字級或截斷。

所有需要「文字放進固定寬度的框」的段型(對話泡泡、好壞消息格子…)都用這裡,不各自估寬。
底部字幕的斷行仍在 ``captions``(以「字寬單位」估、不講像素,用途不同)。
"""

from __future__ import annotations

import re

from loguru import logger

from pmb.video.captions import BREAK_AFTER

# 中日韓全形字在 libass 裡的實際字寬 = 字級 × 0.713。實測:PingFang TC、Bold、fs=60,
# 15 個「測」與 5 個「測」的墨跡寬差 / 10 = 42.8px;libass 的 \fs 是行高,不是 em,所以不是 1.0。
# 換字型(VIDEO_FONT)要重新量。
CJK_EM = 0.713
_WIDE_ASCII = "%&@MWmw"  # 實測比一般英數寬的字元(約 0.8–1.0 個全形字)
_NARROW_ASCII = ".,:;'!()ijl|"  # 實測只有約 0.25–0.35 個全形字(空白沒量,維持保守)
_ESCAPED_ASCII = "{}"  # ass.text_event 會把花括號轉成全形,照全形字寬算

FLOOR_SIZE = 36  # 縮字級的下限
SIZE_STEP = 4
ELLIPSIS = "…"
_BREAK_PREFERENCE = 0.55  # 行寬超過這個比例,遇到標點就先斷行(不硬塞到滿)
# 斷行單位:連續的英數/小數/百分比(7747、1.06%、VIX)算一個字詞,盡量不從中間切;其餘一個字一單位
_TOKEN_RE = re.compile(r"[+\-$]?[A-Za-z0-9]+(?:[.,][A-Za-z0-9]+)*%?|\s|.", re.DOTALL)


def glyph_units(ch: str) -> float:
    """單字寬度(全形字 = 1)。英文大寫/數字/少數寬符號比 ``captions.char_units`` 的 0.55 寬
    (PingFang TC 實測:大寫約 0.65–0.75、數字 0.6、``%`` 約 1.0),標點與細字母則窄很多;
    其餘維持保守估寬,框才包得住字又不至於留太多空。"""
    if not ch.isascii() or ch in _ESCAPED_ASCII:
        return 1.0
    if ch in _WIDE_ASCII:
        return 0.95
    if ch in _NARROW_ASCII:
        return 0.35
    return 0.7 if ch.isupper() or ch.isdigit() else 0.55


def line_px(text: str, size: int) -> float:
    """一行文字在 ``size`` 字級下的估計像素寬。"""
    return sum(glyph_units(ch) for ch in text) * size * CJK_EM


def _fit_prefix(text: str, size: int, max_width: float) -> str:
    """放得進 ``max_width`` 的最長前綴(至少 1 個字,避免無窮迴圈)。"""
    k = 1
    while k < len(text) and line_px(text[: k + 1], size) <= max_width:
        k += 1
    return text[:k]


def wrap_px(text: str, size: int, max_width: float) -> list[str]:
    """依像素寬度斷行,每行(去尾端空白後)都不超過 ``max_width``。

    沿用 ``captions.wrap_lines`` 的偏好:行寬過半後遇標點就斷;英數串不從中間切,
    放不進當行就整串移到下一行,只有單一串自己就超寬時才硬切。行首不留空白。
    """
    lines: list[str] = []
    cur = ""
    for tok in _TOKEN_RE.findall(text):
        if not cur and tok.isspace():
            continue
        if line_px((cur + tok).rstrip(), size) > max_width:
            if cur.strip():
                lines.append(cur.rstrip())
            cur = ""
            if tok.isspace():
                continue
            while len(tok) > 1 and line_px(tok, size) > max_width:
                head = _fit_prefix(tok, size, max_width)
                lines.append(head)
                tok = tok[len(head) :]
        cur += tok
        if tok[-1] in BREAK_AFTER and line_px(cur, size) >= max_width * _BREAK_PREFERENCE:
            lines.append(cur.rstrip())
            cur = ""
    if cur.strip():
        lines.append(cur.rstrip())
    return lines


def shorten(line: str, size: int, max_width: float) -> str:
    """從尾巴砍字、補「…」到放得進 ``max_width``(結果一定以「…」結尾)。"""
    base = line.rstrip(ELLIPSIS).rstrip()
    while base and line_px(base + ELLIPSIS, size) > max_width:
        base = base[:-1]
    return base + ELLIPSIS


def fit_lines(
    text: str,
    *,
    max_width: int,
    sizes: tuple[int, ...],
    max_lines: int,
    floor: int = FLOOR_SIZE,
) -> tuple[list[str], int]:
    """把文字放進 ``max_width`` × ``max_lines`` 的框:回傳 (斷行結果, 字級)。

    先壓縮空白(換行併成空白,斷行只由寬度決定);依序試 ``sizes``(由大到小)、再每次縮
    ``SIZE_STEP`` 直到 ``floor``,第一個行數放得下的字級就用;全部都放不下,在最小字級截成
    ``max_lines`` 行、尾端補「…」。保證每一行 ``line_px(line, size) <= max_width``
    (只要最小字級放得下單一全形字)。
    """
    text = " ".join(text.split())
    smallest = min(sizes)
    candidates = [*sizes, *range(smallest - SIZE_STEP, floor - 1, -SIZE_STEP)]
    for size in candidates:
        lines = wrap_px(text, size, max_width)
        if len(lines) <= max_lines:
            return lines, size
    size = candidates[-1]
    logger.warning("文字過長,截斷為 {} 行:{}", max_lines, text)
    lines = wrap_px(text, size, max_width)[:max_lines]
    lines[-1] = shorten(lines[-1], size, max_width)
    return lines, size
