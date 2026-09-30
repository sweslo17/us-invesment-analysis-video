"""kind → renderer 對應表。新增段型:寫一個 SegmentRenderer 子類別,在 _RENDERERS 註冊一行。"""

from __future__ import annotations

from pmb.video.segments.base import SegmentRenderer
from pmb.video.segments.card import CardRenderer
from pmb.video.segments.chart import ChartRenderer

_RENDERERS: dict[str, SegmentRenderer] = {
    "chart": ChartRenderer(),
    "card": CardRenderer(),
}


def renderer_for(kind: str) -> SegmentRenderer:
    try:
        return _RENDERERS[kind]
    except KeyError:
        raise ValueError(f"沒有段型「{kind}」的 renderer") from None
