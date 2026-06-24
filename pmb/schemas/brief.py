"""brief schema(pydantic v2)——規格 §5.7。

研究 LLM 的結構化輸出。列舉欄位以 ``Literal`` 鎖定,materiality 限 1–5;
LLM 輸出一律 ``model_validate``,失敗自動重試(見 ``research/runner.py``)。
數字只能引用資料層快照,不可編造。
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

Horizon = Literal["ST", "MT", "LT"]
VsThesis = Literal["confirms", "challenges", "new"]
Confidence = Literal["confirmed", "developing", "single-print"]

VolRegime = Literal["low", "normal", "elevated", "high"]
RatesRegime = Literal["falling", "stable", "rising"]
CorrRegime = Literal["negative", "neutral", "positive"]
BreadthRegime = Literal["narrow", "mixed", "broad"]


class Source(BaseModel):
    url: str
    ts: dt.datetime | None = None


class BriefIndex(BaseModel):
    name: str
    level: float
    overnight_pct: float
    drivers: list[str] = []


class LeverageContext(BaseModel):
    """每個市場/指數的「最適槓桿」教育(一般性的倍數概念,非任何特定商品的投資建議)。

    具體數字(已實現波動、波動目標槓桿、波動耗損)由資料層 ``snapshot.leverage_math``
    提供;此處只放 LLM 寫的文字說明,LLM 不產生數字。
    """

    market: str
    edu_note: str


class Regime(BaseModel):
    """市場 regime 的 LLM 判定標籤(數值來自快照的 RegimeMetrics)。"""

    vol: VolRegime
    rates: RatesRegime
    stock_bond_corr: CorrRegime
    breadth: BreadthRegime


class BriefItem(BaseModel):
    headline: str
    horizon: Horizon
    vs_thesis: VsThesis
    materiality: int = Field(ge=1, le=5)
    confidence: Confidence
    audience_value: str
    sources: list[Source] = []


class ThesisDelta(BaseModel):
    changed: bool
    summary: str | None = None
    horizon: Horizon | None = None


class Brief(BaseModel):
    date: dt.date
    indices: list[BriefIndex] = []
    leverage_context: list[LeverageContext] = []
    regime: Regime
    items: list[BriefItem] = []
    catalysts: list[str] = []  # 今日盤中要看的排程事件(數據、Fed、財報…)
    thesis_delta: ThesisDelta
    lead_horizon: Horizon
    # YouTube Shorts 標題鉤子:當天最強、最即時的單一角度(前瞻 / 當下優先,避免「昨天…」起手)。
    # 由研究端撰寫;publish 端優先用它當標題,缺漏時退回最高 materiality 的 item headline。
    title_hook: str | None = None
