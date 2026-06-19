"""衍生指標(股債相關、已實現波動、廣度)的純函式測試。"""

import pandas as pd
import pytest

from pmb.data.derived import (
    pct_above_ma,
    pct_positive,
    realized_volatility,
    rolling_stock_bond_correlation,
    stock_bond_correlation,
    vol_target_leverage,
    volatility_drag,
)


def test_realized_volatility_constant_price_is_zero():
    prices = pd.Series([100.0] * 30)
    assert realized_volatility(prices, window=20) == pytest.approx(0.0)


def test_realized_volatility_constant_log_return_is_zero():
    # 穩定指數成長:每日報酬相同 → 報酬的波動為 0(波動 ≠ 趨勢)
    prices = pd.Series([100.0 * (1.01**i) for i in range(30)])
    assert realized_volatility(prices, window=20) == pytest.approx(0.0, abs=1e-9)


def test_realized_volatility_higher_dispersion_gives_higher_vol():
    calm = pd.Series([100, 100.5, 100, 100.5, 100, 100.5, 100, 100.5, 100, 100.5, 100], dtype=float)
    wild = pd.Series([100, 110, 95, 115, 90, 120, 88, 125, 85, 130, 80], dtype=float)
    assert realized_volatility(wild, window=10) > realized_volatility(calm, window=10)


def test_stock_bond_correlation_identical_series_is_one():
    s = pd.Series([100, 102, 101, 105, 103, 108, 107, 110], dtype=float)
    assert stock_bond_correlation(s, s.copy(), window=6) == pytest.approx(1.0)


def test_stock_bond_correlation_opposite_returns_is_minus_one():
    s = pd.Series([100, 102, 101, 105, 103, 108, 107, 110], dtype=float)
    bond_ret = -s.pct_change()
    bond = (1 + bond_ret.fillna(0)).cumprod() * 100
    assert stock_bond_correlation(s, bond, window=6) == pytest.approx(-1.0)


def test_rolling_stock_bond_correlation_returns_series_ending_near_one():
    s = pd.Series([100, 102, 101, 105, 103, 108, 107, 110], dtype=float)
    out = rolling_stock_bond_correlation(s, s.copy(), window=4)
    assert len(out) >= 1
    assert out.iloc[-1] == pytest.approx(1.0)


def test_pct_above_ma_counts_fraction_above_moving_average():
    # 4 檔;最後一列剛好 3 檔在其 3 期均線之上
    df = pd.DataFrame(
        {
            "A": [10, 10, 10, 20],  # 20 > mean(10,10,20)=13.3 → 上
            "B": [10, 10, 10, 20],  # 上
            "C": [10, 10, 10, 20],  # 上
            "D": [20, 20, 20, 5],   # 5 < mean(20,20,5)=15 → 下
        },
        dtype=float,
    )
    assert pct_above_ma(df, window=3) == pytest.approx(0.75)


def test_vol_target_leverage_equals_one_when_vol_matches_target():
    assert vol_target_leverage(0.15, target_vol=0.15) == pytest.approx(1.0)


def test_vol_target_leverage_halves_when_vol_doubles():
    # 波動翻倍 → 維持同樣風險的曝險砍半
    assert vol_target_leverage(0.30, target_vol=0.15) == pytest.approx(0.5)


def test_vol_target_leverage_allows_above_one_in_calm_markets():
    assert vol_target_leverage(0.075, target_vol=0.15) == pytest.approx(2.0)


def test_volatility_drag_scales_with_leverage_squared():
    # L²σ²/2:σ=0.16 → 1x≈1.28%、3x≈11.52%(9 倍)
    assert volatility_drag(0.16, leverage=1) == pytest.approx(0.0128)
    assert volatility_drag(0.16, leverage=3) == pytest.approx(0.1152)


def test_volatility_drag_zero_leverage_is_zero():
    assert volatility_drag(0.16, leverage=0) == pytest.approx(0.0)


def test_pct_positive_counts_fraction_up_on_day():
    df = pd.DataFrame(
        {
            "A": [100, 101],  # 漲
            "B": [100, 99],   # 跌
            "C": [100, 102],  # 漲
            "D": [100, 100],  # 平 → 不算正
        },
        dtype=float,
    )
    assert pct_positive(df) == pytest.approx(0.5)
