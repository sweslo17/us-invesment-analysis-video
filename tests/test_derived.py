"""衍生指標(股債相關、已實現波動、廣度)的純函式測試。"""

import pandas as pd
import pytest

from pmb.data.derived import (
    pct_above_ma,
    pct_positive,
    realized_volatility,
    stock_bond_correlation,
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
