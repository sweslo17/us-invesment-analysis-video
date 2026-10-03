"""YouTube 封面（自訂縮圖）：直式 1080×1920 版面，用 libass 經 ffmpeg 渲染。

每支影片一張封面，直式 9:16 與影片同比例。文字量寬與斷行走 ``pmb.video.textfit``、色塊與文字事件走
``pmb.video.ass``，和影片內的畫面同一套字型引擎。

版面（px，全部置中）：頂部品牌行「頻道 · 日期 盤前」；中間 kicker（金）疊在大標（白，粗體，
最多三行）上方；有大數字時下方放深藍框（標籤灰藍、數字金），大標上移讓出位置；1500 以下是一條
比底色深的色條，不放字，墊在手機網格疊上來的影片標題底下。所有關鍵文字底緣都在 1500 之上。
背景色是日期對應的調色盤顏色，連續兩天不同。
"""

from __future__ import annotations

import datetime as dt
import tempfile
from pathlib import Path
from typing import NamedTuple

from loguru import logger

from pmb.charts.cards import accent_for
from pmb.schemas.script import Script
from pmb.textnorm import zh_punct
from pmb.video.ass import (
    BG_HEX,
    FREE_STYLE,
    GOLD_HEX,
    MUTED_HEX,
    WHITE_HEX,
    ass_color,
    ass_template,
    rounded_rect,
    shape_event,
    text_event,
)
from pmb.video.assemble import _run_ffmpeg
from pmb.video.textfit import fit_authored_lines, fit_one_line

COVER_W, COVER_H = 1080, 1920
COVER_ASS_TEMPLATE = ass_template(COVER_W, COVER_H, [FREE_STYLE])  # 封面只用 free 樣式
COVER_ASS_NAME = "cover.ass"  # 暫存目錄內的檔名
_SHOWN_SEC = 1.0  # 只輸出一格，事件蓋過這一格就好
_STRIP_DARKEN = 0.55  # 底部條 = 底色逐通道 ×0.55（與 cards._gradient 的底端同比例）

_CENTER_X = COVER_W // 2  # 所有文字與深藍框都以這條中線置中
_TEXT_MAX_W = 940  # 品牌行、kicker、大標的最大寬度：x 70..1010，左右邊距各 70
# 底部條：全寬、貼底，不放字；手機網格把影片標題疊在縮圖底部約四分之一，這條當深色底
_STRIP_TOP = 1500
_STRIP_H = COVER_H - _STRIP_TOP
# 品牌行（頂部，頂緣對齊）
_BRAND_SIZE, _BRAND_Y = 52, 130
# 大標（置中，粗體來自 free 樣式）：有大數字框時上移，沒有時落在畫面中間偏上
_HEADLINE_SIZES = (150, 132, 116, 100)
_HEADLINE_MAX_LINES = 3
_HEADLINE_Y_WITH_STAT, _HEADLINE_Y_BARE = 640, 820
# kicker（底緣對齊）：底緣在大標頂緣之上 _KICKER_GAP
_KICKER_SIZE, _KICKER_GAP = 64, 40
# 大數字框（置中）
_BOX_X, _BOX_Y, _BOX_W, _BOX_H, _BOX_RADIUS = 120, 960, 840, 440, 36
_BOX_TEXT_MAX_W = 760
_LABEL_SIZE, _LABEL_Y = 64, 1050
_VALUE_SIZE = 220
_VALUE_Y_LABELED, _VALUE_Y_BARE = 1230, 1180  # 沒標籤時數字上移到框內中間


class CoverSpec(NamedTuple):
    """封面內容：大標、kicker、大數字（含標籤）、日期（決定底色與底部條的日期文字）。"""

    headline: str
    kicker: str | None
    stat: str | None
    stat_label: str | None
    date: dt.date


def cover_spec(script: Script, date: dt.date) -> CoverSpec | None:
    """決定封面內容：開場鉤子字卡的大標與 kicker，配第一個帶大數字的段落（有就用）。

    大數字取各段 ``display_stats`` 依段落順序的第一組（標籤, 數字）：圖表段 stat、全屏大數字、
    好壞消息格子；對帳結果不算。封面是公開圖片，所有文字在出口做半形標點轉全形。
    沒有字卡（沒有鉤子）就回 None。
    """
    hook = script.hook()
    if hook is None:
        return None
    _, card = hook
    label, stat = next(
        (pair for seg in script.segments for pair in seg.display_stats[:1]), (None, None)
    )
    return CoverSpec(
        headline=zh_punct(card.headline),
        kicker=zh_punct(card.tag) if card.tag else None,
        stat=zh_punct(stat) if stat else None,
        stat_label=zh_punct(label) if label else None,
        date=date,
    )


