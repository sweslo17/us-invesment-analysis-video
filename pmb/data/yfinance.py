"""yfinance 行情 client(確定性資料來源)。

包裝 yfinance:取最新價 / 前收(組 ``Quote``)與歷史收盤序列(供衍生指標)。
低階取數透過可注入的 provider,方便測試與日後替換資料源;對外呼叫包 retry。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

import pandas as pd
from loguru import logger

from pmb.data.retry import call_with_retry
from pmb.schemas.snapshot import Quote

QuoteProvider = Callable[[str], tuple[float, float]]
HistoryProvider = Callable[[str, str], pd.Series]


def _default_quote_provider(ticker: str) -> tuple[float, float]:
    """以 yfinance fast_info 取 (最新價, 前收)。"""
    import yfinance as yf

    fast = yf.Ticker(ticker).fast_info
    last = fast.last_price
    previous_close = fast.previous_close
    if last is None or previous_close is None:
        raise ValueError(f"{ticker} 無有效報價(last={last}, previous_close={previous_close})")
    return float(last), float(previous_close)


def _default_history_provider(ticker: str, period: str) -> pd.Series:
    """以 yfinance 取歷史收盤序列。"""
    import yfinance as yf

    frame = yf.Ticker(ticker).history(period=period)
    if frame.empty:
        raise ValueError(f"{ticker} 取不到歷史資料(period={period})")
    return frame["Close"]


class YFinanceClient:
    def __init__(
        self,
        *,
        quote_provider: QuoteProvider | None = None,
        history_provider: HistoryProvider | None = None,
        retries: int = 3,
        retry_delay: float = 1.0,
    ) -> None:
        self._quote_provider = quote_provider or _default_quote_provider
        self._history_provider = history_provider or _default_history_provider
        self.retries = retries
        self.retry_delay = retry_delay

    def get_quote(self, ticker: str, name: str | None = None) -> Quote:
        last, previous_close = call_with_retry(
            lambda: self._quote_provider(ticker),
            retries=self.retries,
            delay=self.retry_delay,
            what=f"yfinance quote {ticker}",
        )
        return Quote(ticker=ticker, name=name, last=last, previous_close=previous_close)

    def get_quotes(self, specs: Iterable[tuple[str, str | None]]) -> list[Quote]:
        """逐檔取報價;單檔失敗(retry 用盡)記錄並跳過,不中斷整批。"""
        quotes: list[Quote] = []
        for ticker, name in specs:
            try:
                quotes.append(self.get_quote(ticker, name))
            except Exception as exc:  # noqa: BLE001
                logger.error("略過 {}:取報價失敗 {}", ticker, exc)
        return quotes

    def get_history(self, ticker: str, period: str = "6mo") -> pd.Series:
        return call_with_retry(
            lambda: self._history_provider(ticker, period),
            retries=self.retries,
            delay=self.retry_delay,
            what=f"yfinance history {ticker}",
        )

    def get_histories(self, tickers: Sequence[str], period: str = "6mo") -> dict[str, pd.Series]:
        """逐檔取歷史收盤;失敗者跳過。回傳 {ticker: Close series}。"""
        out: dict[str, pd.Series] = {}
        for ticker in tickers:
            try:
                out[ticker] = self.get_history(ticker, period)
            except Exception as exc:  # noqa: BLE001
                logger.error("略過 {} 歷史:{}", ticker, exc)
        return out
