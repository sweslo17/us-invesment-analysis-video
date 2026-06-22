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


def render_overnight_vs_close(
    out_path: str | Path,
    indices: Sequence[Quote],
    futures: Sequence[Quote],
    params: dict | None = None,
) -> Path:
    """昨收回顧(現貨)vs 今日盤前(期貨)對照長條:左為上一交易日收盤漲跌,右為隔夜期貨。

    盤前影片的核心對照——現貨漲跌是「上一交易日的回顧」,期貨漲跌才是「今天的領先訊號」。
    兩者並列,一眼看出隔夜情緒是延續(同向)還是反轉(背向)。依位置配對 indices/futures
    (資料層四大指數順序一致:S&P / Nasdaq / Dow / Russell)。
    """
    out_path = Path(out_path)
    pairs = list(zip(indices, futures, strict=False))
    names = [(spot.name or spot.ticker) for spot, _ in pairs]
    close_pcts = [spot.change_pct if spot.change_pct is not None else 0.0 for spot, _ in pairs]
    fut_pcts = [fut.change_pct if fut.change_pct is not None else 0.0 for _, fut in pairs]

    xs = list(range(len(pairs)))
    width = 0.38
    fig, ax = plt.subplots(figsize=(7, 4.5))
    bars_close = ax.bar(
        [i - width / 2 for i in xs],
        close_pcts,
        width,
        color=[_POSITIVE if p >= 0 else _NEGATIVE for p in close_pcts],
        alpha=0.5,
        hatch="//",
        edgecolor="white",
    )
    bars_fut = ax.bar(
        [i + width / 2 for i in xs],
        fut_pcts,
        width,
        color=[_POSITIVE if p >= 0 else _NEGATIVE for p in fut_pcts],
    )
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(xs)
    ax.set_xticklabels(names, fontsize=9)
    ax.set_ylabel("漲跌 (%)")
    ax.set_title("昨收回顧 vs 今日盤前期貨")
    ax.legend(
        handles=[
            Patch(facecolor="#999", alpha=0.5, hatch="//", edgecolor="white", label="昨收(回顧)"),
            Patch(facecolor="#999", label="今日盤前(期貨)"),
        ],
        fontsize=8,
    )
    for bars, pcts in ((bars_close, close_pcts), (bars_fut, fut_pcts)):
        for bar, pct in zip(bars, pcts, strict=True):
            ax.annotate(
                f"{pct:+.2f}%",
                (bar.get_x() + bar.get_width() / 2, pct),
                ha="center",
                va="bottom" if pct >= 0 else "top",
                fontsize=8,
            )
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def render_concentration(
    out_path: str | Path,
    contributions: Sequence[IndexContribution],
    params: dict | None = None,
) -> Path:
    """漲幅集中度:前 N 大成分股對基準指數當日漲跌的貢獻(權重 × 報酬,單位百分點)。

    凸顯漲幅有多集中——少數權值股扛了多少。依貢獻由大到小排,綠正紅負;附上前 N 大
    合計貢獻,讓「窄反彈」一眼看穿。數字全來自快照的 IndexContribution。
    """
    out_path = Path(out_path)
    params = params or {}
    if not contributions:
        raise ValueError("concentration 需要非空的 index_contributions")

    top_n = int(params.get("top_n", 10))
    ordered = sorted(contributions, key=lambda c: c.contribution, reverse=True)[:top_n]
    labels = [c.name or c.ticker for c in ordered]
    values = [c.contribution for c in ordered]
    colors = [_POSITIVE if v >= 0 else _NEGATIVE for v in values]
    total = sum(values)
    title = str(params.get("title", "S&P 500 漲幅貢獻(前 N 大成分股)"))

    fig, ax = plt.subplots(figsize=(7, 4.5))
    # barh 由下而上;反轉讓貢獻最大者在最上方
    ax.barh(labels[::-1], values[::-1], color=colors[::-1])
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_xlabel("對指數的貢獻(百分點)")
    ax.set_title(title)
    for i, v in enumerate(values[::-1]):
        ax.annotate(
            f"{v:+.3f}",
            (v, i),
            va="center",
            ha="left" if v >= 0 else "right",
            fontsize=8,
        )
    ax.annotate(
        f"前 {len(ordered)} 大合計貢獻 {total:+.2f} 百分點",
        xy=(0.98, 0.04),
        xycoords="axes fraction",
        ha="right",
        va="bottom",
        fontsize=8,
        color="#555",
    )
    ax.margins(x=0.18)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def render_catalyst_timeline(
    out_path: str | Path,
    params: dict | None = None,
) -> Path:
    """本週催化劑時間軸:把排程事件(PMI / 財報 / PCE…)依序鋪在一條時間線上。

    事件由研究 LLM 經 ``params`` 提供(日期屬排程事實、非市場數字),格式::

        {"events": [{"date": "6/25", "label": "核心 PCE", "highlight": true}, ...],
         "title": "本週催化劑"}

    每個 event 至少要有 ``label``;``date`` 與 ``highlight`` 可選。非法/空 events 直接擋下。
    """
    params = params or {}
    events = params.get("events")
    if not isinstance(events, list) or not events:
        raise ValueError("catalyst_timeline 需要非空的 params.events")
    max_events = 8
    truncated = max(0, len(events) - max_events)
    events = events[:max_events]

    out_path = Path(out_path)
    labels: list[str] = []
    dates: list[str] = []
    highlights: list[bool] = []
    for ev in events:
        if not isinstance(ev, dict) or not ev.get("label"):
            raise ValueError("catalyst_timeline 的每個 event 需含 label")
        labels.append(str(ev["label"]))
        dates.append(str(ev.get("date", "")))
        highlights.append(bool(ev.get("highlight", False)))

    title = str(params.get("title", "本週催化劑"))
    if truncated:
        title = f"{title}(另有 {truncated} 項未顯示)"

    xs = list(range(len(labels)))
    levels = [1.0, -1.0, 1.7, -1.7]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.axhline(0, color="#555", linewidth=1.2, zorder=1)
    for i, (x, label, date, hi) in enumerate(zip(xs, labels, dates, highlights, strict=True)):
        level = levels[i % len(levels)]
        color = "#ef6c00" if hi else "#1565c0"
        ax.plot([x, x], [0, level], color=color, linewidth=1.3, zorder=1)
        ax.scatter([x], [0], s=140 if hi else 70, color=color, edgecolor="white", zorder=3)
        text = f"{date}\n{label}" if date else label
        ax.annotate(
            text,
            (x, level),
            ha="center",
            va="bottom" if level > 0 else "top",
            fontsize=9,
            fontweight="bold" if hi else "normal",
            color=color,
        )
    ax.set_xlim(-0.6, len(labels) - 0.4)
    ax.set_ylim(-2.5, 2.5)
    ax.set_title(title)
    ax.axis("off")
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
    ax.set_ylabel("隔夜漲跌 (%)")
    ax.set_title("四大指數・盤前期貨")
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
