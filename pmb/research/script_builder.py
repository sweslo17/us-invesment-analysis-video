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


def build_script_from_brief(brief: Brief, *, total_seconds: float = 30.0) -> Script:
    """回傳一份合法的 30 秒講稿:指數 → regime 重點 → 槓桿教育,三段三圖。"""
    items = sorted(brief.items, key=lambda it: it.materiality, reverse=True)
    lead = items[0] if items else None
    lev_note = (
        brief.leverage_context[0].edu_note
        if brief.leverage_context
        else "高槓桿在高波動下侵蝕複利。"
    )

    charts = [
        ChartSpec(id="idx", module="index_overnight_grid"),
        ChartSpec(id="regime", module=_regime_chart_module(brief.regime)),
        ChartSpec(id="lev", module="leverage_decay"),
    ]

    vos = [
        lead.headline if lead else "隔夜主要指數動向。",
        lead.audience_value if lead else "今天的市場 regime。",
        lev_note,
    ]

    per = total_seconds / len(charts)
    segments: list[Segment] = []
    for i, (chart, vo) in enumerate(zip(charts, vos, strict=True)):
        segments.append(
            Segment(vo=vo, chart_id=chart.id, t_start=round(i * per, 3), duration=round(per, 3))
        )

    return Script(segments=segments, charts=charts)
