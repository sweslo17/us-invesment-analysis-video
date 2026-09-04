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


# --- 2026-09-05 視覺改版:字卡文字改走 ASS(可動畫)、大數字 callout、角標、CTA、安全區 ---


def _take(text: str, duration: float = 2.0):
    from pmb.video.assemble import _Take

    return _Take(text, "x.mp3", duration, [])


def test_build_card_ass_animates_headline_pop_in_with_tag():
    from pmb.video.assemble import build_card_ass

    ass = build_card_ass("鷹鴿吵不完\n今天非農裁判", tag="盤前快報", duration=3.0, font="F")
    assert "Style: card" in ass and "Style: kicker" in ass
    assert "鷹鴿吵不完" in ass and "今天非農裁判" in ass and "盤前快報" in ass
    # 文字要有 pop-in:淡入 + 縮放 transform(靜止字卡是滑走的主因之一)
    assert "\\fad(" in ass and "\\t(" in ass and "\\fscx" in ass


def test_build_card_ass_without_tag_has_no_kicker_event():
    from pmb.video.assemble import build_card_ass

    ass = build_card_ass("只有大標", tag=None, duration=2.0, font="F")
    assert ass.count("Dialogue:") == 1


def test_segment_ass_draws_stat_callout_when_given():
    from pmb.video.assemble import build_segment_ass

    ass = build_segment_ass(
        [_take("標普漲1.06%。")], 3.0, title="昨收", font="F",
        stat="+1.06%", stat_label="標普昨收",
    )
    assert "Style: stat" in ass and "Style: statlabel" in ass
    assert "+1.06%" in ass and "標普昨收" in ass


def test_segment_ass_without_stat_has_no_stat_events():
    from pmb.video.assemble import build_segment_ass

    ass = build_segment_ass([_take("一句。")], 3.0, title=None, font="F")
    assert ass.count("Dialogue:") == 1  # 只有字幕


def test_segment_ass_badge_and_cta_positions():
    from pmb.video.assemble import build_segment_ass

    ass = build_segment_ass(
        [_take("一句。", 6.0)], 6.35, title=None, font="F",
        badge="美股早發車 · 9/4", cta="明天盤前見 · 追蹤 美股早發車",
    )
    assert "美股早發車 · 9/4" in ass and "Style: badge" in ass
    # CTA 只在段尾最後 3 秒出現(不搶正文)
    cta_line = next(line for line in ass.splitlines() if "明天盤前見" in line)
    assert cta_line.startswith("Dialogue: 0,0:00:03.35,0:00:06.35,cta")


def test_layout_keeps_text_out_of_shorts_ui_overlay():
    """YouTube Shorts 播放器會蓋住畫面底部約 400px(標題/頻道)與右側約 160px(按讚欄)。

    字幕與 callout 都不能落在那兩塊,否則觀眾根本看不到字。
    """
    from pmb.video.assemble import layout_safe_zone

    zone = layout_safe_zone()
    assert zone["bottom_ui"] >= 400 and zone["right_ui"] >= 160
    assert zone["sub_margin_v"] >= zone["bottom_ui"]
    assert zone["sub_margin_r"] >= zone["right_ui"]


def test_assemble_video_wires_card_ass_stat_badge_and_cta(tmp_path):
    """整合(靜音 TTS + ffmpeg):字卡文字走 ASS 動畫、圖表段疊 stat、全片角標、片尾 CTA。"""
    import datetime as dt

    from pmb.schemas.script import Script
    from pmb.schemas.snapshot import LeverageMath, Snapshot
    from pmb.tts.edge import silent_synth
    from pmb.video.assemble import assemble_video

    snap = Snapshot(
        session_date=dt.date(2026, 6, 18),
        generated_at=dt.datetime(2026, 6, 18, 12, 0, tzinfo=dt.UTC),
        leverage_math=[
            LeverageMath(market="S&P 500", realized_vol=0.165, vol_target_leverage=0.91,
                         drag_1x=0.0136, drag_2x=0.0545, drag_3x=0.1226),
        ],
    )
    script = Script.model_validate({
        "segments": [
            {"vo": "開場一句。", "headline": "鷹鴿吵不完", "tag": "盤前快報",
             "t_start": 0, "duration": 1},
            {"vo": "圖表一句。", "chart_id": "lev", "title": "槓桿耗損",
             "stat": "+1.06%", "stat_label": "標普昨收", "t_start": 1, "duration": 1},
            {"vo": "收尾一句。", "headline": "別人恐懼我貪婪\n我只敢等非農",
             "tag": "巴菲特 不知道有沒有說過", "t_start": 2, "duration": 1},
        ],
        "charts": [{"id": "lev", "module": "leverage_decay", "params": {}}],
    })
    work = tmp_path / "work"
    out = assemble_video(
        script, snap, tmp_path / "out.mp4",
        synth_fn=lambda vo, path, planned: silent_synth(vo, path, duration=1.0),
        work_dir=work, font="PingFang TC", channel_name="美股早發車", master_audio=False,
    )
    assert out.exists() and out.stat().st_size > 0
    card0 = (work / "card0.ass").read_text(encoding="utf-8")
    assert "Style: card" in card0 and "鷹鴿吵不完" in card0 and "盤前快報" in card0
    assert "美股早發車 · 6/18" in card0  # 品牌·日期角標(每段都有)
    assert "明天盤前見" not in card0  # CTA 只在片尾
    seg1 = (work / "seg1.ass").read_text(encoding="utf-8")
    assert "+1.06%" in seg1 and "標普昨收" in seg1 and "美股早發車 · 6/18" in seg1
    card2 = (work / "card2.ass").read_text(encoding="utf-8")
    assert "明天盤前見" in card2 and "美股早發車" in card2


def test_wrap_caption_never_splits_a_number_across_lines():
    """字幕斷行不可把 7747、1.06% 這類數字切成兩行(dry-run 實際出現「收7 / 747點」)。"""
    text = "上一交易日標普大漲1.06%收7747點,是八月初以來最佳單日"
    for max_units in range(8, 15):
        lines = wrap_caption(text, max_units=max_units).split("\\N")
        assert "".join(lines) == text
        for a, b in zip(lines, lines[1:], strict=False):
            split_run = a[-1].isascii() and a[-1].isalnum() and b[0].isascii() and b[0].isalnum()
            assert not split_run, f"max_units={max_units} 在數字中間斷行:{lines}"
