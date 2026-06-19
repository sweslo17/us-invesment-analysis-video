"""講稿 + 圖表 spec schema(pydantic v2)——規格 §6.3。

講稿與圖表同源:每個 ``segment`` 綁一個 ``chart_id``,合成時在該段旁白期間顯示對應圖。
結構性綁定由 model_validator 保證:segment.chart_id 必須對得上 charts[].id,且 id 不重複。
"""

from __future__ import annotations

from pydantic import BaseModel, model_validator

from pmb.schemas.chart import ChartSpec


class Segment(BaseModel):
    """一段畫面:綁一張圖表(chart_id)**或**一張時事標題卡(headline),兩者擇一。

    標題卡是全屏大字、快速閃過,用來增加視覺變化、打破純圖表的沉悶。
    """

    vo: str  # 旁白逐字稿
    chart_id: str | None = None
    headline: str | None = None
    t_start: float
    duration: float

    @model_validator(mode="after")
    def _exactly_one_visual(self) -> Segment:
        if bool(self.chart_id) == bool(self.headline):
            raise ValueError("每個 segment 必須剛好有 chart_id 或 headline 其中之一")
        return self


class Script(BaseModel):
    segments: list[Segment]
    charts: list[ChartSpec]

    @property
    def total_duration(self) -> float:
        return sum(seg.duration for seg in self.segments)

    @model_validator(mode="after")
    def _check_chart_bindings(self) -> Script:
        chart_ids = [c.id for c in self.charts]
        if len(chart_ids) != len(set(chart_ids)):
            raise ValueError("charts[].id 不可重複")
        valid = set(chart_ids)
        for seg in self.segments:
            if seg.chart_id is not None and seg.chart_id not in valid:
                raise ValueError(f"segment.chart_id「{seg.chart_id}」對不到任何 charts[].id")
        return self
