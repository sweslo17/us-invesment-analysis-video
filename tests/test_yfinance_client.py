"""yfinance client 測試:用注入的假 provider 驗證解析 / retry / 跳過邏輯,不打網路。"""

import pandas as pd
import pytest

from pmb.data.yfinance import YFinanceClient
from pmb.schemas.snapshot import Quote


def test_get_quote_builds_quote_from_provider():
    client = YFinanceClient(quote_provider=lambda t: (110.0, 100.0))
    q = client.get_quote("ES=F", name="S&P fut")
    assert isinstance(q, Quote)
    assert q.ticker == "ES=F"
    assert q.name == "S&P fut"
    assert q.last == 110.0
    assert q.previous_close == 100.0
    assert q.change_pct == pytest.approx(10.0)


def test_get_quote_retries_transient_failures_then_succeeds():
    calls = {"n": 0}

    def flaky(ticker):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("transient")
        return (5.0, 4.0)

    client = YFinanceClient(quote_provider=flaky, retries=3, retry_delay=0)
    q = client.get_quote("X")
    assert q.last == 5.0
    assert calls["n"] == 3


def test_get_quotes_skips_ticker_that_keeps_failing():
    def provider(ticker):
        if ticker == "BAD":
            raise ConnectionError("nope")
        return (2.0, 1.0)

    client = YFinanceClient(quote_provider=provider, retries=2, retry_delay=0)
    quotes = client.get_quotes([("GOOD", "Good"), ("BAD", "Bad")])
    assert [q.ticker for q in quotes] == ["GOOD"]


def test_get_history_returns_close_series_from_provider():
    series = pd.Series([1.0, 2.0, 3.0])
    client = YFinanceClient(history_provider=lambda t, period: series)
    out = client.get_history("^GSPC", period="3mo")
    pd.testing.assert_series_equal(out, series)


def test_get_top_holdings_returns_provider_rows():
    holdings = [("AAPL", "Apple", 7.0), ("MSFT", "Microsoft", 6.5)]
    client = YFinanceClient(holdings_provider=lambda etf: holdings)
    out = client.get_top_holdings("SPY")
    assert out == holdings


def test_get_top_holdings_retries_then_succeeds():
    calls = {"n": 0}

    def flaky(etf):
        calls["n"] += 1
        if calls["n"] < 2:
            raise ConnectionError("transient")
        return [("AAPL", "Apple", 7.0)]

    client = YFinanceClient(holdings_provider=flaky, retries=3, retry_delay=0)
    out = client.get_top_holdings("SPY")
    assert out == [("AAPL", "Apple", 7.0)]
    assert calls["n"] == 2
