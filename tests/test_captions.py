"""段級字幕邏輯測試:分頁、卡拉OK對時、word boundary 對齊與後備(不跑 ffmpeg)。"""

import pytest

from pmb.tts.edge import WordBoundary
from pmb.video.assemble import (
    _audio_graph,
    _fit_box,
    build_caption_pages,
    build_segment_ass,
    _Take,
)


def _units(s: str) -> float:
    return sum(1.0 if not c.isascii() else 0.55 for c in s)


def test_pages_never_exceed_two_lines_and_cover_whole_sentence():
    text = "VIX睡到十五點五、標普波動降到十三點六,公式回推的合理槓桿反而升到一點一倍,最平靜時數學反而鼓勵你加最多,這就是陷阱。"
    pages = build_caption_pages(text, [], 12.0)
    assert len(pages) >= 2  # 長句必須分頁,不能一頁七行蓋掉圖表
    joined = "".join(p.text.replace("\\N", "") for p in pages)
    assert joined == text
    for p in pages:
        assert p.text.count("\\N") <= 1  # 每頁最多兩行


def test_pages_are_contiguous_and_end_at_duration():
    text = "第一句很長很長很長很長很長很長,第二半段也很長很長很長很長很長。"
    pages = build_caption_pages(text, [], 8.0)
    assert pages[0].start == pytest.approx(0.0)
    for prev, nxt in zip(pages, pages[1:], strict=False):
        assert prev.end == pytest.approx(nxt.start)  # 頁與頁相接,不閃黑
    assert pages[-1].end == pytest.approx(8.0)


def test_karaoke_cs_roughly_covers_page_duration():
    text = "短句測試,後面補一點內容讓它有兩頁以上的長度,繼續補繼續補。"
    pages = build_caption_pages(text, [], 6.0)
    for p in pages:
        total_cs = sum(cs for _, cs in p.karaoke)
        assert total_cs == pytest.approx((p.end - p.start) * 100, abs=15)


def test_word_boundaries_drive_page_timing():
    text = "標普漲零點二三,道瓊漲零點二。"
    words = [
        WordBoundary(text="標普", start=0.0, duration=0.4),
        WordBoundary(text="漲", start=0.4, duration=0.2),
        WordBoundary(text="零點二三", start=0.6, duration=0.9),
        WordBoundary(text="道瓊", start=1.8, duration=0.5),
        WordBoundary(text="漲", start=2.3, duration=0.2),
        WordBoundary(text="零點二", start=2.5, duration=0.7),
    ]
    pages = build_caption_pages(text, words, 3.4, max_units=8)
    assert pages[0].start == pytest.approx(0.0)
    # 第二頁應從其第一個字所屬 word 的時間開始(而非比例推估)
    assert pages[-1].end == pytest.approx(3.4)
    starts = [p.start for p in pages]
    assert starts == sorted(starts)


def test_unmatchable_words_fall_back_to_proportional():
    text = "三點八趴的漲幅。"
    words = [WordBoundary(text="完全對不上的詞", start=0.0, duration=1.0)]
    pages = build_caption_pages(text, words, 4.0)
    assert pages[-1].end == pytest.approx(4.0)
    assert pages[0].start == pytest.approx(0.0)


def test_build_segment_ass_offsets_second_sentence_by_gap():
    takes = [
        _Take("第一句。", "a0.mp3", 2.0, []),
        _Take("第二句。", "a1.mp3", 2.0, []),
    ]
    ass = build_segment_ass(takes, 4.53, title="主題", font="PingFang TC")
    assert "Style: sub" in ass and "Style: title" in ass
    assert "SecondaryColour" in ass  # 卡拉OK需要 Secondary 掃色
    # 第二句起點 = 第一句 2.0s + 句間 0.18s
    assert "Dialogue: 0,0:00:02.18" in ass
    assert "{\\k" in ass


def test_fit_box_keeps_aspect_and_even_dims():
    w, h = _fit_box(1080, 1200, 1040, 1180)
    assert w % 2 == 0 and h % 2 == 0
    assert w <= 1040 and h <= 1180
    assert abs((w / h) - (1080 / 1200)) < 0.02


def test_audio_graph_single_take_has_no_gap():
    g = _audio_graph(1, 3.0)
    assert "anullsrc" not in g
    assert "apad=whole_dur=3.000" in g


def test_audio_graph_three_takes_interleaves_two_gaps():
    g = _audio_graph(3, 10.0)
    assert "asplit=2[g0][g1]" in g
    assert "concat=n=5:v=0:a=1" in g
