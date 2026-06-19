"""當日研究報告(markdown)——規格 §7.1。

把同一份 ``brief`` 展開成面向一般讀者的長文;槓桿教育的具體數字由 ``snapshot.leverage_math``
注入(數字走資料層,不靠 LLM 文字)。每份報告固定帶「非投資建議」免責。
"""

from __future__ import annotations

from pmb.schemas.brief import Brief
from pmb.schemas.snapshot import Snapshot

_DISCLAIMER = (
    "本內容為市場資訊與風險教育,**非投資建議**。"
    "數字來自公開資料(FRED / yfinance),不構成任何買賣建議。"
)

_HORIZON_LABEL = {"ST": "短期", "MT": "中期", "LT": "長期"}
_CONF_LABEL = {"confirmed": "已確認", "developing": "發展中", "single-print": "單一數據"}


def render_report(brief: Brief, snapshot: Snapshot | None = None) -> str:
    """把 brief(+ 選配快照)展開成 markdown 報告。"""
    lines: list[str] = []
    lines.append(f"# 盤前市場觀察 · {brief.date}")
    lines.append("")
    lines.append(f"> {_DISCLAIMER}")
    lines.append("")

    items = sorted(brief.items, key=lambda it: it.materiality, reverse=True)

    # 整體盤勢:以最重要的一條當引子
    lines.append("## 整體盤勢")
    if items:
        lead = items[0]
        lines.append(f"**{lead.headline}**")
        lines.append("")
        lines.append(lead.audience_value)
    else:
        lines.append("今日無重大變化。")
    lines.append("")

    # 各大指數
    if brief.indices:
        lines.append("## 各大指數")
        for idx in brief.indices:
            drivers = "、".join(idx.drivers) if idx.drivers else ""
            tail = f" — {drivers}" if drivers else ""
            lines.append(f"- **{idx.name}**:{idx.level:,.2f}({idx.overnight_pct:+.2f}%){tail}")
        lines.append("")

    # 市場 regime
    r = brief.regime
    lines.append("## 市場 regime")
    lines.append(
        f"- 波動:{r.vol} ｜ 利率:{r.rates} ｜ 股債相關:{r.stock_bond_corr} ｜ 廣度:{r.breadth}"
    )
    lines.append("")

    # 最適槓桿教育(全市場視角,非商品建議)
    if brief.leverage_context:
        lines.append("## 最適槓桿教育(非投資建議)")
        math_by_market = {m.market: m for m in (snapshot.leverage_math if snapshot else [])}
        for ctx in brief.leverage_context:
            lines.append(f"- **{ctx.market}**:{ctx.edu_note}")
            m = math_by_market.get(ctx.market)
            if m is not None:
                lines.append(
                    f"  - 已實現波動 {m.realized_vol * 100:.1f}%、"
                    f"波動目標槓桿 ≈ {m.vol_target_leverage:.2f}x、"
                    f"固定 3x 年化波動耗損 ≈ {m.drag_3x * 100:.0f}%"
                )
        lines.append("")

    # 今日重點(完整 items)
    lines.append("## 今日重點")
    for it in items:
        horizon = _HORIZON_LABEL.get(it.horizon, it.horizon)
        conf = _CONF_LABEL.get(it.confidence, it.confidence)
        lines.append(f"### {it.headline}")
        lines.append(f"_{horizon}・{conf}・重要性 {it.materiality}/5_")
        lines.append("")
        lines.append(it.audience_value)
        if it.sources:
            srcs = " ".join(f"[來源]({s.url})" for s in it.sources)
            lines.append("")
            lines.append(srcs)
        lines.append("")

    # thesis 與當日 delta
    if brief.thesis_delta.changed and brief.thesis_delta.summary:
        lines.append("## 中長期 thesis 更新")
        lines.append(brief.thesis_delta.summary)
        lines.append("")

    lines.append("---")
    lines.append(_DISCLAIMER)
    return "\n".join(lines)
