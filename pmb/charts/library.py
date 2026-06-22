"""圖表模組庫:每個模組一支 render 函式,吃真實數據、輸出 PNG。

純渲染邏輯,數據由呼叫端(select)從快照取出後傳入。為直式短影片(9:16)設計:
圖一律**直式**畫布、字級放大,合成時置於畫面中段,手機上也看得清楚。圖本身**不畫
標題**——合成端會把 ``seg.title`` 以大字烤在畫面頂部,避免雙標題、把版面留給數據。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 無 GUI 後端,供批次渲染

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from pmb.schemas.snapshot import (  # noqa: E402
    EconSeries,
    IndexContribution,
    LeverageMath,
    Quote,
    SectorReturn,
    YieldPoint,
)

_POSITIVE = "#2e7d32"
_NEGATIVE = "#c62828"

# 直式短影片畫布:圖比例約 9:10(填滿手機畫面中段),解析度與字級都放大
_FIG: tuple[float, float] = (9.0, 10.0)
_DPI = 120
# 數值標註字級(rcParams 管 label/tick/legend;annotate 要另外指定才放得大)
_ANNOT = 26
_ANNOT_BIG = 30
# 圖不畫標題:合成時畫面頂部會以 seg.title 烤上大字標題(避免雙標題、把版面留給數據)


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


def _apply_chart_style() -> None:
    """直式短影片用:整體放大字級,讓手機上看得清楚(又大又清楚)。"""
    plt.rcParams.update(
        {
            "font.size": 24,
            "axes.labelsize": 30,
            "xtick.labelsize": 26,
            "ytick.labelsize": 26,
            "legend.fontsize": 24,
            "figure.dpi": _DPI,
        }
    )


_configure_cjk_font()
_apply_chart_style()


def _finalize(fig, out_path: str | Path) -> Path:
    """統一收尾:tight_layout + 存檔 + 關閉。圖不畫標題(標題由合成端烤在畫面頂部)。"""
    out_path = Path(out_path)
    fig.tight_layout()
    fig.savefig(out_path, dpi=_DPI)
    plt.close(fig)
    return out_path


def render_leverage_decay(
    out_path: str | Path,
    leverage_math: Sequence[LeverageMath],
    params: dict | None = None,
) -> Path:
    """各市場的波動耗損曲線:固定槓桿越高,年化複利被磨掉越多(教育,非建議)。"""
    leverages = [1, 2, 3]
    fig, ax = plt.subplots(figsize=_FIG)
    for m in leverage_math:
        drags = [m.drag_1x * 100, m.drag_2x * 100, m.drag_3x * 100]
        ax.plot(
            leverages,
            drags,
            marker="o",
            linewidth=3,
            markersize=11,
            label=f"{m.market}(波動 {m.realized_vol * 100:.0f}%)",
        )
    ax.set_xticks(leverages)
    ax.set_xlabel("固定槓桿倍數")
    ax.set_ylabel("年化波動耗損 (%)")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)
    return _finalize(fig, out_path)


def render_vix_regime(
    out_path: str | Path,
    vix_history: Sequence[float],
    params: dict | None = None,
) -> Path:
    """VIX 近期走勢 + 區間門檻帶(預設 15/20/30),標示恐慌/平靜分界。"""
    params = params or {}
    bands = params.get("bands", [15, 20, 30])

    fig, ax = plt.subplots(figsize=_FIG)
    ax.plot(range(len(vix_history)), list(vix_history), color="#1565c0", linewidth=3)
    for band in bands:
        ax.axhline(band, color="#888", linestyle="--", linewidth=1.2)
        ax.annotate(str(band), (0, band), color="#888", fontsize=_ANNOT, va="bottom")
    if vix_history:
        ax.annotate(
            f"{vix_history[-1]:.1f}",
            (len(vix_history) - 1, vix_history[-1]),
            fontsize=_ANNOT_BIG,
            fontweight="bold",
            ha="right",
        )
    ax.set_xlabel("近期交易日")
    ax.set_ylabel("VIX")
    ax.grid(True, alpha=0.3)
    return _finalize(fig, out_path)


def render_yield_curve(
    out_path: str | Path,
    yield_curve: Sequence[YieldPoint],
    params: dict | None = None,
) -> Path:
    """美債殖利率曲線(各到期點的殖利率),標出倒掛或正斜率。"""
    points = sorted(yield_curve, key=lambda p: p.months)
    labels = [p.label for p in points]
    values = [p.value for p in points]

    fig, ax = plt.subplots(figsize=_FIG)
    ax.plot(range(len(points)), values, marker="o", color="#6a1b9a", linewidth=3, markersize=11)
    ax.set_xticks(range(len(points)))
    ax.set_xticklabels(labels)
    for i, v in enumerate(values):
        ax.annotate(f"{v:.2f}%", (i, v), fontsize=_ANNOT, va="bottom", ha="center")
    ax.set_xlabel("到期")
    ax.set_ylabel("殖利率 (%)")
    ax.margins(y=0.15)
    ax.grid(True, alpha=0.3)
    return _finalize(fig, out_path)


def render_breadth(
    out_path: str | Path,
    sector_returns: Sequence[SectorReturn],
    params: dict | None = None,
) -> Path:
    """各類股當日報酬水平長條(市場廣度/輪動),綠漲紅跌、由高到低排序。"""
    ordered = sorted(sector_returns, key=lambda s: s.change_pct)
    names = [s.sector for s in ordered]
    pcts = [s.change_pct for s in ordered]
    colors = [_POSITIVE if p >= 0 else _NEGATIVE for p in pcts]

    fig, ax = plt.subplots(figsize=_FIG)
    ax.barh(names, pcts, color=colors)
    ax.axvline(0, color="black", linewidth=1.0)
    ax.set_xlabel("當日漲跌 (%)")
    ax.margins(x=0.16)
    return _finalize(fig, out_path)


def render_rates_trend(
    out_path: str | Path,
    tnx_history: Sequence[float],
    params: dict | None = None,
) -> Path:
    """美國 10 年期公債殖利率走勢,標最新值。"""
    fig, ax = plt.subplots(figsize=_FIG)
    ax.plot(range(len(tnx_history)), list(tnx_history), color="#00695c", linewidth=3)
    if tnx_history:
        ax.annotate(
            f"{tnx_history[-1]:.2f}%",
            (len(tnx_history) - 1, tnx_history[-1]),
            fontsize=_ANNOT_BIG,
            fontweight="bold",
            ha="right",
        )
    ax.set_xlabel("近期交易日")
    ax.set_ylabel("10Y 殖利率 (%)")
    ax.grid(True, alpha=0.3)
    return _finalize(fig, out_path)


def render_stock_bond_corr(
    out_path: str | Path,
    corr_history: Sequence[float],
    params: dict | None = None,
) -> Path:
    """股債滾動相關係數走勢:正相關時分散效果失效(對所有投資人重要)。"""
    fig, ax = plt.subplots(figsize=_FIG)
    ax.plot(range(len(corr_history)), list(corr_history), color="#ad1457", linewidth=3)
    ax.axhline(0, color="black", linewidth=1.0)
    ax.set_ylim(-1.05, 1.05)
    if corr_history:
        ax.annotate(
            f"{corr_history[-1]:+.2f}",
            (len(corr_history) - 1, corr_history[-1]),
            fontsize=_ANNOT_BIG,
            fontweight="bold",
            ha="right",
        )
    ax.set_xlabel("近期交易日")
    ax.set_ylabel("股債相關係數")
    ax.grid(True, alpha=0.3)
    return _finalize(fig, out_path)


def render_econ_print(
    out_path: str | Path,
    econ_series: EconSeries | None,
    params: dict | None = None,
) -> Path:
    """總經序列走勢,highlight 最新一筆數據。"""
    fig, ax = plt.subplots(figsize=_FIG)
    values = list(econ_series.values) if econ_series else []
    label = econ_series.label if econ_series else "總經序列"
    ax.plot(range(len(values)), values, color="#ef6c00", linewidth=3)
    if values:
        ax.scatter([len(values) - 1], [values[-1]], color="#ef6c00", s=120, zorder=5)
        ax.annotate(
            f"{values[-1]:.2f}",
            (len(values) - 1, values[-1]),
            fontsize=_ANNOT_BIG,
            fontweight="bold",
            ha="right",
        )
    ax.set_xlabel("近期期數")
    ax.set_ylabel(label)
    ax.grid(True, alpha=0.3)
    return _finalize(fig, out_path)


def render_overnight_vs_close(
    out_path: str | Path,
    indices: Sequence[Quote],
    futures: Sequence[Quote],
    params: dict | None = None,
) -> Path:
    """昨收回顧(現貨)vs 今日盤前(期貨)對照長條:斜線為上一交易日收盤,實心為隔夜期貨。

    盤前影片的核心對照——現貨漲跌是「上一交易日的回顧」,期貨漲跌才是「今天的領先訊號」。
    兩者並列,一眼看出隔夜情緒是延續(同向)還是反轉(背向)。依位置配對 indices/futures
    (資料層四大指數順序一致:S&P / Nasdaq / Dow / Russell)。
    """
    pairs = list(zip(indices, futures, strict=False))
    names = [(spot.name or spot.ticker) for spot, _ in pairs]
    close_pcts = [spot.change_pct if spot.change_pct is not None else 0.0 for spot, _ in pairs]
    fut_pcts = [fut.change_pct if fut.change_pct is not None else 0.0 for _, fut in pairs]

    ys = list(range(len(pairs)))
    height = 0.38
    fig, ax = plt.subplots(figsize=_FIG)
    bars_close = ax.barh(
        [i + height / 2 for i in ys],
        close_pcts,
        height,
        color=[_POSITIVE if p >= 0 else _NEGATIVE for p in close_pcts],
        alpha=0.5,
        hatch="//",
        edgecolor="white",
    )
    bars_fut = ax.barh(
        [i - height / 2 for i in ys],
        fut_pcts,
        height,
        color=[_POSITIVE if p >= 0 else _NEGATIVE for p in fut_pcts],
    )
    ax.axvline(0, color="black", linewidth=1.0)
    ax.set_yticks(ys)
    ax.set_yticklabels(names)
    ax.set_xlabel("漲跌 (%)")
    # 圖例放在圖區上方(橫排),避開長條與數值標註
    ax.legend(
        handles=[
            Patch(facecolor="#999", alpha=0.5, hatch="//", edgecolor="white", label="昨收(斜線)"),
            Patch(facecolor="#999", label="盤前(實心)"),
        ],
        loc="lower center",
        bbox_to_anchor=(0.5, 1.0),
        ncol=2,
        frameon=False,
        fontsize=22,
        columnspacing=1.2,
        handletextpad=0.5,
    )
    for bars, pcts in ((bars_close, close_pcts), (bars_fut, fut_pcts)):
        for bar, pct in zip(bars, pcts, strict=True):
            ax.annotate(
                f"{pct:+.2f}%",
                (pct, bar.get_y() + bar.get_height() / 2),
                va="center",
                ha="left" if pct >= 0 else "right",
                fontsize=_ANNOT,
            )
    ax.margins(x=0.2)
    ax.grid(True, axis="x", alpha=0.3)
    return _finalize(fig, out_path)


def render_concentration(
    out_path: str | Path,
    contributions: Sequence[IndexContribution],
    params: dict | None = None,
) -> Path:
    """漲幅集中度:前 N 大成分股對基準指數當日漲跌的貢獻(權重 × 報酬,單位百分點)。

    凸顯漲幅有多集中——少數權值股扛了多少。依貢獻由大到小排,綠正紅負;附上前 N 大
    合計貢獻,讓「窄反彈」一眼看穿。數字全來自快照的 IndexContribution。
    """
    params = params or {}
    if not contributions:
        raise ValueError("concentration 需要非空的 index_contributions")

    top_n = int(params.get("top_n", 10))
    ordered = sorted(contributions, key=lambda c: c.contribution, reverse=True)[:top_n]
    labels = [c.name or c.ticker for c in ordered]
    values = [c.contribution for c in ordered]
    colors = [_POSITIVE if v >= 0 else _NEGATIVE for v in values]
    total = sum(values)

    fig, ax = plt.subplots(figsize=_FIG)
    # barh 由下而上;反轉讓貢獻最大者在最上方
    ax.barh(labels[::-1], values[::-1], color=colors[::-1])
    ax.axvline(0, color="black", linewidth=1.0)
    ax.set_xlabel("對指數的貢獻(百分點)")
    for i, v in enumerate(values[::-1]):
        ax.annotate(
            f"{v:+.3f}",
            (v, i),
            va="center",
            ha="left" if v >= 0 else "right",
            fontsize=_ANNOT,
        )
    ax.annotate(
        f"前 {len(ordered)} 大合計貢獻 {total:+.2f} 百分點",
        xy=(0.98, 0.02),
        xycoords="axes fraction",
        ha="right",
        va="bottom",
        fontsize=_ANNOT,
        color="#555",
    )
    ax.margins(x=0.2)
    return _finalize(fig, out_path)


def render_catalyst_timeline(
    out_path: str | Path,
    params: dict | None = None,
) -> Path:
    """本週催化劑時間軸(直式):排程事件(PMI / 財報 / PCE…)由上而下鋪在一條垂直線上。

    事件由研究 LLM 經 ``params`` 提供(日期屬排程事實、非市場數字),格式::

        {"events": [{"date": "6/25", "label": "核心 PCE", "highlight": true}, ...],
         "title": "本週催化劑"}

    每個 event 至少要有 ``label``;``date`` 與 ``highlight`` 可選。非法/空 events 直接擋下。
    """
    params = params or {}
    events = params.get("events")
    if not isinstance(events, list) or not events:
        raise ValueError("catalyst_timeline 需要非空的 params.events")
    max_events = 7
    truncated = max(0, len(events) - max_events)
    events = events[:max_events]

    labels: list[str] = []
    dates: list[str] = []
    highlights: list[bool] = []
    for ev in events:
        if not isinstance(ev, dict) or not ev.get("label"):
            raise ValueError("catalyst_timeline 的每個 event 需含 label")
        labels.append(str(ev["label"]))
        dates.append(str(ev.get("date", "")))
        highlights.append(bool(ev.get("highlight", False)))

    n = len(labels)
    fig, ax = plt.subplots(figsize=_FIG)
    ax.plot([0, 0], [-0.5, n - 0.5], color="#555", linewidth=2.4, zorder=1)
    for i, (label, date, hi) in enumerate(zip(labels, dates, highlights, strict=True)):
        y = n - 1 - i  # 第一個事件放最上面
        color = "#ef6c00" if hi else "#1565c0"
        ax.scatter([0], [y], s=420 if hi else 230, color=color, edgecolor="white", zorder=3)
        text = f"{date}  {label}" if date else label
        ax.annotate(
            text,
            (0.16, y),
            ha="left",
            va="center",
            fontsize=_ANNOT_BIG if hi else _ANNOT,
            fontweight="bold" if hi else "normal",
            color=color,
        )
    ax.set_xlim(-0.4, 2.4)
    ax.set_ylim(-0.7, n - 0.3)
    ax.axis("off")
    if truncated:
        ax.annotate(
            f"另有 {truncated} 項未顯示",
            xy=(0.5, 0.01),
            xycoords="axes fraction",
            ha="center",
            va="bottom",
            fontsize=_ANNOT - 4,
            color="#888",
        )
    return _finalize(fig, out_path)


def render_index_overnight_grid(
    out_path: str | Path,
    indices: Sequence[Quote],
    params: dict | None = None,
) -> Path:
    """主要指數的隔夜/當日漲跌長條圖,綠漲紅跌。"""
    names = [q.name or q.ticker for q in indices]
    pcts = [q.change_pct if q.change_pct is not None else 0.0 for q in indices]
    colors = [_POSITIVE if p >= 0 else _NEGATIVE for p in pcts]

    fig, ax = plt.subplots(figsize=_FIG)
    bars = ax.bar(names, pcts, color=colors)
    ax.axhline(0, color="black", linewidth=1.0)
    ax.set_ylabel("隔夜漲跌 (%)")
    ax.tick_params(axis="x", labelrotation=20)
    for bar, pct in zip(bars, pcts, strict=True):
        ax.annotate(
            f"{pct:+.2f}%",
            (bar.get_x() + bar.get_width() / 2, pct),
            ha="center",
            va="bottom" if pct >= 0 else "top",
            fontsize=_ANNOT,
        )
    ax.margins(y=0.16)
    return _finalize(fig, out_path)
