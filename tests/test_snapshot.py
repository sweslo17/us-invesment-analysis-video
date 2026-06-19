"""快照組裝測試:compute_regime 純函式 + build_snapshot 以假 client 驗證接線。"""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from pmb.data import universe
from pmb.data.snapshot import (
    build_snapshot,
    build_yield_curve,
    compute_leverage_math,
    compute_regime,
    compute_sector_returns,
)
from pmb.schemas.snapshot import FredObservation, Quote, Snapshot


def test_compute_regime_fills_metrics_from_histories():
    idx = pd.date_range("2026-01-01", periods=60, freq="D")
    histories = {
        "^GSPC": pd.Series(np.linspace(100, 110, 60), index=idx),
        "TLT": pd.Series(np.linspace(90, 80, 60), index=idx),
        "XLK": pd.Series(np.linspace(10, 11, 60), index=idx),
        "XLF": pd.Series(np.linspace(20, 19, 60), index=idx),
        "XLE": pd.Series(np.linspace(30, 33, 60), index=idx),
    }
    regime = compute_regime(histories, vix=18.5, sector_tickers=["XLK", "XLF", "XLE"])

    assert regime.vix == 18.5
    assert regime.realized_vol_20d is not None
    assert regime.stock_bond_corr_20d is not None
    assert 0.0 <= regime.breadth_pct_above_ma50 <= 1.0
    assert 0.0 <= regime.breadth_pct_positive <= 1.0


def test_compute_regime_handles_missing_series_gracefully():
    regime = compute_regime({}, vix=None, sector_tickers=["XLK"])
    assert regime.vix is None
    assert regime.realized_vol_20d is None
    assert regime.stock_bond_corr_20d is None
    assert regime.breadth_pct_above_ma50 is None
    assert regime.breadth_pct_positive is None


def test_compute_leverage_math_per_index():
    idx = pd.date_range("2026-01-01", periods=60, freq="D")
    histories = {
        "^GSPC": pd.Series(np.linspace(100, 110, 60) + np.sin(range(60)), index=idx),
        "^RUT": pd.Series(np.linspace(50, 60, 60) + 2 * np.sin(range(60)), index=idx),
    }
    out = compute_leverage_math(
        histories,
        [("^GSPC", "S&P 500"), ("^RUT", "Russell 2000")],
        reference_vol=0.15,
    )
    assert [m.market for m in out] == ["S&P 500", "Russell 2000"]
    m = out[0]
    assert m.realized_vol > 0
    assert m.vol_target_leverage == pytest.approx(0.15 / m.realized_vol)
    assert m.drag_3x == pytest.approx(9 * m.drag_1x)  # 耗損隨槓桿平方


def test_compute_leverage_math_skips_missing_history():
    assert compute_leverage_math({}, [("^GSPC", "S&P 500")], reference_vol=0.15) == []


def test_compute_sector_returns_labels_and_pct():
    idx = pd.date_range("2026-06-17", periods=2, freq="D")
    histories = {
        "XLK": pd.Series([100.0, 101.0], index=idx),
        "XLF": pd.Series([100.0, 99.0], index=idx),
    }
    out = compute_sector_returns(histories, ["XLK", "XLF"])
    assert (out[0].sector, out[0].change_pct) == ("科技", pytest.approx(1.0))
    assert (out[1].sector, out[1].change_pct) == ("金融", pytest.approx(-1.0))


class _FakeFredCurve:
    def get_latest(self, series_id, label, units=None):
        vals = {"DGS3MO": 4.30, "DGS2": 4.20, "DGS10": 4.49}
        return FredObservation(
            series_id=series_id, label=label, value=vals[series_id],
            date=dt.date(2026, 6, 18), units=units,
        )


def test_build_yield_curve_orders_points_with_months():
    specs = [("DGS3MO", "3M", 3), ("DGS2", "2Y", 24), ("DGS10", "10Y", 120)]
    out = build_yield_curve(_FakeFredCurve(), specs)
    assert [(p.label, p.months, p.value) for p in out] == [
        ("3M", 3, pytest.approx(4.30)),
        ("2Y", 24, pytest.approx(4.20)),
        ("10Y", 120, pytest.approx(4.49)),
    ]


class _FakeYF:
    """對任何 ticker 都回固定報價;歷史只回 provided 字典中有的。"""

    def __init__(self, histories):
        self._histories = histories

    def get_quotes(self, specs):
        return [Quote(ticker=t, name=n, last=100.0, previous_close=99.0) for t, n in specs]

    def get_histories(self, tickers, period="6mo"):
        return {t: self._histories[t] for t in tickers if t in self._histories}


class _FakeFred:
    def get_observations(self, specs):
        return [
            FredObservation(series_id=sid, label=lab, value=1.0, date=dt.date(2026, 6, 18), units=u)
            for sid, lab, u in specs
        ]

    def get_latest(self, series_id, label, units=None):
        return FredObservation(
            series_id=series_id, label=label, value=4.0, date=dt.date(2026, 6, 18), units=units
        )


def test_build_snapshot_wires_all_sections():
    idx = pd.date_range("2026-01-01", periods=60, freq="D")
    histories = {
        "^GSPC": pd.Series(np.linspace(100, 110, 60), index=idx),
        "TLT": pd.Series(np.linspace(90, 80, 60), index=idx),
        "^VIX": pd.Series(np.linspace(20, 16, 60), index=idx),
        "XLK": pd.Series(np.linspace(100, 105, 60), index=idx),
    }
    snap = build_snapshot(
        dt.date(2026, 6, 18),
        yf_client=_FakeYF(histories),
        fred_client=_FakeFred(),
        generated_at=dt.datetime(2026, 6, 19, 11, 30, tzinfo=dt.UTC),
    )

    assert isinstance(snap, Snapshot)
    assert snap.session_date == dt.date(2026, 6, 18)
    futures_tickers = {q.ticker for q in snap.futures}
    assert "ES=F" in futures_tickers
    assert snap.volatility is not None and snap.volatility.ticker == "^VIX"
    assert snap.treasury_10y is not None and snap.treasury_10y.ticker == "^TNX"
    assert snap.dollar_index is not None
    assert any(q.ticker == "UPRO" for q in snap.leverage)
    assert any(o.series_id == "DGS10" for o in snap.macro)
    assert snap.regime.realized_vol_20d is not None
    assert any(m.market == "S&P 500" for m in snap.leverage_math)  # 由 ^GSPC 歷史算出
    assert len(snap.yield_curve) == len(universe.YIELD_CURVE_SERIES)
    assert snap.vix_history  # 由 ^VIX 歷史帶入
    assert any(s.sector == "科技" for s in snap.sector_returns)  # XLK → 科技
