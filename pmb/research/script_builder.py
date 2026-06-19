"""從 brief 確定性建構 30 秒講稿(供 pipeline / dry-run)。

正式日更的講稿與選圖由雲端 routine(agentic Claude)依編輯判斷產出;此處是確定性
後備:依 regime 規則選圖、把最重要的判斷切成段,確保 pipeline 永遠有一份合法、
圖文對得上的 Script。數字不入講稿(影片合成時由資料層注入)。
"""

from __future__ import annotations

from pmb.schemas.brief import Brief, Regime
from pmb.schemas.chart import ChartSpec
from pmb.schemas.script import Script, Segment


def _regime_chart_module(regime: Regime) -> str:
    """依 regime 規則挑一張最能幫觀眾理解今天市場的圖。"""
    if regime.rates == "rising":
        return "yield_curve"
    if regime.vol in ("elevated", "high"):
        return "vix_regime"
    if regime.stock_bond_corr == "positive":
        return "stock_bond_corr"
    return "vix_regime"


def build_script_from_brief(
    brief: Brief, *, total_seconds: float = 30.0, max_segments: int = 8
) -> Script:
    """回傳一份合法、**高資訊密度**的 30 秒講稿(6–8 段、6–8 張圖,快節奏)。

    短影片靠多圖 + 快語速堆資訊量:每段一張圖、一句短旁白。圖序依 regime 動態增減,
    短語優先取 brief 的 item 標題,其餘用圖表用途短句。正式版由雲端 routine 編輯式產出。
    """
    items = sorted(brief.items, key=lambda it: it.materiality, reverse=True)
    regime = brief.regime
    lev_note = (
        brief.leverage_context[0].edu_note
        if brief.leverage_context
        else "高槓桿在高波動下侵蝕複利。"
    )

    def headline(i: int) -> str | None:
        return items[i].headline if i < len(items) else None

    # (module, 短旁白)候選,依序;每個模組最多出現一次
    candidates: list[tuple[str, str]] = [
        ("index_overnight_grid", headline(0) or "隔夜四大指數這樣收"),
        ("breadth", "看類股輪動:誰領漲、誰殺尾"),
        ("vix_regime", "波動 VIX 在這個位置"),
    ]
    if regime.rates == "rising":
        candidates.append(("yield_curve", headline(1) or "殖利率曲線:利率往哪走"))
    candidates.append(("rates_trend", "10 年期殖利率走勢"))
    if regime.stock_bond_corr == "positive":
        candidates.append(("stock_bond_corr", "股債同向,分散效果打折"))
    candidates.append(("econ_print", headline(2) or "最新總經數據"))
    candidates.append(("leverage_decay", lev_note))

    chosen: list[tuple[str, str]] = []
    seen: set[str] = set()
    for module, vo in candidates:
        if module in seen:
            continue
        seen.add(module)
        chosen.append((module, vo))
        if len(chosen) >= max_segments:
            break

    charts = [ChartSpec(id=f"c{i}", module=module) for i, (module, _) in enumerate(chosen)]
    per = total_seconds / len(chosen)
    segments = [
        Segment(vo=vo, chart_id=charts[i].id, t_start=round(i * per, 3), duration=round(per, 3))
        for i, (_, vo) in enumerate(chosen)
    ]
    return Script(segments=segments, charts=charts)
