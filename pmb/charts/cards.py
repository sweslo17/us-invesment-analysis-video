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


def _wrap_cjk(text: str, width: int = 9) -> str:
    """每 ``width`` 個字斷一行;保留原本就有的換行(對句兩行不會被打散)。"""
    out: list[str] = []
    for line in text.split("\n"):
        if line:
            out.extend(line[i : i + width] for i in range(0, len(line), width))
        else:
            out.append("")
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
