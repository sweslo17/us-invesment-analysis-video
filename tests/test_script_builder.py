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


def test_build_script_mixes_cards_and_charts_about_30s():
    script = build_script_from_brief(_brief())
    assert script.total_duration == pytest.approx(30.0, abs=0.1)  # 每段四捨五入會有微小誤差

    cards = [s for s in script.segments if s.headline]
    chart_segs = [s for s in script.segments if s.chart_id]
    assert len(cards) >= 1  # 有時事標題卡(視覺變化)
    assert len(chart_segs) == len(script.charts)  # 圖表段一一對應 charts
    assert len(script.segments) >= 6

    modules = {c.module for c in script.charts}
    assert "index_overnight_grid" in modules
    assert "leverage_decay" in modules


def test_intro_card_carries_date_and_outro_is_daily_couplet():
    script = build_script_from_brief(_brief())
    assert "2026-06-18" in (script.segments[0].tag or "")  # 首卡帶日期
    last = script.segments[-1]
    assert last.headline and "\n" in last.headline  # 對句兩行
    assert last.tag and "不知道有沒有說過" in last.tag


def test_rising_rates_picks_yield_curve_as_regime_chart():
    script = build_script_from_brief(_brief(rates="rising"))
    assert "yield_curve" in {c.module for c in script.charts}


def test_elevated_vol_picks_vix_regime():
    script = build_script_from_brief(_brief(rates="stable", vol="elevated"))
    assert "vix_regime" in {c.module for c in script.charts}
