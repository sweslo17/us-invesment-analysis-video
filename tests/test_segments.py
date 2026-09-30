"""段型 renderer 共用機制測試:句子計畫、停頓、時間軸、registry(不跑 ffmpeg)。"""

import re
from pathlib import Path

import pytest

from pmb.schemas.script import DialogueSegment, SplitSegment
from pmb.video.ass import ass_color, rounded_rect, text_event
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
from pmb.video.segments.split import panel_text_layout, reveal_times
from pmb.video.textfit import FLOOR_SIZE, fit_lines, line_px, wrap_px


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
    # 容量依 PingFang TC 實測校準:60px 一行約 17 個全形字、48px 約 22 個
    lines, fs = bubble_layout("短句")
    assert lines == ["短句"] and fs == 60
    assert bubble_layout("字" * 17) == (["字" * 17], 60)  # 剛好一行
    lines, fs = bubble_layout("字" * 18)
    assert len(lines) == 2 and fs == 60  # 多一個字就換行,但還不用縮字級
    lines, fs = bubble_layout("這一句真的" + "超級" * 12 + "長,長到兩行都裝不下喔")
    assert fs == 48 and len(lines) == 2  # 60px 要 3 行 → 改 48px 收成 2 行
    lines, fs = bubble_layout("字" * 50)
    assert fs == 40 and len(lines) == 2 and not lines[1].endswith("…")  # 48px 要 3 行 → 續縮放得下
    lines, fs = bubble_layout("字" * 80)
    assert fs == FLOOR_SIZE and len(lines) == 2 and lines[1].endswith("…")  # 縮到底還放不下才截斷
    assert bubble_layout("十月升息\n不急。")[0] == ["十月升息 不急。"]  # 內文換行不影響斷行與框高


def _events(ass: str):
    """(泡泡框 [(x, y, w, h)], 角色名頂緣 y 清單);座標取 ``\\move`` 的終點、框尺寸取繪圖路徑。"""
    boxes, label_tops = [], []
    for ln in ass.splitlines():
        if not ln.startswith("Dialogue:") or ",free," not in ln:
            continue
        x, y = (int(v) for v in re.search(r"\\move\(-?\d+,-?\d+,(-?\d+),(-?\d+),", ln).groups())
        if "\\p1" in ln:
            nums = [int(n) for n in re.findall(r"-?\d+", re.search(r"\}(m [^{]+)\{", ln).group(1))]
            boxes.append((x, y, max(nums[0::2]), max(nums[1::2])))
        elif "\\fs40" in ln:
            label_tops.append(y)
    return boxes, label_tops


def _render_ass(seg, tmp_path):
    renderer = renderer_for("dialogue")
    takes = [Take(u.text, f"{i}.mp3", 1.0, [], GAP, False)
             for i, u in enumerate(renderer.utterances(seg))]
    return renderer.render(seg, _ctx(takes, work_dir=tmp_path)).ass


def test_dialogue_shapes_stay_inside_safe_zone(tmp_path):
    """最長的四句、兩種聲線:每個圓角框的右緣 <= 910(按讚欄之外)、下緣 <= 1520(底部 UI 之上)。"""
    long_text = "這一句真的超級超級超級超級超級超級長,長到兩行都裝不下喔"
    seg = _dialogue(lines=[
        {"speaker": "Fed", "voice": "a", "text": long_text},
        {"speaker": "債市", "voice": "b", "text": long_text},
        {"speaker": "Fed", "voice": "a", "text": "字" * 60},
        {"speaker": "債市", "voice": "b", "text": "VIX 一路衝上 2026 點"},
    ])
    boxes, _ = _events(_render_ass(seg, tmp_path))
    assert len(boxes) == 4
    for x, y, w, h in boxes:
        assert x + w <= 910 and y + h <= 1520


def test_two_line_bubbles_leave_room_for_the_next_label(tmp_path):
    """libass 行距 = 字級:四個兩行 60px 泡泡交錯排,每個泡泡底緣離下一槽角色名頂緣 >= 10px。"""
    texts = ["十月升息不急,但債市完全不買單,而且覺得自己被大家當成冤大頭。",
             "你說不急就不急,債市的帳本上,我手上的部位可不是這麼說的喔。",
             "那我問你,殖利率都創新高了,你還敢說不急嗎?給個痛快話。",
             "敢啊,鴿派的話我可以一天講三遍,債市愛不愛聽我都完全不管啦。"]
    for text in texts:
        lines, fs = bubble_layout(text)
        assert fs == 60 and len(lines) == 2 and all(13 <= len(ln) <= 16 for ln in lines), text
    seg = _dialogue(lines=[
        {"speaker": "Fed" if k % 2 == 0 else "債市", "voice": "ab"[k % 2], "text": t}
        for k, t in enumerate(texts)
    ])
    boxes, label_tops = _events(_render_ass(seg, tmp_path))
    assert len(boxes) == len(label_tops) == 4
    for (_, y, _, h), next_label in zip(boxes, label_tops[1:], strict=False):
        assert next_label - (y + h) >= 10


