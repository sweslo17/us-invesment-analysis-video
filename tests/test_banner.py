"""標題橫幅(金底深字)的版面與 ASS:靜態、置中、避開右側按讚欄。"""

import re

from pmb.video.ass import (
    BANNER_H,
    BANNER_TOP,
    BANNER_W,
    BANNER_X,
    BG_HEX,
    CENTER_X,
    GOLD_HEX,
    RIGHT_UI,
    WIDTH,
    ass_color,
)
from pmb.video.banner import BANNER_ASS, banner_layout, build_banner_ass
from pmb.video.textfit import line_px

_TWO_LINES = "航母開三艘\nVIX卻打哈欠"


def _events(ass: str) -> list[str]:
    return [ln for ln in ass.splitlines() if ln.startswith("Dialogue:")]


def test_banner_file_name_is_shared_per_video():
    assert BANNER_ASS == "banner.ass"


def test_authored_two_line_headline_is_kept_at_the_largest_size():
    lines, size = banner_layout(_TWO_LINES)
    assert lines == ["航母開三艘", "VIX卻打哈欠"] and size == 88
    assert "\\N" in build_banner_ass(_TWO_LINES, "F")


def test_every_line_stays_left_of_the_like_column():
    long_one_line = "殖利率一路往上衝而且完全沒有要停下來的意思" * 3
    for headline in (_TWO_LINES, long_one_line, "字" * 200, "VIX" * 40):
        lines, size = banner_layout(headline)
        assert 1 <= len(lines) <= 2
        for line in lines:
            assert CENTER_X + line_px(line, size) / 2 <= WIDTH - RIGHT_UI, (headline, line, size)


def test_banner_ass_is_static_with_exactly_two_full_length_events():
    ass = build_banner_ass(_TWO_LINES, "PingFang TC")
    assert "\\move" not in ass and "\\fad" not in ass
    events = _events(ass)
    assert len(events) == 2
    assert all(ev.startswith("Dialogue: ") for ev in events)
    for ev in events:
        assert ",0:00:00.00,1:00:00.00," in ev  # 0 → 3600 秒
    assert "Fontname" in ass and "PingFang TC" in ass  # 完整 ASS 文件(字型帶入樣式)


def test_box_event_is_the_gold_rounded_rect_at_the_banner_origin():
    box = _events(build_banner_ass(_TWO_LINES, "F"))[0]
    assert f"\\pos({BANNER_X},{BANNER_TOP})" in box and "\\p1" in box
    assert f"\\1c{ass_color('#' + GOLD_HEX)}" in box
    path = re.search(r"\}(m [^{]+)\{", box).group(1)
    nums = [int(n) for n in re.findall(r"-?\d+", path)]
    assert (max(nums[0::2]), max(nums[1::2])) == (BANNER_W, BANNER_H)


def test_text_event_is_centred_in_the_box_in_the_canvas_colour():
    text = _events(build_banner_ass(_TWO_LINES, "F"))[1]
    assert f"\\an5\\pos({CENTER_X},{BANNER_TOP + BANNER_H // 2})" in text
    assert "\\fs88" in text and f"\\1c{ass_color('#' + BG_HEX)}" in text
    assert text.endswith("航母開三艘\\NVIX卻打哈欠")