def cover_accent(date: dt.date) -> str:
    """當天封面的底色（``#RRGGBB``）：以日期序數取調色盤，連續兩天一定不同色。"""
    return accent_for(date.toordinal())


def _darken(hex_rgb: str, factor: float) -> str:
    """``#RRGGBB`` 逐通道乘 ``factor``、四捨五入成整數，回 ``#RRGGBB``。"""
    h = hex_rgb.lstrip("#")
    r, g, b = (round(int(h[i : i + 2], 16) * factor) for i in (0, 2, 4))
    return f"#{r:02X}{g:02X}{b:02X}"


def build_cover_ass(spec: CoverSpec, font: str, *, channel: str = "美股早發車") -> str:
    """封面的完整 .ass：底部條、品牌行、大標、kicker、（有大數字時）深藍框 + 標籤 + 數字。

    全部是靜態事件（``move_px=None``）。文字一律先過 ``textfit`` 擬合：大標依寬度縮字級／斷行
    （保留作者自己的換行，最多三行），其餘單行文字放不下就縮字級、再放不下才截斷，所以每個文字
    事件都在 x 70..1010 內、底緣在 1500 之上。底色不在 ASS 裡，由 ``render_cover`` 交給 ffmpeg 的
    色源。
    """
    end = _SHOWN_SEC
    events: list[str] = []

    def text(y: int, body: str, size: int, color_hex: str, align: int) -> None:
        events.append(
            text_event(
                0.0, end, _CENTER_X, y, body, size=size, color=ass_color(color_hex), align=align,
                move_px=None,
            )
        )

    events.append(
        shape_event(
            0.0, end, 0, _STRIP_TOP, rounded_rect(COVER_W, _STRIP_H, 0),
            ass_color(_darken(cover_accent(spec.date), _STRIP_DARKEN)), move_px=None,
        )
    )
    brand, brand_size = fit_one_line(
        f"{channel} · {spec.date.month}/{spec.date.day} 盤前", _BRAND_SIZE, _TEXT_MAX_W
    )
    text(_BRAND_Y, brand, brand_size, WHITE_HEX, 8)

    headline_y = _HEADLINE_Y_WITH_STAT if spec.stat else _HEADLINE_Y_BARE
    lines, size = fit_authored_lines(
        spec.headline, max_width=_TEXT_MAX_W, sizes=_HEADLINE_SIZES, max_lines=_HEADLINE_MAX_LINES
    )
    if lines:
        text(headline_y, "\\N".join(lines), size, WHITE_HEX, 5)
    if spec.kicker:
        kicker, kicker_size = fit_one_line(spec.kicker, _KICKER_SIZE, _TEXT_MAX_W)
        kicker_bottom = headline_y - len(lines) * size // 2 - _KICKER_GAP  # 大標頂緣再往上
        text(kicker_bottom, kicker, kicker_size, GOLD_HEX, 2)

    if spec.stat:
        events.append(
            shape_event(
                0.0, end, _BOX_X, _BOX_Y, rounded_rect(_BOX_W, _BOX_H, _BOX_RADIUS),
                ass_color(BG_HEX), move_px=None,
            )
        )
        if spec.stat_label:
            label, label_size = fit_one_line(spec.stat_label, _LABEL_SIZE, _BOX_TEXT_MAX_W)
            text(_LABEL_Y, label, label_size, MUTED_HEX, 5)
        value, value_size = fit_one_line(spec.stat, _VALUE_SIZE, _BOX_TEXT_MAX_W)
        text(_VALUE_Y_LABELED if spec.stat_label else _VALUE_Y_BARE, value, value_size, GOLD_HEX, 5)

    return COVER_ASS_TEMPLATE.format(font=font, events="\n".join(events))


def render_cover(
    spec: CoverSpec, out_path: str | Path, *, font: str, channel: str = "美股早發車"
) -> Path:
    """渲染封面 PNG（1080×1920）並回傳絕對路徑；ffmpeg 失敗就拋 ``RuntimeError``。

    ASS 寫進暫存目錄、ffmpeg 以該目錄為工作目錄（``subtitles=`` 吃相對檔名，路徑不必跳脫）；
    底色用 ``color=`` 色源，所以輸出路徑要先轉成絕對路徑。
    """
    out = Path(out_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    accent = cover_accent(spec.date).lstrip("#")
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / COVER_ASS_NAME).write_text(
            build_cover_ass(spec, font, channel=channel), encoding="utf-8"
        )
        _run_ffmpeg(
            [
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", f"color=c=0x{accent}:s={COVER_W}x{COVER_H}:d=1",
                "-vf", f"subtitles={COVER_ASS_NAME}",
                "-frames:v", "1", str(out),
            ],
            cwd=work,
        )
    logger.info("封面已輸出：{}", out)
    return out
