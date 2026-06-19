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

from pmb.schemas.snapshot import (  # noqa: E402
    EconSeries,
    LeverageMath,
    Quote,
    SectorReturn,
    YieldPoint,
)

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


def render_vix_regime(
    out_path: str | Path,
    vix_history: Sequence[float],
    params: dict | None = None,
) -> Path:
    """VIX 近期走勢 + 區間門檻帶(預設 15/20/30),標示恐慌/平靜分界。"""
    out_path = Path(out_path)
    params = params or {}
    bands = params.get("bands", [15, 20, 30])

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(range(len(vix_history)), list(vix_history), color="#1565c0", linewidth=2)
    for band in bands:
        ax.axhline(band, color="#888", linestyle="--", linewidth=0.8)
        ax.annotate(str(band), (0, band), color="#888", fontsize=8, va="bottom")
    if vix_history:
        ax.annotate(
            f"{vix_history[-1]:.1f}",
            (len(vix_history) - 1, vix_history[-1]),
            fontsize=10,
            fontweight="bold",
            ha="right",
        )
    ax.set_xlabel("近期交易日")
    ax.set_ylabel("VIX")
    ax.set_title("VIX 波動率與區間門檻")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def render_yield_curve(
    out_path: str | Path,
    yield_curve: Sequence[YieldPoint],
    params: dict | None = None,
) -> Path:
    """美債殖利率曲線(各到期點的殖利率),標出倒掛或正斜率。"""
    out_path = Path(out_path)
    points = sorted(yield_curve, key=lambda p: p.months)
    labels = [p.label for p in points]
    values = [p.value for p in points]

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(range(len(points)), values, marker="o", color="#6a1b9a", linewidth=2)
    ax.set_xticks(range(len(points)))
    ax.set_xticklabels(labels)
    for i, v in enumerate(values):
        ax.annotate(f"{v:.2f}%", (i, v), fontsize=9, va="bottom", ha="center")
    ax.set_xlabel("到期")
    ax.set_ylabel("殖利率 (%)")
    ax.set_title("美債殖利率曲線")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def render_breadth(
    out_path: str | Path,
    sector_returns: Sequence[SectorReturn],
    params: dict | None = None,
) -> Path:
    """各類股當日報酬水平長條(市場廣度/輪動),綠漲紅跌、由高到低排序。"""
    out_path = Path(out_path)
    ordered = sorted(sector_returns, key=lambda s: s.change_pct)
    names = [s.sector for s in ordered]
    pcts = [s.change_pct for s in ordered]
    colors = [_POSITIVE if p >= 0 else _NEGATIVE for p in pcts]

    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.barh(names, pcts, color=colors)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_xlabel("當日漲跌 (%)")
    ax.set_title("類股表現(市場廣度)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def render_rates_trend(
    out_path: str | Path,
    tnx_history: Sequence[float],
    params: dict | None = None,
) -> Path:
    """美國 10 年期公債殖利率走勢,標最新值。"""
    out_path = Path(out_path)
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(range(len(tnx_history)), list(tnx_history), color="#00695c", linewidth=2)
    if tnx_history:
        ax.annotate(
            f"{tnx_history[-1]:.2f}%",
            (len(tnx_history) - 1, tnx_history[-1]),
            fontsize=10,
            fontweight="bold",
            ha="right",
        )
    ax.set_xlabel("近期交易日")
    ax.set_ylabel("10Y 殖利率 (%)")
    ax.set_title("10 年期公債殖利率走勢")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def render_stock_bond_corr(
    out_path: str | Path,
    corr_history: Sequence[float],
    params: dict | None = None,
) -> Path:
    """股債滾動相關係數走勢:正相關時分散效果失效(對所有投資人重要)。"""
    out_path = Path(out_path)
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(range(len(corr_history)), list(corr_history), color="#ad1457", linewidth=2)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_ylim(-1.05, 1.05)
    if corr_history:
        ax.annotate(
            f"{corr_history[-1]:+.2f}",
            (len(corr_history) - 1, corr_history[-1]),
            fontsize=10,
            fontweight="bold",
            ha="right",
        )
    ax.set_xlabel("近期交易日")
    ax.set_ylabel("股債相關係數")
    ax.set_title("股債滾動相關性")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def render_econ_print(
    out_path: str | Path,
    econ_series: EconSeries | None,
    params: dict | None = None,
) -> Path:
    """總經序列走勢,highlight 最新一筆數據。"""
    out_path = Path(out_path)
    fig, ax = plt.subplots(figsize=(7, 4))
    values = list(econ_series.values) if econ_series else []
    label = econ_series.label if econ_series else "總經序列"
    ax.plot(range(len(values)), values, color="#ef6c00", linewidth=2)
    if values:
        ax.scatter([len(values) - 1], [values[-1]], color="#ef6c00", zorder=5)
        ax.annotate(
            f"{values[-1]:.2f}",
            (len(values) - 1, values[-1]),
            fontsize=10,
            fontweight="bold",
            ha="right",
        )
    ax.set_xlabel("近期期數")
    ax.set_ylabel(label)
    ax.set_title(f"{label}(highlight 最新)")
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
