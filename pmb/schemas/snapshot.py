"""當日真實數據快照的 pydantic v2 schema。

``Snapshot`` 是資料層的最終產出,同時餵給研究(LLM)與圖表渲染。所有數字來自
FRED / yfinance,LLM 只能引用、不能編造。漲跌幅計算集中在 ``Quote.change_pct``,
為唯一真實來源(DRY)。
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, computed_field


class Quote(BaseModel):
    """一檔行情:最新價與前收,漲跌幅由兩者計算得出。"""

    ticker: str
    name: str | None = None
    last: float
    previous_close: float

    @computed_field  # type: ignore[prop-decorator]
    @property
    def change_pct(self) -> float | None:
        """相對前收的百分比變動;前收為 0 時無法計算,回傳 None。"""
        if self.previous_close == 0:
            return None
        return (self.last - self.previous_close) / self.previous_close * 100


class FredObservation(BaseModel):
    """FRED 單一序列的最新觀測值。"""

    series_id: str
    label: str
    value: float
    date: dt.date
    units: str | None = None
    prior_value: float | None = None


class LeverageMath(BaseModel):
    """單一市場/指數的槓桿教育數值(全數據驅動,非投資建議)。

    ``vol_target_leverage`` = 參考風險 / 當前已實現波動;``drag_*`` 為 L²σ²/2 的年化
    波動耗損。圖表(leverage_decay)與報告用這些數字,LLM 只寫文字說明、不產生數字。
    """

    market: str
    realized_vol: float
    vol_target_leverage: float
    drag_1x: float
    drag_2x: float
    drag_3x: float


class RegimeMetrics(BaseModel):
    """市場 regime 的數值輸入(自算衍生指標)。

    這裡只放數字;categorical 標籤(elevated/rising/...)由研究 LLM 在 brief 判定。
    """

    vix: float | None = None
    realized_vol_20d: float | None = None
    stock_bond_corr_20d: float | None = None
    breadth_pct_above_ma50: float | None = None
    breadth_pct_positive: float | None = None


class Snapshot(BaseModel):
    """當日盤前真實數據快照。"""

    session_date: dt.date
    generated_at: dt.datetime
    indices: list[Quote] = []
    futures: list[Quote] = []
    volatility: Quote | None = None
    treasury_10y: Quote | None = None
    dollar_index: Quote | None = None
    leverage: list[Quote] = []
    macro: list[FredObservation] = []
    regime: RegimeMetrics = RegimeMetrics()
    reference_vol: float = 0.15
    leverage_math: list[LeverageMath] = []
