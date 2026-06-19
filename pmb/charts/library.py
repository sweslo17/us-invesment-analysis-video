"""圖表模組庫:每個模組一支 render 函式,吃真實數據、輸出 PNG。

純渲染邏輯,數據由呼叫端(select)從快照取出後傳入。本階段先實作兩支:
``leverage_decay``(吃 leverage_math)與 ``index_overnight_grid``(吃指數報價)。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 無 GUI 後端,供批次渲染

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from pmb.schemas.snapshot import LeverageMath, Quote  # noqa: E402

_POSITIVE = "#2e7d32"
_NEGATIVE = "#c62828"


def _configure_cjk_font() -> None:
    """挑一個系統可用的 CJK 字型,避免中文變成豆腐方塊。"""
    candidates = [
        "PingFang TC",
        "Heiti TC",
        "Arial Unicode MS",
        "Noto Sans CJK TC",
        "Microsoft JhengHei",
    ]
    available = {f.name for f in font_manager.fontManager.ttflist}
    chosen = next((c for c in candidates if c in available), None)
    if chosen:
        plt.rcParams["font.sans-serif"] = [chosen, "sans-serif"]
    plt.rcParams["axes.unicode_minus"] = False


_configure_cjk_font()


def render_leverage_decay(
    out_path: str | Path,
    leverage_math: Sequence[LeverageMath],
    params: dict | None = None,
) -> Path:
    """各市場的波動耗損曲線:固定槓桿越高,年化複利被磨掉越多(教育,非建議)。"""
    out_path = Path(out_path)
    leverages = [1, 2, 3]
    fig, ax = plt.subplots(figsize=(7, 4))
    for m in leverage_math:
        drags = [m.drag_1x * 100, m.drag_2x * 100, m.drag_3x * 100]
        ax.plot(leverages, drags, marker="o", label=f"{m.market}(波動 {m.realized_vol * 100:.0f}%)")
    ax.set_xticks(leverages)
    ax.set_xlabel("固定槓桿倍數")
    ax.set_ylabel("年化波動耗損 (%)")
    ax.set_title("波動耗損:槓桿越高,複利被磨掉越多")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def render_index_overnight_grid(
    out_path: str | Path,
    indices: Sequence[Quote],
    params: dict | None = None,
) -> Path:
    """主要指數的隔夜/當日漲跌長條圖,綠漲紅跌。"""
    out_path = Path(out_path)
    names = [q.name or q.ticker for q in indices]
    pcts = [q.change_pct if q.change_pct is not None else 0.0 for q in indices]
    colors = [_POSITIVE if p >= 0 else _NEGATIVE for p in pcts]

    fig, ax = plt.subplots(figsize=(7, 4))
    bars = ax.bar(names, pcts, color=colors)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_ylabel("漲跌 (%)")
    ax.set_title("主要指數")
    for bar, pct in zip(bars, pcts, strict=True):
        ax.annotate(
            f"{pct:+.2f}%",
            (bar.get_x() + bar.get_width() / 2, pct),
            ha="center",
            va="bottom" if pct >= 0 else "top",
            fontsize=9,
        )
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path