@pytest.mark.parametrize("run", ["1234567890" * 4, "x" * 40, "W" * 40, "VIX" + "9" * 37])
def test_unbreakable_ascii_run_never_leaves_the_bubble_column(run, tmp_path):
    """wrap_lines 不會從中間切英數串;泡泡要縮字級(下限 36)到放得進,A/B 兩側框都在 70..870。"""
    lines, fs = bubble_layout(run)
    assert 36 <= fs <= 60 and len(lines) <= 2
    seg = _dialogue(lines=[
        {"speaker": "Fed", "voice": "a", "text": run},
        {"speaker": "債市", "voice": "b", "text": run},
    ])
    boxes, _ = _events(_render_ass(seg, tmp_path))
    assert len(boxes) == 2
    for x, _, w, _ in boxes:
        assert 70 <= x and x + w <= 870


def test_text_event_escapes_override_braces_and_raw_newlines():
    ev = text_event(0, 1, 10, 20, "a{b}c\nd\\Ne", size=40, color="&H000000&")
    assert ev.split("}", 1)[1] == "a｛b｝c\\Nd\\Ne"  # 花括號全形化、真換行變 \N、既有的 \N 不動
    assert "\n" not in ev


def _split(vo="好消息是Fed說不急。壞消息是債市沒在聽。", **kw):
    return SplitSegment(vo=vo, top={"label": "好消息", "text": kw.get("top", "Fed說不急"),
                                    "tone": "good"},
                        bottom={"label": "壞消息", "text": "債市沒在聽", "stat": "5.26%",
                                "tone": "bad"})


def test_split_bottom_panel_appears_at_second_sentence(tmp_path):
    takes = [Take("好消息是Fed說不急。", "a.mp3", 2.0, []),
             Take("壞消息是債市沒在聽。", "b.mp3", 2.0, [])]
    ctx = _ctx(takes, work_dir=tmp_path)
    assert reveal_times(ctx) == pytest.approx((0.0, 2.18))
    visual = renderer_for("split").render(_split(), ctx)
    assert visual.stem == "split" and "好消息" in visual.ass and "5.26%" in visual.ass
    assert "0:00:02.18" in visual.ass
    assert ",sub," in visual.ass  # 旁白照常上字幕


def test_split_single_sentence_reveals_bottom_at_half(tmp_path):
    takes = [Take("一句話講完。", "a.mp3", 3.0, [])]
    assert reveal_times(_ctx(takes, duration=4.0, work_dir=tmp_path)) == pytest.approx((0.0, 2.0))


def test_panel_text_layout_fits_or_shrinks():
    assert panel_text_layout("Fed說不急", has_stat=False) == (["Fed說不急"], 96)
    lines, size = panel_text_layout("債市完全沒在聽而且還很生氣", has_stat=True)
    assert size == 80 and len(lines) <= 2
    body = "債市完全沒在聽而且還很生氣啊真的假的欸欸"
    assert len(body) == 20
    lines, size = panel_text_layout(body, has_stat=True)  # 96px 一行放不下 → 80px 兩行
    assert size == 80 and len(lines) == 2 and not lines[-1].endswith("…")
    assert panel_text_layout("字" * 13, has_stat=True) == (["字" * 13], 80)
    assert panel_text_layout("字" * 10, has_stat=True) == (["字" * 10], 96)
    lines, size = panel_text_layout("字" * 40, has_stat=True)  # 80px 兩行裝不下 → 續縮,內容完整
    assert len(lines) == 2 and size < 80 and not lines[-1].endswith("…")
    lines, size = panel_text_layout("字" * 80, has_stat=True)  # 縮到底還放不下 → 截斷補「…」
    assert len(lines) == 2 and size == FLOOR_SIZE and lines[-1].endswith("…")
    assert len(panel_text_layout("字" * 40, has_stat=False)[0]) == 2


def test_fit_lines_fits_shrinks_then_truncates_with_ellipsis():
    kw = {"max_width": 750, "sizes": (96, 80)}
    assert fit_lines("短句", max_lines=1, **kw) == (["短句"], 96)  # 放得下就用最大字級
    assert fit_lines("字" * 13, max_lines=1, **kw) == (["字" * 13], 80)  # 96px 放不下 → 第二字級
    assert fit_lines("字" * 14, max_lines=1, **kw) == (["字" * 14], 72)  # 列表字級不夠 → 每次縮 4px
    lines, size = fit_lines("字" * 200, max_lines=2, **kw)
    assert size == FLOOR_SIZE and len(lines) == 2 and lines[-1].endswith("…")  # 縮到底才截斷
    assert not lines[0].endswith("…")


def test_fit_lines_normalises_whitespace_and_newlines():
    lines, _ = fit_lines(" 十月升息\n\n不急。\t對吧  ", max_width=750, sizes=(60,), max_lines=2)
    assert lines == ["十月升息 不急。 對吧"]
    assert fit_lines("", max_width=750, sizes=(60,), max_lines=2) == ([], 60)


