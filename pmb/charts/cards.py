"""字卡:全屏漸層底 + (封面用)大字 PNG。

影片裡的字卡分兩層:``render_card_background`` 只畫漸層底(無文字),文字由
``video.assemble.build_card_ass`` 以 ASS 疊上去做 pop-in 動畫——靜止字卡是 Shorts
滑走的主因之一。``render_headline_card`` 把文字烤進 PNG,給 YouTube 封面用(封面是
靜態圖,可帶一個大數字 stat 抓眼球)。純文字(matplotlib 無法上色 emoji,梗靠用字)。
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import to_rgb  # noqa: E402

from pmb.charts.library import _configure_cjk_font  # noqa: E402

_configure_cjk_font()

_W, _H = 1080, 1920
_GOLD = "#FFD166"

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


def wrap_card_text(text: str, max_units: float = 9) -> list[str]:
    """字卡大標斷行:保留原有換行(對句),過長時在標點或平衡點斷,避免標點落單。

    回傳行清單(串接 == 原文去掉換行),供 PNG 與 ASS 兩種輸出共用。
    """
    out: list[str] = []
    for line in text.split("\n"):
        out.extend(_wrap_segment(line, max_units) if line else [""])
    return out


def _gradient(accent: str) -> np.ndarray:
    """直向漸層:上方為 accent 本色、往下漸深(約 45%),讓純色字卡有層次與方向感。"""
    top = np.array(to_rgb(accent))
    bottom = top * 0.55
    t = np.linspace(0.0, 1.0, _H)[:, None, None]
    return (top[None, None, :] * (1 - t) + bottom[None, None, :] * t).repeat(_W, axis=1)


def _new_canvas(accent: str):
    fig = plt.figure(figsize=(_W / 100, _H / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.imshow(_gradient(accent), aspect="auto", interpolation="bilinear")
    ax.set_axis_off()
    return fig


def render_card_background(out_path: str | Path, *, accent: str) -> str:
    """畫一張 1080×1920 的漸層底圖(無文字);文字由合成端以 ASS 疊上做動畫。"""
    fig = _new_canvas(accent)
    fig.savefig(out_path, dpi=100)
    plt.close(fig)
    return str(out_path)


def render_headline_card(
    out_path: str | Path,
    text: str,
    *,
    accent: str = "#0D1B2A",
    tag: str | None = None,
    stat: str | None = None,
    brand: str | None = None,
) -> str:
    """畫一張 1080×1920 的靜態字卡(文字烤進 PNG),給 YouTube 封面用。

    版面:上 kicker 小標(tag)→ 大數字 stat(金,選配)→ 大標 → 底部品牌線(brand)。
    有 stat 時大標下移,讓數字成為第一視覺焦點。
    """
    fig = _new_canvas(accent)
    if tag:
        fig.text(0.5, 0.80, tag, ha="center", va="center", color=_GOLD, fontsize=40,
                 fontweight="bold")
    headline_y = 0.50
    if stat:
        fig.text(0.5, 0.62, stat, ha="center", va="center", color=_GOLD, fontsize=150,
                 fontweight="bold")
        headline_y = 0.42
    fig.text(
        0.5, headline_y, "\n".join(wrap_card_text(text)), ha="center", va="center",
        color="white", fontsize=84, fontweight="bold", linespacing=1.3,
    )
    if brand:
        fig.text(0.5, 0.16, brand, ha="center", va="center", color="white", alpha=0.75,
                 fontsize=34)
    fig.savefig(out_path, dpi=100)
    plt.close(fig)
    return str(out_path)
