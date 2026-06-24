"""選圖:驗證 LLM 選的模組/參數,從快照取真實數據,呼叫對應 render。

``module`` 的合法性由 ``ChartSpec`` 的 Literal 在驗證期擋下(非法模組進不來);
這裡負責把合法 spec 對應到 render 函式,並用真實快照數據渲染。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from loguru import logger

from pmb.charts.library import (
    render_breadth,
    render_catalyst_timeline,
    render_concentration,
    render_econ_print,
    render_fed_path,
    render_global_equity_overnight,
    render_index_overnight_grid,
    render_leverage_decay,
    render_overnight_vs_close,
    render_rates_trend,
    render_stock_bond_corr,
    render_vix_regime,
    render_yield_curve,
)
from pmb.schemas.chart import ChartSpec
from pmb.schemas.snapshot import Snapshot

# 模組 → 渲染器(從快照取對應數據)。新增模組只要在這註冊,不動 render_chart(開放封閉)。
_RENDERERS: dict[str, Callable[[Path, Snapshot, dict], Path]] = {
    "leverage_decay": lambda out, snap, params: render_leverage_decay(
        out, snap.leverage_math, params
    ),
    # 盤前影片:四大指數「隔夜期貨」是今天的領先訊號(現貨是昨日收盤,屬回顧)
    "index_overnight_grid": lambda out, snap, params: render_index_overnight_grid(
        out, snap.futures or snap.indices, params
    ),
    # 昨收(現貨)回顧 vs 今日盤前(期貨)領先訊號並列對照
    "overnight_vs_close": lambda out, snap, params: render_overnight_vs_close(
        out, snap.indices, snap.futures, params
    ),
    # 海外/亞歐股隔夜對照:指出今日盤前外溢的 contagion 源頭
    "global_equity_overnight": lambda out, snap, params: render_global_equity_overnight(
        out, snap.global_equities, params
    ),
    # 市場隱含 Fed 政策路徑(期貨優先、Treasury 曲線保底)
    "fed_path": lambda out, snap, params: render_fed_path(out, snap.fed_path, params),
    "vix_regime": lambda out, snap, params: render_vix_regime(out, snap.vix_history, params),
    "yield_curve": lambda out, snap, params: render_yield_curve(out, snap.yield_curve, params),
    "breadth": lambda out, snap, params: render_breadth(out, snap.sector_returns, params),
    # 漲幅集中度:基準指數前 N 大成分股的貢獻(權重 × 報酬)
    "concentration": lambda out, snap, params: render_concentration(
        out, snap.index_contributions, params
    ),
    "rates_trend": lambda out, snap, params: render_rates_trend(out, snap.tnx_history, params),
    "stock_bond_corr": lambda out, snap, params: render_stock_bond_corr(
        out, snap.stock_bond_corr_history, params
    ),
    "econ_print": lambda out, snap, params: render_econ_print(out, snap.econ_series, params),
    # 本週催化劑時間軸:事件由研究 LLM 經 params 提供(排程事實,非市場數字),不取快照
    "catalyst_timeline": lambda out, snap, params: render_catalyst_timeline(out, params),
}


def implemented_modules() -> list[str]:
    """目前已實作的圖表模組清單。"""
    return sorted(_RENDERERS)


def render_chart(spec: ChartSpec, snapshot: Snapshot, out_dir: str | Path) -> Path:
    """依 ``spec`` 渲染單一圖表,回傳 PNG 路徑。未實作的模組明確拋 NotImplementedError。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{spec.id}.png"

    renderer = _RENDERERS.get(spec.module)
    if renderer is None:
        raise NotImplementedError(f"圖表模組 {spec.module} 尚未實作")
    renderer(out_path, snapshot, spec.params)

    logger.info("渲染圖表 {} → {}", spec.module, out_path)
    return out_path
