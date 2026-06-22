"""圖表 spec schema(pydantic v2)——規格 §6.

``module`` 用 ``Literal`` 鎖定為固定模組庫:LLM 只能從這份封閉清單挑,不能發明圖表
類型;``params`` 由各模組於渲染時驗證。多樣性來自 driver 不同→組合不同 + 數據天天變。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

ChartModule = Literal[
    "index_overnight_grid",
    "overnight_vs_close",
    "yield_curve",
    "vix_regime",
    "rates_trend",
    "stock_bond_corr",
    "breadth",
    "econ_print",
    "leverage_decay",
    "catalyst_timeline",
]


class ChartSpec(BaseModel):
    id: str
    module: ChartModule
    params: dict[str, Any] = {}
