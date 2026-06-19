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
    brief: Brief, *, total_seconds: float = 30.0, max_charts: int = 6, max_cards: int = 3
) -> Script:
    """回傳一份合法、**高視覺變化**的直式短影片講稿。

    結構:開場幾張「時事標題卡」快速閃過(top item 標題)→ 圖表段,每段一張圖配完整解說
    (內容 + 代表意義,脫離畫面也聽得懂)。圖序依 regime 動態增減,一定含指數與槓桿教育。
    正式版由雲端 routine 編輯式產出(含網路梗/時事梗)。
    """
    items = sorted(brief.items, key=lambda it: it.materiality, reverse=True)
    regime = brief.regime
    lev_note = (
        brief.leverage_context[0].edu_note
        if brief.leverage_context
        else "高槓桿在高波動下侵蝕複利。"
    )

    def explain(i: int) -> str:
        if i < len(items):
            return f"{items[i].headline}。{items[i].audience_value}"
        return ""

    # 圖表段候選(依序);index 開頭、leverage 結尾,中間依 regime 增減
    ordered: list[tuple[str, str]] = [
        (
            "index_overnight_grid",
            explain(0) or "先看隔夜四大指數怎麼收,漲跌幅一次看懂今天的盤勢基調。",
        ),
        ("breadth", "看類股輪動,誰領漲、誰殺尾盤,就知道資金往哪跑、這波漲是不是全面。"),
        ("vix_regime", "VIX 是市場的恐慌溫度計,它在這個位置,代表現在大家有多緊張或多鬆懈。"),
    ]
    if regime.rates == "rising":
        ordered.append(
            ("yield_curve", explain(1) or "殖利率曲線的形狀,藏著市場對利率和景氣的預期,別小看它。")
        )
    ordered.append(
        ("rates_trend", "十年期殖利率是全球資產的定價錨,它一動,股票和債券的估值都得重算。")
    )
    if regime.stock_bond_corr == "positive":
        ordered.append(
            ("stock_bond_corr", "股債正相關時,股票殺低、債券不一定救你,傳統分散風險的效果會打折。")
        )
    ordered.append(
        ("econ_print", explain(2) or "最新總經數據直接牽動 Fed 下一步,也牽動你的荷包。")
    )
    ordered.append(("leverage_decay", f"{lev_note}槓桿放大的不只是報酬,還有風險。"))

    # 超過上限時保留開頭(指數)與結尾(槓桿教育),修剪中間
    if len(ordered) > max_charts:
        ordered = [ordered[0], *ordered[1:-1][: max_charts - 2], ordered[-1]]

    charts = [ChartSpec(id=f"c{i}", module=module) for i, (module, _) in enumerate(ordered)]

    # 開場時事標題卡(取 top item 標題,快速閃過,增加視覺變化)
    card_texts = [it.headline for it in items[:max_cards]]
    card_dur = 2.0
    charts_total = max(total_seconds - len(card_texts) * card_dur, float(len(ordered)))
    per_chart = charts_total / len(ordered)

    segments: list[Segment] = []
    cursor = 0.0
    for text in card_texts:
        segments.append(
            Segment(vo=text, headline=text, t_start=round(cursor, 3), duration=card_dur)
        )
        cursor += card_dur
    for i, (_, vo) in enumerate(ordered):
        segments.append(
            Segment(
                vo=vo, chart_id=charts[i].id, t_start=round(cursor, 3), duration=round(per_chart, 3)
            )
        )
        cursor += per_chart

    return Script(segments=segments, charts=charts)
