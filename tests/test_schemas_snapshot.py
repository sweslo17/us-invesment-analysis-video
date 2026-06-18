"""snapshot schema(pydantic v2)行為測試:漲跌幅計算 + 結構 round-trip。"""

import datetime as dt

import pytest

from pmb.schemas.snapshot import (
    FredObservation,
    Quote,
    RegimeMetrics,
    Snapshot,
)


def test_quote_change_pct_computed_from_last_and_previous_close():
    q = Quote(ticker="ES=F", last=110.0, previous_close=100.0)
    assert q.change_pct == pytest.approx(10.0)


def test_quote_change_pct_none_when_previous_close_zero():
    q = Quote(ticker="X", last=5.0, previous_close=0.0)
    assert q.change_pct is None


def test_quote_change_pct_appears_in_serialization():
    q = Quote(ticker="ES=F", last=99.0, previous_close=100.0)
    assert q.model_dump()["change_pct"] == pytest.approx(-1.0)


def test_snapshot_round_trips_through_json_and_recomputes_change_pct():
    snap = Snapshot(
        session_date=dt.date(2026, 6, 18),
        generated_at=dt.datetime(2026, 6, 19, 11, 30, tzinfo=dt.UTC),
        indices=[Quote(ticker="^GSPC", name="S&P 500", last=5300.0, previous_close=5280.0)],
        volatility=Quote(ticker="^VIX", name="VIX", last=18.4, previous_close=17.0),
        leverage=[Quote(ticker="UPRO", last=80.0, previous_close=79.0)],
        macro=[
            FredObservation(
                series_id="DGS10",
                label="10Y Treasury",
                value=4.25,
                date=dt.date(2026, 6, 18),
                units="percent",
            )
        ],
        regime=RegimeMetrics(
            vix=18.4,
            realized_vol_20d=0.12,
            stock_bond_corr_20d=0.30,
            breadth_pct_above_ma50=0.60,
            breadth_pct_positive=0.55,
        ),
    )

    restored = Snapshot.model_validate_json(snap.model_dump_json())

    assert restored.session_date == dt.date(2026, 6, 18)
    assert restored.indices[0].change_pct == pytest.approx((5300 - 5280) / 5280 * 100)
    assert restored.macro[0].series_id == "DGS10"
    assert restored.regime.vix == pytest.approx(18.4)
