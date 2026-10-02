"""今日標題橫幅:金底深字的圓角框,疊在每個中段畫面的頂端。

YouTube 的直式縮圖是從影片中段自動挑的一格(API 不能指定),橫幅讓任何一格看起來都像封面。
橫幅內容整支片不變,所以只產一份 ``banner.ass``(長度蓋過全片),不放進各段自己的 ASS。
位置與尺寸常數在 ``pmb.video.ass``,文字斷行走 ``textfit``。
"""

from __future__ import annotations

from pmb.video.ass import (
    ASS_TEMPLATE,
    BANNER_H,
    BANNER_MAX_LINES,
    BANNER_RADIUS,
    BANNER_SIZES,
    BANNER_TOP,
    BANNER_W,
    BANNER_X,
    BG_HEX,
    CENTER_X,
    CENTERED_TEXT_MAX_W,
    GOLD_HEX,
    ass_color,
    rounded_rect,
    shape_event,
    text_event,
)
from pmb.video.textfit import fit_authored_lines

BANNER_ASS = "banner.ass"  # work_dir 內的檔名(一支片共用一份)
_FOREVER = 3600.0  # 橫幅事件的結束秒數(1 小時):遠大於任何一段的長度,等同全程顯示


def banner_layout(headline: str) -> tuple[list[str], int]:
    """標題斷行 + 字級:保留作者自己的換行,放不進 740px 才縮字級(88 → 76 → 66)或重排,
    最多 2 行。每行都落在 x=170..910 之內,不碰 Shorts 右側按讚欄。"""
    return fit_authored_lines(
        headline,
        max_width=CENTERED_TEXT_MAX_W,
        sizes=BANNER_SIZES,
        max_lines=BANNER_MAX_LINES,
    )


def build_banner_ass(headline: str, font: str) -> str:
    """橫幅的完整 .ass:金色圓角底框 + 置中的深色標題,兩個事件都是靜態、全長顯示。

    ``headline`` 是 hook 字卡的大標(可含 ``\\n``);轉義交給 ``text_event``。框高固定
    ``BANNER_H``,一行標題在框內垂直置中(``\\an5`` 錨在框的正中)。
    """
    lines, size = banner_layout(headline)
    events = [
        shape_event(
            0.0, _FOREVER, BANNER_X, BANNER_TOP,
            rounded_rect(BANNER_W, BANNER_H, BANNER_RADIUS), ass_color("#" + GOLD_HEX),
            move_px=None,
        ),
        text_event(
            0.0, _FOREVER, CENTER_X, BANNER_TOP + BANNER_H // 2, "\\N".join(lines),
            size=size, color=ass_color("#" + BG_HEX), align=5, move_px=None,
        ),
    ]
    return ASS_TEMPLATE.format(font=font, events="\n".join(events))
