"""對帳:1–3 列「昨天說要看的 → 結果」,逐列跟著旁白出現;✓/✗/〰 用繪圖畫,不賭字型。

文字全走 ``textfit`` 的像素寬度模型:ask 一行(放不下縮字級)、result 最多兩行(72px → 60px
→ 續縮、截斷),保證右緣都在 890 之內(不碰 Shorts 右側按讚欄),也不壓到下一列。
"""

from __future__ import annotations

from typing import NamedTuple

from pmb.schemas.script import RecapRow, RecapSegment
from pmb.video.ass import (
    ASS_TEMPLATE,
    CONTENT_TOP,
    FADE_TAG,
    MUTED_HEX,
    WHITE_HEX,
    ass_color,
    center_block_top,
    common_events,
    full_event,
    polygon,
    rounded_rect,
    shape_event,
    text_event,
    top_layout,
)
from pmb.video.segments.base import (
    RenderContext,
    SegmentRenderer,
    Visual,
    canvas_background,
    caption_events,
)
from pmb.video.textfit import fit_lines, fit_one_line

_DEFAULT_TITLE = "昨天說要看的"
_ROW_PITCH = 250  # 相鄰兩列頂緣的間距
_RIGHT_EDGE = 890  # 避開右側按讚欄
_X = 70
_RESULT_X = 160
_MARK = 64
_MARK_DY = 62  # ✓/✗ 圖示頂緣到列頂
_RESULT_DY = 56  # 結果文字頂緣到列頂(ask 在列頂)
_SEP_DY = 210  # 分隔線到列頂
_ASK_FS = 44
_ASK_MAX_W = _RIGHT_EDGE - _X
_RESULT_SIZES = (72, 60)
_RESULT_MAX_LINES = 2
_RESULT_MAX_W = _RIGHT_EDGE - _RESULT_X
_SEP_W = 770
_SEP_HEX = "#2A4058"
# ✓:一條折線(左下短撇 + 右上長撇);✗:十字形的 12 點多邊形,都是 0–1 正規化座標
_CHECK = [(0.0, 0.55), (0.38, 0.92), (1.0, 0.18), (0.86, 0.05), (0.38, 0.66), (0.13, 0.42)]
_CROSS = [(0.15, 0.0), (0.5, 0.35), (0.85, 0.0), (1.0, 0.15), (0.65, 0.5), (1.0, 0.85),
          (0.85, 1.0), (0.5, 0.65), (0.15, 1.0), (0.0, 0.85), (0.35, 0.5), (0.0, 0.15)]
_MARK_HEX = {"yes": "#97C459", "no": "#F09595", "mixed": "#FAC775"}


def row_times(n_rows: int, starts: list[float], duration: float) -> list[float]:
    """第 k 列在第 k 句起點;句數不夠時,沒有對應句的 m 列平均分布在最後一句起點到段尾之間
    (``last + (duration - last) * j / (m + 1)``,j = 1..m)。完全沒有句子就整段平均分布。"""
    if not starts:
        return [duration * k / n_rows for k in range(n_rows)]
    matched = list(starts[:n_rows])
    remaining = n_rows - len(matched)
    last = matched[-1]
    return matched + [
        last + (duration - last) * j / (remaining + 1) for j in range(1, remaining + 1)
    ]


def result_layout(text: str) -> tuple[list[str], int]:
    """結果文字斷行 + 字級:72px 一行放得下就一行;放不下依序縮字級、最多 2 行,縮到底才截斷。"""
    return fit_lines(
        text, max_width=_RESULT_MAX_W, sizes=_RESULT_SIZES, max_lines=_RESULT_MAX_LINES
    )


def _mark_event(mark: str, start: float, end: float, x: int, y: int) -> str:
    color = ass_color(_MARK_HEX[mark])
    if mark == "yes":
        path = polygon(_CHECK, _MARK)
    elif mark == "no":
        path = polygon(_CROSS, _MARK)
    else:  # mixed:一條圓角橫槓
        path = rounded_rect(_MARK, 14, 7)
        y += (_MARK - 14) // 2
    return shape_event(start, end, x, y, path, color)


class _RowLayout(NamedTuple):
    """一列的版面:ask 單行 + 結果斷行,都已套好字級(``textfit`` 縮字/截斷之後)。"""

    row: RecapRow
    ask: str
    ask_size: int
    lines: list[str]
    size: int

    @property
    def extent(self) -> int:
        """內容從列頂算起的真實下緣:結果文字(行數 × 字級)與 ✓/✗ 圖示取最低者。"""
        return max(_RESULT_DY + len(self.lines) * self.size, _MARK_DY + _MARK, self.ask_size)


def _row_layout(row: RecapRow) -> _RowLayout:
    ask, ask_size = fit_one_line(row.ask, _ASK_FS, _ASK_MAX_W)  # 單行
    lines, size = result_layout(row.result)
    return _RowLayout(row, ask, ask_size, lines, size)


def row_tops(extents: list[int], top: int = CONTENT_TOP) -> list[int]:
    """各列頂緣 y。列距固定 ``_ROW_PITCH``,整塊(第一列頂緣 → 最後一列真實下緣)在內容帶裡
    上下置中:列少就落在畫面中間,不再貼著標題。``extents`` 是各列內容的實際高度,
    ``top`` 是內容帶上緣(有橫幅時要比橫幅底緣低)。

    置中後頂緣不會高過 ``top``(預設 ``CONTENT_TOP`` = 270,標題底緣約 245 已淨空);最多 3 列時
    整塊不超過 700px,預設下置中的頂緣至少在 445,所以不需要另外把首列壓在 330 以下。
    """
    if not extents:
        return []
    first = center_block_top((len(extents) - 1) * _ROW_PITCH + extents[-1], top)
    return [first + k * _ROW_PITCH for k in range(len(extents))]


def _row_events(layout: _RowLayout, top: int, start: float, end: float, last: bool) -> list[str]:
    row = layout.row
    events = [
        text_event(start, end, _X, top, layout.ask, size=layout.ask_size,
                   color=ass_color(MUTED_HEX)),
        _mark_event(row.mark, start, end, _X, top + _MARK_DY),
        text_event(start, end, _RESULT_X, top + _RESULT_DY, "\\N".join(layout.lines),
                   size=layout.size, color=ass_color(WHITE_HEX)),
    ]
    if not last:
        events.append(shape_event(start, end, _X, top + _SEP_DY, rounded_rect(_SEP_W, 2, 1),
                                  ass_color(_SEP_HEX)))
    return events


class RecapRenderer(SegmentRenderer):
    def render(self, seg: RecapSegment, ctx: RenderContext) -> Visual:
        layout = top_layout(ctx.banner)
        events = [full_event(layout.title_style, ctx.duration,
                             FADE_TAG + (seg.title or _DEFAULT_TITLE))]
        events += common_events(ctx.duration, badge=ctx.badge, cta=ctx.cta)
        times = row_times(len(seg.rows), ctx.starts, ctx.duration)
        rows = [_row_layout(row) for row in seg.rows]
        tops = row_tops([row.extent for row in rows], layout.content_top)
        for k, (row, top, start) in enumerate(zip(rows, tops, times, strict=True)):
            events += _row_events(row, top, start, ctx.duration, k == len(rows) - 1)
        events += caption_events(ctx.takes, ctx.starts)
        ass = ASS_TEMPLATE.format(font=ctx.font, events="\n".join(events))
        return Visual(canvas_background(ctx.work_dir), True, ass, "recap")
