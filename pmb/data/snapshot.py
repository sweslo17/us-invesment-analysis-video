"""組出當日真實數據快照——餵研究(LLM)與圖表渲染的唯一資料入口。

``compute_regime`` 是純函式(吃歷史序列回 regime 數值);``build_snapshot`` 負責用
注入的 client 取數並組裝。所有數字皆來自資料層,LLM 不得編造。
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
from loguru import logger

from pmb.data import universe
from pmb.data.calendar import previous_trading_day
from pmb.data.derived import (
    pct_above_ma,
    pct_positive,
    realized_volatility,
    rolling_stock_bond_correlation,
    stock_bond_correlation,
    vol_target_leverage,
    volatility_drag,
)
from pmb.schemas.snapshot import (
    EconSeries,
    IndexContribution,
    LeverageMath,
    Quote,
    RegimeMetrics,
    SectorReturn,
    Snapshot,
    YieldPoint,
)


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


def compute_leverage_math(
    histories: dict[str, pd.Series],
    index_specs: list[tuple[str, str]],
    *,
    reference_vol: float = 0.15,
    vol_window: int = 20,
) -> list[LeverageMath]:
    """每個指數的槓桿教育數值(波動目標槓桿 + 波動耗損)。缺歷史的指數跳過。

    全數據驅動:用各指數自身的已實現波動,不假設任何預期報酬。
    """
    out: list[LeverageMath] = []
    for ticker, name in index_specs:
        series = histories.get(ticker)
        if series is None:
            continue
        realized_vol = realized_volatility(series, window=vol_window)
        out.append(
            LeverageMath(
                market=name,
                realized_vol=realized_vol,
                vol_target_leverage=vol_target_leverage(realized_vol, target_vol=reference_vol),
                drag_1x=volatility_drag(realized_vol, 1),
                drag_2x=volatility_drag(realized_vol, 2),
                drag_3x=volatility_drag(realized_vol, 3),
            )
        )
    return out


def compute_sector_returns(
    histories: dict[str, pd.Series], sector_tickers: list[str]
) -> list[SectorReturn]:
    """各類股當日報酬(市場廣度長條圖用)。缺歷史的類股跳過。"""
    out: list[SectorReturn] = []
    for ticker in sector_tickers:
        series = histories.get(ticker)
        if series is None or len(series) < 2:
            continue
        change_pct = float(series.pct_change().iloc[-1] * 100)
        out.append(
            SectorReturn(sector=universe.SECTOR_LABELS.get(ticker, ticker), change_pct=change_pct)
        )
    return out


def compute_index_contributions(
    holdings: list[tuple[str, str, float]],
    quotes: dict[str, Quote],
) -> list[IndexContribution]:
    """把前 N 大持股(權重)與其當日報價合成貢獻度。缺報價或無漲跌的個股跳過。"""
    out: list[IndexContribution] = []
    for ticker, name, weight_pct in holdings:
        quote = quotes.get(ticker)
        if quote is None or quote.change_pct is None:
            continue
        out.append(
            IndexContribution(
                ticker=ticker,
                name=name,
                weight_pct=weight_pct,
                change_pct=quote.change_pct,
            )
        )
    return out


def build_yield_curve(fred_client, specs: list[tuple[str, str, int]]) -> list[YieldPoint]:
    """組殖利率曲線到期點(各 FRED 序列的最新值)。單點失敗跳過。"""
    out: list[YieldPoint] = []
    for series_id, label, months in specs:
        try:
            obs = fred_client.get_latest(series_id, label, "percent")
        except Exception as exc:  # noqa: BLE001
            logger.warning("略過殖利率點 {}:{}", series_id, exc)
            continue
        out.append(YieldPoint(label=label, months=months, value=obs.value))
    return out


def _first(quotes: list[Quote]) -> Quote | None:
    return quotes[0] if quotes else None


def build_snapshot(
    session_date: dt.date,
    *,
    yf_client,
    fred_client,
    generated_at: dt.datetime,
    history_period: str = "6mo",
    reference_vol: float = 0.15,
    vix_lookback: int = 60,
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

    vix_ticker = universe.VIX[0]
    tnx_ticker = universe.TREASURY_10Y[0]
    index_tickers = [t for t, _ in universe.INDEX_CASH]
    history_tickers = [
        vix_ticker,
        tnx_ticker,
        universe.BOND_PROXY,
        *index_tickers,
        *universe.SECTOR_ETFS,
    ]
    histories = yf_client.get_histories(history_tickers, period=history_period)

    regime = compute_regime(
        histories,
        vix=volatility.last if volatility else None,
        sector_tickers=universe.SECTOR_ETFS,
    )
    leverage_math = compute_leverage_math(
        histories, universe.INDEX_CASH, reference_vol=reference_vol
    )
    sector_returns = compute_sector_returns(histories, universe.SECTOR_ETFS)
    yield_curve = build_yield_curve(fred_client, universe.YIELD_CURVE_SERIES)

    index_contributions: list[IndexContribution] = []
    try:
        bench_ticker, _ = universe.CONCENTRATION_BENCHMARK
        holdings = yf_client.get_top_holdings(bench_ticker)
        holding_quotes = {
            q.ticker: q for q in yf_client.get_quotes([(t, n) for t, n, _ in holdings])
        }
        index_contributions = compute_index_contributions(holdings, holding_quotes)
    except Exception as exc:  # noqa: BLE001
        logger.warning("略過漲幅集中度(index_contributions):{}", exc)

    def _recent(ticker: str) -> list[float]:
        series = histories.get(ticker)
        return [] if series is None else [float(x) for x in series.dropna().tail(vix_lookback)]

    vix_history = _recent(vix_ticker)
    tnx_history = _recent(tnx_ticker)

    stock_bond_corr_history: list[float] = []
    if universe.STOCK_PROXY in histories and universe.BOND_PROXY in histories:
        corr_series = rolling_stock_bond_correlation(
            histories[universe.STOCK_PROXY], histories[universe.BOND_PROXY]
        )
        stock_bond_corr_history = [float(x) for x in corr_series.tail(vix_lookback)]

    econ_id, econ_label = universe.ECON_PRINT_SERIES
    try:
        econ_values = fred_client.get_recent_values(econ_id, 24)
        econ_series = EconSeries(label=econ_label, values=econ_values)
    except Exception as exc:  # noqa: BLE001
        logger.warning("略過 econ_print 序列 {}:{}", econ_id, exc)
        econ_series = None

    snapshot = Snapshot(
        session_date=session_date,
        previous_session_date=previous_trading_day(session_date),
        generated_at=generated_at,
        indices=indices,
        futures=futures,
        volatility=volatility,
        treasury_10y=treasury_10y,
        dollar_index=dollar_index,
        leverage=leverage,
        macro=macro,
        regime=regime,
        reference_vol=reference_vol,
        leverage_math=leverage_math,
        yield_curve=yield_curve,
        sector_returns=sector_returns,
        index_contributions=index_contributions,
        vix_history=vix_history,
        tnx_history=tnx_history,
        stock_bond_corr_history=stock_bond_corr_history,
        econ_series=econ_series,
    )
    logger.info(
        "快照組裝完成:指數 {} 槓桿教育 {} 殖利率點 {} 類股 {} 成分貢獻 {} 總經 {} 筆",
        len(indices),
        len(leverage_math),
        len(yield_curve),
        len(sector_returns),
        len(index_contributions),
        len(macro),
    )
    return snapshot
