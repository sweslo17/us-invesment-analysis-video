"""圖表模組庫測試:spec 驗證、render 產 PNG、選圖 dispatch、非法模組/參數被擋。"""

import datetime as dt
from typing import get_args

import pytest
from pydantic import ValidationError

from pmb.charts.library import (
    render_breadth,
    render_econ_print,
    render_index_overnight_grid,
    render_leverage_decay,
    render_overnight_vs_close,
    render_rates_trend,
    render_stock_bond_corr,
    render_vix_regime,
    render_yield_curve,
)
from pmb.charts.select import implemented_modules, render_chart
from pmb.schemas.chart import ChartModule, ChartSpec
from pmb.schemas.snapshot import (
    EconSeries,
    LeverageMath,
    Quote,
    SectorReturn,
    Snapshot,
    YieldPoint,
)


def _snapshot() -> Snapshot:
    return Snapshot(
        session_date=dt.date(2026, 6, 18),
        generated_at=dt.datetime(2026, 6, 18, 12, 0, tzinfo=dt.UTC),
        indices=[
            Quote(ticker="^GSPC", name="S&P 500", last=7500.0, previous_close=7420.0),
            Quote(ticker="^IXIC", name="Nasdaq", last=26517.0, previous_close=26020.0),
        ],
        futures=[
            Quote(ticker="ES=F", name="S&P 500 期貨", last=7540.0, previous_close=7515.0),
            Quote(ticker="NQ=F", name="Nasdaq 期貨", last=26700.0, previous_close=26550.0),
        ],
        leverage_math=[
            LeverageMath(
                market="S&P 500",
                realized_vol=0.165,
                vol_target_leverage=0.91,
                drag_1x=0.0136,
                drag_2x=0.0545,
                drag_3x=0.1226,
            ),
            LeverageMath(
                market="Nasdaq",
                realized_vol=0.256,
                vol_target_leverage=0.59,
                drag_1x=0.0328,
                drag_2x=0.1311,
                drag_3x=0.2950,
            ),
        ],
        vix_history=[22.0, 20.5, 19.0, 18.2, 17.1, 16.4],
        yield_curve=[
            YieldPoint(label="3M", months=3, value=4.30),
            YieldPoint(label="2Y", months=24, value=4.20),
            YieldPoint(label="10Y", months=120, value=4.49),
            YieldPoint(label="30Y", months=360, value=4.70),
        ],
        sector_returns=[
            SectorReturn(sector="科技", change_pct=2.1),
            SectorReturn(sector="能源", change_pct=-0.8),
            SectorReturn(sector="金融", change_pct=0.5),
        ],
        tnx_history=[4.30, 4.35, 4.42, 4.49, 4.45],
        stock_bond_corr_history=[0.2, 0.35, 0.5, 0.53],
        econ_series=EconSeries(label="失業率 (%)", values=[4.0, 4.1, 4.2, 4.3]),
    )


# --- spec 驗證 ---

def test_chart_spec_accepts_known_module():
    spec = ChartSpec(id="lev", module="leverage_decay", params={})
    assert spec.module == "leverage_decay"


def test_chart_spec_rejects_unknown_module():
    with pytest.raises(ValidationError):
        ChartSpec(id="x", module="candlestick_3d", params={})


# --- render 模組產 PNG ---

def test_render_leverage_decay_writes_png(tmp_path):
    out = tmp_path / "lev.png"
    render_leverage_decay(out, _snapshot().leverage_math, {})
    assert out.exists() and out.stat().st_size > 0


def test_render_index_overnight_grid_writes_png(tmp_path):
    out = tmp_path / "grid.png"
    render_index_overnight_grid(out, _snapshot().indices, {})
    assert out.exists() and out.stat().st_size > 0


def test_render_overnight_vs_close_writes_png(tmp_path):
    out = tmp_path / "ovc.png"
    snap = _snapshot()
    render_overnight_vs_close(out, snap.indices, snap.futures, {})
    assert out.exists() and out.stat().st_size > 0


def test_render_overnight_vs_close_dispatches(tmp_path):
    spec = ChartSpec(id="ovc", module="overnight_vs_close")
    path = render_chart(spec, _snapshot(), tmp_path)
    assert path.exists() and path.stat().st_size > 0
    assert path.name == "ovc.png"


def test_render_vix_regime_writes_png(tmp_path):
    out = tmp_path / "vix.png"
    render_vix_regime(out, _snapshot().vix_history, {"bands": [15, 20, 30]})
    assert out.exists() and out.stat().st_size > 0


def test_render_yield_curve_writes_png(tmp_path):
    out = tmp_path / "curve.png"
    render_yield_curve(out, _snapshot().yield_curve, {})
    assert out.exists() and out.stat().st_size > 0


def test_render_breadth_writes_png(tmp_path):
    out = tmp_path / "breadth.png"
    render_breadth(out, _snapshot().sector_returns, {})
    assert out.exists() and out.stat().st_size > 0


def test_render_rates_trend_writes_png(tmp_path):
    out = tmp_path / "rates.png"
    render_rates_trend(out, _snapshot().tnx_history, {})
    assert out.exists() and out.stat().st_size > 0


def test_render_stock_bond_corr_writes_png(tmp_path):
    out = tmp_path / "corr.png"
    render_stock_bond_corr(out, _snapshot().stock_bond_corr_history, {})
    assert out.exists() and out.stat().st_size > 0


def test_render_econ_print_writes_png(tmp_path):
    out = tmp_path / "econ.png"
    render_econ_print(out, _snapshot().econ_series, {})
    assert out.exists() and out.stat().st_size > 0


# --- 選圖 dispatch ---

def test_render_chart_dispatches_to_module(tmp_path):
    spec = ChartSpec(id="lev", module="leverage_decay")
    path = render_chart(spec, _snapshot(), tmp_path)
    assert path.exists() and path.stat().st_size > 0
    assert path.name == "lev.png"


def test_every_chart_module_has_a_renderer():
    # 固定模組庫(Literal)的每個模組都要有對應 render,不能有缺口
    assert set(get_args(ChartModule)) == set(implemented_modules())
