"""組出當日真實數據快照——餵研究(LLM)與圖表渲染的唯一資料入口。

``compute_regime`` 是純函式(吃歷史序列回 regime 數值);``build_snapshot`` 負責用
注入的 client 取數並組裝。所有數字皆來自資料層,LLM 不得編造。
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
from loguru import logger

from pmb.data import universe
from pmb.data.derived import (
    pct_above_ma,
    pct_positive,
    realized_volatility,
    stock_bond_correlation,
)
from pmb.schemas.snapshot import Quote, RegimeMetrics, Snapshot


def compute_regime(
    histories: dict[str, pd.Series],
    vix: float | None,
    *,
    sector_tickers: list[str],
    vol_window: int = 20,
    corr_window: int = 20,
    ma_window: int = 50,
    stock_proxy: str = universe.STOCK_PROXY,
    bond_proxy: str = universe.BOND_PROXY,
) -> RegimeMetrics:
    """由歷史收盤序列算出市場 regime 的數值(缺資料的項目回 None)。"""
    realized_vol = None
    if stock_proxy in histories:
        realized_vol = realized_volatility(histories[stock_proxy], window=vol_window)

    corr = None
    if stock_proxy in histories and bond_proxy in histories:
        corr = stock_bond_correlation(
            histories[stock_proxy], histories[bond_proxy], window=corr_window
        )

    above_ma = None
    pct_up = None
    sector_series = {t: histories[t] for t in sector_tickers if t in histories}
    if sector_series:
        basket = pd.concat(sector_series, axis=1)
        above_ma = pct_above_ma(basket, window=ma_window)
        pct_up = pct_positive(basket)

    return RegimeMetrics(
        vix=vix,
        realized_vol_20d=realized_vol,
        stock_bond_corr_20d=corr,
        breadth_pct_above_ma50=above_ma,
        breadth_pct_positive=pct_up,
    )


def _first(quotes: list[Quote]) -> Quote | None:
    return quotes[0] if quotes else None


def build_snapshot(
    session_date: dt.date,
    *,
    yf_client,
    fred_client,
    generated_at: dt.datetime,
    history_period: str = "6mo",
) -> Snapshot:
    """取數並組出 ``Snapshot``。client 以注入方式提供(便於測試與替換)。"""
    logger.info("組裝 {} 的市場快照", session_date)

    futures = yf_client.get_quotes(universe.INDEX_FUTURES)
    indices = yf_client.get_quotes(universe.INDEX_CASH)
    leverage = yf_client.get_quotes(universe.LEVERAGE)
    volatility = _first(yf_client.get_quotes([universe.VIX]))
    treasury_10y = _first(yf_client.get_quotes([universe.TREASURY_10Y]))
    dollar_index = _first(yf_client.get_quotes([universe.DOLLAR_INDEX]))

    macro = fred_client.get_observations(universe.FRED_SERIES)

    history_tickers = [universe.STOCK_PROXY, universe.BOND_PROXY, *universe.SECTOR_ETFS]
    histories = yf_client.get_histories(history_tickers, period=history_period)
    regime = compute_regime(
        histories,
        vix=volatility.last if volatility else None,
        sector_tickers=universe.SECTOR_ETFS,
    )

    snapshot = Snapshot(
        session_date=session_date,
        generated_at=generated_at,
        indices=indices,
        futures=futures,
        volatility=volatility,
        treasury_10y=treasury_10y,
        dollar_index=dollar_index,
        leverage=leverage,
        macro=macro,
        regime=regime,
    )
    logger.info(
        "快照組裝完成:指數 {} 期貨 {} 槓桿 {} 總經 {} 筆",
        len(indices),
        len(futures),
        len(leverage),
        len(macro),
    )
    return snapshot
