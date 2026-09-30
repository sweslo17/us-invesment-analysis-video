"""段型 renderer 共用機制測試:句子計畫、停頓、時間軸、registry(不跑 ffmpeg)。"""

import re

import pytest

from pmb.video.captions import is_beat, split_sentences, strip_beat
from pmb.video.segments.base import (
    BEAT_GAP,
    GAP,
    TAIL,
    Take,
    Utterance,
    append_outro,
    caption_events,
    plan_vo,
    segment_duration,
    take_starts,
)
from pmb.video.segments.registry import renderer_for


def test_ellipsis_ends_a_sentence_and_marks_a_beat():
    out = split_sentences("好消息是Fed說不急……壞消息是債市沒在聽。")
    assert out == ["好消息是Fed說不急……", "壞消息是債市沒在聽。"]
    assert is_beat(out[0]) and not is_beat(out[1])
    assert is_beat("先別急⋯⋯」")
    assert strip_beat("不急……") == "不急"


def test_ellipsis_after_sentence_end_attaches_to_previous_sentence():
    out = split_sentences("Fed說不急。……債市不信。")
    assert out == ["Fed說不急。……", "債市不信。"]
    assert is_beat(out[0]) and not is_beat(out[1])
    assert [u.gap_after for u in plan_vo("Fed說不急。……債市不信。")] == [BEAT_GAP, GAP]


def test_leading_ellipsis_is_kept_in_first_sentence_and_is_not_a_beat():
    out = split_sentences("……好吧,Fed又改口了。")
    assert out == ["……好吧,Fed又改口了。"]
    assert not is_beat(out[0])


def test_split_sentences_never_drops_trailing_punctuation_runs():
    assert split_sentences("真的假的!?") == ["真的假的!?"]
    assert split_sentences("好吧。……") == ["好吧。……"]
    assert split_sentences("……") == []


def test_plan_vo_uses_long_gap_after_beat():
    utts = plan_vo("Fed說不急……債市說我急。")
    assert [u.gap_after for u in utts] == [BEAT_GAP, GAP]
    assert utts[0].tts_text == "Fed說不急" and utts[0].text == "Fed說不急……"
    assert all(u.voice == "narrator" and u.caption for u in utts)


def test_take_starts_and_duration_follow_per_take_gaps():
    takes = [Take("a", "a.mp3", 2.0, [], BEAT_GAP), Take("b", "b.mp3", 1.0, [], GAP)]
    assert take_starts(takes) == pytest.approx([0.0, 2.5])
    assert take_starts(takes, lead_in=0.15) == pytest.approx([0.15, 2.65])
    assert segment_duration(takes) == pytest.approx(2.0 + 0.5 + 1.0 + TAIL)
    assert segment_duration(takes, lead_in=0.15, min_duration=10.0) == pytest.approx(10.0)


def test_caption_events_skip_takes_without_caption():
    takes = [Take("泡泡句。", "a.mp3", 1.0, [], GAP, False), Take("旁白句。", "b.mp3", 1.0, [])]
    events = caption_events(takes, take_starts(takes))
    assert len(events) == 1
    assert "旁白句" in re.sub(r"\{[^}]*\}", "", events[0])  # 卡拉OK標籤把字拆開,先剝掉再比
    assert events[0].startswith("Dialogue: 0,0:00:01.18")


def test_append_outro_adds_once():
    utts = [Utterance("金句。")]
    outro = "以上非投資建議,明天盤前見。"
    assert append_outro(utts, outro)[-1].text == outro
    already = [Utterance("金句。"), Utterance(outro)]
    assert append_outro(already, outro) == already
    assert append_outro(utts, None) == utts


def test_registry_knows_chart_and_card_and_rejects_unknown():
    assert renderer_for("chart") is not None and renderer_for("card") is not None
    with pytest.raises(ValueError):
        renderer_for("hologram")
