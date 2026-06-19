"""FRED 總經序列 client(確定性資料來源)。

包裝 fredapi:取單一序列最新觀測值(含前一筆作對比)。低階取數透過可注入的
series provider,方便測試與替換;對外呼叫包 retry。需 ``FRED_API_KEY``。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

import pandas as pd
from loguru import logger

from pmb.data.retry import call_with_retry
from pmb.schemas.snapshot import FredObservation

SeriesProvider = Callable[[str], pd.Series]


def _make_default_provider(api_key: str | None) -> SeriesProvider:
    def provider(series_id: str) -> pd.Series:
        if not api_key:
            raise RuntimeError("缺少 FRED_API_KEY,無法向 FRED 取數")
        from fredapi import Fred

        return Fred(api_key=api_key).get_series(series_id)

    return provider


class FredClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        series_provider: SeriesProvider | None = None,
        retries: int = 3,
        retry_delay: float = 1.0,
    ) -> None:
        self._series_provider = series_provider or _make_default_provider(api_key)
        self.retries = retries
        self.retry_delay = retry_delay

    def get_latest(self, series_id: str, label: str, units: str | None = None) -> FredObservation:
        series = call_with_retry(
            lambda: self._series_provider(series_id),
            retries=self.retries,
            delay=self.retry_delay,
            what=f"FRED series {series_id}",
        )
        clean = series.dropna()
        if clean.empty:
            raise ValueError(f"FRED 序列 {series_id} 無有效觀測值")
        value = float(clean.iloc[-1])
        date = clean.index[-1].date()
        prior_value = float(clean.iloc[-2]) if len(clean) >= 2 else None
        return FredObservation(
            series_id=series_id,
            label=label,
            value=value,
            date=date,
            units=units,
            prior_value=prior_value,
        )

    def get_recent_values(self, series_id: str, n: int = 24) -> list[float]:
        """序列最近 ``n`` 筆有效觀測值(去 NaN),供 econ_print 圖表畫趨勢。"""
        series = call_with_retry(
            lambda: self._series_provider(series_id),
            retries=self.retries,
            delay=self.retry_delay,
            what=f"FRED series {series_id}",
        )
        clean = series.dropna().tail(n)
        return [float(x) for x in clean]

    def get_observations(
        self, specs: Iterable[tuple[str, str, str | None]]
    ) -> list[FredObservation]:
        """逐序列取最新觀測;單一序列失敗(retry 用盡)記錄並跳過。

        ``specs`` 為 ``(series_id, label, units)`` 序列。
        """
        out: list[FredObservation] = []
        for series_id, label, units in specs:
            try:
                out.append(self.get_latest(series_id, label, units))
            except Exception as exc:  # noqa: BLE001
                logger.error("略過 FRED 序列 {}:{}", series_id, exc)
        return out
