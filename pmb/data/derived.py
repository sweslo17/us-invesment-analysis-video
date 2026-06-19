"""衍生市場指標(自算)——股債相關性、已實現波動率、市場廣度。

全部是純函式:吃 pandas 價格序列,回傳數值。供 ``snapshot`` 組裝市場 regime
的數值輸入(LLM 只負責把數值轉成文字判斷,不自行產生數字)。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _log_returns(prices: pd.Series) -> pd.Series:
    """日對數報酬,去掉因 shift 產生的 NaN。"""
    return np.log(prices / prices.shift(1)).dropna()


def realized_volatility(
    prices: pd.Series,
    window: int = 20,
    periods_per_year: int = 252,
) -> float:
    """年化已實現波動率(以分數表示,例如 0.18 = 18%)。

    取最近 ``window`` 筆日對數報酬的樣本標準差,乘上 ``sqrt(periods_per_year)``。
    報酬筆數不足 2 筆時回傳 NaN。
    """
    rets = _log_returns(prices).tail(window)
    if len(rets) < 2:
        return float("nan")
    return float(rets.std(ddof=1) * np.sqrt(periods_per_year))


def stock_bond_correlation(
    stock_prices: pd.Series,
    bond_prices: pd.Series,
    window: int = 20,
) -> float:
    """股債日報酬的滾動相關係數(取最近 ``window`` 筆,回傳最新值)。

    對齊兩邊報酬、去 NaN 後計算 Pearson 相關;有效筆數不足 2 筆時回傳 NaN。
    """
    s = stock_prices.pct_change()
    b = bond_prices.pct_change()
    paired = pd.concat([s, b], axis=1).dropna().tail(window)
    if len(paired) < 2:
        return float("nan")
    return float(paired.iloc[:, 0].corr(paired.iloc[:, 1]))


def vol_target_leverage(realized_vol: float, target_vol: float = 0.15) -> float:
    """波動目標槓桿:維持 ``target_vol`` 風險水準對應的曝險 = target_vol / realized_vol。

    波動越高、合理曝險越低(高波動環境連 1x 都可能超過風險預算)。realized_vol 為 0
    時無法定義,回傳 NaN。純教育用,不含買賣建議。
    """
    if realized_vol <= 0:
        return float("nan")
    return target_vol / realized_vol


def volatility_drag(realized_vol: float, leverage: float) -> float:
    """固定槓桿的年化波動耗損 ≈ L²σ²/2(對複利成長的拖累)。

    耗損隨槓桿平方放大,這就是固定高槓桿在高波動環境侵蝕複利的原因。
    """
    return (leverage**2) * (realized_vol**2) / 2.0


def pct_above_ma(prices: pd.DataFrame, window: int = 50) -> float:
    """市場廣度:最後一日收在自身 ``window`` 期均線之上的比例(0~1)。"""
    ma = prices.rolling(window).mean().iloc[-1]
    last = prices.iloc[-1]
    return float((last > ma).mean())


def pct_positive(prices: pd.DataFrame) -> float:
    """市場廣度:最後一日相對前一日上漲的比例(0~1)。"""
    last_return = prices.pct_change().iloc[-1]
    return float((last_return > 0).mean())
