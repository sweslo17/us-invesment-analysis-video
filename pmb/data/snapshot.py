"""組出當日真實數據快照——餵研究(LLM)與圖表渲染的唯一資料入口。

``compute_regime`` 是純函式(吃歷史序列回 regime 數值);``build_snapshot`` 負責用
注入的 client 取數並組裝。所有數字皆來自資料層,LLM 不得編造。
"""

from __future__ import annotations

import datetime as dt
import math

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
    FedPath,
    FedPathPoint,
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
        # 歷史不足或全 NaN 時 realized_vol 為 NaN → 各 drag 也 NaN;NaN 進非 optional
        # float 欄位會讓快照寫得出、讀不回。跳過此市場(槓桿圖少一條線)。
        if not math.isfinite(realized_vol):
            logger.debug("市場 {} realized_vol 非有限數,跳過槓桿數學", name)
            continue
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
        # 盤前 yfinance 常回 NaN 收盤 → change_pct 為 NaN;NaN 經 model_dump_json 變 null,
        # 重載 float 欄位即爆。跳過(圖表少一根類股),不讓 NaN 進快照。
        if not math.isfinite(change_pct):
            logger.debug("類股 {} change_pct 非有限數,跳過", ticker)
            continue
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


def _next_month(year: int, month: int) -> tuple[int, int]:
    """回傳 ``(year, month)`` 的下一個月份(跨年進位)。"""
    return (year, month + 1) if month < 12 else (year + 1, 1)


def compute_fed_path_from_futures(
    meetings: list[tuple[str, float]],
    current_rate: float,
) -> list[FedPathPoint]:
    """由各次會議後的市場隱含政策利率算出路徑 + 逐次升息機率(純函式)。

    ``meetings`` 為時間序的 ``[(會議標籤, 該會議後隱含政策利率 %)]``(隱含利率 = 100 − 期貨價)。
    逐次升息機率 = max(0, 本次隱含 − 前次隱含) / 0.25(>1 表市場定價超過一碼);
    ``change_bps`` 為相對現行政策利率的累計變動。
    """
    points: list[FedPathPoint] = []
    prev = current_rate
    for label, implied in meetings:
        step = implied - prev
        prob = step / 0.25 if step > 0 else 0.0
        points.append(
            FedPathPoint(
                label=label,
                implied_rate=round(implied, 4),
                hike_prob=round(prob, 4),
                change_bps=round((implied - current_rate) * 100, 1),
            )
        )
        prev = implied
    return points


def compute_fed_path_from_curve(
    points_in: list[tuple[str, float]],
    current_rate: float,
) -> list[FedPathPoint]:
    """保底:Treasury 短端各到期點殖利率 vs 現行政策利率(純函式,不算逐次會議機率)。"""
    return [
        FedPathPoint(
            label=label,
            implied_rate=round(value, 4),
            hike_prob=None,
            change_bps=round((value - current_rate) * 100, 1),
        )
        for label, value in points_in
    ]


def build_fed_path(yf_client, fred_client, session_date: dt.date) -> FedPath | None:
    """市場隱含 Fed 政策路徑:期貨優先、Treasury 曲線保底(混合)。

    1) baseline = 現行政策利率(FEDFUNDS)。
    2) 期貨:取「會議後第一個整月」的 Fed funds 期貨合約,以 100−價 作該次會議後的隱含政策
       利率;任一合約缺報價、或隱含利率落在 [0,10] 之外即視為不可用,退回曲線保底。
    3) 曲線保底:Treasury 短端殖利率相對現行政策利率,呈現市場對未來利率的定價方向。
    """
    try:
        pol = fred_client.get_latest(*universe.POLICY_RATE_SERIES, "percent")
        current_rate = pol.value
    except Exception as exc:  # noqa: BLE001
        logger.warning("Fed 路徑:取不到現行政策利率,跳過:{}", exc)
        return None

    upcoming = [(d, lbl) for d, lbl in universe.FOMC_MEETINGS if d > session_date]
    if upcoming:
        try:
            specs: list[tuple[str, str]] = []
            for d, lbl in upcoming:
                yy, mm = _next_month(d.year, d.month)
                specs.append((universe.fed_funds_future_ticker(yy, mm), lbl))
            quotes = {q.ticker: q for q in yf_client.get_quotes(specs)}
            meetings: list[tuple[str, float]] = []
            for ticker, lbl in specs:
                q = quotes.get(ticker)
                if q is None:
                    raise ValueError(f"缺 {ticker} 期貨報價")
                implied = 100.0 - q.last
                if not 0.0 <= implied <= 10.0:
                    raise ValueError(f"{ticker} 隱含利率異常({implied:.2f}%)")
                meetings.append((lbl, implied))
            points = compute_fed_path_from_futures(meetings, current_rate)
            logger.info("Fed 路徑:用 Fed funds 期貨,涵蓋 {} 次會議", len(points))
            return FedPath(
                source="futures",
                current_rate=current_rate,
                points=points,
                note="市場隱含:Fed funds 期貨(100−價)推算各次 FOMC 會議後政策利率與升息機率",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fed 路徑:期貨不可用,改用 Treasury 曲線保底:{}", exc)

    try:
        curve_pts: list[tuple[str, float]] = []
        for series_id, label, _months in universe.FED_PATH_CURVE_SERIES:
            obs = fred_client.get_latest(series_id, label, "percent")
            curve_pts.append((label, obs.value))
        if not curve_pts:
            return None
        points = compute_fed_path_from_curve(curve_pts, current_rate)
        logger.info("Fed 路徑:用 Treasury 短端曲線保底,{} 個到期點", len(points))
        return FedPath(
            source="curve",
            current_rate=current_rate,
            points=points,
            note=(
                "保底:Treasury 短端殖利率(含期限溢價)相對現行政策利率,"
                "反映市場對未來利率的定價方向"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Fed 路徑:曲線保底也失敗,跳過:{}", exc)
        return None


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

    global_equities = yf_client.get_quotes(universe.GLOBAL_EQUITY)
    fed_path = build_fed_path(yf_client, fred_client, session_date)

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
        global_equities=global_equities,
        fed_path=fed_path,
        vix_history=vix_history,
        tnx_history=tnx_history,
        stock_bond_corr_history=stock_bond_corr_history,
        econ_series=econ_series,
    )
    logger.info(
        "快照組裝完成:指數 {} 槓桿教育 {} 殖利率點 {} 類股 {} 成分貢獻 {} 海外股 {} "
        "Fed路徑 {} 總經 {} 筆",
        len(indices),
        len(leverage_math),
        len(yield_curve),
        len(sector_returns),
        len(index_contributions),
        len(global_equities),
        (fed_path.source if fed_path else "無"),
        len(macro),
    )
    return snapshot
