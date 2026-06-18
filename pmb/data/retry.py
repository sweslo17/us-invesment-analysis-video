"""共用的外部 endpoint retry 小工具。

資料層對外部服務(yfinance / FRED)的呼叫都可能短暫失敗,集中於此處理重試,
避免在多個 client 重複邏輯(DRY)。
"""

from __future__ import annotations

import time
from collections.abc import Callable

from loguru import logger


def call_with_retry[T](fn: Callable[[], T], *, retries: int, delay: float, what: str) -> T:
    """呼叫 ``fn``,失敗時重試;用盡後拋出最後一次例外。

    ``delay`` 為 0 時不睡(測試用)。每次失敗以 warning 記錄。
    """
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — 外部 endpoint,需吸收並重試
            last_exc = exc
            logger.warning("{} 第 {}/{} 次失敗:{}", what, attempt, retries, exc)
            if attempt < retries and delay:
                time.sleep(delay)
    assert last_exc is not None
    raise last_exc
