"""影片合成的純邏輯測試:SRT 字幕格式、時間軸累積(不跑 ffmpeg)。"""

import pytest

from pmb.video.assemble import (
    build_ass,
    build_srt,
    has_speakable,
    segment_timeline,
    split_sentences,
    wrap_caption,
)


def test_build_srt_formats_cues_with_ms():
    srt = build_srt([("你好", 0.0, 2.5), ("世界", 2.5, 1.5)])
    assert "00:00:00,000 --> 00:00:02,500" in srt
    assert "你好" in srt
    assert "00:00:02,500 --> 00:00:04,000" in srt
    assert "世界" in srt


def test_split_sentences_breaks_on_terminators_keeping_punctuation():
    out = split_sentences("隔夜美股收紅。費半領漲!VIX 回落到十六。")
    assert out == ["隔夜美股收紅。", "費半領漲!", "VIX 回落到十六。"]


def test_split_sentences_single_returns_one():
    assert split_sentences("沒有句號的一句話") == ["沒有句號的一句話"]


def test_split_sentences_ignores_blank_fragments():
    assert split_sentences("一句。\n\n二句。") == ["一句。", "二句。"]


def test_split_sentences_keeps_closing_quote_with_its_sentence():
    """句尾標點後的右引號不可自成一句——2026-07-30 實際故障:

    「…結果吵起來了。』」被切成 '…了。' + '』',而 '』' 沒有可唸內容,
    edge-tts 回 NoAudioReceived、重試三次後整支影片掛掉。
    """
    out = split_sentences("主席華許自己說:『我要一場好架,結果吵起來了。』")
    assert out == ["主席華許自己說:『我要一場好架,結果吵起來了。』"]
    assert all(has_speakable(s) for s in out)


def test_split_sentences_drops_unspeakable_fragments():
    # 只有符號、沒有可唸內容的碎片要被併入前句或丟棄,不可單獨送進 TTS
    for text in ["結束了。」", "沒錯!)", "就這樣。⋯⋯", "這樣。——"]:
        out = split_sentences(text)
        assert out, f"{text} 不該切成空清單"
        assert all(has_speakable(s) for s in out), f"{text} → {out} 含無法發音的碎片"


def test_has_speakable_detects_content():
    assert has_speakable("你好") and has_speakable("VIX 19") and has_speakable("3.8%")
    assert not has_speakable("』") and not has_speakable("、。!") and not has_speakable("  ")


def test_split_sentences_does_not_break_decimals():
    # 3.8% / 0.53 的小數點不可被當句尾切斷
    out = split_sentences("中位數拉到 3.8%。股債相關 0.53,分散打折。")
    assert out == ["中位數拉到 3.8%。", "股債相關 0.53,分散打折。"]


def test_wrap_caption_short_stays_one_line():
    assert "\\N" not in wrap_caption("短短一句話", max_units=14)


def test_wrap_caption_breaks_long_line_into_multiple():
    text = "不管你用融資、期貨還是槓桿型產品,數學都一樣,開到三倍很危險很危險"
    lines = wrap_caption(text, max_units=10).split("\\N")
    assert len(lines) >= 2
    # 每行寬度單位不超過上限太多(中文算 1、英數算 0.55)
    for line in lines:
        units = sum(1.0 if not c.isascii() else 0.55 for c in line)
        assert units <= 12


def test_wrap_caption_prefers_breaking_after_punctuation():
    out = wrap_caption("第一段話講完了、第二段話開始", max_units=8)
    assert out.split("\\N")[0].endswith("、")


def test_build_ass_has_pixel_playres_title_and_subtitle():
    ass = build_ass("這是字幕。", 3.0, title="主題")
    assert "PlayResY: 1920" in ass  # 像素級定位
    assert "Style: sub" in ass and "Style: title" in ass
    assert "這是字幕。" in ass and "主題" in ass
    assert ass.count("Dialogue:") == 2  # 字幕 + 標題


def test_build_ass_without_title_has_only_subtitle():
    ass = build_ass("只有字幕。", 2.0)
    assert ass.count("Dialogue:") == 1


def test_segment_timeline_accumulates_actual_durations():
    # 給每段「實際配音長度」,回傳累積起點 + 總長
    starts, total = segment_timeline([3.0, 4.5, 2.5])
    assert starts == pytest.approx([0.0, 3.0, 7.5])
    assert total == pytest.approx(10.0)