@pytest.mark.parametrize("text", [
    "x" * 40, "W" * 60, "A" * 30, "1234567890" * 5, "字" * 200, "a b c " * 30, "5.26%" * 12,
    "VIX 與 10 年期殖利率同步飆升到 2026 年新高點", "好,壞。" * 30, "{花括號}" * 20,
])
@pytest.mark.parametrize(("max_width", "sizes", "max_lines"), [
    (750, (96, 80), 1), (750, (96, 80), 2), (756, (60, 48), 2), (200, (48,), 1),
])
def test_fit_lines_every_line_fits_the_width(text, max_width, sizes, max_lines):
    lines, size = fit_lines(text, max_width=max_width, sizes=sizes, max_lines=max_lines)
    assert 1 <= len(lines) <= max_lines and size >= FLOOR_SIZE
    assert all(line_px(ln, size) <= max_width for ln in lines)
    assert all("\n" not in ln and ln == ln.strip() for ln in lines)


def test_line_px_measures_braces_as_the_fullwidth_glyphs_text_event_renders():
    assert line_px("{}", 60) == line_px("｛｝", 60)


def test_wrap_px_keeps_number_runs_whole_unless_a_run_alone_overflows():
    assert wrap_px("收盤在7747點", 60, 200) == ["收盤在", "7747點"]  # 放不下就整串移到下一行
    lines = wrap_px("x" * 40, 60, 400)  # 單一英數串自己就超寬才硬切
    assert len(lines) > 1 and "".join(lines) == "x" * 40
    assert all(line_px(ln, 60) <= 400 for ln in lines)


def _text_extents(ass: str):
    """(錨點 x, 錨點 y, 字級, 是否底部對齊, 斷行清單) 依事件順序;只取 free 樣式的文字事件。"""
    out = []
    for ln in ass.splitlines():
        if not ln.startswith("Dialogue:") or ",free," not in ln or "\\p1" in ln:
            continue
        x, y = (int(v) for v in re.search(r"\\move\(-?\d+,-?\d+,(-?\d+),(-?\d+),", ln).groups())
        size = int(re.search(r"\\fs(\d+)", ln).group(1))
        out.append((x, y, size, "\\an1" in ln, ln.split("}", 1)[1].split("\\N")))
    return out


@pytest.mark.parametrize(("top", "bottom", "stat", "label"), [
    ("Fed說不急", "債市沒在聽", "5.26%", "壞消息"),
    ("x" * 40, "A" * 30, "5.26%", "壞消息"),  # 不可斷的長英數串
    ("Fed說不急", "債市沒在聽", "一二三四五六七八九十一二", "壞消息"),  # 12 個全形字的大數字
    ("Fed說不急\n再說一次\n第三行\n第四行", "債\n市\n沒\n在\n聽", "5.26%", "壞消息"),  # 含換行
    ("字" * 60, "字" * 60, "W" * 20, "壞" * 40),  # 全部過長:縮字級後截斷
    ("Fed說不急", "債市完全沒在聽而且還很生氣啊真的假的欸欸", "5.26%", "壞消息"),  # 20 字兩行
])
def test_split_text_never_leaves_its_panel(top, bottom, stat, label, tmp_path):
    """逐個文字事件:估計右緣(錨點 x + line_px)<= 890、行數在允許範圍(下格有大數字時內文最多 2 行)、
    文字不超出所屬格子,下格內文底緣(y + 行數 × 字級)不壓到大數字頂緣(格底 - 24 - 數字字級)。
    事件順序 = 上格 [標籤, 內文] + 下格 [標籤, 內文, 大數字]。"""
    takes = [Take("好。", "a.mp3", 1.0, []), Take("壞。", "b.mp3", 1.0, [])]
    seg = SplitSegment(vo="好。壞。",
                       top={"label": "好消息", "text": top, "tone": "good"},
                       bottom={"label": label, "text": bottom, "stat": stat, "tone": "bad"})
    ass = renderer_for("split").render(seg, _ctx(takes, work_dir=tmp_path)).ass
    boxes, _ = _events(ass)
    events = _text_extents(ass)
    assert len(boxes) == 2 and len(events) == 5
    panels = [boxes[0]] * 2 + [boxes[1]] * 3
    for (x, y, size, bottom_anchored, lines), allowed, (bx, by, bw, bh) in zip(
            events, [1, 2, 1, 2, 1], panels, strict=True):
        assert 1 <= len(lines) <= allowed
        assert x >= bx and x + max(line_px(ln, size) for ln in lines) <= bx + bw <= 890
        bottom_edge = y if bottom_anchored else y + len(lines) * size
        assert by <= y and bottom_edge <= by + bh
    (_, body_y, body_size, _, body_lines), (_, stat_y, stat_size, _, _) = events[3], events[4]
    assert stat_y - stat_size - (body_y + len(body_lines) * body_size) >= 40
