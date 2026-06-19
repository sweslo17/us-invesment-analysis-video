"""NYSE 交易行事曆測試,以已知真實日期驗證(pandas_market_calendars 為本地資料)。"""

import datetime as dt

from pmb.data.calendar import (
    is_trading_day,
    most_recent_trading_day,
    next_trading_day,
    previous_trading_day,
)


def test_regular_weekday_is_trading_day():
    # 2026-06-18 週四,平常交易日
    assert is_trading_day(dt.date(2026, 6, 18)) is True


def test_weekend_is_not_trading_day():
    # 2026-06-20 週六
    assert is_trading_day(dt.date(2026, 6, 20)) is False


def test_new_year_holiday_is_not_trading_day():
    assert is_trading_day(dt.date(2026, 1, 1)) is False


def test_juneteenth_friday_is_not_trading_day():
    # 2026-06-19 週五 = Juneteenth,NYSE 休市
    assert is_trading_day(dt.date(2026, 6, 19)) is False


def test_previous_trading_day_skips_holiday_and_weekend():
    # 週六 6/20 往前:6/19 Juneteenth 休市 → 落在週四 6/18
    assert previous_trading_day(dt.date(2026, 6, 20)) == dt.date(2026, 6, 18)


def test_most_recent_trading_day_on_holiday_returns_prior_session():
    assert most_recent_trading_day(dt.date(2026, 6, 19)) == dt.date(2026, 6, 18)


def test_most_recent_trading_day_on_session_returns_same_day():
    assert most_recent_trading_day(dt.date(2026, 6, 18)) == dt.date(2026, 6, 18)


def test_next_trading_day_skips_weekend_and_holiday():
    # 週六 6/20 往後:6/22 週一(6/19 Juneteenth 已過、週末跳過)
    assert next_trading_day(dt.date(2026, 6, 20)) == dt.date(2026, 6, 22)


def test_next_trading_day_from_session_is_strictly_after():
    # 週四 6/18 的下一交易日:週五 6/19 休市 → 週一 6/22
    assert next_trading_day(dt.date(2026, 6, 18)) == dt.date(2026, 6, 22)
