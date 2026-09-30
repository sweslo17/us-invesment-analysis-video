"""段型 renderer 共用機制測試:句子計畫、停頓、時間軸、registry(不跑 ffmpeg)。"""

import re
from pathlib import Path

import pytest

from pmb.schemas.script import DialogueSegment
from pmb.video.ass import ass_color, rounded_rect
from pmb.video.captions import is_beat, split_sentences, strip_beat
from pmb.video.segments.base import (
    BEAT_GAP,
    GAP,
    TAIL,
    RenderContext,
    Take,
    Utterance,
    append_outro,
    caption_events,
    plan_vo,
    segment_duration,
    take_starts,
)
from pmb.video.segments.dialogue import bubble_layout, speakable_lines
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


def _ctx(takes, duration=6.0, work_dir=Path("/tmp"), lead_in=0.0):
    return RenderContext(index=2, duration=duration, takes=takes,
                         starts=take_starts(takes, lead_in), font="F", work_dir=work_dir,
                         badge="美股早發車 · 9/30")


def test_ass_color_and_rounded_rect():
    assert ass_color("#185FA5") == "&HA55F18&"
    path = rounded_rect(100, 60, 20)
    assert path.startswith("m 20 0 l 80 0 b 100 0") and path.count(" b ") == 4


def _dialogue(**kw):
    return DialogueSegment(lines=kw.get("lines", [
        {"speaker": "Fed", "voice": "a", "text": "十月升息,不急。"},
        {"speaker": "債市", "voice": "b", "text": "你不急,我急。"},
    ]), vo=kw.get("vo", ""))


def test_dialogue_utterances_use_line_voices_without_captions_then_narrator():
    seg = _dialogue(vo="意思是長天期利率自己往上衝。")
    utts = renderer_for("dialogue").utterances(seg)
    assert [(u.voice, u.caption) for u in utts] == [("a", False), ("b", False), ("narrator", True)]


def test_dialogue_bubbles_pop_at_their_take_start(tmp_path):
    seg = _dialogue()
    takes = [Take("十月升息,不急。", "a.mp3", 1.5, [], GAP, False),
             Take("你不急,我急。", "b.mp3", 1.2, [], GAP, False)]
    visual = renderer_for("dialogue").render(seg, _ctx(takes, work_dir=tmp_path))
    assert visual.is_card and visual.stem == "dialogue"
    assert (tmp_path / visual.image).exists()
    ass = visual.ass
    assert "Style: free" in ass and "\\p1" in ass
    assert "Fed" in ass and "債市" in ass
    # 第二個泡泡在第二句起點(1.5 + 0.18)出現
    assert "Dialogue: 0,0:00:01.68" in ass or "Dialogue: 1,0:00:01.68" in ass
    assert ",sub," not in ass  # 泡泡句不上底部字幕
    # 右側 B 角泡泡不越過 x=910(按讚欄)
    for line in ass.splitlines():
        if "\\pos(" in line or "\\move(" in line:
            x = int(line.split("\\move(")[1].split(",")[0]) if "\\move(" in line else 0
            assert x <= 910


def test_unspeakable_line_is_dropped_consistently():
    seg = _dialogue(lines=[
        {"speaker": "Fed", "voice": "a", "text": "……?"},
        {"speaker": "債市", "voice": "b", "text": "我急。"},
        {"speaker": "Fed", "voice": "a", "text": "蛤。"},
    ])
    kept = speakable_lines(seg)
    assert [line.text for line in kept] == ["我急。", "蛤。"]
    assert len(renderer_for("dialogue").utterances(seg)) == 2


def test_bubble_layout_shrinks_then_truncates_long_text():
    lines, fs = bubble_layout("短句")
    assert lines == ["短句"] and fs == 60
    lines, fs = bubble_layout("這一句真的超級超級超級超級超級超級長,長到兩行都裝不下喔")
    assert fs == 48 and len(lines) == 2
    lines, fs = bubble_layout("字" * 60)
    assert len(lines) == 2 and lines[1].endswith("…")


def test_dialogue_shapes_stay_inside_safe_zone(tmp_path):
    """最長的四句、兩種聲線:每個圓角框的右緣 <= 910(按讚欄之外)、下緣 <= 1520(底部 UI 之上)。"""
    long_text = "這一句真的超級超級超級超級超級超級長,長到兩行都裝不下喔"
    seg = _dialogue(lines=[
        {"speaker": "Fed", "voice": "a", "text": long_text},
        {"speaker": "債市", "voice": "b", "text": long_text},
        {"speaker": "Fed", "voice": "a", "text": "字" * 60},
        {"speaker": "債市", "voice": "b", "text": "VIX 一路衝上 2026 點"},
    ])
    takes = [Take(u.text, f"{i}.mp3", 1.0, [], GAP, False)
             for i, u in enumerate(renderer_for("dialogue").utterances(seg))]
    ass = renderer_for("dialogue").render(seg, _ctx(takes, work_dir=tmp_path)).ass
    shapes = [ln for ln in ass.splitlines() if "\\p1" in ln]
    assert len(shapes) == 4
    for ln in shapes:
        x, y = (int(v) for v in re.search(r"\\move\(\d+,\d+,(\d+),(\d+),", ln).groups())
        path = re.search(r"\}(m [^{]+)\{", ln).group(1)
        nums = [int(n) for n in re.findall(r"-?\d+", path)]
        width, height = max(nums[0::2]), max(nums[1::2])
        assert x + width <= 910 and y + height <= 1520
