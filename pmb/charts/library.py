"""圖表模組庫:每個模組一支 render 函式,吃真實數據、輸出 PNG。

純渲染邏輯,數據由呼叫端(select)從快照取出後傳入。為直式短影片(9:16)設計:
圖一律**直式**畫布、字級放大,合成時置於畫面中段,手機上也看得清楚。圖本身**不畫
標題**——合成端會把 ``seg.title`` 以大字烤在畫面頂部,避免雙標題、把版面留給數據。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 無 GUI 後端,供批次渲染

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from pmb.schemas.snapshot import (  # noqa: E402
    EconSeries,
    FedPath,
    IndexContribution,
    LeverageMath,
    Quote,
    SectorReturn,
    YieldPoint,
)

# 深色主題:圖底色 = 影片畫布色,合成後圖「長在畫面上」而非白色貼紙
_CANVAS = "#0D1B2A"  # 與 video/assemble 的 _BG 一致
_PANEL = "#13253C"  # 繪圖區稍亮一階,提供圖面邊界
_FG = "#E6EDF5"  # 主要文字
_MUTED = "#9AA8BC"  # 次要文字/註記
_ZERO = "#8FA1B8"  # 零軸/基準線
_GOLD = "#FFD166"  # 品牌強調(與標題/進度條同色)
_POSITIVE = "#2EBD85"
_NEGATIVE = "#F6465D"
# 亮色系數據色(深底可讀)
_BLUE = "#4FC3F7"
_ORANGE = "#FFB74D"
_PURPLE = "#B388FF"
_TEAL = "#4DD0E1"
_PINK = "#F48FB1"
_INDIGO = "#8C9EFF"

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
    # macOS 的 PingFang TC 沒有獨立 bold(700)字面,fontweight="bold" 會 fallback 到 600(semibold)
    # 並印出 "findfont: Failed to find font weight bold" 雜訊。渲染結果正常(semibold 看起來已夠粗),
    # 雲端 Linux 用的 Noto Sans CJK TC 本就有真 bold、不會觸發。把這條 weight-fallback 提醒降級隱藏,
    # 真正的缺字(tofu)警告走別的 logger、仍會顯示。
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)


def _apply_chart_style() -> None:
    """直式短影片用:深色主題 + 放大字級,合成後圖直接融入畫布(不再是白色貼紙)。"""
    from cycler import cycler

    plt.rcParams.update(
        {
            "font.size": 24,
            "axes.labelsize": 30,
            "xtick.labelsize": 26,
            "ytick.labelsize": 26,
            "legend.fontsize": 24,
            "figure.dpi": _DPI,
            # 深色主題:圖底 = 影片畫布色,繪圖區稍亮一階
            "figure.facecolor": _CANVAS,
            "savefig.facecolor": _CANVAS,
            "axes.facecolor": _PANEL,
            "text.color": _FG,
            "axes.labelcolor": _FG,
            "xtick.color": _FG,
            "ytick.color": _FG,
            "axes.edgecolor": "#33475E",
            "axes.linewidth": 1.2,
            "grid.color": "#FFFFFF",
            "grid.alpha": 0.10,
            "legend.facecolor": _PANEL,
            "legend.edgecolor": "#33475E",
            "legend.labelcolor": _FG,
            "axes.prop_cycle": cycler(
                color=[_BLUE, _ORANGE, _POSITIVE, _NEGATIVE, _PURPLE, _PINK]
            ),
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
    ax.plot(range(len(vix_history)), list(vix_history), color=_BLUE, linewidth=3)
    for band in bands:
        ax.axhline(band, color=_MUTED, linestyle="--", linewidth=1.2)
        ax.annotate(str(band), (0, band), color=_MUTED, fontsize=_ANNOT, va="bottom")
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
    ax.plot(range(len(points)), values, marker="o", color=_PURPLE, linewidth=3, markersize=11)
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
    ax.axvline(0, color=_ZERO, linewidth=1.2)
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
    ax.plot(range(len(tnx_history)), list(tnx_history), color=_TEAL, linewidth=3)
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
    ax.plot(range(len(corr_history)), list(corr_history), color=_PINK, linewidth=3)
    ax.axhline(0, color=_ZERO, linewidth=1.2)
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
    ax.plot(range(len(values)), values, color=_ORANGE, linewidth=3)
    if values:
        ax.scatter([len(values) - 1], [values[-1]], color=_ORANGE, s=120, zorder=5)
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
        edgecolor=_FG,
    )
    bars_fut = ax.barh(
        [i - height / 2 for i in ys],
        fut_pcts,
        height,
        color=[_POSITIVE if p >= 0 else _NEGATIVE for p in fut_pcts],
    )
    ax.axvline(0, color=_ZERO, linewidth=1.2)
    ax.set_yticks(ys)
    ax.set_yticklabels(names)
    ax.set_xlabel("漲跌 (%)")
    # 圖例放在圖區上方(橫排),避開長條與數值標註
    ax.legend(
        handles=[
            Patch(facecolor=_MUTED, alpha=0.5, hatch="//", edgecolor=_FG, label="昨收(斜線)"),
            Patch(facecolor=_MUTED, label="盤前(實心)"),
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


# 權值股中文短名(手機上一眼看懂,也避免英文全名擠壓圖面);缺映射時退回清理後的英文名
_ZH_NAMES = {
    "NVDA": "輝達", "META": "Meta", "AAPL": "蘋果", "MSFT": "微軟", "AMZN": "亞馬遜",
    "GOOGL": "Google A", "GOOG": "Google C", "AVGO": "博通", "TSLA": "特斯拉", "MU": "美光",
    "LLY": "禮來", "JPM": "摩根大通", "BRK-B": "波克夏", "UNH": "聯合健康", "XOM": "埃克森",
    "WMT": "沃爾瑪", "V": "Visa", "MA": "萬事達", "COST": "好市多", "HD": "家得寶",
    "PG": "寶僑", "JNJ": "嬌生", "ORCL": "甲骨文", "NFLX": "網飛", "AMD": "超微",
    "PLTR": "Palantir", "INTC": "英特爾", "QCOM": "高通", "TSM": "台積電 ADR", "CRM": "賽富時",
}
_NAME_NOISE = (" Incorporated", " Corporation", " Platforms", " Technologies", " Technology",
               " Holdings", " Interactive", ".com", " Inc", " Corp", " Class A", " Class B",
               " Class C", " Co", " Ltd", " PLC")


_WRAP_BREAK = "，、,。;；:：…)）」』】 "


def _wrap_units(text: str, max_units: float, max_lines: int = 2) -> str:
    """依顯示寬度換行(中文 1、英數 0.55),優先在標點/空白後斷;超過行數截斷加「…」。

    matplotlib 的 annotate 不會自動換行,長標籤(如催化劑事件)不換行會直接爆出圖框。
    """
    lines: list[str] = []
    cur: list[str] = []
    width = 0.0
    for ch in text:
        cur.append(ch)
        width += 1.0 if not ch.isascii() else 0.55
        if (ch in _WRAP_BREAK and width >= max_units * 0.6) or width >= max_units:
            lines.append("".join(cur))
            cur = []
            width = 0.0
    if cur:
        lines.append("".join(cur))
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-1] + "…"
    return "\n".join(lines)


def _short_name(ticker: str, name: str | None) -> str:
    """權值股顯示名:優先中文短名,否則剝掉公司後綴的英文名(過長再截斷)。"""
    zh = _ZH_NAMES.get(ticker.upper())
    if zh:
        return zh
    cleaned = name or ticker
    for noise in _NAME_NOISE:
        cleaned = cleaned.replace(noise, "")
    cleaned = cleaned.strip(" ,.")
    return cleaned[:12] if cleaned else ticker


def render_concentration(
    out_path: str | Path,
    contributions: Sequence[IndexContribution],
    params: dict | None = None,
) -> Path:
    """漲幅集中度:前 N 大成分股對基準指數當日漲跌的貢獻(權重 × 報酬,單位百分點)。

    凸顯漲幅有多集中——少數權值股扛了多少。依貢獻由大到小排,綠正紅負;前 N 大合計
    貢獻放在 x 軸標籤第二行,讓「窄反彈」一眼看穿。數字全來自快照的 IndexContribution。
    """
    params = params or {}
    if not contributions:
        raise ValueError("concentration 需要非空的 index_contributions")

    top_n = int(params.get("top_n", 10))
    ordered = sorted(contributions, key=lambda c: c.contribution, reverse=True)[:top_n]
    labels = [_short_name(c.ticker, c.name) for c in ordered]
    values = [c.contribution for c in ordered]
    colors = [_POSITIVE if v >= 0 else _NEGATIVE for v in values]
    total = sum(values)

    fig, ax = plt.subplots(figsize=_FIG)
    # barh 由下而上;反轉讓貢獻最大者在最上方
    ax.barh(labels[::-1], values[::-1], color=colors[::-1])
    ax.axvline(0, color=_ZERO, linewidth=1.2)
    ax.set_xlabel(f"對指數的貢獻(百分點)\n前 {len(ordered)} 大合計 {total:+.2f} 百分點")
    for i, v in enumerate(values[::-1]):
        ax.annotate(
            f"{v:+.3f}",
            (v, i),
            textcoords="offset points",
            xytext=(6 if v >= 0 else -6, 0),
            va="center",
            ha="left" if v >= 0 else "right",
            fontsize=_ANNOT,
        )
    lo = min([*values, 0.0])
    hi = max([*values, 0.0])
    span = max(hi - lo, 0.05)
    ax.set_xlim(lo - 0.55 * span, hi + 0.42 * span)
    ax.grid(True, axis="x", alpha=0.3)
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
    ax.plot([0, 0], [-0.5, n - 0.5], color="#55677F", linewidth=2.4, zorder=1)
    for i, (label, date, hi) in enumerate(zip(labels, dates, highlights, strict=True)):
        y = n - 1 - i  # 第一個事件放最上面
        color = _GOLD if hi else _BLUE
        ax.scatter([0], [y], s=420 if hi else 230, color=color, edgecolor=_CANVAS, zorder=3)
        text = f"{date}  {label}" if date else label
        # 長標籤換行(highlight 字大、每行塞得少),最多兩行、再長就截斷——
        # 版寬有限,事件寫太長時保重點而非爆框
        text = _wrap_units(text, max_units=16 if hi else 19, max_lines=2)
        ax.annotate(
            text,
            (0.16, y),
            ha="left",
            va="center",
            fontsize=_ANNOT_BIG if hi else _ANNOT,
            fontweight="bold" if hi else "normal",
            color=color,
            linespacing=1.25,
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
            color=_MUTED,
        )
    return _finalize(fig, out_path)


def render_global_equity_overnight(
    out_path: str | Path,
    indices: Sequence[Quote],
    params: dict | None = None,
) -> Path:
    """海外/亞歐股隔夜對照:各國指數最近一筆漲跌的水平長條(綠漲紅跌,由高到低排)。

    盤前影片用來「指出 contagion 從哪來」——亞股收盤 + 歐股盤中,作為今日美股盤前的外溢
    領先訊號。數字全來自快照的 ``global_equities``(各指數 ``change_pct``)。
    """
    if not indices:
        raise ValueError("global_equity_overnight 需要非空的海外指數報價")

    ordered = sorted(indices, key=lambda q: (q.change_pct if q.change_pct is not None else 0.0))
    names = [q.name or q.ticker for q in ordered]
    pcts = [q.change_pct if q.change_pct is not None else 0.0 for q in ordered]
    colors = [_POSITIVE if p >= 0 else _NEGATIVE for p in pcts]

    fig, ax = plt.subplots(figsize=_FIG)
    ax.barh(names, pcts, color=colors)
    ax.axvline(0, color=_ZERO, linewidth=1.2)
    ax.set_xlabel("最近一盤漲跌 (%)")
    # 數值標在長條尖端外側、用 offset(點)留固定間隙;x 軸範圍另留非對稱留白,
    # 確保最長的負向長條(如熔斷日 -10%)的數值也不會壓到左側 y 軸國名。
    for i, p in enumerate(pcts):
        ax.annotate(
            f"{p:+.2f}%",
            (p, i),
            textcoords="offset points",
            xytext=(6 if p >= 0 else -6, 0),
            va="center",
            ha="left" if p >= 0 else "right",
            fontsize=_ANNOT - 4,
        )
    lo = min([*pcts, 0.0])
    hi = max([*pcts, 0.0])
    span = max(hi - lo, 1.0)
    ax.set_xlim(lo - 0.50 * span, hi + 0.28 * span)
    ax.grid(True, axis="x", alpha=0.3)
    return _finalize(fig, out_path)


def render_fed_path(
    out_path: str | Path,
    fed_path: FedPath | None,
    params: dict | None = None,
) -> Path:
    """市場隱含 Fed 政策路徑:從現行政策利率往未來各節點的階梯線。

    ``source="futures"`` 時於各節點標出該次會議的升息機率;``source="curve"`` 為 Treasury
    短端保底路徑(只標利率水準)。數字全來自快照的 ``fed_path``,LLM 不產生。
    """
    if fed_path is None or not fed_path.points:
        raise ValueError("fed_path 需要非空的 FedPath")

    labels = ["現行", *[p.label for p in fed_path.points]]
    rates = [fed_path.current_rate, *[p.implied_rate for p in fed_path.points]]
    xs = list(range(len(labels)))

    fig, ax = plt.subplots(figsize=_FIG)
    ax.step(xs, rates, where="mid", color=_INDIGO, linewidth=3, marker="o", markersize=11)
    ax.axhline(fed_path.current_rate, color=_MUTED, linestyle="--", linewidth=1.4)
    for i, r in enumerate(rates):
        ax.annotate(
            f"{r:.2f}%",
            (i, r),
            fontsize=_ANNOT,
            fontweight="bold" if i == 0 else "normal",
            va="bottom",
            ha="center",
        )
    if fed_path.source == "futures":
        for i, p in enumerate(fed_path.points, start=1):
            if p.hike_prob:
                ax.annotate(
                    f"升息 {min(p.hike_prob, 9.99) * 100:.0f}%",
                    (i, rates[i]),
                    fontsize=_ANNOT - 6,
                    color=_NEGATIVE,
                    va="top",
                    ha="center",
                )
    ax.set_xticks(xs)
    ax.set_xticklabels(labels)
    ax.set_ylabel("政策利率 (%)")
    ax.margins(y=0.22)
    ax.grid(True, alpha=0.3)
    source_tag = (
        "Fed funds 期貨隱含"
        if fed_path.source == "futures"
        else "Treasury 短端隱含(含期限溢價)"
    )
    ax.annotate(
        source_tag,
        xy=(0.98, 0.02),
        xycoords="axes fraction",
        ha="right",
        va="bottom",
        fontsize=_ANNOT - 6,
        color=_MUTED,
    )
    return _finalize(fig, out_path)


def render_index_overnight_grid(
    out_path: str | Path,
    indices: Sequence[Quote],
    params: dict | None = None,
) -> Path:
    """主要指數的隔夜/當日漲跌水平長條,綠漲紅跌。

    水平排列讓「S&P 500 期貨」這類長名稱放 y 軸,不再旋轉重疊;第一個指數在最上方。
    """
    names = [q.name or q.ticker for q in indices]
    pcts = [q.change_pct if q.change_pct is not None else 0.0 for q in indices]
    colors = [_POSITIVE if p >= 0 else _NEGATIVE for p in pcts]

    fig, ax = plt.subplots(figsize=_FIG)
    ax.barh(names[::-1], pcts[::-1], color=colors[::-1])
    ax.axvline(0, color=_ZERO, linewidth=1.2)
    ax.set_xlabel("隔夜漲跌 (%)")
    for i, p in enumerate(pcts[::-1]):
        ax.annotate(
            f"{p:+.2f}%",
            (p, i),
            textcoords="offset points",
            xytext=(8 if p >= 0 else -8, 0),
            va="center",
            ha="left" if p >= 0 else "right",
            fontsize=_ANNOT,
            fontweight="bold",
        )
    lo = min([*pcts, 0.0])
    hi = max([*pcts, 0.0])
    span = max(hi - lo, 0.5)
    # 負向標註往左長,左側留白要比右側大,避免壓到 y 軸的指數名稱
    ax.set_xlim(lo - 0.62 * span, hi + 0.45 * span)
    ax.grid(True, axis="x", alpha=0.3)
    return _finalize(fig, out_path)
