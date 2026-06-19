"""圖表模組庫測試:spec 驗證、render 產 PNG、選圖 dispatch、非法模組/參數被擋。"""

import datetime as dt

import pytest
from pydantic import ValidationError

from pmb.charts.library import render_index_overnight_grid, render_leverage_decay
from pmb.charts.select import render_chart
from pmb.schemas.chart import ChartSpec
from pmb.schemas.snapshot import LeverageMath, Quote, Snapshot


def _snapshot() -> Snapshot:
    return Snapshot(
        session_date=dt.date(2026, 6, 18),
        generated_at=dt.datetime(2026, 6, 18, 12, 0, tzinfo=dt.UTC),
        indices=[
            Quote(ticker="^GSPC", name="S&P 500", last=7500.0, previous_close=7420.0),
            Quote(ticker="^IXIC", name="Nasdaq", last=26517.0, previous_close=26020.0),
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


# --- 選圖 dispatch ---

def test_render_chart_dispatches_to_module(tmp_path):
    spec = ChartSpec(id="lev", module="leverage_decay")
    path = render_chart(spec, _snapshot(), tmp_path)
    assert path.exists() and path.stat().st_size > 0
    assert path.name == "lev.png"


def test_render_chart_rejects_unimplemented_module(tmp_path):
    # econ_print 在 Literal 內合法,但本階段尚未實作 → 應明確擋下
    spec = ChartSpec(id="e", module="econ_print")
    with pytest.raises(NotImplementedError):
        render_chart(spec, _snapshot(), tmp_path)
