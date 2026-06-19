"""時事標題卡渲染測試:全屏大字 PNG。"""

from pmb.charts.cards import accent_for, render_headline_card


def test_render_headline_card_writes_fullframe_png(tmp_path):
    out = tmp_path / "card.png"
    render_headline_card(out, "Fed 轉鷹,2026 恐升息", accent="#C1121F", tag="盤前快報")
    assert out.exists() and out.stat().st_size > 0


def test_accent_for_cycles_palette():
    assert accent_for(0) == accent_for(0)
    assert accent_for(0) != accent_for(1)
