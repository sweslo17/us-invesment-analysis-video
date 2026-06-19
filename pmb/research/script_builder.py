"""從 brief 確定性建構 30 秒講稿(供 pipeline / dry-run)。

正式日更的講稿與選圖由雲端 routine(agentic Claude)依編輯判斷產出;此處是確定性
後備:依 regime 規則選圖、把最重要的判斷切成段,確保 pipeline 永遠有一份合法、
圖文對得上的 Script。數字不入講稿(影片合成時由資料層注入)。
"""

from __future__ import annotations

from pmb.schemas.brief import Brief
from pmb.schemas.chart import ChartSpec
from pmb.schemas.script import Script, Segment

# 圖表段頂部主題標題(放畫面上方,與底部字幕分開)
_CHART_TITLES: dict[str, str] = {
    "index_overnight_grid": "四大指數",
    "breadth": "類股輪動",
    "vix_regime": "恐慌指數 VIX",
    "yield_curve": "殖利率曲線",
    "rates_trend": "10 年期殖利率",
    "stock_bond_corr": "股債相關",
    "econ_print": "總經數據",
    "leverage_decay": "槓桿耗損",
}

_DEFAULT_INTRO = "30 秒看懂今天美股盤前"
_DEFAULT_OUTRO = "每天盤前見,記得追蹤;非投資建議"


def build_script_from_brief(
    brief: Brief,
    *,
    total_seconds: float = 30.0,
    max_charts: int = 6,
    max_cards: int = 3,
    intro_slogan: str = _DEFAULT_INTRO,
    outro_slogan: str = _DEFAULT_OUTRO,
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
    card_texts = [it.headline for it in items[:max_cards]]

    # 時長配置:卡片/slogan 各 2s 快閃,其餘平分給圖表段
    card_dur = 2.0
    n_cardlike = len(card_texts) + 2  # + 開頭/結尾 slogan
    charts_total = max(total_seconds - n_cardlike * card_dur, float(len(ordered)))
    per_chart = charts_total / len(ordered)

    def card(text: str) -> Segment:
        return Segment(vo=text, headline=text, t_start=0.0, duration=card_dur)

    def chart_seg(idx: int, module: str, vo: str) -> Segment:
        return Segment(
            vo=vo,
            chart_id=charts[idx].id,
            title=_CHART_TITLES.get(module),
            t_start=0.0,
            duration=per_chart,
        )

    # 編排:開頭 slogan →(時事卡、圖表交錯)→ 結尾 slogan,讓視覺一直變
    sequence: list[Segment] = [card(intro_slogan)]
    ci = 0
    for idx, (module, vo) in enumerate(ordered):
        if ci < len(card_texts):
            sequence.append(card(card_texts[ci]))
            ci += 1
        sequence.append(chart_seg(idx, module, vo))
    while ci < len(card_texts):
        sequence.append(card(card_texts[ci]))
        ci += 1
    sequence.append(card(outro_slogan))

    cursor = 0.0
    for seg in sequence:
        seg.t_start = round(cursor, 3)
        seg.duration = round(seg.duration, 3)
        cursor += seg.duration

    return Script(segments=sequence, charts=charts)
