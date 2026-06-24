"""圖表模組庫測試:spec 驗證、render 產 PNG、選圖 dispatch、非法模組/參數被擋。"""

import datetime as dt
from typing import get_args

import pytest
from pydantic import ValidationError

from pmb.charts.library import (
    render_breadth,
    render_catalyst_timeline,
    render_concentration,
    render_econ_print,
    render_fed_path,
    render_global_equity_overnight,
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
    FedPath,
    FedPathPoint,
    IndexContribution,
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
        index_contributions=[
            IndexContribution(ticker="AAPL", name="Apple", weight_pct=7.0, change_pct=1.5),
            IndexContribution(ticker="MSFT", name="Microsoft", weight_pct=6.5, change_pct=-0.5),
            IndexContribution(ticker="NVDA", name="NVIDIA", weight_pct=6.0, change_pct=3.0),
        ],
        global_equities=[
            Quote(ticker="^KS11", name="南韓 KOSPI", last=2900.0, previous_close=3100.0),
            Quote(ticker="^N225", name="日經 225", last=42000.0, previous_close=42500.0),
            Quote(ticker="^STOXX50E", name="歐洲 STOXX50", last=5200.0, previous_close=5180.0),
        ],
        fed_path=FedPath(
            source="futures",
            current_rate=3.63,
            points=[
                FedPathPoint(label="7月", implied_rate=3.70, hike_prob=0.28, change_bps=7.0),
                FedPathPoint(label="9月", implied_rate=3.88, hike_prob=0.72, change_bps=25.0),
                FedPathPoint(label="12月", implied_rate=4.05, hike_prob=0.68, change_bps=42.0),
            ],
        ),
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


def test_render_concentration_writes_png(tmp_path):
    out = tmp_path / "conc.png"
    render_concentration(out, _snapshot().index_contributions, {})
    assert out.exists() and out.stat().st_size > 0


def test_render_concentration_dispatches(tmp_path):
    spec = ChartSpec(id="conc", module="concentration")
    path = render_chart(spec, _snapshot(), tmp_path)
    assert path.exists() and path.stat().st_size > 0
    assert path.name == "conc.png"


def test_render_concentration_rejects_empty(tmp_path):
    with pytest.raises(ValueError, match="index_contributions"):
        render_concentration(tmp_path / "x.png", [])


def test_render_catalyst_timeline_writes_png(tmp_path):
    out = tmp_path / "cal.png"
    params = {
        "title": "本週催化劑",
        "events": [
            {"date": "6/23", "label": "PMI 初值"},
            {"date": "6/24", "label": "Micron 財報"},
            {"date": "6/25", "label": "核心 PCE", "highlight": True},
        ],
    }
    render_catalyst_timeline(out, params)
    assert out.exists() and out.stat().st_size > 0


def test_render_catalyst_timeline_dispatches(tmp_path):
    spec = ChartSpec(
        id="cal",
        module="catalyst_timeline",
        params={"events": [{"date": "6/25", "label": "核心 PCE", "highlight": True}]},
    )
    path = render_chart(spec, _snapshot(), tmp_path)
    assert path.exists() and path.stat().st_size > 0
    assert path.name == "cal.png"


def test_render_catalyst_timeline_rejects_empty_events(tmp_path):
    with pytest.raises(ValueError, match="events"):
        render_catalyst_timeline(tmp_path / "x.png", {"events": []})


def test_render_catalyst_timeline_rejects_event_without_label(tmp_path):
    with pytest.raises(ValueError, match="label"):
        render_catalyst_timeline(tmp_path / "x.png", {"events": [{"date": "6/25"}]})


def test_render_global_equity_overnight_writes_png(tmp_path):
    out = tmp_path / "glob.png"
    render_global_equity_overnight(out, _snapshot().global_equities, {})
    assert out.exists() and out.stat().st_size > 0


def test_render_global_equity_overnight_dispatches(tmp_path):
    spec = ChartSpec(id="glob", module="global_equity_overnight")
    path = render_chart(spec, _snapshot(), tmp_path)
    assert path.exists() and path.stat().st_size > 0
    assert path.name == "glob.png"


def test_render_global_equity_overnight_rejects_empty(tmp_path):
    with pytest.raises(ValueError, match="global_equity_overnight"):
        render_global_equity_overnight(tmp_path / "x.png", [])


def test_render_fed_path_futures_writes_png(tmp_path):
    out = tmp_path / "fed.png"
    render_fed_path(out, _snapshot().fed_path, {})
    assert out.exists() and out.stat().st_size > 0


def test_render_fed_path_curve_writes_png(tmp_path):
    out = tmp_path / "fedc.png"
    fp = FedPath(
        source="curve",
        current_rate=3.63,
        points=[
            FedPathPoint(label="3個月", implied_rate=3.85, change_bps=22.0),
            FedPathPoint(label="2年", implied_rate=4.24, change_bps=61.0),
        ],
    )
    render_fed_path(out, fp, {})
    assert out.exists() and out.stat().st_size > 0


def test_render_fed_path_dispatches(tmp_path):
    spec = ChartSpec(id="fed", module="fed_path")
    path = render_chart(spec, _snapshot(), tmp_path)
    assert path.exists() and path.stat().st_size > 0
    assert path.name == "fed.png"


def test_render_fed_path_rejects_empty(tmp_path):
    with pytest.raises(ValueError, match="fed_path"):
        render_fed_path(tmp_path / "x.png", None)


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
