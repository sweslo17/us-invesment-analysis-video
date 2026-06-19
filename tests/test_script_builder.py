"""講稿建構測試:從 brief 確定性產出合法 Script(供 pipeline / dry-run)。"""

import pytest

from pmb.research.script_builder import build_script_from_brief
from pmb.schemas.brief import Brief


def _brief(rates="rising", vol="low", corr="positive") -> Brief:
    return Brief.model_validate(
        {
            "date": "2026-06-18",
            "leverage_context": [{"market": "S&P 500", "edu_note": "波動下合理曝險約 1x。"}],
            "regime": {"vol": vol, "rates": rates, "stock_bond_corr": corr, "breadth": "mixed"},
            "items": [
                {
                    "headline": "Fed 轉鷹",
                    "horizon": "LT",
                    "vs_thesis": "new",
                    "materiality": 5,
                    "confidence": "confirmed",
                    "audience_value": "利率牽動一切。",
                },
                {
                    "headline": "半導體領漲",
                    "horizon": "ST",
                    "vs_thesis": "new",
                    "materiality": 3,
                    "confidence": "confirmed",
                    "audience_value": "AI 主線還在。",
                },
            ],
            "thesis_delta": {"changed": False},
            "lead_horizon": "LT",
        }
    )


def test_build_script_is_dense_and_about_30s():
    script = build_script_from_brief(_brief())
    assert script.total_duration == pytest.approx(30.0)
    # 短影片要高資訊密度:至少 6 張圖/段
    assert len(script.segments) >= 6
    assert len(script.charts) == len(script.segments)
    modules = {c.module for c in script.charts}
    assert "index_overnight_grid" in modules
    assert "leverage_decay" in modules
    # segment 綁定都對得上(能建構就代表通過 Script 的交叉驗證)
    chart_ids = {c.id for c in script.charts}
    assert all(seg.chart_id in chart_ids for seg in script.segments)


def test_rising_rates_picks_yield_curve_as_regime_chart():
    script = build_script_from_brief(_brief(rates="rising"))
    assert "yield_curve" in {c.module for c in script.charts}


def test_elevated_vol_picks_vix_regime():
    script = build_script_from_brief(_brief(rates="stable", vol="elevated"))
    assert "vix_regime" in {c.module for c in script.charts}
