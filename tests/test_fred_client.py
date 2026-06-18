"""FRED client 測試:用注入的假 series provider 驗證最新觀測抽取 / retry / 跳過。"""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from pmb.data.fred import FredClient
from pmb.schemas.snapshot import FredObservation


def _series(values, dates):
    return pd.Series(values, index=pd.to_datetime(dates))


def test_get_latest_returns_last_observation_with_prior():
    s = _series([4.1, 4.2, 4.3], ["2026-04-01", "2026-05-01", "2026-06-01"])
    client = FredClient(series_provider=lambda sid: s)
    obs = client.get_latest("DGS10", "10Y Treasury", units="percent")
    assert isinstance(obs, FredObservation)
    assert obs.value == pytest.approx(4.3)
    assert obs.date == dt.date(2026, 6, 1)
    assert obs.prior_value == pytest.approx(4.2)
    assert obs.units == "percent"


def test_get_latest_skips_trailing_nan():
    s = _series([4.1, 4.2, np.nan], ["2026-04-01", "2026-05-01", "2026-06-01"])
    client = FredClient(series_provider=lambda sid: s)
    obs = client.get_latest("DGS10", "10Y Treasury")
    assert obs.value == pytest.approx(4.2)
    assert obs.date == dt.date(2026, 5, 1)
    assert obs.prior_value == pytest.approx(4.1)


def test_get_latest_prior_is_none_with_single_observation():
    s = _series([4.2], ["2026-05-01"])
    client = FredClient(series_provider=lambda sid: s)
    obs = client.get_latest("X", "x")
    assert obs.value == pytest.approx(4.2)
    assert obs.prior_value is None


def test_get_latest_retries_then_succeeds():
    calls = {"n": 0}
    s = _series([1.0, 2.0], ["2026-01-01", "2026-02-01"])

    def flaky(sid):
        calls["n"] += 1
        if calls["n"] < 2:
            raise ConnectionError("transient")
        return s

    client = FredClient(series_provider=flaky, retries=3, retry_delay=0)
    obs = client.get_latest("X", "x")
    assert obs.value == pytest.approx(2.0)
    assert calls["n"] == 2


def test_get_observations_skips_failing_series():
    s = _series([1.0], ["2026-01-01"])

    def provider(sid):
        if sid == "BAD":
            raise ValueError("no such series")
        return s

    client = FredClient(series_provider=provider, retries=1, retry_delay=0)
    out = client.get_observations([("GOOD", "Good", None), ("BAD", "Bad", None)])
    assert [o.series_id for o in out] == ["GOOD"]


def test_default_provider_requires_api_key():
    client = FredClient(retries=1, retry_delay=0)  # 無 key、無注入 provider
    with pytest.raises(RuntimeError):
        client.get_latest("DGS10", "10Y Treasury")
