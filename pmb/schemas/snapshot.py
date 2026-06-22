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


class YieldPoint(BaseModel):
    """殖利率曲線上的一個到期點。"""

    label: str
    months: int
    value: float


class IndexContribution(BaseModel):
    """單一成分股對基準指數當日漲跌的貢獻(漲幅集中度用)。

    ``weight_pct`` 為該股在基準 ETF 的權重(%),``change_pct`` 為其當日漲跌(%);
    ``contribution`` = 權重 × 報酬,單位為「指數百分點」,由兩者計算得出(DRY,
    LLM 不產生數字)。少數權值股若貢獻佔比偏高,即反映漲幅集中、廣度偏窄。
    """

    ticker: str
    name: str | None = None
    weight_pct: float
    change_pct: float

    @computed_field  # type: ignore[prop-decorator]
    @property
    def contribution(self) -> float:
        """對指數的貢獻(百分點)= 權重% × 報酬% / 100。"""
        return self.weight_pct * self.change_pct / 100.0


class SectorReturn(BaseModel):
    """單一類股當日報酬(市場廣度用)。"""

    sector: str
    change_pct: float


class EconSeries(BaseModel):
    """總經序列(econ_print 圖表用):一條時間序列 + 標籤。"""

    label: str
    values: list[float] = []


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
    previous_session_date: dt.date | None = None  # 上一個交易日(假期/週末後可能跨多天)
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
    yield_curve: list[YieldPoint] = []
    sector_returns: list[SectorReturn] = []
    index_contributions: list[IndexContribution] = []  # 基準指數前 N 大成分股的漲幅貢獻
    vix_history: list[float] = []
    tnx_history: list[float] = []
    stock_bond_corr_history: list[float] = []
    econ_series: EconSeries | None = None
