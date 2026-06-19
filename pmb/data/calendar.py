"""NYSE 交易行事曆(確定性)。

包裝 ``pandas_market_calendars`` 的 NYSE 行事曆,提供休市判斷與最近交易日查詢。
資料為套件內建(無外部網路),休市日 / 週末 / 國定假日皆涵蓋。
"""

from __future__ import annotations

import datetime as dt

import pandas_market_calendars as mcal
from loguru import logger

_NYSE = mcal.get_calendar("NYSE")


def is_trading_day(date: dt.date) -> bool:
    """``date`` 是否為 NYSE 正常交易日(非週末、非休市日)。"""
    schedule = _NYSE.schedule(start_date=str(date), end_date=str(date))
    return not schedule.empty


def previous_trading_day(date: dt.date, *, lookback_days: int = 10) -> dt.date:
    """``date`` 之前(不含當日)最近的一個交易日。

    往前看 ``lookback_days`` 天搜尋(足以跨越任何週末 + 連假)。
    """
    start = date - dt.timedelta(days=lookback_days)
    valid = _NYSE.valid_days(start_date=str(start), end_date=str(date - dt.timedelta(days=1)))
    if len(valid) == 0:
        raise ValueError(f"{date} 前 {lookback_days} 天內找不到交易日;請加大 lookback_days")
    return valid[-1].date()


def most_recent_trading_day(date: dt.date) -> dt.date:
    """``date`` 當日若開市則回傳當日,否則回傳前一個交易日。"""
    if is_trading_day(date):
        return date
    prior = previous_trading_day(date)
    logger.debug("{} 非交易日,回退至最近交易日 {}", date, prior)
    return prior


def next_trading_day(date: dt.date, *, lookahead_days: int = 10) -> dt.date:
    """``date`` 之後(不含當日)最近的一個交易日。

    往後看 ``lookahead_days`` 天搜尋(足以跨越任何週末 + 連假)。
    """
    end = date + dt.timedelta(days=lookahead_days)
    valid = _NYSE.valid_days(start_date=str(date + dt.timedelta(days=1)), end_date=str(end))
    if len(valid) == 0:
        raise ValueError(f"{date} 後 {lookahead_days} 天內找不到交易日;請加大 lookahead_days")
    return valid[0].date()
