"""textfit.fit_authored_lines：保留作者自己的斷行，放不下才退回依寬度斷行。"""

from pmb.video.textfit import fit_authored_lines, fit_lines, line_px

_SIZES = (88, 76, 66)


def test_authored_two_lines_that_fit_are_kept_at_the_largest_size():
    lines, size = fit_authored_lines(
        "航母開三艘\nVIX卻打哈欠", max_width=740, sizes=_SIZES, max_lines=2
    )
    assert lines == ["航母開三艘", "VIX卻打哈欠"] and size == 88


def test_authored_parts_are_stripped_and_blank_lines_dropped():
    lines, size = fit_authored_lines(
        "  殖利率飆升 \n\n  股市先跌  ", max_width=740, sizes=_SIZES, max_lines=2
    )
    assert lines == ["殖利率飆升", "股市先跌"] and size == 88


def test_a_part_too_wide_at_the_big_size_shrinks_but_keeps_the_parts():
    wide = "字" * 12  # 88px：12 × 88 × 0.713 ≈ 753 > 740；76px：≈ 650 放得下
    assert line_px(wide, 88) > 740 >= line_px(wide, 76)
    lines, size = fit_authored_lines(f"{wide}\n短句", max_width=740, sizes=_SIZES, max_lines=2)
    assert lines == [wide, "短句"] and size == 76


def test_more_parts_than_max_lines_falls_back_to_width_wrapping():
    text = "第一句\n第二句\n第三句"
    lines, size = fit_authored_lines(text, max_width=740, sizes=_SIZES, max_lines=2)
    assert 1 <= len(lines) <= 2 and "".join(lines) == "第一句第二句第三句"
    assert all(line_px(line, size) <= 740 for line in lines)


def test_a_part_too_wide_at_every_size_falls_back_to_fit_lines():
    too_wide = "字" * 16  # 66px：16 × 66 × 0.713 ≈ 753 > 740，三個字級都放不下
    assert line_px(too_wide, 66) > 740
    text = f"{too_wide}\n短"
    lines, size = fit_authored_lines(text, max_width=740, sizes=_SIZES, max_lines=2)
    assert lines == fit_lines(too_wide + "短", max_width=740, sizes=_SIZES, max_lines=2)[0]
    assert len(lines) <= 2 and all(line_px(line, size) <= 740 for line in lines)


def test_fallback_joins_ascii_alnum_boundaries_with_a_space_only():
    # 三段 → 退回 fit_lines；VIX|ETF 的 ASCII 邊界補空白，中文與英數之間不補
    lines, _ = fit_authored_lines("VIX\nETF\n大漲", max_width=2000, sizes=_SIZES, max_lines=2)
    assert lines == ["VIX ETF大漲"]
    lines, _ = fit_authored_lines("航母開三艘\nVIX\n卻打哈欠", max_width=2000, sizes=_SIZES,
                                  max_lines=2)
    assert lines == ["航母開三艘VIX卻打哈欠"]
    lines, _ = fit_authored_lines("5.2%\n3個月\nUPRO", max_width=2000, sizes=_SIZES, max_lines=2)
    assert lines == ["5.2%3個月UPRO"]  # % 結尾、中文開頭都不補空白
    lines, _ = fit_authored_lines("A1\nb2\nc", max_width=2000, sizes=_SIZES, max_lines=2)
    assert lines == ["A1 b2 c"]


def test_empty_or_blank_text_returns_no_lines_and_the_first_size():
    assert fit_authored_lines("", max_width=740, sizes=_SIZES, max_lines=2) == ([], 88)
    assert fit_authored_lines(" \n \t\n", max_width=740, sizes=_SIZES, max_lines=2) == ([], 88)


def test_single_authored_line_that_fits_is_returned_as_is():
    assert fit_authored_lines("十年期殖利率", max_width=740, sizes=_SIZES, max_lines=2) == (
        ["十年期殖利率"], 88)
