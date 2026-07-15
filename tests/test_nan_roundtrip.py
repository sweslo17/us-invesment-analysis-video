"""回歸:NaN 不得進入非 optional float 欄位。

根因(2026-07-15 實際故障):pydantic v2 的 model_dump_json 把 NaN 寫成 JSON `null`,
重載時非 optional 的 float 欄位收到 null 就 ValidationError。凡是 yfinance/pandas
可能回 NaN 的計算餵進這類欄位,快照就會「寫得出、讀不回」。這些測試鎖住四個源頭
在資料不足時「跳過或轉 None」,確保快照永遠可 round-trip。
"""

import datetime as dt

import numpy as np
import pandas as pd

from pmb.data.snapshot import compute_leverage_math, compute_sector_returns
from pmb.schemas.snapshot import Snapshot


def test_sector_returns_skips_nan_change_pct():
    # 只有一根收盤(pct_change 尾端為 NaN)→ 該類股應被跳過,不得產出 NaN 的 change_pct
    idx = pd.date_range("2026-07-01", periods=5, freq="D")
    histories = {
        "XLK": pd.Series([np.nan, np.nan, np.nan, np.nan, np.nan], index=idx),  # 全 NaN
        "XLF": pd.Series([20.0, 20.5, 20.4, 20.6, 20.8], index=idx),  # 正常
    }
    out = compute_sector_returns(histories, ["XLK", "XLF"])
    assert [s.sector for s in out] == ["金融"]  # NaN 的科技被跳過
    assert all(np.isfinite(s.change_pct) for s in out)


def test_leverage_math_skips_insufficient_history():
    # 只有一筆價格 → realized_volatility 回 NaN → 該市場應被跳過(不得留 NaN 欄位)
    idx = pd.date_range("2026-07-01", periods=1, freq="D")
    histories = {"^GSPC": pd.Series([100.0], index=idx)}
    out = compute_leverage_math(histories, [("^GSPC", "S&P 500")])
    assert out == []


def test_snapshot_with_nan_prone_data_roundtrips():
    # 端到端:類股全 NaN、指數只有一筆(realized_vol=NaN),建快照後 dump→load 必須成功
    # (今天 7/15 故障的正是這步:NaN change_pct 被 dump 成 null、重載爆)
    sec_idx = pd.date_range("2026-07-01", periods=5, freq="D")
    histories = {
        "XLK": pd.Series([np.nan] * 5, index=sec_idx),  # yfinance 盤前回 NaN
        "XLF": pd.Series([20.0, 20.5, 20.4, 20.6, 20.8], index=sec_idx),
        "^GSPC": pd.Series([100.0], index=sec_idx[:1]),  # 只有一筆 → realized_vol NaN
    }
    sectors = compute_sector_returns(histories, ["XLK", "XLF"])
    leverage = compute_leverage_math(histories, [("^GSPC", "S&P 500")])

    snap = Snapshot(
        session_date=dt.date(2026, 7, 15),
        generated_at=dt.datetime.now(tz=dt.UTC),
        sector_returns=sectors,
        leverage=leverage,
    )
    reloaded = Snapshot.model_validate_json(snap.model_dump_json())  # 不得拋例外
    assert reloaded.session_date == dt.date(2026, 7, 15)
    assert all(np.isfinite(s.change_pct) for s in reloaded.sector_returns)
    assert all(np.isfinite(lm.realized_vol) for lm in reloaded.leverage)


def test_list_of_float_field_also_hits_the_bug():
    # 佐證同一根因也適用 list[float]:陣列裡的 NaN 被 dump 成 null,重載即失敗。
    # (實際的 stock_bond_corr_history 安全:rolling_stock_bond_correlation 已內建 dropna)
    import pytest
    from pydantic import ValidationError

    snap = Snapshot(
        session_date=dt.date(2026, 7, 15),
        generated_at=dt.datetime.now(tz=dt.UTC),
        stock_bond_corr_history=[float("nan"), 0.2],
    )
    with pytest.raises(ValidationError):
        Snapshot.model_validate_json(snap.model_dump_json())
