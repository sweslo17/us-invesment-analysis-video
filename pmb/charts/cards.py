"""時事標題卡:全屏大字 + 彩色底的 PNG,用來在圖表之間快速閃過、增加視覺變化。

純文字(matplotlib 無法上色 emoji,所以梗靠用字而非表情符號)。
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

from pmb.charts.library import _configure_cjk_font  # noqa: E402

_configure_cjk_font()

# 高彩度配色,逐張輪替製造視覺節奏
_ACCENTS = ["#C1121F", "#0353A4", "#2A9D8F", "#E76F51", "#6A4C93", "#1B4332"]


def accent_for(index: int) -> str:
    return _ACCENTS[index % len(_ACCENTS)]


_CARD_BREAK = "，、,。!?!?;;；…)）」』】"


def _seg_width(s: str) -> float:
    return sum(1.0 if not c.isascii() else 0.55 for c in s)


def _balanced_index(s: str) -> int:
    """回傳寬度約一半的切點。"""
    half = _seg_width(s) / 2
    acc = 0.0
    for i, ch in enumerate(s):
        acc += 1.0 if not ch.isascii() else 0.55
        if acc >= half:
            return i + 1
    return max(1, len(s) // 2)


def _wrap_segment(s: str, max_units: float) -> list[str]:
    if _seg_width(s) <= max_units:
        return [s]
    # 候選切點:標點「之後」,但不可在最後一字(避免標點落單成孤兒行)
    n = len(s)
    cands = [i + 1 for i, ch in enumerate(s) if ch in _CARD_BREAK and 0 < i + 1 < n]
    target = n / 2
    split = min(cands, key=lambda p: abs(p - target)) if cands else _balanced_index(s)
    left, right = s[:split], s[split:]
    out: list[str] = []
    out += _wrap_segment(left, max_units) if _seg_width(left) > max_units else [left]
    out += _wrap_segment(right, max_units) if _seg_width(right) > max_units else [right]
    return out


def _wrap_cjk(text: str, max_units: float = 9) -> str:
    """字卡大標題斷行:保留原有換行(對句),過長時在標點或平衡點斷,避免標點落單。"""
    out: list[str] = []
    for line in text.split("\n"):
        out.extend(_wrap_segment(line, max_units) if line else [""])
    return "\n".join(out)


def render_headline_card(
    out_path: str,
    text: str,
    *,
    accent: str = "#0D1B2A",
    tag: str | None = None,
) -> str:
    """畫一張 1080×1920 的全屏標題卡。"""
    fig = plt.figure(figsize=(10.8, 19.2), dpi=100)
    fig.patch.set_facecolor(accent)
    if tag:
        fig.text(
            0.5, 0.80, tag, ha="center", va="center",
            color="#FFD166", fontsize=46, fontweight="bold",
        )
    fig.text(
        0.5, 0.5, _wrap_cjk(text), ha="center", va="center",
        color="white", fontsize=84, fontweight="bold", linespacing=1.3,
    )
    fig.savefig(out_path, facecolor=accent)
    plt.close(fig)
    return str(out_path)
