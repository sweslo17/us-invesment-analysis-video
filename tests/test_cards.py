"""時事標題卡渲染測試:全屏大字 PNG。"""

import numpy as np
from matplotlib.image import imread

from pmb.charts.cards import accent_for, render_headline_card, render_solid_background


def test_render_headline_card_writes_fullframe_png(tmp_path):
    out = tmp_path / "card.png"
    render_headline_card(out, "Fed 轉鷹,2026 恐升息", accent="#C1121F", tag="盤前快報")
    assert out.exists() and out.stat().st_size > 0


def test_accent_for_cycles_palette():
    assert accent_for(0) == accent_for(0)
    assert accent_for(0) != accent_for(1)


def test_render_card_background_is_fullframe_gradient(tmp_path):
    """字卡底圖:1080×1920 漸層(上下顏色不同),不含文字——文字改由 ASS 疊上去才能動。"""
    from pmb.charts.cards import render_card_background

    out = tmp_path / "bg.png"
    render_card_background(out, accent="#C1121F")
    img = imread(out)
    assert img.shape[0] == 1920 and img.shape[1] == 1080
    top, bottom = img[40, 540, :3], img[1880, 540, :3]
    assert abs(float(top.sum()) - float(bottom.sum())) > 0.15  # 明顯漸層


def test_wrap_card_text_keeps_couplet_lines_and_wraps_long_line():
    from pmb.charts.cards import wrap_card_text

    assert wrap_card_text("別人恐懼我貪婪\n我只敢等非農") == ["別人恐懼我貪婪", "我只敢等非農"]
    lines = wrap_card_text("荷姆茲海峽通行量比戰前掉了九成五,原油站上95美元")
    assert len(lines) >= 2 and "".join(lines) == "荷姆茲海峽通行量比戰前掉了九成五,原油站上95美元"


def test_render_headline_card_accepts_stat_for_cover(tmp_path):
    out = tmp_path / "cover.png"
    render_headline_card(
        out, "鷹鴿吵不完,今天非農裁判", accent="#C1121F", tag="盤前快報",
        stat="+1.06%", brand="美股早發車",
    )
    assert out.exists() and out.stat().st_size > 0


def test_render_solid_background_is_flat_fullframe(tmp_path):
    """純色底圖:1080×1920、每個像素都等於指定色(不能有漸層,Ken Burns 放大才不會出現色階斷層)。"""
    out = tmp_path / "flat.png"
    assert render_solid_background(out, color="#0D1B2A") == str(out)
    img = imread(out)
    assert img.shape[:2] == (1920, 1080)
    pixels = np.rint(img[:, :, :3] * 255).astype(int).reshape(-1, 3)
    assert (pixels == (0x0D, 0x1B, 0x2A)).all()
